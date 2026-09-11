#!/usr/bin/env python3
"""
Event Coupon System — Flask application.

Two faces on one process:

* an operator console (upload a sheet, map its columns, compose the email,
  send, watch it go out), reachable only from the host machine, and
* a scanner, reachable from any phone on the network behind a PIN.

Everything persistent lives in ``src.store``; this module is routing, access
control and the send job runner.
"""

from __future__ import annotations

import atexit
import io
import logging
import os
import secrets
import signal
import socket
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from flask import (
    Flask, jsonify, redirect, render_template, request, session, send_file,
    url_for,
)
from werkzeug.utils import secure_filename

from src import csv_mapper, templating
from src.issuer import (
    CouponIssuer, QRSizeError, coupon_qr_png, describe_payload, make_link_qr,
    make_qr_png, qr_data_uri,
)
from src.mailer import Account, MailerPool, Message, dry_run_enabled
from src.outbox import OutboxWorker
from src.tunnel import (
    ZrokTunnel, find_free_port, is_public_host, port_is_free, port_owner,
)
from src.store import (
    Coupon, CouponStore, Recipient, food_colour, normalise_food, parse_scan,
)

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("coupons")

app = Flask(__name__)

# A missing SECRET_KEY used to crash at import with a bare KeyError. Generating
# an ephemeral one keeps a fresh checkout runnable; the warning is loud because
# it silently invalidates every session on restart.
_secret = os.getenv("SECRET_KEY")
if not _secret:
    _secret = secrets.token_hex(32)
    logger.warning(
        "SECRET_KEY is not set — generated a temporary one. Sessions will not "
        "survive a restart. Add SECRET_KEY to your .env for anything real."
    )
app.config.update(
    SECRET_KEY=_secret,
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    UPLOAD_FOLDER="uploads",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    JSON_SORT_KEYS=False,
    TEMPLATES_AUTO_RELOAD=True,
)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

store = CouponStore(os.getenv("DATABASE_PATH", "data/coupons.db"))
issuer = CouponIssuer(store)
mailer = MailerPool()
outbox = OutboxWorker(store, mailer, throttle=float(os.getenv("OUTBOX_THROTTLE", "0.5")))
tunnel = ZrokTunnel()
if os.getenv("FLASK_DEBUG", "false").lower() not in ("1", "true", "yes") \
        or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    # Close any share left running by a previous crash. Skipped in the reloader's
    # watcher process, which would otherwise reap the share its own child opened.
    tunnel.reap_orphan()

# --------------------------------------------------------------------- config

DEFAULT_SETTINGS = {
    "event_name": os.getenv("EVENT_NAME", "Our Event"),
    "event_date": os.getenv("EVENT_DATE", "To be announced"),
    "event_time": os.getenv("EVENT_TIME", "To be announced"),
    "event_venue": os.getenv("EVENT_VENUE", "To be announced"),
    "organizer_batch": os.getenv("ORGANIZER_BATCH", ""),
    "organizer_institution": os.getenv("ORGANIZER_INSTITUTION", "IISER Kolkata"),
    "reply_to": os.getenv("REPLY_TO", ""),
}

APP_PORT = int(os.getenv("PORT", "5000"))
# Which stored template is sent on check-in. Blank disables thank-you mail.
THANK_YOU_TEMPLATE = os.getenv("THANK_YOU_TEMPLATE", "thank_you").strip()


def event_settings() -> Dict[str, str]:
    """Event fields, database first and environment as the fallback."""
    stored = store.all_settings()
    return {key: stored.get(key, default) for key, default in DEFAULT_SETTINGS.items()}


def _lan_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


SERVER_IP = _lan_ip()
ADMIN_IPS = {"127.0.0.1", "::1", "localhost", SERVER_IP}
ADMIN_IPS.update(
    ip.strip() for ip in os.getenv("ADMIN_EXTRA_IPS", "").split(",") if ip.strip()
)
OPEN_ADMIN = os.getenv("DISABLE_ADMIN_CHECK", "false").lower() in ("1", "true", "yes")

# The scanner is used by volunteers on their own phones, so it cannot be locked
# to an IP. A short PIN keeps it from being simply a URL anyone on the wifi can
# open and start burning coupons with.
SCANNER_PIN = os.getenv("SCANNER_PIN", "").strip()


def client_ip() -> str:
    """The real client address, honouring one layer of reverse proxy.

    Only the last hop in X-Forwarded-For is trusted; the rest is attacker-
    controlled. Without TRUST_PROXY set we ignore the header entirely, because
    otherwise anyone could spoof an admin IP by sending the right header.
    """
    if os.getenv("TRUST_PROXY", "false").lower() in ("1", "true", "yes"):
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.remote_addr or "unknown"


# Paths reachable through the public tunnel. Everything else is refused, so
# opening a share exposes the scanner without exposing the console with it.
PUBLIC_PREFIXES = (
    "/scan", "/api/scan", "/static/", "/favicon.ico", "/api/health",
)


@app.before_request
def block_console_over_tunnel():
    """Refuse non-scanner paths arriving through the public share.

    The tunnel address is on the open internet. Without this, opening a share so
    volunteers can scan would also publish the recipient list, the template
    editor and the send controls to anyone who guessed the URL.

    Host is client-supplied, but this rule only ever *removes* access: forging
    the header locks you out of the console, it cannot let you in.
    """
    if not is_public_host(request.host):
        return None
    if any(request.path.startswith(p) for p in PUBLIC_PREFIXES):
        return None
    logger.warning("Blocked %s over the public tunnel", request.path)
    if request.path.startswith("/api/"):
        return jsonify({
            "success": False,
            "error": "Only the scanner is available on the public address.",
        }), 403
    return redirect(url_for("scanner_page"))


