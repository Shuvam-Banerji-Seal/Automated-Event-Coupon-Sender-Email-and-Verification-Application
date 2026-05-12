#!/home/shuvam/.global-pymaster/bin/python
"""smtp_mailer.py
SMTP-based email service for 21MS Farewell Party coupon distribution.
Replaces GmailEmailService for the 21ms_farewell branch.
Uses TLS SMTP (default: smtp.gmail.com:587).
"""

import os
import time
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from typing import Optional, Callable


class SMTPMailer:
    """SMTP email service using standard smtplib.
    Configuration loaded entirely from environment variables.
    No OAuth required.
    """

    SMTP_CONFIG_FILE = "smtp_config.json"

    def __init__(self):
        """Load config from smtp_config.json (if exists) or environment. Raise if missing."""
        self.host = "smtp.gmail.com"
        self.port = 587
        self.username = ""
        self.password = ""
        self.sender_name = ""
        self.sender_email = ""
        self.use_tls = True

        # Try loading from UI-saved config first
        config_loaded = False
        if os.path.exists(self.SMTP_CONFIG_FILE):
            try:
                import json as _json

                with open(self.SMTP_CONFIG_FILE, "r") as _f:
                    cfg = _json.load(_f)
                self.host = cfg.get("host", self.host)
                self.port = int(cfg.get("port", self.port))
                self.username = cfg.get("username", "")
                self.password = cfg.get("password", "")
                self.sender_name = cfg.get("sender_name", "")
                self.sender_email = cfg.get("sender_email", "")
                self.use_tls = cfg.get("use_tls", True)
                config_loaded = bool(self.username and self.password)
            except Exception:
                pass

        # Fall back to environment variables
        if not config_loaded:
            self.host = os.getenv("SMTP_HOST", self.host)
            self.port = int(os.getenv("SMTP_PORT", str(self.port)))
            self.username = os.getenv("SMTP_USERNAME", self.username)
            self.password = os.getenv("SMTP_PASSWORD", self.password)
            self.sender_name = os.getenv("SMTP_SENDER_NAME", self.sender_name)
            self.sender_email = os.getenv("SMTP_SENDER_EMAIL", self.sender_email)
            self.use_tls = os.getenv("SMTP_USE_TLS", "True").lower() == "true"

        if not self.username or not self.password:
            raise EnvironmentError(
                "SMTPMailer missing credentials. Configure via Settings panel or .env file."
            )

    def test_connection(self) -> dict:
        """Attempt SMTP login and immediately disconnect.
        Returns: {"success": bool, "message": str, "host": str, "port": int, "username": str}
        Never raises — catches all exceptions and returns success=False with message.
        """
        result = {
            "success": False,
            "message": "Unknown error",
            "host": self.host,
            "port": self.port,
            "username": self.username,
        }
        try:
            if self.use_tls:
                server = smtplib.SMTP(self.host, self.port, timeout=10)
                server.ehlo()
                server.starttls()
                server.ehlo()
            else:
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=10)

            server.login(self.username, self.password)
            server.quit()

            result["success"] = True
            result["message"] = (
                f"Connected to {self.host}:{self.port} and authenticated successfully"
            )
        except smtplib.SMTPAuthenticationError as e:
            result["message"] = f"Authentication failed: {e}"
        except smtplib.SMTPException as e:
            result["message"] = f"SMTP error: {e}"
        except Exception as e:
            result["message"] = f"Connection failed: {e}"

        return result

    def send_email(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        html_body: str,
        attachment_path: Optional[str] = None,
        qr_code_bytes: Optional[bytes] = None,
    ) -> dict:
        """Send a single HTML email via SMTP.
        Args:
            to_email: Recipient email address
            to_name: Recipient display name (used in To: header)
            subject: Email subject line
            html_body: Full HTML string (already rendered Jinja2 template)
            attachment_path: Optional path to file attachment
            qr_code_bytes: Optional raw PNG bytes of QR code for CID embedding
        Returns:
            {"success": bool, "to_email": str, "message": str, "error": str or None}
        Uses MIMEMultipart('related') for HTML with embedded images (CID).
        Opens a NEW SMTP connection per call (thread-safe).
        """
        result = {
            "success": False,
            "to_email": to_email,
            "message": "",
            "error": None,
        }

        try:
            # Use 'related' multipart so CID images can be embedded
            msg = MIMEMultipart("related")
            msg["Subject"] = subject
            msg["From"] = f"{self.sender_name} <{self.sender_email}>"
            msg["To"] = f"{to_name} <{to_email}>"
            msg["X-Mailer"] = "21MS-Farewell-Mailer"

            # Create the alternative part (plain text + html)
            alt_part = MIMEMultipart("alternative")
            text_part = MIMEText(
                "This email requires an HTML-enabled mail client.",
                "plain",
            )
            html_part = MIMEText(html_body, "html")
            alt_part.attach(text_part)
            alt_part.attach(html_part)
            msg.attach(alt_part)

            # Attach QR code as embedded image with Content-ID
            if qr_code_bytes:
                from email.mime.image import MIMEImage

                qr_image = MIMEImage(qr_code_bytes, _subtype="png")
                qr_image.add_header("Content-ID", "<qrcode>")
                qr_image.add_header(
                    "Content-Disposition", "inline", filename="qrcode.png"
                )
                msg.attach(qr_image)

            if attachment_path:
                with open(attachment_path, "rb") as f:
                    attach = MIMEApplication(
                        f.read(), Name=os.path.basename(attachment_path)
                    )
                attach["Content-Disposition"] = (
                    f'attachment; filename="{os.path.basename(attachment_path)}"'
                )
                msg.attach(attach)

            if self.use_tls:
                server = smtplib.SMTP(self.host, self.port, timeout=10)
                server.ehlo()
                server.starttls()
                server.ehlo()
            else:
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=10)

            server.login(self.username, self.password)
            server.sendmail(self.sender_email, [to_email], msg.as_string())
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

    def send_batch(
        self,
        recipients: list[dict],
        subject: str,
        template_renderer: Callable,
        delay_seconds: float = 1.0,
        on_success: Optional[Callable] = None,
        on_failure: Optional[Callable] = None,
    ) -> dict:
        """Send emails to a batch of recipients.
        Args:
            recipients: List of {'email': str, 'name': str, ...}
            subject: Email subject
            template_renderer: Callable(recipient_dict) -> html_string
            delay_seconds: Pause between sends (default 1.0 to avoid spam flags)
            on_success: Optional callback(recipient, result)
            on_failure: Optional callback(recipient, result)
        Returns:
            {"total": int, "sent": int, "failed": int, "failed_list": [...], "duration_seconds": float}
        """
        total = len(recipients)
        sent = 0
        failed = 0
        failed_list = []
        start_time = time.time()

        for i, recipient in enumerate(recipients, 1):
            email = recipient.get("email", "")
            name = recipient.get("name", email.split("@")[0])

            print(
                f"[21MS Farewell Mailer] Sending {i}/{total} → {email} ... ",
                end="",
                flush=True,
            )

            try:
                html_body = template_renderer(recipient)
                result = self.send_email(email, name, subject, html_body)

                if result["success"]:
                    print("✓ Sent")
                    sent += 1
                    if on_success:
                        on_success(recipient, result)
                else:
                    print(f"✗ Failed: {result['error']}")
                    failed += 1
                    failed_list.append({"email": email, "error": result["error"]})
                    if on_failure:
                        on_failure(recipient, result)

            except Exception as e:
                print(f"✗ Failed: {e}")
                failed += 1
                failed_list.append({"email": email, "error": str(e)})
                if on_failure:
                    on_failure(recipient, {"success": False, "error": str(e)})

            if i < total:
                time.sleep(delay_seconds)

        duration = time.time() - start_time

        return {
            "total": total,
            "sent": sent,
            "failed": failed,
            "failed_list": failed_list,
            "duration_seconds": round(duration, 2),
        }
