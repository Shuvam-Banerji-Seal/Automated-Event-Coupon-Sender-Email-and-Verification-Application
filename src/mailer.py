"""
SMTP delivery: account pool, connection reuse and rotation.

Replaces the previous pair of modules (``smtp_mailer`` sending from a single
account, ``smtp_pool`` rotating between several) which had drifted into two
different MIME builders and two different notions of what a send result looks
like.

The important behavioural change is connection reuse. The old pool opened a TCP
connection, negotiated STARTTLS and authenticated once *per email*. For a
five-hundred-person send that is five hundred handshakes — minutes of pure
overhead, and a pattern that looks enough like abuse that providers start
throttling. A campaign here keeps one authenticated connection open and only
reconnects when it breaks or the account is exhausted.
"""

from __future__ import annotations

import json
import logging
import os
import re
import smtplib
import ssl
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

CONFIG_FILE = "smtp_configs.json"
COUNTER_FILE = "smtp_counters.json"


def dry_run_enabled() -> bool:
    """Whether delivery is suppressed.

    Set MAIL_DRY_RUN=true to have every send logged and counted but never
    handed to an SMTP server. This exists because the configuration that makes
    the app work — a populated .env and smtp_configs.json sitting in the repo
    root — is also the configuration that makes an exploratory run deliver real
    mail to whatever addresses happen to be in the test sheet.
    """
    return os.getenv("MAIL_DRY_RUN", "false").lower() in ("1", "true", "yes")


# Provider responses that mean "slow down" or "you are done for today" rather
# than "this message is bad". These rotate to the next account; a bad-recipient
# error must not, or one malformed address would burn the whole pool.
RATE_LIMIT_PATTERNS = (
    "550 5.4.5", "550 5.7.1", "421 4.7.0", "451 4.7.1", "550 5.2.1",
    "452 4.2.2", "daily user sending", "quota", "rate limit", "too many",
    "try again later", "exceeded", "throttl",
)
AUTH_PATTERNS = (
    "authentication failed", "username and password not accepted",
    "invalid credentials", "5.7.8", "application-specific password",
)
# Permanent, recipient-specific failures. Retrying or rotating cannot help.
PERMANENT_PATTERNS = (
    "550 5.1.1", "no such user", "user unknown", "recipient address rejected",
    "mailbox unavailable", "does not exist", "invalid recipient",
)


def _classify(error: str) -> str:
    low = (error or "").lower()
    if any(p in low for p in PERMANENT_PATTERNS):
        return "permanent"
    if any(p in low for p in AUTH_PATTERNS):
        return "auth"
    if any(p in low for p in RATE_LIMIT_PATTERNS):
        return "rate_limit"
    return "transient"


@dataclass
class Account:
    """One sending mailbox."""

    username: str
    password: str = ""
    host: str = "smtp.gmail.com"
    port: int = 587
    use_tls: bool = True
    sender_name: str = ""
    sender_email: str = ""
    daily_limit: int = 450
    enabled: bool = True

    def __post_init__(self):
        if not self.sender_email:
            self.sender_email = self.username

    def masked(self) -> Dict[str, Any]:
        data = asdict(self)
        data["password"] = "********" if self.password else ""
        data["has_password"] = bool(self.password)
        return data


@dataclass
class Message:
    """One outgoing email, already rendered."""

    to_email: str
    subject: str
    html: str
    to_name: str = ""
    inline_images: Dict[str, bytes] = field(default_factory=dict)
    attachments: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)