def admin_only(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        # Through the tunnel every request appears to come from localhost,
        # because zrok connects to the app locally. IP allow-listing is
        # therefore meaningless there and the host check must win.
        if is_public_host(request.host):
            return jsonify({
                "success": False,
                "error": "The console is not available on the public address.",
            }), 403
        if OPEN_ADMIN or client_ip() in ADMIN_IPS:
            return view(*args, **kwargs)
        logger.warning("Console access denied for %s on %s", client_ip(), request.path)
        if request.path.startswith("/api/"):
            return jsonify({
                "success": False,
                "error": "The operator console is only available on the host machine.",
            }), 403
        return redirect(url_for("scanner_page"))
    return wrapper


def scanner_access(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        public = is_public_host(request.host)

        if session.get("scanner_ok"):
            return view(*args, **kwargs)

        # On the public address the PIN is mandatory, with no way around it.
        # The convenience bypasses below are both useless and dangerous here:
        # zrok connects to the application from localhost, so every visitor
        # from the internet appears to come from 127.0.0.1 — an address that is
        # in ADMIN_IPS. Without this branch, publishing the scanner would hand
        # an unauthenticated redemption endpoint to anyone who found the URL.
        if public:
            if not SCANNER_PIN:
                logger.error(
                    "Public scanner request refused: SCANNER_PIN is not set."
                )
                if request.path.startswith("/api/"):
                    return jsonify({
                        "success": False,
                        "error": "Scanner is not configured for public access.",
                        "error_code": "LOCKED",
                    }), 401
                return render_template(
                    "error.html", code=503,
                    message="This scanner is not set up for public access yet.",
                ), 503
            if request.path.startswith("/api/"):
                return jsonify({
                    "success": False, "error": "Scanner locked.",
                    "error_code": "LOCKED",
                }), 401
            return redirect(url_for("scanner_unlock"))

        # On the local network, an unset PIN means open, and the host machine
        # and admin addresses skip it.
        if not SCANNER_PIN or OPEN_ADMIN or client_ip() in ADMIN_IPS:
            return view(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify({
                "success": False, "error": "Scanner locked.", "error_code": "LOCKED",
            }), 401
        return redirect(url_for("scanner_unlock"))
    return wrapper


# ------------------------------------------------------------- rate limiting

_rate_buckets: Dict[str, deque] = defaultdict(deque)
_rate_lock = threading.Lock()

# Rate limiting for the scanner is about stopping somebody guessing six-digit
# codes, and nothing else. It must never throttle a real queue.
#
# The obvious design — N requests per IP per minute — is actively wrong here.
# Behind the public tunnel zrok connects to the application from localhost, so
# every scanner in the building shares one source address. A per-IP limit
# therefore throttles the whole door at once: a burst test with ten scanners had
# 296 of 448 legitimate scans rejected.
#
# Brute force is characterised by *failures*, so that is what is counted. A
# volunteer admitting a hundred guests never trips it; somebody trying random
# codes trips it within seconds. A very high global ceiling remains as a
# backstop against a flood.
SCAN_FAIL_MAX = int(os.getenv("SCAN_FAIL_MAX", "20"))
SCAN_FAIL_WINDOW = int(os.getenv("SCAN_FAIL_WINDOW", "300"))
SCAN_GLOBAL_MAX = int(os.getenv("SCAN_GLOBAL_MAX", "3000"))
SCAN_GLOBAL_WINDOW = int(os.getenv("SCAN_GLOBAL_WINDOW", "60"))


def _window_ok(key: str, limit: int, window: int, record: bool = True) -> bool:
    """Sliding-window check. ``record`` false only tests, without consuming."""
    now = time.monotonic()
    with _rate_lock:
        bucket = _rate_buckets[key]
        while bucket and bucket[0] < now - window:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        if record:
            bucket.append(now)
        return True


def as_int(value: Any, default: int, low: int = 0, high: int = 10 ** 9) -> int:
    """Parse a number from request data without letting it raise.

    Anything the browser sends can be a typo, a stale client or someone poking
    at the API, and an unguarded int() turns that into a 500. Out-of-range
    values are clamped rather than rejected: a negative LIMIT is not an error in
    SQLite, it silently means "no limit", which is worse than being wrong.
    """
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float, low: float = 0.0,
             high: float = 60.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


def rate_ok(key: str, limit: int = SCAN_GLOBAL_MAX,
            window: int = SCAN_GLOBAL_WINDOW) -> bool:
    return _window_ok(key, limit, window)


def scan_allowed(device: str) -> bool:
    """Whether this device has failed too often to be given another try."""
    return _window_ok(f"fail:{device}", SCAN_FAIL_MAX, SCAN_FAIL_WINDOW,
                      record=False)


def record_scan_failure(device: str):
    """Count a lookup that matched nothing. Only these count toward the limit."""
    _window_ok(f"fail:{device}", SCAN_FAIL_MAX, SCAN_FAIL_WINDOW, record=True)


# --------------------------------------------------------------------- pages


@app.route("/")
@admin_only
def dashboard():
    return render_template("console/dashboard.html", page="dashboard",
                           settings=event_settings())


@app.route("/recipients")
@admin_only
def recipients_page():
    return render_template("console/recipients.html", page="recipients",
                           settings=event_settings())


@app.route("/compose")
@admin_only
def compose_page():
    return render_template("console/compose.html", page="compose",
                           settings=event_settings())


@app.route("/send")
@admin_only
def send_page():
    return render_template("console/send.html", page="send",
                           settings=event_settings())


@app.route("/settings")
@admin_only
def settings_page():
    return render_template("console/settings.html", page="settings",
                           settings=event_settings(), server_ip=SERVER_IP,
                           scanner_locked=bool(SCANNER_PIN))


@app.route("/scan")
@scanner_access
def scanner_page():
    return render_template("scanner.html", settings=event_settings())


@app.route("/scan/unlock", methods=["GET", "POST"])
def scanner_unlock():
    if request.method == "POST":
        supplied = (request.form.get("pin") or "").strip()
        if not rate_ok(f"unlock:{client_ip()}", limit=10, window=300):
            return render_template("unlock.html",
                                   error="Too many attempts. Wait a few minutes."), 429
        if SCANNER_PIN and secrets.compare_digest(supplied, SCANNER_PIN):
            session["scanner_ok"] = True
            session.permanent = True
            return redirect(url_for("scanner_page"))
        return render_template("unlock.html", error="That PIN is not right."), 401
    return render_template("unlock.html", error=None)


@app.route("/favicon.ico")
def favicon():
    return redirect(url_for("static", filename="icons/favicon.svg"))


# ------------------------------------------------------------------ overview


@app.get("/api/overview")
@admin_only
def api_overview():
    stats = store.stats()
    return jsonify({
        "success": True,
        "stats": stats,
        "settings": event_settings(),
        "smtp": mailer.status(),
        "recent_scans": store.recent_scans(limit=12),
        "send_summary": store.send_summary(),
        "templates": store.list_templates(),
        "scanner_url": (
            f"{tunnel.state().url}/scan" if tunnel.state().running and tunnel.state().url
            else f"{'https' if os.getenv('SSL_ENABLED','').lower() in ('1','true','yes') else 'http'}"
                 f"://{SERVER_IP}:{APP_PORT}/scan"
        ),
        "scanner_locked": bool(SCANNER_PIN),
        "dry_run": dry_run_enabled(),
        "tunnel": tunnel.state().as_dict(),
        "outbox": outbox.status(),
        "thank_you": {
            "template": THANK_YOU_TEMPLATE,
            "enabled": bool(THANK_YOU_TEMPLATE),
            "template_exists": bool(
                THANK_YOU_TEMPLATE and store.get_template(THANK_YOU_TEMPLATE)
            ),
        },
    })


@app.get("/api/health")
def api_health():
    return jsonify({"ok": True, "time": datetime.now(timezone.utc).isoformat()})


# ------------------------------------------------------------ CSV → recipients

# Parsed uploads waiting for the operator to confirm a mapping. Held in memory
# deliberately: the raw sheet is attendee PII and there is no reason to leave a
# copy on disk once it has been parsed.
_warned_missing_thank_you = False

_pending_uploads: Dict[str, Dict[str, Any]] = {}
_uploads_lock = threading.Lock()


def _remember_upload(payload: Dict[str, Any]) -> str:
    upload_id = uuid.uuid4().hex
    with _uploads_lock:
        cutoff = time.time() - 3600
        for key in [k for k, v in _pending_uploads.items() if v["at"] < cutoff]:
            _pending_uploads.pop(key, None)
        _pending_uploads[upload_id] = {**payload, "at": time.time()}
    return upload_id


@app.post("/api/csv/inspect")
@admin_only
def api_csv_inspect():
    """Parse an uploaded sheet and propose a column mapping."""
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"success": False, "error": "No file was uploaded."}), 400
    if not upload.filename.lower().endswith((".csv", ".tsv", ".txt")):
        return jsonify({
            "success": False,
            "error": "Upload a .csv file. If you have a spreadsheet, export it as CSV first.",
        }), 400

    raw = upload.read()
    if not raw.strip():
        return jsonify({"success": False, "error": "That file is empty."}), 400

    try:
        result = csv_mapper.inspect(raw)
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator
        logger.exception("CSV inspection failed")
        return jsonify({"success": False, "error": f"Could not read that CSV: {exc}"}), 400

    if not result["row_count"]:
        return jsonify({"success": False, "error": "No data rows found in that file."}), 400

    headers, rows, _ = csv_mapper.read_csv_bytes(raw)
    upload_id = _remember_upload({
        "rows": rows, "headers": headers, "filename": secure_filename(upload.filename),
    })
    result.update({"success": True, "upload_id": upload_id,
                   "filename": secure_filename(upload.filename)})
    return jsonify(result)


@app.post("/api/csv/commit")
@admin_only
def api_csv_commit():
    """Apply a confirmed mapping and store the recipients."""
    body = request.get_json(silent=True) or {}
    upload_id = body.get("upload_id", "")
    mapping = body.get("mapping") or {}
    mode = body.get("mode", "replace")

    with _uploads_lock:
        pending = _pending_uploads.get(upload_id)
    if pending is None:
        return jsonify({
            "success": False,
            "error": "That upload has expired. Please choose the file again.",
        }), 400
    if not mapping.get("email"):
        return jsonify({"success": False, "error": "Choose which column holds the email address."}), 400

    accepted, rejected = csv_mapper.build_recipients(pending["rows"], mapping)
    if not accepted:
        return jsonify({
            "success": False,
            "error": "No usable rows — every row was missing or had a malformed email address.",
            "rejected": rejected[:20],
        }), 400

    recipients = [
        Recipient(email=r["email"], name=r["name"],
                  food_preference=r["food_preference"],
                  include_qr=r["include_qr"], extra=r["extra"])
        for r in accepted
    ]
    source = pending.get("filename", "")
    if mode == "merge":
        store.add_recipients(recipients, source=source)
    else:
        store.replace_recipients(recipients, source=source)

    with _uploads_lock:
        _pending_uploads.pop(upload_id, None)

    logger.info("Loaded %d recipients from %s (%s)", len(recipients), source, mode)
    return jsonify({
        "success": True, "imported": len(recipients), "rejected": rejected[:50],
        "rejected_count": len(rejected), "mode": mode,
        "total_recipients": store.recipient_count(),
        "variables": store.recipient_columns(),
    })


@app.get("/api/recipients")
@admin_only
def api_recipients():
    rows = store.recipients_with_status()
    search = (request.args.get("search") or "").strip().lower()
    status = request.args.get("status", "all")
    if search:
        rows = [r for r in rows
                if search in r["email"].lower() or search in (r["name"] or "").lower()]
    if status != "all":
        rows = [r for r in rows if r["status"] == status]
    return jsonify({"success": True, "recipients": rows, "total": len(rows),
                    "variables": store.recipient_columns()})


@app.delete("/api/recipients")
@admin_only
def api_clear_recipients():
    store.replace_recipients([])
    return jsonify({"success": True, "total_recipients": 0})


# ------------------------------------------------------------------- coupons


@app.get("/api/coupons")
@admin_only
def api_coupons():
    status = request.args.get("status", "all")
    search = (request.args.get("search") or "").strip()
    limit = as_int(request.args.get("limit"), 200, low=1, high=1000)
    offset = as_int(request.args.get("offset"), 0, low=0)
    return jsonify({
        "success": True,
        "coupons": store.list_coupons(status=status, search=search,
                                      limit=limit, offset=offset),
        "total": store.count_coupons(status=status, search=search),
    })


@app.get("/api/coupons/<coupon_id>/qr.png")
@admin_only
def api_coupon_qr(coupon_id: str):
    coupon = store.find_by_id(coupon_id)
    if coupon is None:
        return jsonify({"success": False, "error": "No such coupon"}), 404
    png = coupon_qr_png(coupon, box_size=as_int(request.args.get("size"), 10,
                                                low=2, high=40))
    return send_file(io.BytesIO(png), mimetype="image/png")


@app.post("/api/coupons/<coupon_id>/revoke")
@admin_only
def api_revoke(coupon_id: str):
    return jsonify({"success": store.revoke(coupon_id)})


@app.get("/api/qr/scanner.png")
@admin_only
def api_scanner_qr():
    """QR pointing at the scanner page, rendered locally.

    Generated here rather than by a third-party image service: the venue
    network is often captive or offline, and the attendee-facing address of
    this machine is not something to hand to an external server.
    """
    state = tunnel.state()
    if state.running and state.url:
        url = f"{state.url}/scan"
    else:
        scheme = "https" if os.getenv("SSL_ENABLED", "").lower() in ("1", "true", "yes") else "http"
        url = f"{scheme}://{SERVER_IP}:{APP_PORT}/scan"
    return send_file(io.BytesIO(make_link_qr(url)), mimetype="image/png")


@app.get("/api/qr/diagnostics")
@admin_only
def api_qr_diagnostics():
    """Report how dense the QR codes actually are.

    Surfaced in the console because payload size is the one thing that silently
    breaks scanning at an event, and it is invisible until you are standing at
    a door with a queue.
    """
    sample = store.list_coupons(limit=1)
    token = "K7M2QX9RT4WD"
    if sample:
        found = store.find_by_id(sample[0]["coupon_id"])
        if found and found.qr_token:
            token = found.qr_token
    return jsonify({"success": True, **describe_payload(token)})


# ----------------------------------------------------------------- templates


@app.get("/api/variables")
@admin_only
def api_variables():
    return jsonify({
        "success": True,
        "groups": templating.variable_catalogue(
            extra_columns=store.recipient_columns(), settings=event_settings()
        ),
    })


@app.get("/api/templates")
@admin_only
def api_templates():
    return jsonify({"success": True, "templates": store.list_templates()})


@app.get("/api/templates/<name>")
@admin_only
def api_template_get(name: str):
    template = store.get_template(name)
    if template is None:
        return jsonify({"success": False, "error": "No such template"}), 404
    return jsonify({"success": True, "template": template})


@app.put("/api/templates/<name>")
@admin_only
def api_template_save(name: str):
    body = request.get_json(silent=True) or {}
    html = body.get("html", "")
    subject = body.get("subject", "")
    known = set(templating.build_context().keys()) | set(store.recipient_columns()) \
        | set(event_settings().keys())
    check = templating.validate(html, known)
    if not check["ok"]:
        return jsonify({"success": False, "error": check["errors"][0],
                        "errors": check["errors"]}), 400
    store.save_template(name, subject, html, body.get("description", ""))
    return jsonify({"success": True, "warnings": check["warnings"],
                    "lint": templating.lint_email_html(html)})


@app.delete("/api/templates/<name>")
@admin_only
def api_template_delete(name: str):
    return jsonify({"success": store.delete_template(name)})


@app.post("/api/templates/preview")
@admin_only
def api_template_preview():
    """Render a template against a sample or a real recipient."""
    body = request.get_json(silent=True) or {}
    html = body.get("html", "")
    subject = body.get("subject", "")
    food = normalise_food(body.get("food_preference", "Vegetarian"))
    target = (body.get("email") or "").strip().lower()

    settings = event_settings()
    context = None
    if target:
        for row in store.recipients_with_status():
            if row["email"] == target:
                context = templating.build_context(
                    name=row["name"], email=row["email"],
                    food_preference=row["food_preference"],
                    include_qr=row["include_qr"],
                    verification_code=row["verification_code"] or "000000",
                    coupon_id=row["coupon_id"] or "preview",
                    extra=row["extra"], settings=settings,
                )
                break
    if context is None:
        context = templating.sample_context(
            settings=settings, extra_columns=store.recipient_columns(),
            food_preference=food,
        )

    # Preview needs a real image, not a cid: reference the browser cannot resolve.
    preview_qr = qr_data_uri(make_qr_png("EC1:PREVIEW00000", box_size=8))
    context["qr_code_src"] = preview_qr

    try:
        rendered = templating.render(html, context)
        rendered_subject = templating.render_subject(subject, context)
    except templating.TemplateError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    known = set(context.keys())
    return jsonify({
        "success": True, "html": rendered, "subject": rendered_subject,
        "lint": templating.lint_email_html(rendered),
        "validation": templating.validate(html, known),
        "context_keys": sorted(known),
    })


# ---------------------------------------------------------------- send jobs


class SendJob:
    """A running send, observable from the UI while it happens."""

    def __init__(self, job_id: str, total: int, template: str):
        self.id = job_id
        self.total = total
        self.template = template
        self.sent = 0
        self.failed = 0
        self.done = False
        self.cancelled = False
        self.error: Optional[str] = None
        self.started = time.time()
        self.finished: Optional[float] = None
        self.current = ""
        self.failures: List[Dict[str, Any]] = []
        self.lock = threading.Lock()

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            elapsed = (self.finished or time.time()) - self.started
            processed = self.sent + self.failed
            rate = processed / elapsed if elapsed > 0.5 else 0
            remaining = max(0, self.total - processed)
            return {
                "id": self.id, "total": self.total, "sent": self.sent,
                "failed": self.failed, "processed": processed,
                "done": self.done, "cancelled": self.cancelled,
                "error": self.error, "current": self.current,
                "template": self.template,
                "elapsed_seconds": round(elapsed, 1),
                "rate_per_minute": round(rate * 60, 1),
                "eta_seconds": round(remaining / rate) if rate > 0 else None,
                "failures": self.failures[-50:],
            }


_jobs: Dict[str, SendJob] = {}
_jobs_lock = threading.Lock()


def _build_message(coupon: Coupon, template: Dict[str, Any],
                   settings: Dict[str, str], attachments: List[str]) -> Message:
    context = templating.build_context(
        name=coupon.name, email=coupon.email,
        food_preference=coupon.food_preference, include_qr=coupon.include_qr,
        verification_code=coupon.verification_code, coupon_id=coupon.coupon_id,
        qr_code_src="cid:qrcode", extra=coupon.extra, settings=settings,
    )
    html = templating.render(template["html"], context)
    subject = templating.render_subject(template["subject"], context)

    # Check the rendered HTML, not the source: templates reference the image as
    # {{ qr_code_src }}, which only becomes "cid:qrcode" after rendering.
    inline: Dict[str, bytes] = {}
    if coupon.include_qr and "cid:qrcode" in html:
        inline["qrcode"] = coupon_qr_png(coupon)

    return Message(
        to_email=coupon.email, to_name=coupon.name, subject=subject, html=html,
        inline_images=inline, attachments=attachments,
        meta={"coupon_id": coupon.coupon_id},
    )


def _run_send(job: SendJob, coupons: List[Coupon], template: Dict[str, Any],
              settings: Dict[str, str], attachments: List[str], throttle: float):
    delivered: List[str] = []
    try:
        with mailer.campaign(throttle=throttle) as campaign:
            if not campaign.accounts:
                with job.lock:
                    job.error = ("No SMTP account is configured. Add one in "
                                 "Settings before sending.")
                    job.done = True
                    job.finished = time.time()
                return

            for coupon in coupons:
                if job.cancelled:
                    break
                with job.lock:
                    job.current = coupon.email
                try:
                    message = _build_message(coupon, template, settings, attachments)
                except (templating.TemplateError, QRSizeError) as exc:
                    with job.lock:
                        job.failed += 1
                        job.failures.append({"email": coupon.email, "error": str(exc)})
                    store.log_send(coupon.email, coupon.coupon_id, job.template,
                                   template["subject"], False, str(exc))
                    continue

                result = campaign.send(message)
                if result["success"]:
                    delivered.append(coupon.coupon_id)
                    with job.lock:
                        job.sent += 1
                    store.log_send(coupon.email, coupon.coupon_id, job.template,
                                   message.subject, True, account=result["account"])
                    # Flush in batches so a crash mid-run cannot lose the record
                    # of what already went out.
                    if len(delivered) >= 25:
                        store.mark_sent(delivered)
                        delivered = []
                else:
                    with job.lock:
                        job.failed += 1
                        job.failures.append({"email": coupon.email,
                                             "error": result.get("error", "")})
                    store.log_send(coupon.email, coupon.coupon_id, job.template,
                                   message.subject, False, result.get("error", ""),
                                   result.get("account", ""))
                    if not campaign.available:
                        with job.lock:
                            job.error = ("Every SMTP account is out of quota or "
                                         "rejected the login. Sending stopped.")
                        break
    except Exception as exc:  # noqa: BLE001 - recorded on the job
        logger.exception("Send job %s crashed", job.id)
        with job.lock:
            job.error = str(exc)
    finally:
        if delivered:
            store.mark_sent(delivered)
        with job.lock:
            job.done = True
            job.finished = time.time()
            job.current = ""
        logger.info("Send job %s finished: %d sent, %d failed",
                    job.id, job.sent, job.failed)


@app.post("/api/send/start")
@admin_only
def api_send_start():
    """Issue coupons for the selected recipients and start emailing them."""
    body = request.get_json(silent=True) or {}
    template_name = body.get("template", "")
    audience = body.get("audience", "pending")
    selected = [e.lower() for e in body.get("emails", [])]
    attachments = [p for p in body.get("attachments", []) if p]
    throttle = as_float(body.get("throttle"), 0.8, low=0.0, high=30.0)

    template = store.get_template(template_name)
    if template is None:
        return jsonify({"success": False, "error": "Choose a template first."}), 400
    if not template["html"].strip():
        return jsonify({"success": False, "error": "That template has no content."}), 400

    with _jobs_lock:
        running = [j for j in _jobs.values() if not j.snapshot()["done"]]
    if running:
        return jsonify({
            "success": False,
            "error": "A send is already running. Wait for it to finish or stop it.",
            "job_id": running[0].id,
        }), 409

    settings = event_settings()
    event_name = settings.get("event_name", "")

    # Decide who to send to.
    if audience == "selected":
        if not selected:
            return jsonify({"success": False, "error": "No recipients were selected."}), 400
        chosen = [r for r in store.recipients() if r.email in selected]
    elif audience == "resend":
        # Everyone who already holds a coupon — used to re-send after a failure.
        # An empty selection here used to mean "all of them", so a mis-click
        # emailed the entire event a second time. Re-sending to everybody is a
        # real need after a partly failed run, so it stays possible, but it has
        # to be asked for rather than defaulted into.
        if not selected and not body.get("resend_all"):
            return jsonify({
                "success": False,
                "error": "List the addresses to re-send to, or tick "
                         "'re-send to everyone' to mail all recipients again.",
                "error_code": "NO_SELECTION",
            }), 400
        chosen = []
    else:
        chosen = store.recipients_without_coupons()

    coupons: List[Coupon] = []
    if audience == "resend":
        wanted = set(selected)
        for row in store.list_coupons(limit=10000):
            if wanted and row["email"] not in wanted:
                continue
            found = store.find_by_id(row["coupon_id"])
            if found is not None:
                coupons.append(found)
    else:
        pending = [r for r in chosen if r.email not in store.existing_emails()]
        result = issuer.issue_batch(pending, event_name=event_name)
        coupons = result["issued"]
        # Anyone selected who already had a coupon keeps it and still gets mail.
        if audience == "selected":
            for recipient in chosen:
                if recipient.email in store.existing_emails():
                    existing = store.find_by_email(recipient.email)
                    if existing and existing.coupon_id not in {c.coupon_id for c in coupons}:
                        coupons.append(existing)

    if not coupons:
        return jsonify({
            "success": False,
            "error": "Nobody to send to — every selected recipient already has a coupon.",
        }), 400

    job = SendJob(uuid.uuid4().hex[:12], len(coupons), template_name)
    with _jobs_lock:
        _jobs[job.id] = job
    threading.Thread(
        target=_run_send,
        args=(job, coupons, template, settings, attachments, throttle),
        daemon=True, name=f"send-{job.id}",
    ).start()

    logger.info("Send job %s started: %d recipients, template %s",
                job.id, len(coupons), template_name)
    return jsonify({"success": True, "job_id": job.id, "total": len(coupons)})


@app.get("/api/send/status/<job_id>")
@admin_only
def api_send_status(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        return jsonify({"success": False, "error": "No such job"}), 404
    return jsonify({"success": True, "job": job.snapshot()})


@app.post("/api/send/stop/<job_id>")
@admin_only
def api_send_stop(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        return jsonify({"success": False, "error": "No such job"}), 404
    job.cancelled = True
    return jsonify({"success": True})


@app.post("/api/send/test")
@admin_only
def api_send_test():
    """Send one rendered message to a chosen address, issuing no coupon."""
    body = request.get_json(silent=True) or {}
    address = (body.get("email") or "").strip()
    if not address:
        return jsonify({"success": False, "error": "Enter an address to test with."}), 400

    template = store.get_template(body.get("template", ""))
    if template is None:
        return jsonify({"success": False, "error": "Choose a template first."}), 400

    settings = event_settings()
    context = templating.sample_context(
        settings=settings, extra_columns=store.recipient_columns(),
        food_preference=normalise_food(body.get("food_preference", "Vegetarian")),
    )
    context.update({"email": address, "qr_code_src": "cid:qrcode"})
    try:
        html = templating.render(template["html"], context)
        subject = "[TEST] " + templating.render_subject(template["subject"], context)
    except templating.TemplateError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    message = Message(
        to_email=address, to_name=context.get("name", ""), subject=subject, html=html,
        inline_images={"qrcode": make_qr_png("EC1:TESTTESTTEST")},
    )
    result = mailer.send_one(message)
    store.log_send(address, None, template["name"], subject, result["success"],
                   result.get("error", ""), result.get("account", ""))
    return jsonify({"success": result["success"], "error": result.get("error"),
                    "account": result.get("account")})


@app.post("/api/send/attachment")
@admin_only
def api_upload_attachment():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"success": False, "error": "No file uploaded."}), 400
    name = secure_filename(upload.filename)
    path = os.path.join(app.config["UPLOAD_FOLDER"], f"{uuid.uuid4().hex[:8]}_{name}")
    upload.save(path)
    return jsonify({"success": True, "path": path, "name": name,
                    "size": os.path.getsize(path)})


# -------------------------------------------------------------------- scanner


@app.post("/api/scan")
@scanner_access
def api_scan():
    """Redeem a coupon. The one endpoint that must never be wrong."""
    ip = client_ip()
    body = request.get_json(silent=True) or {}
    raw = (body.get("payload") or body.get("code") or "").strip()
    scanner_name = (body.get("scanner") or "").strip()[:40]

    # Each phone names itself, so a single misbehaving device is isolated
    # rather than the whole door being throttled with it.
    device = scanner_name or ip

    if not rate_ok(f"global:{ip}"):
        logger.warning("Global scan ceiling hit from %s", ip)
        return jsonify({"success": False, "error": "Too many scans, slow down.",
                        "error_code": "RATE_LIMITED"}), 429

    if not scan_allowed(device):
        logger.warning("Device %s blocked after repeated failed lookups", device)
        return jsonify({
            "success": False,
            "error": "Too many codes that did not match. Wait a few minutes, or "
                     "check with the organisers.",
            "error_code": "RATE_LIMITED",
        }), 429

    parsed = parse_scan(raw)
    if not parsed["token"] and not parsed["code"]:
        record_scan_failure(device)
        return jsonify({"success": False, "error": "That is not a valid coupon code.",
                        "error_code": "UNREADABLE"}), 400

    result = store.redeem(
        verification_code=parsed["code"], qr_token=parsed["token"],
        email=parsed["email"], scanner=scanner_name, client_ip=ip,
    )

    # Only a lookup that matched nothing looks like guessing. An already-used
    # coupon is a real coupon, so it must not count against the door.
    if result.get("error_code") == "NOT_FOUND":
        record_scan_failure(device)

    coupon = result.get("coupon")
    payload: Dict[str, Any] = {
        "success": result["valid"],
        "error_code": result.get("error_code"),
        "error": result.get("error"),
    }
    if coupon is not None:
        payload.update({
            "coupon_id": coupon.coupon_id,
            "name": coupon.name or coupon.email.split("@")[0],
            "email": coupon.email,
            "food_preference": coupon.food_preference,
            "food_colour": food_colour(coupon.food_preference),
            "used_at": result.get("used_at") or coupon.used_at,
        })
    if result["valid"]:
        stats = store.stats()
        payload["progress"] = {"used": stats["used"], "total": stats["total"]}
        _queue_thank_you(coupon)
    return jsonify(payload)


def _queue_thank_you(coupon: Coupon):
    """Add a thank-you message to the outbox.

    Rendering happens here, on the request thread, because it is fast and
    predictable; delivery happens on the worker, because it is neither. Any
    failure is swallowed — a template mistake must never stop somebody getting
    through the door.
    """
    if not THANK_YOU_TEMPLATE:
        return
    template = store.get_template(THANK_YOU_TEMPLATE)
    if template is None:
        # Warn once rather than on every scan, but do warn: silently skipping
        # means the operator discovers it after the event, if at all.
        global _warned_missing_thank_you
        if not _warned_missing_thank_you:
            _warned_missing_thank_you = True
            logger.error(
                "No template named %r — thank-you emails are NOT being sent. "
                "Create it in Compose, or clear THANK_YOU_TEMPLATE in .env.",
                THANK_YOU_TEMPLATE,
            )
        return
    try:
        context = templating.build_context(
            name=coupon.name, email=coupon.email,
            food_preference=coupon.food_preference, include_qr=False,
            verification_code=coupon.verification_code,
            coupon_id=coupon.coupon_id, qr_code_src="",
            extra=coupon.extra, settings=event_settings(),
        )
        html = templating.render(template["html"], context)
        subject = templating.render_subject(
            template["subject"] or "Thank you for coming", context
        )
        queued = store.enqueue_email(
            to_email=coupon.email, to_name=coupon.name, subject=subject,
            html=html, kind="thank_you", coupon_id=coupon.coupon_id,
        )
        if queued is not None:
            outbox.nudge()
    except Exception:  # noqa: BLE001 - never block a check-in
        logger.exception("Could not queue a thank-you for %s", coupon.email)


@app.post("/api/scan/undo")
@scanner_access
def api_scan_undo():
    body = request.get_json(silent=True) or {}
    coupon_id = body.get("coupon_id", "")
    ok = store.undo_redeem(coupon_id, scanner=(body.get("scanner") or "")[:40])
    return jsonify({"success": ok,
                    "error": None if ok else "That coupon was not marked used."})


@app.get("/api/scan/recent")
@scanner_access
def api_scan_recent():
    return jsonify({"success": True, "scans": store.recent_scans(limit=25),
                    "stats": store.stats()})


@app.get("/api/scan/lookup")
@scanner_access
def api_scan_lookup():
    """Find a coupon without redeeming it — for sorting out disputes at a door."""
    query = (request.args.get("q") or "").strip()
    if len(query) < 3:
        return jsonify({"success": False, "error": "Type at least 3 characters."}), 400
    rows = store.list_coupons(search=query, limit=15)
    return jsonify({"success": True, "results": rows})


# ------------------------------------------------------------------ settings


@app.get("/api/settings")
@admin_only
def api_settings_get():
    return jsonify({"success": True, "settings": event_settings(),
                    "smtp": mailer.status(), "server_ip": SERVER_IP,
                    "scanner_locked": bool(SCANNER_PIN)})


@app.post("/api/settings")
@admin_only
def api_settings_save():
    body = request.get_json(silent=True) or {}
    for key in DEFAULT_SETTINGS:
        if key in body:
            store.set_setting(key, str(body[key]))
    return jsonify({"success": True, "settings": event_settings()})


@app.get("/api/smtp")
@admin_only
def api_smtp_get():
    return jsonify({"success": True, **mailer.status()})


@app.post("/api/smtp")
@admin_only
def api_smtp_save():
    """Replace the account list.

    A blank password on an existing account means "unchanged" rather than
    "clear it", so the UI never has to send a real password back to the server
    just to toggle a daily limit.
    """
    body = request.get_json(silent=True) or {}
    existing = {a.username: a.password for a in mailer.load_accounts()}
    accounts = []
    for entry in body.get("accounts", []):
        username = (entry.get("username") or "").strip()
        if not username:
            continue
        password = entry.get("password") or ""
        if not password or password == "********":
            password = existing.get(username, "")
        accounts.append(Account(
            username=username, password=password,
            host=entry.get("host", "smtp.gmail.com"),
            port=as_int(entry.get("port"), 587, low=1, high=65535),
            use_tls=bool(entry.get("use_tls", True)),
            sender_name=entry.get("sender_name", ""),
            sender_email=entry.get("sender_email", "") or username,
            daily_limit=as_int(entry.get("daily_limit"), 450, low=1, high=100000),
            enabled=bool(entry.get("enabled", True)),
        ))
    mailer.save_accounts(accounts)
    return jsonify({"success": True, **mailer.status()})


@app.post("/api/smtp/test")
@admin_only
def api_smtp_test():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    stored = {a.username: a for a in mailer.load_accounts()}
    password = body.get("password") or ""
    if (not password or password == "********") and username in stored:
        password = stored[username].password
    account = Account(
        username=username, password=password,
        host=body.get("host", "smtp.gmail.com"),
        port=as_int(body.get("port"), 587, low=1, high=65535),
        use_tls=bool(body.get("use_tls", True)),
    )
    return jsonify(mailer.test_account(account))


# --------------------------------------------------------------------- tunnel


@app.get("/api/tunnel")
@admin_only
def api_tunnel_status():
    return jsonify({
        "success": True,
        "tunnel": tunnel.state().as_dict(),
        "environment": tunnel.environment(),
        "port": APP_PORT,
        "scanner_pin_set": bool(SCANNER_PIN),
    })


@app.post("/api/tunnel/start")
@admin_only
def api_tunnel_start():
    """Open the public share.

    Refused without a scanner PIN: the share address is on the public internet,
    and an unprotected scanner there is one guessed URL away from someone
    burning every coupon at the event.
    """
    if not SCANNER_PIN:
        return jsonify({
            "success": False,
            "error": "Set SCANNER_PIN in your .env and restart before going "
                     "public. Without it, anyone who finds the address can "
                     "redeem coupons.",
            "error_code": "NO_PIN",
        }), 400

    body = request.get_json(silent=True) or {}
    result = tunnel.start(APP_PORT, basic_auth=body.get("basic_auth") or None)
    if result.get("success"):
        store.set_setting("last_tunnel_url", result.get("url") or "")
    return jsonify(result), (200 if result.get("success") else 500)


@app.post("/api/tunnel/stop")
@admin_only
def api_tunnel_stop():
    return jsonify(tunnel.stop())


@app.get("/api/ports")
@admin_only
def api_ports():
    """Port availability around the configured one, for the settings screen."""
    rows = []
    for port in range(APP_PORT, APP_PORT + 6):
        free = port_is_free(port)
        rows.append({
            "port": port,
            "free": free,
            "in_use_by": None if free else
                         ("this application" if port == APP_PORT else port_owner(port)),
            "current": port == APP_PORT,
        })
    return jsonify({
        "success": True, "current": APP_PORT, "ports": rows,
        "suggestion": find_free_port(APP_PORT + 1),
    })


# --------------------------------------------------------------------- outbox


@app.get("/api/outbox")
@admin_only
def api_outbox():
    return jsonify({
        "success": True,
        "worker": outbox.status(),
        "recent": store.recent_outbox(limit=25),
    })


@app.post("/api/outbox/retry")
@admin_only
def api_outbox_retry():
    count = store.retry_failed_emails()
    outbox.nudge()
    return jsonify({"success": True, "requeued": count})


# -------------------------------------------------------------------- exports


@app.get("/api/export/<what>.csv")
@admin_only
def api_export(what: str):
    # send_file resolves a relative path against the app root rather than the
    # working directory, so build an absolute one.
    export_dir = os.path.abspath("exports")
    os.makedirs(export_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if what == "coupons":
        path = os.path.join(export_dir, f"coupons_{stamp}.csv")
        store.export_coupons_csv(path)
    elif what == "scans":
        path = os.path.join(export_dir, f"scans_{stamp}.csv")
        store.export_scans_csv(path)
    else:
        return jsonify({"success": False, "error": "Unknown export"}), 404
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


@app.post("/api/event/reset")
@admin_only
def api_event_reset():
    """Clear the current event after archiving it to CSV."""
    body = request.get_json(silent=True) or {}
    if body.get("confirm") != "RESET":
        return jsonify({"success": False, "error": "Type RESET to confirm."}), 400
    os.makedirs("exports", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    store.export_coupons_csv(f"exports/coupons_before_reset_{stamp}.csv")
    store.export_scans_csv(f"exports/scans_before_reset_{stamp}.csv")
    counts = store.reset_event(keep_recipients=bool(body.get("keep_recipients")))
    logger.warning("Event reset: %s", counts)
    return jsonify({"success": True, "cleared": counts,
                    "archived_to": f"exports/coupons_before_reset_{stamp}.csv"})


# --------------------------------------------------------------------- errors


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "Not found"}), 404
    return render_template("error.html", code=404,
                           message="That page does not exist."), 404


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"success": False,
                    "error": "That file is larger than 16 MB."}), 413


