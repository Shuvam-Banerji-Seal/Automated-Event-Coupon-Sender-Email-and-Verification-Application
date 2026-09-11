"""
SQLite-backed store for the coupon system.

This replaces the previous "CSV is the primary store" design. That design had to
rewrite the entire coupons file (hundreds of KB of base64 QR data) on every single
scan, could not express an atomic state transition, and re-read the whole file once
per recipient when the dashboard loaded.

Here SQLite is the source of truth and CSV is an import/export format. The
properties that matter:

* ``redeem()`` is a single conditional UPDATE, so two simultaneous scans of the
  same code cannot both succeed. The database, not application logic, decides.
* Lookups by verification code and by email go through indexes.
* QR images are never stored. A QR is regenerated from the coupon's short token
  whenever it is needed, which keeps the payload small (see ``qr_payload``) and the
  database compact.
* Every scan attempt, successful or not, is appended to ``scans`` for audit.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

DEFAULT_DB = "data/coupons.db"

# Statuses a coupon may hold. A coupon is redeemable from any REDEEMABLE state.
STATUS_GENERATED = "generated"
STATUS_SENT = "sent"
STATUS_USED = "used"
STATUS_REVOKED = "revoked"
REDEEMABLE = (STATUS_GENERATED, STATUS_SENT)

SCHEMA_VERSION = 1


def utcnow() -> str:
    """Timezone-aware UTC timestamp in ISO-8601, used for every stored time."""
    return datetime.now(timezone.utc).isoformat()


# Crockford-style base32: no I, L, O or U, so a token cannot be misread by a
# human retyping it and cannot accidentally spell anything.
TOKEN_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
TOKEN_LENGTH = 12          # 12 * 5 = 60 bits of entropy
QR_PREFIX = "EC1"          # identifies our codes, and versions the format


def qr_payload(qr_token: str) -> str:
    """Build the string encoded into a coupon QR code.

    This is the single most performance-critical decision in the system, and it
    is about physics rather than software. A QR's *version* — how many modules
    it packs into the same printed square — is driven entirely by payload
    length. More modules mean smaller modules, and below roughly 8 screen-pixels
    per module a scanner stops reliably decoding a phone held at an angle, with
    a cracked screen, under bad hall lighting.

    Encoding ``EC1:<12-char token>`` costs 16 bytes and stays at QR version 1
    (21x21) even at error-correction level Q. The previous format embedded the
    email address too, which cost 45-69 bytes and forced version 4-5 (33x33 to
    37x37) — around 30% smaller modules and weaker error correction, for no
    security benefit, since the email is printed in the same message the QR
    arrives in.

    Identity lives in the token, which is unguessable at 60 bits. Everything
    else about the attendee is looked up server-side. Do not add fields here.
    """
    return f"{QR_PREFIX}:{qr_token}"


_LEGACY_JSON_RE = re.compile(r'"v"\s*:\s*"(\d{4,8})"')


def parse_scan(raw: str) -> Dict[str, Optional[str]]:
    """Interpret whatever the scanner read, tolerantly.

    Accepts the current ``EC1:TOKEN`` format, a bare 6-digit code (manual entry,
    and the fallback when someone reads the code off the email), and the legacy
    JSON payload ``{"v":"123456","e":"..."}`` so coupons issued by the previous
    version of this system still scan.
    """
    text = (raw or "").strip()
    if not text:
        return {"token": None, "code": None, "email": None}

    if text.upper().startswith(QR_PREFIX + ":"):
        token = text.split(":", 1)[1].strip().upper()
        return {"token": token or None, "code": None, "email": None}

    if text.isdigit() and 4 <= len(text) <= 8:
        return {"token": None, "code": text, "email": None}

    if text.startswith("{"):
        try:
            data = json.loads(text)
            return {
                "token": (data.get("t") or None),
                "code": str(data.get("v")) if data.get("v") else None,
                "email": (data.get("e") or None),
            }
        except (ValueError, AttributeError):
            match = _LEGACY_JSON_RE.search(text)
            if match:
                return {"token": None, "code": match.group(1), "email": None}

    return {"token": None, "code": None, "email": None}


@dataclass
class Coupon:
    """One coupon. ``extra`` carries any unmapped columns from the source CSV."""

    coupon_id: str
    email: str
    verification_code: str
    qr_token: str = ""
    name: str = ""
    food_preference: str = "Vegetarian"
    include_qr: bool = True
    status: str = STATUS_GENERATED
    event_name: str = ""
    encrypted_data: str = ""
    created_at: str = ""
    sent_at: Optional[str] = None
    used_at: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def qr_payload(self) -> str:
        return qr_payload(self.qr_token)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "coupon_id": self.coupon_id,
            "email": self.email,
            "name": self.name,
            "verification_code": self.verification_code,
            "qr_token": self.qr_token,
            "food_preference": self.food_preference,
            "include_qr": self.include_qr,
            "status": self.status,
            "event_name": self.event_name,
            "created_at": self.created_at,
            "sent_at": self.sent_at,
            "used_at": self.used_at,
        }
        d.update({f"extra_{k}": v for k, v in self.extra.items()})
        return d


@dataclass
class Recipient:
    """A person loaded from an uploaded CSV, before a coupon exists for them."""

    email: str
    name: str = ""
    food_preference: str = "Vegetarian"
    include_qr: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)

    def as_context(self) -> Dict[str, Any]:
        """Flatten into a template-rendering context (extras included verbatim)."""
        ctx = dict(self.extra)
        ctx.update(
            {
                "email": self.email,
                "name": self.name,
                "first_name": first_name(self.name, self.email),
                "food_preference": self.food_preference,
                "include_qr": self.include_qr,
            }
        )
        return ctx


def first_name(name: str, email: str = "") -> str:
    """"Shuvam Banerji Seal" -> "Shuvam"; falls back to the email local part."""
    if isinstance(name, str) and name.strip():
        return name.strip().split()[0]
    return (email or "").split("@")[0] or "Guest"


_VEG = "Vegetarian"
_NONVEG = "Non-Vegetarian"
_NONVEG_TOKENS = {
    "non-veg", "nonveg", "non veg", "non_veg", "nv", "n",
    "non-vegetarian", "nonvegetarian", "non vegetarian",
    "chicken", "egg", "eggetarian", "no", "false",
}
_VEG_TOKENS = {"veg", "vegetarian", "v", "pure veg", "yes", "true", "vegan"}


def normalise_food(raw: Any) -> str:
    """Map any spelling of a food preference onto exactly two canonical values.

    Unknown or empty values default to Vegetarian, which is the safe direction to
    fail in: serving a vegetarian meal to someone who eats meat is a
    disappointment, the reverse can be a serious problem.
    """
    if raw is None:
        return _VEG
    token = str(raw).strip().lower()
    if not token:
        return _VEG
    if token in _NONVEG_TOKENS:
        return _NONVEG
    if token in _VEG_TOKENS:
        return _VEG
    # Substring fallback: "non-veg (chicken)", "Veg only", ...
    if "non" in token and "veg" in token:
        return _NONVEG
    if "veg" in token:
        return _VEG
    return _VEG


def food_colour(preference: str) -> str:
    """Badge colour for a normalised preference."""
    return "#c81e3c" if preference == _NONVEG else "#1f8a4c"


def as_bool(value: Any, default: bool = True) -> bool:
    """Interpret CSV truthiness ("TRUE"/"no"/"1"/""/...) without surprises."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    token = str(value).strip().lower()
    if not token:
        return default
    if token in ("false", "0", "no", "n", "off", "none", "-"):
        return False
    if token in ("true", "1", "yes", "y", "on"):
        return True
    return default