_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(html: str) -> str:
    """A readable plain-text alternative.

    Every message needs one. A multipart/alternative with only an HTML part
    raises spam scores and renders as an empty message in text-only clients.
    """
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|h[1-6]|li)>", "\n", text)
    text = _TAG_RE.sub(" ", text)
    text = (
        text.replace("&nbsp;", " ").replace("&amp;", "&")
        .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def build_mime(message: Message, account: Account) -> EmailMessage:
    """Assemble a multipart/alternative message with inline images.

    Inline images are attached as ``related`` parts with Content-IDs, referenced
    from the HTML as ``cid:name``. That is the one embedding method that works
    across Gmail, Outlook and Apple Mail — remote images get blocked by default
    and data: URIs in ``<img>`` are stripped by Outlook and Gmail's web client.
    """
    mime = EmailMessage()
    mime["Subject"] = message.subject
    mime["From"] = formataddr(
        (account.sender_name or None, account.sender_email or account.username)
    )
    mime["To"] = formataddr((message.to_name or None, message.to_email))
    mime["Message-ID"] = make_msgid()
    mime["X-Mailer"] = "Event Coupon System"
    # Lets recipients' clients group the campaign, and keeps us out of the
    # "this looks like a phishing burst" bucket.
    mime["X-Auto-Response-Suppress"] = "OOF, AutoReply"

    mime.set_content(html_to_text(message.html))

    html = message.html
    cid_map: Dict[str, str] = {}
    for name in message.inline_images:
        cid = make_msgid(idstring=name)[1:-1]      # strip the angle brackets
        cid_map[name] = cid
        html = html.replace(f"cid:{name}", f"cid:{cid}")

    mime.add_alternative(html, subtype="html")

    html_part = mime.get_payload()[-1]
    for name, data in message.inline_images.items():
        html_part.add_related(
            data, maintype="image", subtype="png", cid=f"<{cid_map[name]}>",
            filename=f"{name}.png",
        )

    for path in message.attachments:
        if not path or not os.path.exists(path):
            logger.warning("Attachment missing, skipped: %s", path)
            continue
        with open(path, "rb") as handle:
            mime.add_attachment(
                handle.read(), maintype="application", subtype="octet-stream",
                filename=os.path.basename(path),
            )
    return mime


class MailerPool:
    """Accounts, daily counters, and the sending session."""

    def __init__(
        self, config_file: str = CONFIG_FILE, counter_file: str = COUNTER_FILE
    ):
        self.config_file = config_file
        self.counter_file = counter_file
        self._lock = threading.Lock()

    # -------------------------------------------------------------- accounts

    def load_accounts(self) -> List[Account]:
        if not os.path.exists(self.config_file):
            return self._from_environment()
        try:
            with open(self.config_file, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (ValueError, OSError) as exc:
            logger.error("Could not read %s: %s", self.config_file, exc)
            return self._from_environment()

        raw = data.get("configs", data) if isinstance(data, dict) else data
        accounts = []
        for entry in raw or []:
            accounts.append(
                Account(
                    username=entry.get("username", ""),
                    password=entry.get("password", ""),
                    host=entry.get("host", "smtp.gmail.com"),
                    port=int(entry.get("port", 587)),
                    use_tls=bool(entry.get("use_tls", True)),
                    sender_name=entry.get("sender_name", ""),
                    sender_email=entry.get("sender_email", ""),
                    daily_limit=int(entry.get("daily_limit", 450)),
                    enabled=bool(entry.get("active", entry.get("enabled", True))),
                )
            )
        return accounts or self._from_environment()

    @staticmethod
    def _from_environment() -> List[Account]:
        username = os.getenv("SMTP_USERNAME", "")
        if not username:
            return []
        return [
            Account(
                username=username,
                password=os.getenv("SMTP_PASSWORD", ""),
                host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
                port=int(os.getenv("SMTP_PORT", "587")),
                use_tls=os.getenv("SMTP_USE_TLS", "true").lower() != "false",
                sender_name=os.getenv("SMTP_SENDER_NAME", ""),
                sender_email=os.getenv("SMTP_SENDER_EMAIL", username),
            )
        ]

    def save_accounts(self, accounts: Iterable[Account]):
        """Persist accounts, readable only by the owner.

        The file holds app passwords in clear text, so the mode matters. It is
        also in .gitignore; both guards are needed, since neither prevents the
        other's failure mode.
        """
        payload = {"configs": [asdict(a) for a in accounts]}
        for entry in payload["configs"]:
            entry["active"] = entry.pop("enabled")
        tmp = f"{self.config_file}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.config_file)

    # -------------------------------------------------------------- counters

    def _counters(self) -> Dict[str, Any]:
        today = date.today().isoformat()
        if os.path.exists(self.counter_file):
            try:
                with open(self.counter_file, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if data.get("date") == today:
                    return data
            except (ValueError, OSError):
                pass
        return {"date": today, "counts": {}}

    def _bump(self, username: str, n: int = 1):
        with self._lock:
            counters = self._counters()
            counters["counts"][username] = counters["counts"].get(username, 0) + n
            tmp = f"{self.counter_file}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(counters, handle, indent=2)
            os.replace(tmp, self.counter_file)

    def sent_today(self, username: str) -> int:
        return self._counters().get("counts", {}).get(username, 0)

    def status(self) -> Dict[str, Any]:
        accounts = self.load_accounts()
        rows = []
        for account in accounts:
            used = self.sent_today(account.username)
            rows.append(
                {
                    **account.masked(),
                    "sent_today": used,
                    "remaining": max(0, account.daily_limit - used),
                }
            )
        return {
            "accounts": rows,
            "total_remaining": sum(r["remaining"] for r in rows if r["enabled"]),
            "configured": bool(accounts),
        }

    # ------------------------------------------------------------ connections

    def _connect(self, account: Account) -> smtplib.SMTP:
        context = ssl.create_default_context()
        if account.use_tls:
            server = smtplib.SMTP(account.host, account.port, timeout=30)
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
        else:
            server = smtplib.SMTP_SSL(
                account.host, account.port, timeout=30, context=context
            )
        if account.password:
            server.login(account.username, account.password)
        return server

    def test_account(self, account: Account) -> Dict[str, Any]:
        """Authenticate and disconnect. Sends nothing."""
        started = time.time()
        try:
            server = self._connect(account)
            server.quit()
            return {
                "success": True,
                "message": f"Authenticated as {account.username}",
                "elapsed_ms": int((time.time() - started) * 1000),
            }
        except Exception as exc:  # noqa: BLE001 - reported to the UI
            return {
                "success": False,
                "error": str(exc),
                "kind": _classify(str(exc)),
                "elapsed_ms": int((time.time() - started) * 1000),
            }

    @contextmanager
    def campaign(self, throttle: float = 0.6):
        """A sending session that holds connections open across many messages."""
        session = _Campaign(self, throttle=throttle)
        try:
            yield session
        finally:
            session.close()

    def send_one(self, message: Message) -> Dict[str, Any]:
        with self.campaign(throttle=0) as session:
            return session.send(message)


class _Campaign:
    """Sends a run of messages, rotating accounts as they fail or fill up."""

    def __init__(self, pool: MailerPool, throttle: float = 0.6):
        self.pool = pool
        self.throttle = throttle
        self.accounts = [a for a in pool.load_accounts() if a.enabled and a.password]
        if dry_run_enabled() and not self.accounts:
            # A dry run must still look runnable so the whole flow is testable.
            self.accounts = [Account(username="dry-run", password="x")]
        self._index = 0
        self._server: Optional[smtplib.SMTP] = None
        self._current: Optional[Account] = None
        self._exhausted: set = set()
        self._last_send = 0.0

    @property
    def available(self) -> bool:
        if dry_run_enabled():
            return True
        return any(a.username not in self._exhausted for a in self.accounts)

    def _next_account(self) -> Optional[Account]:
        """Pick the next account with quota left, starting from the current one."""
        for offset in range(len(self.accounts)):
            account = self.accounts[(self._index + offset) % len(self.accounts)]
            if account.username in self._exhausted:
                continue
            if self.pool.sent_today(account.username) >= account.daily_limit:
                logger.info("%s reached its daily limit", account.username)
                self._exhausted.add(account.username)
                continue
            self._index = (self._index + offset) % len(self.accounts)
            return account
        return None

    def _ensure_connection(self) -> Optional[Account]:
        if self._server is not None and self._current is not None:
            try:
                self._server.noop()
                return self._current
            except Exception:  # noqa: BLE001 - stale connection, reopen below
                self._drop()

        while True:
            account = self._next_account()
            if account is None:
                return None
            try:
                self._server = self.pool._connect(account)
                self._current = account
                logger.info("Connected to %s as %s", account.host, account.username)
                return account
            except Exception as exc:  # noqa: BLE001
                kind = _classify(str(exc))
                logger.error(
                    "Could not connect as %s (%s): %s", account.username, kind, exc
                )
                self._exhausted.add(account.username)
                self._drop()

    def _drop(self):
        if self._server is not None:
            try:
                self._server.quit()
            except Exception:  # noqa: BLE001 - already broken
                pass
        self._server = None
        self._current = None

    def send(self, message: Message) -> Dict[str, Any]:
        """Deliver one message, rotating past accounts that refuse it."""
        if dry_run_enabled():
            logger.warning(
                "DRY RUN — not delivering to %s (subject: %s)",
                message.to_email, message.subject,
            )
            return {
                "success": True, "to_email": message.to_email,
                "account": "dry-run", "dry_run": True, "meta": message.meta,
            }

        attempts = max(1, len(self.accounts))
        last_error = "No SMTP account available"
        last_kind = "config"

        for _ in range(attempts):
            account = self._ensure_connection()
            if account is None:
                break

            if self.throttle:
                wait = self.throttle - (time.time() - self._last_send)
                if wait > 0:
                    time.sleep(wait)

            try:
                mime = build_mime(message, account)
                self._server.send_message(mime)
                self._last_send = time.time()
                self.pool._bump(account.username)
                return {
                    "success": True,
                    "to_email": message.to_email,
                    "account": account.username,
                    "meta": message.meta,
                }
            except Exception as exc:  # noqa: BLE001 - classified below
                last_error = str(exc)
                last_kind = _classify(last_error)
                logger.warning(
                    "Send to %s via %s failed (%s): %s",
                    message.to_email, account.username, last_kind, last_error,
                )
                if last_kind == "permanent":
                    # The address is bad, not the account. Stop here.
                    break
                if last_kind in ("rate_limit", "auth"):
                    self._exhausted.add(account.username)
                self._drop()

        return {
            "success": False,
            "to_email": message.to_email,
            "error": last_error,
            "kind": last_kind,
            "account": self._current.username if self._current else "",
            "meta": message.meta,
        }

    def send_many(
        self,
        messages: Iterable[Message],
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        results, sent, failed = [], 0, 0
        for index, message in enumerate(messages, 1):
            if should_stop is not None and should_stop():
                break
            result = self.send(message)
            results.append(result)
            if result["success"]:
                sent += 1
            else:
                failed += 1
            if on_progress is not None:
                on_progress({"index": index, "result": result,
                             "sent": sent, "failed": failed})
            if not self.available:
                logger.error("Every SMTP account is exhausted; stopping the run")
                break
        return {"sent": sent, "failed": failed, "results": results}

    def close(self):
        self._drop()