@app.errorhandler(500)
def server_error(error):
    logger.exception("Unhandled error: %s", error)
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "Internal error"}), 500
    return render_template("error.html", code=500,
                           message="Something went wrong on the server."), 500


def _seed_templates():
    """Install the starter templates the first time the app runs."""
    if store.list_templates():
        return
    seed_dir = os.path.join(os.path.dirname(__file__), "templates", "seed")
    if not os.path.isdir(seed_dir):
        return
    for filename in sorted(os.listdir(seed_dir)):
        if not filename.endswith(".html"):
            continue
        name = filename[:-5]
        with open(os.path.join(seed_dir, filename), encoding="utf-8") as handle:
            content = handle.read()
        subject = "You're invited to {{ event_name }}"
        if content.startswith("{#"):
            header, _, content = content.partition("#}")
            for line in header.splitlines():
                if line.strip().lower().startswith("subject:"):
                    subject = line.split(":", 1)[1].strip()
        store.save_template(name, subject, content.strip(),
                            description="Starter template")
    logger.info("Seeded %d starter templates", len(store.list_templates()))


_seed_templates()


def _is_reloader_watcher() -> bool:
    """Whether this process is Flask's file watcher rather than the real server.

    In debug mode Werkzeug runs the module twice: once in a parent that only
    watches files and restarts the child, and once in the child that actually
    serves. Module-level side effects therefore happen twice, which was starting
    two outbox workers against one database — both polling, both sending.
    Werkzeug marks the real child with WERKZEUG_RUN_MAIN.
    """
    debug = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    return debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true"


