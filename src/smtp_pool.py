#!/home/shuvam/.global-pymaster/bin/python
"""smtp_pool.py
SMTP rotation pool — manages multiple SMTP configs with automatic failover.

When one account hits its daily limit (or returns a rate-limit error),
the pool rotates to the next available account.  Daily counters reset
at midnight (server local time).
"""

import json
import os
import time
import smtplib
import logging
from datetime import date, datetime
from typing import Optional
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage

logger = logging.getLogger(__name__)

# ---------- rate-limit detection ----------
RATE_LIMIT_PATTERNS = [
    "550 5.4.5",  # Gmail daily quota
    "550 5.7.1",  # Gmail abuse limit
    "421 4.7.0",  # Temporary rate limit
    "451 4.7.1",  # Rate limit
    "550 5.2.1",  # Yahoo rate limit
    "exceed",  # generic
    "quota",  # generic
    "rate limit",  # generic
    "too many",  # generic
    "try again later",  # generic
    "daily user sending",  # Gmail specific
]


def _is_rate_limit(error_msg: str) -> bool:
    """Check if an SMTP error message indicates a rate/quota limit."""
    lower = (error_msg or "").lower()
    return any(pat.lower() in lower for pat in RATE_LIMIT_PATTERNS)


def _is_auth_error(error_msg: str) -> bool:
    """Check if error is authentication failure (bad password, not rate limit)."""
    lower = (error_msg or "").lower()
    return any(
        kw in lower
        for kw in ["authentication failed", "auth", "invalid credentials", "login"]
    )


# ---------- config persistence ----------
CONFIG_FILE = "smtp_configs.json"
COUNTERS_FILE = "smtp_counters.json"