class CouponStore:
    """All persistence for the system. One instance is shared by the Flask app.

    Connections are per-thread (SQLite objects cannot cross threads) and opened
    in WAL mode so the scanner can read while a send batch writes.
    """

    def __init__(self, db_path: str = DEFAULT_DB):
        self.db_path = db_path
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._init_schema()

    # ---------------------------------------------------------------- plumbing

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    @contextmanager
    def write(self):
        """A serialised write transaction. Rolls back on any exception."""
        with self._write_lock:
            conn = self.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def close(self):
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def _init_schema(self):
        with self.write() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS coupons (
                    coupon_id         TEXT PRIMARY KEY,
                    email             TEXT NOT NULL,
                    name              TEXT DEFAULT '',
                    verification_code TEXT NOT NULL,
                    qr_token          TEXT NOT NULL DEFAULT '',
                    food_preference   TEXT NOT NULL DEFAULT 'Vegetarian',
                    include_qr        INTEGER NOT NULL DEFAULT 1,
                    status            TEXT NOT NULL DEFAULT 'generated',
                    event_name        TEXT DEFAULT '',
                    encrypted_data    TEXT DEFAULT '',
                    extra             TEXT DEFAULT '{}',
                    created_at        TEXT,
                    sent_at           TEXT,
                    used_at           TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ix_coupons_code
                    ON coupons(verification_code);
                CREATE UNIQUE INDEX IF NOT EXISTS ix_coupons_token
                    ON coupons(qr_token) WHERE qr_token != '';
                CREATE INDEX IF NOT EXISTS ix_coupons_email  ON coupons(email);
                CREATE INDEX IF NOT EXISTS ix_coupons_status ON coupons(status);

                CREATE TABLE IF NOT EXISTS recipients (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    email           TEXT NOT NULL,
                    name            TEXT DEFAULT '',
                    food_preference TEXT DEFAULT 'Vegetarian',
                    include_qr      INTEGER NOT NULL DEFAULT 1,
                    extra           TEXT DEFAULT '{}',
                    source          TEXT DEFAULT '',
                    created_at      TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ix_recipients_email
                    ON recipients(email);

                CREATE TABLE IF NOT EXISTS templates (
                    name        TEXT PRIMARY KEY,
                    subject     TEXT NOT NULL DEFAULT '',
                    html        TEXT NOT NULL DEFAULT '',
                    description TEXT DEFAULT '',
                    updated_at  TEXT
                );

                CREATE TABLE IF NOT EXISTS scans (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    coupon_id   TEXT,
                    email       TEXT,
                    code        TEXT,
                    result      TEXT NOT NULL,
                    detail      TEXT DEFAULT '',
                    scanner     TEXT DEFAULT '',
                    client_ip   TEXT DEFAULT '',
                    scanned_at  TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_scans_time ON scans(scanned_at);
                CREATE INDEX IF NOT EXISTS ix_scans_coupon ON scans(coupon_id);

                CREATE TABLE IF NOT EXISTS send_log (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    email      TEXT NOT NULL,
                    coupon_id  TEXT,
                    template   TEXT DEFAULT '',
                    subject    TEXT DEFAULT '',
                    success    INTEGER NOT NULL,
                    error      TEXT DEFAULT '',
                    account    TEXT DEFAULT '',
                    sent_at    TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_sendlog_time ON send_log(sent_at);
                CREATE INDEX IF NOT EXISTS ix_sendlog_email ON send_log(email);

                CREATE TABLE IF NOT EXISTS outbox (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    to_email      TEXT NOT NULL,
                    to_name       TEXT DEFAULT '',
                    subject       TEXT NOT NULL,
                    html          TEXT NOT NULL,
                    kind          TEXT DEFAULT 'thank_you',
                    coupon_id     TEXT,
                    status        TEXT NOT NULL DEFAULT 'queued',
                    attempts      INTEGER NOT NULL DEFAULT 0,
                    last_error    TEXT DEFAULT '',
                    queued_at     TEXT NOT NULL,
                    next_try_at   TEXT NOT NULL,
                    sent_at       TEXT
                );
                CREATE INDEX IF NOT EXISTS ix_outbox_pending
                    ON outbox(status, next_try_at);
                -- One thank-you per coupon, enforced by the database rather than
                -- by a check-then-insert that six scanners could race through.
                CREATE UNIQUE INDEX IF NOT EXISTS ix_outbox_once
                    ON outbox(coupon_id, kind) WHERE coupon_id IS NOT NULL;

                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    # ---------------------------------------------------------------- settings

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        with self.write() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def all_settings(self) -> Dict[str, str]:
        return {
            r["key"]: r["value"]
            for r in self.conn.execute("SELECT key, value FROM settings")
        }

    # -------------------------------------------------------------- recipients

    def replace_recipients(
        self, recipients: Sequence[Recipient], source: str = ""
    ) -> int:
        """Swap in a new recipient list, wholesale, in one transaction.

        Coupons are never touched by this. Someone who already has a coupon keeps
        it even if they drop off the new list.
        """
        now = utcnow()
        with self.write() as conn:
            conn.execute("DELETE FROM recipients")
            conn.executemany(
                "INSERT OR REPLACE INTO recipients"
                "(email, name, food_preference, include_qr, extra, source, created_at)"
                " VALUES(?,?,?,?,?,?,?)",
                [
                    (
                        r.email.lower().strip(),
                        r.name,
                        normalise_food(r.food_preference),
                        1 if r.include_qr else 0,
                        json.dumps(r.extra, ensure_ascii=False),
                        source,
                        now,
                    )
                    for r in recipients
                ],
            )
        return len(recipients)

    def add_recipients(self, recipients: Sequence[Recipient], source: str = "") -> int:
        """Merge recipients into the existing list, keyed on email."""
        now = utcnow()
        with self.write() as conn:
            conn.executemany(
                "INSERT INTO recipients"
                "(email, name, food_preference, include_qr, extra, source, created_at)"
                " VALUES(?,?,?,?,?,?,?)"
                " ON CONFLICT(email) DO UPDATE SET"
                "   name = excluded.name,"
                "   food_preference = excluded.food_preference,"
                "   include_qr = excluded.include_qr,"
                "   extra = excluded.extra,"
                "   source = excluded.source",
                [
                    (
                        r.email.lower().strip(),
                        r.name,
                        normalise_food(r.food_preference),
                        1 if r.include_qr else 0,
                        json.dumps(r.extra, ensure_ascii=False),
                        source,
                        now,
                    )
                    for r in recipients
                ],
            )
        return len(recipients)

    def _row_to_recipient(self, row: sqlite3.Row) -> Recipient:
        return Recipient(
            email=row["email"],
            name=row["name"] or "",
            food_preference=row["food_preference"] or _VEG,
            include_qr=bool(row["include_qr"]),
            extra=json.loads(row["extra"] or "{}"),
        )

    def recipients(self) -> List[Recipient]:
        rows = self.conn.execute(
            "SELECT * FROM recipients ORDER BY id"
        ).fetchall()
        return [self._row_to_recipient(r) for r in rows]

    def recipient_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) c FROM recipients").fetchone()["c"]

    def recipient_columns(self) -> List[str]:
        """Every variable name available from the current recipient list.

        The mapped fields, plus whatever extra columns survived the upload. This
        is what the template editor offers as insertable variables.
        """
        base = ["email", "name", "first_name", "food_preference", "include_qr"]
        seen: List[str] = []
        for row in self.conn.execute("SELECT extra FROM recipients LIMIT 500"):
            for key in json.loads(row["extra"] or "{}"):
                if key not in seen:
                    seen.append(key)
        return base + sorted(seen)

    def recipients_without_coupons(self) -> List[Recipient]:
        rows = self.conn.execute(
            "SELECT r.* FROM recipients r "
            "LEFT JOIN coupons c ON lower(c.email) = lower(r.email) "
            "WHERE c.coupon_id IS NULL ORDER BY r.id"
        ).fetchall()
        return [self._row_to_recipient(r) for r in rows]

    def recipients_with_status(self) -> List[Dict[str, Any]]:
        """Recipient list joined to coupon state — one query, not one per row.

        The old implementation re-opened and re-scanned the entire coupons CSV
        once for every recipient, which is why the dashboard crawled.
        """
        rows = self.conn.execute(
            """
            SELECT r.email, r.name, r.food_preference, r.include_qr, r.extra,
                   c.coupon_id, c.verification_code, c.status, c.sent_at, c.used_at
            FROM recipients r
            LEFT JOIN coupons c ON lower(c.email) = lower(r.email)
            ORDER BY r.id
            """
        ).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "email": r["email"],
                    "name": r["name"] or "",
                    "food_preference": r["food_preference"],
                    "include_qr": bool(r["include_qr"]),
                    "coupon_id": r["coupon_id"],
                    "verification_code": r["verification_code"],
                    "status": r["status"] or "pending",
                    "sent_at": r["sent_at"],
                    "used_at": r["used_at"],
                    "extra": json.loads(r["extra"] or "{}"),
                }
            )
        return out

    # ----------------------------------------------------------------- coupons

    def _row_to_coupon(self, row: sqlite3.Row) -> Coupon:
        return Coupon(
            coupon_id=row["coupon_id"],
            email=row["email"],
            name=row["name"] or "",
            verification_code=row["verification_code"],
            qr_token=row["qr_token"] if "qr_token" in row.keys() else "",
            food_preference=row["food_preference"],
            include_qr=bool(row["include_qr"]),
            status=row["status"],
            event_name=row["event_name"] or "",
            encrypted_data=row["encrypted_data"] or "",
            created_at=row["created_at"] or "",
            sent_at=row["sent_at"],
            used_at=row["used_at"],
            extra=json.loads(row["extra"] or "{}"),
        )

    def reserve_code(self, conn: sqlite3.Connection, rng) -> str:
        """Draw a 6-digit code not already present. Caller supplies the RNG."""
        for _ in range(200):
            code = "".join(rng.choice("0123456789") for _ in range(6))
            hit = conn.execute(
                "SELECT 1 FROM coupons WHERE verification_code = ?", (code,)
            ).fetchone()
            if not hit:
                return code
        raise RuntimeError("Could not find a free verification code after 200 tries")

    def reserve_token(self, conn: sqlite3.Connection, rng) -> str:
        """Draw an unused QR token. 60 bits, so collisions are theoretical."""
        for _ in range(200):
            token = "".join(rng.choice(TOKEN_ALPHABET) for _ in range(TOKEN_LENGTH))
            hit = conn.execute(
                "SELECT 1 FROM coupons WHERE qr_token = ?", (token,)
            ).fetchone()
            if not hit:
                return token
        raise RuntimeError("Could not find a free QR token after 200 tries")

    def find_by_token(self, qr_token: str) -> Optional[Coupon]:
        row = self.conn.execute(
            "SELECT * FROM coupons WHERE qr_token = ?", (qr_token,)
        ).fetchone()
        return self._row_to_coupon(row) if row else None

    def insert_coupons(self, coupons: Sequence[Coupon]) -> int:
        """Persist a batch of coupons in a single transaction."""
        now = utcnow()
        with self.write() as conn:
            conn.executemany(
                "INSERT INTO coupons"
                "(coupon_id, email, name, verification_code, qr_token, food_preference,"
                " include_qr, status, event_name, encrypted_data, extra, created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        c.coupon_id,
                        c.email.lower(),
                        c.name,
                        c.verification_code,
                        c.qr_token,
                        normalise_food(c.food_preference),
                        1 if c.include_qr else 0,
                        c.status,
                        c.event_name,
                        c.encrypted_data,
                        json.dumps(c.extra, ensure_ascii=False),
                        c.created_at or now,
                    )
                    for c in coupons
                ],
            )
        return len(coupons)

    def find_by_code(
        self, verification_code: str, email: Optional[str] = None
    ) -> Optional[Coupon]:
        if email:
            row = self.conn.execute(
                "SELECT * FROM coupons WHERE verification_code = ? "
                "AND lower(email) = lower(?)",
                (verification_code, email),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM coupons WHERE verification_code = ?",
                (verification_code,),
            ).fetchone()
        return self._row_to_coupon(row) if row else None

    def find_by_email(self, email: str) -> Optional[Coupon]:
        row = self.conn.execute(
            "SELECT * FROM coupons WHERE lower(email) = lower(?) "
            "ORDER BY created_at DESC LIMIT 1",
            (email,),
        ).fetchone()
        return self._row_to_coupon(row) if row else None

    def find_by_id(self, coupon_id: str) -> Optional[Coupon]:
        row = self.conn.execute(
            "SELECT * FROM coupons WHERE coupon_id = ?", (coupon_id,)
        ).fetchone()
        return self._row_to_coupon(row) if row else None

    def existing_emails(self) -> set:
        return {
            r["email"].lower()
            for r in self.conn.execute("SELECT email FROM coupons")
        }

    def redeem(
        self,
        verification_code: Optional[str] = None,
        email: Optional[str] = None,
        scanner: str = "",
        client_ip: str = "",
        qr_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atomically mark a coupon used. The single source of truth for entry.

        The conditional UPDATE is what makes this safe: if two scanners submit the
        same code at the same instant, exactly one UPDATE matches a redeemable row
        and reports ``rowcount == 1``. The loser is told the coupon is already
        used. No read-then-write window exists for them to race through.
        """
        now = utcnow()
        presented = qr_token or verification_code or ""
        with self.write() as conn:
            if qr_token:
                row = conn.execute(
                    "SELECT * FROM coupons WHERE qr_token = ?", (qr_token,)
                ).fetchone()
            elif email:
                row = conn.execute(
                    "SELECT * FROM coupons WHERE verification_code = ? "
                    "AND lower(email) = lower(?)",
                    (verification_code, email),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM coupons WHERE verification_code = ?",
                    (verification_code,),
                ).fetchone()

            if row is None:
                conn.execute(
                    "INSERT INTO scans(coupon_id, email, code, result, detail,"
                    " scanner, client_ip, scanned_at) VALUES(?,?,?,?,?,?,?,?)",
                    (None, email or "", presented, "not_found",
                     "No coupon matches this code", scanner, client_ip, now),
                )
                return {
                    "valid": False,
                    "error_code": "NOT_FOUND",
                    "error": "No coupon matches that code.",
                }

            coupon = self._row_to_coupon(row)

            if coupon.status == STATUS_REVOKED:
                conn.execute(
                    "INSERT INTO scans(coupon_id, email, code, result, detail,"
                    " scanner, client_ip, scanned_at) VALUES(?,?,?,?,?,?,?,?)",
                    (coupon.coupon_id, coupon.email, presented, "revoked",
                     "", scanner, client_ip, now),
                )
                return {
                    "valid": False,
                    "error_code": "REVOKED",
                    "error": "This coupon has been revoked.",
                    "coupon": coupon,
                }

            cur = conn.execute(
                "UPDATE coupons SET status = ?, used_at = ? "
                "WHERE coupon_id = ? AND status IN (?, ?)",
                (STATUS_USED, now, coupon.coupon_id, STATUS_GENERATED, STATUS_SENT),
            )

            if cur.rowcount == 1:
                conn.execute(
                    "INSERT INTO scans(coupon_id, email, code, result, detail,"
                    " scanner, client_ip, scanned_at) VALUES(?,?,?,?,?,?,?,?)",
                    (coupon.coupon_id, coupon.email, presented, "ok",
                     "", scanner, client_ip, now),
                )
                coupon.status = STATUS_USED
                coupon.used_at = now
                return {"valid": True, "coupon": coupon, "used_at": now}

            # rowcount == 0: the row was already 'used' before our UPDATE landed.
            conn.execute(
                "INSERT INTO scans(coupon_id, email, code, result, detail,"
                " scanner, client_ip, scanned_at) VALUES(?,?,?,?,?,?,?,?)",
                (coupon.coupon_id, coupon.email, presented, "already_used",
                 f"first used at {coupon.used_at}", scanner, client_ip, now),
            )
            return {
                "valid": False,
                "error_code": "ALREADY_USED",
                "error": "This coupon has already been used.",
                "coupon": coupon,
                "used_at": coupon.used_at,
            }

    def undo_redeem(self, coupon_id: str, scanner: str = "") -> bool:
        """Put a mistakenly scanned coupon back. Needed at a real door."""
        now = utcnow()
        with self.write() as conn:
            cur = conn.execute(
                "UPDATE coupons SET status = ?, used_at = NULL "
                "WHERE coupon_id = ? AND status = ?",
                (STATUS_SENT, coupon_id, STATUS_USED),
            )
            if cur.rowcount == 1:
                conn.execute(
                    "INSERT INTO scans(coupon_id, email, code, result, detail,"
                    " scanner, client_ip, scanned_at) VALUES(?,?,?,?,?,?,?,?)",
                    (coupon_id, "", "", "undo", "redemption reverted",
                     scanner, "", now),
                )
                return True
            return False

    def mark_sent(self, coupon_ids: Iterable[str]) -> int:
        """Flip coupons to 'sent'. Takes a batch — one transaction, not one per email."""
        ids = [i for i in coupon_ids if i]
        if not ids:
            return 0
        now = utcnow()
        with self.write() as conn:
            conn.executemany(
                "UPDATE coupons SET status = ?, sent_at = ? "
                "WHERE coupon_id = ? AND status != ?",
                [(STATUS_SENT, now, cid, STATUS_USED) for cid in ids],
            )
        return len(ids)

    def revoke(self, coupon_id: str) -> bool:
        with self.write() as conn:
            cur = conn.execute(
                "UPDATE coupons SET status = ? WHERE coupon_id = ?",
                (STATUS_REVOKED, coupon_id),
            )
            return cur.rowcount == 1

    def stats(self) -> Dict[str, Any]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) c FROM coupons GROUP BY status"
        ).fetchall()
        by_status = {r["status"]: r["c"] for r in rows}
        total = sum(by_status.values())
        food = {
            r["food_preference"]: r["c"]
            for r in self.conn.execute(
                "SELECT food_preference, COUNT(*) c FROM coupons GROUP BY food_preference"
            )
        }
        used_food = {
            r["food_preference"]: r["c"]
            for r in self.conn.execute(
                "SELECT food_preference, COUNT(*) c FROM coupons "
                "WHERE status = 'used' GROUP BY food_preference"
            )
        }
        return {
            "total": total,
            "generated": by_status.get(STATUS_GENERATED, 0),
            "sent": by_status.get(STATUS_SENT, 0),
            "used": by_status.get(STATUS_USED, 0),
            "revoked": by_status.get(STATUS_REVOKED, 0),
            "recipients": self.recipient_count(),
            "pending": max(
                0, self.recipient_count() - total
            ),
            "food": food,
            "food_used": used_food,
            "scan_count": self.conn.execute(
                "SELECT COUNT(*) c FROM scans"
            ).fetchone()["c"],
        }

    def list_coupons(
        self,
        status: Optional[str] = None,
        search: str = "",
        limit: int = 500,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        if search:
            clauses.append(
                "(lower(email) LIKE ? OR lower(name) LIKE ? OR verification_code LIKE ?)"
            )
            token = f"%{search.lower()}%"
            params += [token, token, f"%{search}%"]
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT coupon_id, email, name, verification_code, food_preference,"
            f" include_qr, status, sent_at, used_at, created_at FROM coupons {where}"
            f" ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_coupons(self, status: Optional[str] = None, search: str = "") -> int:
        clauses, params = [], []
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        if search:
            clauses.append(
                "(lower(email) LIKE ? OR lower(name) LIKE ? OR verification_code LIKE ?)"
            )
            token = f"%{search.lower()}%"
            params += [token, token, f"%{search}%"]
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.conn.execute(
            f"SELECT COUNT(*) c FROM coupons {where}", params
        ).fetchone()["c"]

    # ------------------------------------------------------------------- scans

    def recent_scans(self, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT s.*, c.name, c.food_preference FROM scans s "
            "LEFT JOIN coupons c ON c.coupon_id = s.coupon_id "
            "ORDER BY s.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def scan_timeline(self) -> List[Dict[str, Any]]:
        """Successful scans bucketed by minute, for the live dashboard chart."""
        rows = self.conn.execute(
            "SELECT substr(scanned_at, 1, 16) bucket, COUNT(*) c FROM scans "
            "WHERE result = 'ok' GROUP BY bucket ORDER BY bucket"
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- send log

    def log_send(
        self,
        email: str,
        coupon_id: Optional[str],
        template: str,
        subject: str,
        success: bool,
        error: str = "",
        account: str = "",
    ):
        with self.write() as conn:
            conn.execute(
                "INSERT INTO send_log(email, coupon_id, template, subject, success,"
                " error, account, sent_at) VALUES(?,?,?,?,?,?,?,?)",
                (email, coupon_id, template, subject, 1 if success else 0,
                 error, account, utcnow()),
            )

    def failed_sends(self, limit: int = 500) -> List[Dict[str, Any]]:
        """Most recent failure per address, excluding ones that later succeeded."""
        rows = self.conn.execute(
            """
            SELECT email, MAX(sent_at) last_try, error, template
            FROM send_log
            WHERE success = 0
              AND email NOT IN (SELECT email FROM send_log WHERE success = 1)
            GROUP BY email ORDER BY last_try DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def send_summary(self) -> Dict[str, int]:
        row = self.conn.execute(
            "SELECT SUM(success) ok, SUM(1 - success) failed, COUNT(*) total "
            "FROM send_log"
        ).fetchone()
        return {
            "sent": row["ok"] or 0,
            "failed": row["failed"] or 0,
            "total": row["total"] or 0,
        }

    # --------------------------------------------------------------- templates

    def save_template(
        self, name: str, subject: str, html: str, description: str = ""
    ):
        with self.write() as conn:
            conn.execute(
                "INSERT INTO templates(name, subject, html, description, updated_at)"
                " VALUES(?,?,?,?,?)"
                " ON CONFLICT(name) DO UPDATE SET subject = excluded.subject,"
                "   html = excluded.html, description = excluded.description,"
                "   updated_at = excluded.updated_at",
                (name, subject, html, description, utcnow()),
            )

    def get_template(self, name: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM templates WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None

    def list_templates(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT name, subject, description, updated_at, length(html) size "
            "FROM templates ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_template(self, name: str) -> bool:
        with self.write() as conn:
            cur = conn.execute("DELETE FROM templates WHERE name = ?", (name,))
            return cur.rowcount == 1

    # ------------------------------------------------------------------ outbox

    def enqueue_email(
        self,
        to_email: str,
        subject: str,
        html: str,
        to_name: str = "",
        kind: str = "thank_you",
        coupon_id: Optional[str] = None,
    ) -> Optional[int]:
        """Queue a message for the background sender.

        Returns the row id, or None when this coupon already has a message of
        this kind queued. Sending happens on one worker thread; the scan request
        only writes a row, so a rush at the door is never waiting on SMTP.
        """
        now = utcnow()
        try:
            with self.write() as conn:
                cur = conn.execute(
                    "INSERT INTO outbox(to_email, to_name, subject, html, kind,"
                    " coupon_id, queued_at, next_try_at) VALUES(?,?,?,?,?,?,?,?)",
                    (to_email, to_name, subject, html, kind, coupon_id, now, now),
                )
                return cur.lastrowid
        except sqlite3.IntegrityError:
            # The unique index fired: this coupon was already queued. Expected
            # whenever a coupon is un-done and re-scanned.
            return None

    def claim_emails(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Atomically take a batch of due messages and mark them sending.

        Claiming inside the transaction that selects them means a second worker
        (or a restarted one) cannot pick up the same rows.
        """
        now = utcnow()
        with self.write() as conn:
            rows = conn.execute(
                "SELECT * FROM outbox WHERE status = 'queued' AND next_try_at <= ?"
                " ORDER BY id LIMIT ?",
                (now, limit),
            ).fetchall()
            if not rows:
                return []
            ids = [r["id"] for r in rows]
            conn.execute(
                f"UPDATE outbox SET status = 'sending' WHERE id IN "
                f"({','.join('?' * len(ids))})",
                ids,
            )
            return [dict(r) for r in rows]

    def finish_email(
        self, row_id: int, success: bool, error: str = "", retry_in: int = 0
    ):
        """Record the outcome of one queued message."""
        now = utcnow()
        with self.write() as conn:
            if success:
                conn.execute(
                    "UPDATE outbox SET status = 'sent', sent_at = ?, last_error = ''"
                    " WHERE id = ?",
                    (now, row_id),
                )
            elif retry_in > 0:
                nxt = (
                    datetime.now(timezone.utc) + timedelta(seconds=retry_in)
                ).isoformat()
                conn.execute(
                    "UPDATE outbox SET status = 'queued', attempts = attempts + 1,"
                    " last_error = ?, next_try_at = ? WHERE id = ?",
                    (error[:500], nxt, row_id),
                )
            else:
                conn.execute(
                    "UPDATE outbox SET status = 'failed', attempts = attempts + 1,"
                    " last_error = ? WHERE id = ?",
                    (error[:500], row_id),
                )

    def requeue_stuck_emails(self, older_than_seconds: int = 300) -> int:
        """Return messages left 'sending' by a crash to the queue."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
        ).isoformat()
        with self.write() as conn:
            cur = conn.execute(
                "UPDATE outbox SET status = 'queued' WHERE status = 'sending'"
                " AND queued_at < ?",
                (cutoff,),
            )
            return cur.rowcount

    def retry_failed_emails(self) -> int:
        now = utcnow()
        with self.write() as conn:
            cur = conn.execute(
                "UPDATE outbox SET status = 'queued', next_try_at = ?,"
                " attempts = 0 WHERE status = 'failed'",
                (now,),
            )
            return cur.rowcount

    def outbox_stats(self) -> Dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) c FROM outbox GROUP BY status"
        ).fetchall()
        by_status = {r["status"]: r["c"] for r in rows}
        return {
            "queued": by_status.get("queued", 0),
            "sending": by_status.get("sending", 0),
            "sent": by_status.get("sent", 0),
            "failed": by_status.get("failed", 0),
            "total": sum(by_status.values()),
        }

    def recent_outbox(self, limit: int = 25) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, to_email, subject, kind, status, attempts, last_error,"
            " queued_at, sent_at FROM outbox ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------ import/export

    def export_coupons_csv(self, path: str) -> int:
        """Write the full coupon table to CSV, extras flattened into columns."""
        rows = self.conn.execute(
            "SELECT * FROM coupons ORDER BY created_at, rowid"
        ).fetchall()
        extra_keys: List[str] = []
        for r in rows:
            for k in json.loads(r["extra"] or "{}"):
                if k not in extra_keys:
                    extra_keys.append(k)
        base = [
            "coupon_id", "email", "name", "verification_code", "qr_token", "food_preference",
            "include_qr", "status", "event_name", "created_at", "sent_at", "used_at",
        ]
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=base + extra_keys)
            writer.writeheader()
            for r in rows:
                record = {k: r[k] for k in base}
                record["include_qr"] = bool(r["include_qr"])
                record.update(json.loads(r["extra"] or "{}"))
                writer.writerow(record)
        return len(rows)

    def export_scans_csv(self, path: str) -> int:
        rows = self.conn.execute(
            "SELECT s.scanned_at, s.result, s.code, s.email, c.name,"
            " c.food_preference, s.scanner, s.detail FROM scans s"
            " LEFT JOIN coupons c ON c.coupon_id = s.coupon_id ORDER BY s.id"
        ).fetchall()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["scanned_at", "result", "code", "email", "name",
                 "food_preference", "scanner", "detail"]
            )
            for r in rows:
                writer.writerow([r[k] for k in r.keys()])
        return len(rows)

    def import_legacy_csv(self, csv_path: str, event_name: str = "") -> Dict[str, Any]:
        """Load a coupons.csv written by the pre-SQLite version of this system.

        Preserves coupon_id, code, status and timestamps so an in-flight event can
        be migrated without invalidating codes already sitting in people's inboxes.
        The base64 QR column is intentionally dropped — QRs are regenerated.
        """
        imported, skipped = 0, 0
        batch: List[Coupon] = []
        with open(csv_path, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                code = (row.get("verification_code") or "").strip()
                email = (row.get("email") or "").strip().lower()
                if not code or not email:
                    skipped += 1
                    continue
                batch.append(
                    Coupon(
                        coupon_id=row.get("coupon_id") or str(uuid.uuid4()),
                        email=email,
                        name=row.get("name", "") or "",
                        verification_code=code,
                        food_preference=normalise_food(row.get("food_preference")),
                        include_qr=as_bool(row.get("include_qr"), True),
                        status=row.get("status") or STATUS_GENERATED,
                        event_name=event_name,
                        encrypted_data=row.get("encrypted_data", "") or "",
                        created_at=row.get("sent_at") or utcnow(),
                        sent_at=row.get("sent_at") or None,
                        used_at=row.get("used_at") or None,
                    )
                )
                imported += 1
        if batch:
            self.insert_coupons(batch)
        return {"imported": imported, "skipped": skipped}

    def reset_event(self, keep_recipients: bool = False) -> Dict[str, int]:
        """Clear coupons, scans and send history to start a new event."""
        with self.write() as conn:
            counts = {
                "coupons": conn.execute("SELECT COUNT(*) c FROM coupons").fetchone()["c"],
                "scans": conn.execute("SELECT COUNT(*) c FROM scans").fetchone()["c"],
                "send_log": conn.execute("SELECT COUNT(*) c FROM send_log").fetchone()["c"],
                "outbox": conn.execute("SELECT COUNT(*) c FROM outbox").fetchone()["c"],
            }
            conn.execute("DELETE FROM coupons")
            conn.execute("DELETE FROM scans")
            conn.execute("DELETE FROM send_log")
            # Queued mail references coupons that are about to stop existing;
            # leaving it would send thank-yous for a finished event.
            conn.execute("DELETE FROM outbox")
            if not keep_recipients:
                counts["recipients"] = conn.execute(
                    "SELECT COUNT(*) c FROM recipients"
                ).fetchone()["c"]
                conn.execute("DELETE FROM recipients")
        return counts