# The worker runs for the life of the process; it is a daemon thread, so it does
# not hold the interpreter open at shutdown.
if not _is_reloader_watcher():
    outbox.start()


def _shutdown(*_args):
    """Close the public share before exiting.

    The zrok process is deliberately started in its own session so that
    stopping a share never signals the application. The cost is that it
    outlives us unless we say otherwise: a killed server would leave a share
    advertising a dead port, and no way to close it from a console that is no
    longer running.
    """
    try:
        if tunnel.state().running:
            logger.info("Closing the public share")
            tunnel.stop()
    except Exception:  # noqa: BLE001 - best effort during shutdown
        pass


atexit.register(_shutdown)


def _install_signal_handlers():
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous = signal.getsignal(sig)

        def handler(signum, frame, previous=previous):
            _shutdown()
            if callable(previous):
                previous(signum, frame)
            else:
                raise SystemExit(0)

        try:
            signal.signal(sig, handler)
        except ValueError:
            # Not the main thread (a test runner or WSGI worker); atexit covers it.
            pass


_install_signal_handlers()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    ssl_context = None
    if os.getenv("SSL_ENABLED", "false").lower() in ("1", "true", "yes"):
        if os.path.exists("cert.pem") and os.path.exists("key.pem"):
            ssl_context = ("cert.pem", "key.pem")
        else:
            logger.warning("SSL_ENABLED but cert.pem/key.pem missing — using HTTP")

    scheme = "https" if ssl_context else "http"
    logger.info("Console  %s://127.0.0.1:%d/", scheme, port)
    logger.info("Scanner  %s://%s:%d/scan", scheme, SERVER_IP, port)
    if dry_run_enabled():
        logger.warning(
            "MAIL_DRY_RUN is on — messages are logged and counted but NOT "
            "delivered. Unset it in .env before a real send."
        )
    # Debug mode exposes the Werkzeug debugger, which is an interactive Python
    # console on any traceback. It is PIN-protected, but the PIN is printed to
    # this very log. Combined with an open admin check that is remote code
    # execution for anyone who can reach the machine.
    if debug and OPEN_ADMIN:
        logger.error(
            "FLASK_DEBUG and DISABLE_ADMIN_CHECK are BOTH on. The interactive "
            "debugger is reachable from every device on this network. Set "
            "FLASK_DEBUG=false in .env before an event."
        )
    elif debug:
        logger.warning(
            "FLASK_DEBUG is on — the interactive debugger is active. Turn it "
            "off before running a real event."
        )
    if not SCANNER_PIN:
        logger.warning(
            "SCANNER_PIN is not set — anyone who can reach this machine on the "
            "network can redeem coupons. Set one in .env before an event."
        )
    app.run(host="0.0.0.0", port=port, debug=debug, ssl_context=ssl_context,
            threaded=True)