def _load_configs() -> tuple[list[dict], int]:
    """Load SMTP configs and active index from disk. Returns (configs, active_index)."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data.get("configs", []), data.get("active_index", 0)
            elif isinstance(data, list):
                return data, 0
        except Exception:
            pass
    # Migrate from legacy single-config file
    legacy = "smtp_config.json"
    if os.path.exists(legacy):
        try:
            with open(legacy, "r") as f:
                cfg = json.load(f)
            cfg["daily_limit"] = cfg.get("daily_limit", 500)
            cfg["active"] = True
            return [cfg], 0
        except Exception:
            pass
    return [], 0


def _save_configs(configs: list[dict], active_index: int = 0):
    """Persist SMTP configs and active index to disk."""
    data = {"configs": configs, "active_index": active_index}
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _load_counters() -> dict:
    """Load daily send counters.  Keys are SMTP usernames."""
    today = date.today().isoformat()
    if os.path.exists(COUNTERS_FILE):
        try:
            with open(COUNTERS_FILE, "r") as f:
                data = json.load(f)
            if data.get("date") != today:
                # New day — reset counters
                return {"date": today, "counts": {}}
            return data
        except Exception:
            pass
    return {"date": today, "counts": {}}


def _save_counters(counters: dict):
    with open(COUNTERS_FILE, "w") as f:
        json.dump(counters, f, indent=2)


# ---------- SMTPPool ----------


class SMTPPool:
    """Manages multiple SMTP accounts with rotation and rate-limit handling.

    Usage:
        pool = SMTPPool()
        result = pool.send_email(to, name, subject, html, ...)
        # result now includes which config was used and whether rotation happened
    """

    def __init__(self):
        self.configs, self._active_idx = _load_configs()
        self.counters = _load_counters()

    # ---- public helpers ----

    def get_configs(self) -> list[dict]:
        """Return all configs (passwords masked)."""
        out = []
        for i, c in enumerate(self.configs):
            masked = dict(c)
            if masked.get("password"):
                masked["password"] = "••••••••"
            masked["emails_sent_today"] = self._count(c.get("username", ""))
            masked["is_active"] = i == self._active_idx
            out.append(masked)
        return out

    def add_config(self, cfg: dict) -> dict:
        """Add a new SMTP config.  Returns the saved config."""
        cfg.setdefault("daily_limit", 500)
        cfg.setdefault("active", True)
        cfg.setdefault("host", "smtp.gmail.com")
        cfg.setdefault("port", 587)
        cfg.setdefault("use_tls", True)
        self.configs.append(cfg)
        _save_configs(self.configs, self._active_idx)
        return cfg

    def update_config(self, index: int, cfg: dict) -> dict:
        """Update an existing config by index."""
        if 0 <= index < len(self.configs):
            self.configs[index].update(cfg)
            _save_configs(self.configs, self._active_idx)
            return self.configs[index]
        raise IndexError(f"Config index {index} out of range")

    def remove_config(self, index: int):
        """Remove a config by index."""
        if 0 <= index < len(self.configs):
            self.configs.pop(index)
            if self._active_idx >= len(self.configs):
                self._active_idx = max(0, len(self.configs) - 1)
            _save_configs(self.configs, self._active_idx)
        else:
            raise IndexError(f"Config index {index} out of range")

    def set_active(self, index: int):
        """Manually set the active config and persist to disk."""
        if 0 <= index < len(self.configs):
            self._active_idx = index
            _save_configs(self.configs, self._active_idx)
        else:
            raise IndexError(f"Config index {index} out of range")

    def get_status(self) -> dict:
        """Return summary status of the pool."""
        self.counters = _load_counters()
        configs_status = []
        for i, c in enumerate(self.configs):
            sent = self._count(c.get("username", ""))
            limit = c.get("daily_limit", 500)
            configs_status.append(
                {
                    "index": i,
                    "username": c.get("username", ""),
                    "sender_name": c.get("sender_name", ""),
                    "daily_limit": limit,
                    "emails_sent_today": sent,
                    "remaining": max(0, limit - sent),
                    "active": i == self._active_idx,
                    "enabled": c.get("active", True),
                }
            )
        return {
            "total_configs": len(self.configs),
            "active_index": self._active_idx,
            "configs": configs_status,
        }

    # ---- core send ----

    def send_email(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        html_body: str,
        attachment_path: Optional[str] = None,
        qr_code_bytes: Optional[bytes] = None,
    ) -> dict:
        """Send an email, rotating SMTP configs on ANY failure.

        Tries each enabled config at most once.  Rotates immediately on
        any error (rate limit, auth, network, quota, etc.).  Returns the
        result from the successful attempt (or the last failure if all
        exhausted).  Daily limits are checked but NOT used to skip — the
        server itself will reject if over limit, triggering rotation.
        """
        self.configs, self._active_idx = _load_configs()
        self.counters = _load_counters()

        if not self.configs:
            return {
                "success": False,
                "to_email": to_email,
                "message": "No SMTP configurations available",
                "error": "No SMTP configurations",
                "config_used": None,
            }

        # Build ordered list of configs to try (active first, then others)
        enabled = [(i, c) for i, c in enumerate(self.configs) if c.get("active", True)]
        if not enabled:
            return {
                "success": False,
                "to_email": to_email,
                "message": "No enabled SMTP configurations",
                "error": "All SMTP configs disabled",
                "config_used": None,
            }

        # Sort: active index first, then the rest
        active_username = (
            self.configs[self._active_idx].get("username", "")
            if self._active_idx < len(self.configs)
            else ""
        )
        enabled.sort(key=lambda x: 0 if x[1].get("username") == active_username else 1)

        last_result = None
        for idx, cfg in enabled:
            username = cfg.get("username", "")

            result = self._send_with_config(
                cfg,
                to_email,
                to_name,
                subject,
                html_body,
                attachment_path,
                qr_code_bytes,
            )

            if result["success"]:
                # Increment counter
                self._increment(username)
                result["config_used"] = username
                result["config_index"] = idx
                # Update active index to this config (it's working)
                self._active_idx = idx
                return result

            last_result = result
            error_msg = result.get("error", "")

            if _is_rate_limit(error_msg):
                logger.warning(f"SMTP {username} rate-limited: {error_msg} — rotating")
                # Don't try this config again for this email
                continue
            elif _is_auth_error(error_msg):
                logger.error(f"SMTP {username} auth failure: {error_msg} — skipping")
                continue
            else:
                # Non-rate-limit error (network, etc.) — still try next config
                logger.warning(f"SMTP {username} failed: {error_msg} — trying next")
                continue

        # All configs exhausted
        if last_result:
            last_result["config_used"] = (
                enabled[-1][1].get("username") if enabled else None
            )
            last_result["all_configs_exhausted"] = True
            return last_result

        return {
            "success": False,
            "to_email": to_email,
            "message": "All SMTP configs exhausted or rate-limited",
            "error": "All SMTP configs exhausted",
            "config_used": None,
            "all_configs_exhausted": True,
        }

    # ---- internals ----

    def _send_with_config(
        self,
        cfg: dict,
        to_email,
        to_name,
        subject,
        html_body,
        attachment_path,
        qr_code_bytes,
    ) -> dict:
        """Send using a specific config.  Returns result dict."""
        result = {
            "success": False,
            "to_email": to_email,
            "message": "",
            "error": None,
        }
        try:
            msg = MIMEMultipart("related")
            msg["Subject"] = subject
            msg["From"] = (
                f"{cfg.get('sender_name', '')} <{cfg.get('sender_email', cfg.get('username', ''))}>"
            )
            msg["To"] = f"{to_name} <{to_email}>"
            msg["X-Mailer"] = "DCS-Freshers-Mailer"

            alt_part = MIMEMultipart("alternative")
            alt_part.attach(
                MIMEText("This email requires an HTML-enabled mail client.", "plain")
            )
            alt_part.attach(MIMEText(html_body, "html"))
            msg.attach(alt_part)

            if qr_code_bytes:
                qr_image = MIMEImage(qr_code_bytes, _subtype="png")
                qr_image.add_header("Content-ID", "<qrcode>")
                qr_image.add_header(
                    "Content-Disposition", "inline", filename="qrcode.png"
                )
                msg.attach(qr_image)

            if attachment_path and os.path.exists(attachment_path):
                with open(attachment_path, "rb") as f:
                    attach = MIMEApplication(
                        f.read(), Name=os.path.basename(attachment_path)
                    )
                attach["Content-Disposition"] = (
                    f'attachment; filename="{os.path.basename(attachment_path)}"'
                )
                msg.attach(attach)

            use_tls = cfg.get("use_tls", True)
            host = cfg.get("host", "smtp.gmail.com")
            port = int(cfg.get("port", 587))
            username = cfg.get("username", "")
            password = cfg.get("password", "")
            sender_email = cfg.get("sender_email", username)

            if use_tls:
                server = smtplib.SMTP(host, port, timeout=15)
                server.ehlo()
                server.starttls()
                server.ehlo()
            else:
                server = smtplib.SMTP_SSL(host, port, timeout=15)

            server.login(username, password)
            server.sendmail(sender_email, [to_email], msg.as_string())
            server.quit()

            result["success"] = True
            result["message"] = f"Email sent to {to_email}"

        except smtplib.SMTPAuthenticationError as e:
            result["error"] = f"Authentication failed: {e}"
            result["message"] = result["error"]
        except smtplib.SMTPException as e:
            result["error"] = f"SMTP error: {e}"
            result["message"] = result["error"]
        except FileNotFoundError as e:
            result["error"] = f"Attachment not found: {e}"
            result["message"] = result["error"]
        except Exception as e:
            result["error"] = f"Failed to send email: {e}"
            result["message"] = result["error"]

        return result

    def _count(self, username: str) -> int:
        """Get today's send count for a username."""
        return self.counters.get("counts", {}).get(username, 0)

    def _increment(self, username: str):
        """Increment today's send count for a username."""
        if "counts" not in self.counters:
            self.counters["counts"] = {}
        self.counters["counts"][username] = self.counters["counts"].get(username, 0) + 1
        _save_counters(self.counters)
