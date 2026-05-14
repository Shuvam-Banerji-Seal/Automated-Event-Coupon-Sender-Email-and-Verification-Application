#!/usr/bin/env python3
"""
Email Coupon System - Flask Application
Main application entry point with integrated services
"""

import os
import json
import base64
import logging
import time
import threading
import shutil
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import secrets

# Import our services
from src.coupons import CouponManager
from src.data import CSVManager
from src.auth import GoogleAuthService, GmailEmailService
from src.smtp_mailer import SMTPMailer  # 21MS_FAREWELL BRANCH

# Load environment variables
load_dotenv()

# 21MS_FAREWELL BRANCH: Load event config from environment
EVENT_NAME = os.getenv("EVENT_NAME", "21MS Farewell Party")
EVENT_DATE = os.getenv("EVENT_DATE", "To Be Announced")
EVENT_TIME = os.getenv("EVENT_TIME", "To Be Announced")
EVENT_VENUE = os.getenv("EVENT_VENUE", "IISER Kolkata Campus")
ORGANIZER_BATCH = "22MS Batch"
ORGANIZER_INSTITUTION = "IISER Kolkata"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask application
app = Flask(__name__)

# Configuration
app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]

# zrok tunnel host pattern (any shares.zrok.io subdomain)
ZROK_HOST_SUFFIX = ".shares.zrok.io"


@app.before_request
def restrict_zrok_tunnel():
    """Block admin pages when accessed through the zrok public tunnel."""
    host = request.host if request.host else ""
    if ZROK_HOST_SUFFIX in host:
        # Allow only scanner-related paths through the tunnel
        allowed_prefixes = (
            "/scanner",
            "/verify-coupon",
            "/coupon-status",
            "/favicon.ico",
            "/static/",
        )
        path = request.path
        if not any(path.startswith(p) for p in allowed_prefixes):
            return jsonify(
                {
                    "error": "Access denied. Use the scanner page.",
                    "scanner_url": f"{request.scheme}://{request.host}/scanner",
                }
            ), 403


app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max file size
app.config["UPLOAD_FOLDER"] = "uploads"

# Ensure upload directory exists
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Initialize services
try:
    csv_manager = CSVManager()
    coupon_manager = CouponManager(csv_manager=csv_manager)
    google_auth_service = GoogleAuthService()
    logger.info("Services initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize services: {str(e)}")
    csv_manager = None
    coupon_manager = None
    google_auth_service = None


# S-08: Simple in-memory rate limiter for verify-coupon
rate_limit_store = defaultdict(list)
RATE_LIMIT_MAX = 10  # max attempts
RATE_LIMIT_WINDOW = 60  # seconds


def check_rate_limit(ip: str) -> bool:
    """Returns True if request is allowed, False if rate limited."""
    now = datetime.now()
    window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW)
    rate_limit_store[ip] = [t for t in rate_limit_store[ip] if t > window_start]
    if len(rate_limit_store[ip]) >= RATE_LIMIT_MAX:
        return False
    rate_limit_store[ip].append(now)
    return True


# Authentication helper functions
def login_required(f):
    """Decorator to require Google authentication"""
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


def _get_server_ip():
    """Get the server's LAN IP address for access-control comparison."""
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# Cache the server IP at startup
SERVER_LAN_IP = _get_server_ip()
ADMIN_ALLOWED_IPS = {"127.0.0.1", "::1", SERVER_LAN_IP}


def admin_only(f):
    """Decorator to restrict route access to the host machine only.
    Remote devices on the LAN are denied access (403) and redirected to /scanner.
    This protects all management routes (sender, SMTP config, email sending, etc.)
    while keeping the scanner accessible to staff devices on the network.
    """
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):
        client_ip = request.remote_addr or "unknown"
        if client_ip not in ADMIN_ALLOWED_IPS:
            logger.warning(f"Admin access denied for {client_ip} on {request.path}")
            if request.is_json or request.content_type == "application/json":
                return jsonify(
                    {
                        "success": False,
                        "error": "Access denied. Admin panel is only available on the host machine.",
                    }
                ), 403
            return redirect(url_for("scanner"))
        return f(*args, **kwargs)

    return decorated_function


def get_current_user():
    """Get current authenticated user from session"""
    return session.get("user")


# Authentication routes
@app.route("/login")
def login():
    """Show login page or initiate Google OAuth login"""
    # If user is already logged in, redirect to dashboard
    if "user" in session:
        return redirect(url_for("dashboard"))

    # If OAuth is initiated (has 'start' parameter), begin OAuth flow
    if request.args.get("start") == "true":
        if not google_auth_service or not google_auth_service.is_configured():
            return render_template(
                "login_error.html",
                error="Google OAuth is not configured. Please check your environment variables.",
            )

        try:
            # Use configured redirect URI from .env, fallback to dynamic detection
            configured_redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
            if configured_redirect_uri:
                redirect_uri = configured_redirect_uri
            else:
                # Fallback to dynamic detection
                current_host = request.host
                redirect_uri = f"http://{current_host}/auth/callback"

            authorization_url, state = google_auth_service.get_authorization_url(
                redirect_uri
            )
            session["oauth_state"] = state
            session["oauth_redirect_uri"] = redirect_uri  # Store for callback
            return redirect(authorization_url)
        except Exception as e:
            logger.error(f"Error initiating OAuth: {e}")
            return render_template("login_error.html", error=str(e))

    # Show login page
    return render_template("login.html")


@app.route("/auth/callback")
def auth_callback():
    """Handle Google OAuth callback"""
    if not google_auth_service:
        return render_template(
            "login_error.html", error="Google OAuth service not available"
        )

    try:
        # Get authorization code from callback
        authorization_code = request.args.get("code")
        state = request.args.get("state")

        if not authorization_code:
            return render_template(
                "login_error.html", error="Authorization code not received"
            )

        # Verify state parameter
        if state != session.get("oauth_state"):
            return render_template("login_error.html", error="Invalid state parameter")

        # Get the redirect URI used for this OAuth flow
        redirect_uri = session.get("oauth_redirect_uri")

        # Exchange code for tokens
        token_data = google_auth_service.exchange_code_for_tokens(
            authorization_code, state, redirect_uri
        )

        # Store user data in session
        session["user"] = token_data["user_info"]
        session["oauth_tokens"] = {
            "access_token": token_data["access_token"],
            "refresh_token": token_data["refresh_token"],
            "token_uri": token_data["token_uri"],
            "client_id": token_data["client_id"],
            "client_secret": token_data["client_secret"],
            "scopes": token_data["scopes"],
        }

        # Clear state and redirect URI
        session.pop("oauth_state", None)
        session.pop("oauth_redirect_uri", None)

        logger.info(f"User {token_data['user_info']['email']} logged in successfully")
        return redirect(url_for("dashboard"))

    except Exception as e:
        logger.error(f"Error in OAuth callback: {e}")
        return render_template("login_error.html", error=str(e))


@app.route("/logout")
def logout():
    """Logout user and clear session"""
    user_email = session.get("user", {}).get("email", "Unknown")
    session.clear()
    logger.info(f"User {user_email} logged out")
    return redirect(url_for("login"))


# Main routes
@app.route("/")
@admin_only
def dashboard():
    """21MS_FAREWELL BRANCH: Main dashboard route - admin only"""
    user = get_current_user()
    return render_template("sender.html", user=user)


@app.route("/sender")
@admin_only
def sender():
    """21MS_FAREWELL BRANCH: Sender interface route - admin only"""
    user = get_current_user()
    return render_template("sender.html", user=user)


@app.route("/scanner")
def scanner():
    """QR scanner interface route - no authentication required"""
    return render_template("scanner.html")


# API endpoints
@app.route("/send-emails", methods=["POST"])
@login_required
def send_emails():
    """Send email campaign with coupon generation using authenticated user's Gmail"""
    if not all([coupon_manager, csv_manager, google_auth_service]):
        return jsonify({"success": False, "error": "Services not initialized"}), 500

    try:
        # Get current user and their OAuth tokens
        user = get_current_user()
        oauth_tokens = session.get("oauth_tokens")

        if not user or not oauth_tokens:
            return jsonify({"success": False, "error": "User not authenticated"}), 401

        # Create Gmail service with user's credentials
        credentials = google_auth_service.create_credentials_from_session(oauth_tokens)
        if not credentials:
            return jsonify(
                {"success": False, "error": "Failed to create credentials"}
            ), 401

        gmail_service = GmailEmailService(credentials)

        data = request.get_json()
        event_name = data.get("event_name", "Special Event")

        # Read recipients from CSV
        recipients = csv_manager.read_recipients()
        if not recipients:
            return jsonify({"success": False, "error": "No recipients found"}), 400

        # Generate coupons for all recipients
        logger.info(f"Generating coupons for {len(recipients)} recipients")
        coupon_results = coupon_manager.generate_coupons_batch(recipients, event_name)

        if coupon_results["generated"] == 0:
            return jsonify(
                {"success": False, "error": "Failed to generate any coupons"}
            ), 500

        # Prepare email data with coupon information
        email_recipients = []
        for coupon in coupon_results["coupons"]:
            email_recipients.append(
                {
                    "email": coupon["email"],
                    "coupon_id": coupon["coupon_id"],
                    "event_name": coupon["event_name"],
                    "qr_code_base64": coupon["qr_code_base64"],
                    "verification_code": coupon[
                        "verification_code"
                    ],  # Include 6-digit code
                    "subject": f"Your Digital Coupon for {event_name}",
                }
            )

        # Send emails with progress tracking using Gmail API
        def progress_callback(progress):
            logger.info(
                f"Gmail email progress: {progress['current']}/{progress['total']}"
            )

        # Create template renderer function
        def template_renderer(template_name, context):
            return render_template(template_name, **context)

        sender_email = user["email"]
        logger.info(
            f"Sending emails from {sender_email} to {len(email_recipients)} recipients via Gmail API"
        )

        email_results = gmail_service.send_batch_emails(
            sender_email, email_recipients, template_renderer, progress_callback
        )

        # Update coupon status for successfully sent emails
        successful_emails = []
        failed_emails = []

        for result in email_results["results"]:
            if result.success:
                successful_emails.append(result.recipient)
                # Find the coupon for this recipient and mark as sent
                for coupon in coupon_results["coupons"]:
                    if coupon["email"] == result.recipient:
                        coupon_manager.mark_coupon_sent(coupon["coupon_id"])
                        break
            else:
                failed_emails.append(
                    {
                        "email": result.recipient,
                        "error": result.error_message,
                        "timestamp": result.timestamp,
                    }
                )

        # Save failed emails to CSV if any failures occurred
        failure_log_file = None
        if failed_emails:
            failure_log_file = csv_manager.save_failed_emails(failed_emails, event_name)
            logger.warning(
                f"Saved {len(failed_emails)} failed emails to {failure_log_file}"
            )

        # Save organizer credentials for thank you emails during verification
        csv_manager.save_organizer_credentials(user, oauth_tokens, event_name)

        # Update OAuth tokens in session if they were refreshed
        updated_credentials = gmail_service.credentials
        if updated_credentials.token != oauth_tokens.get("access_token"):
            session["oauth_tokens"]["access_token"] = updated_credentials.token

        return jsonify(
            {
                "success": True,
                "sender_email": sender_email,
                "coupons_generated": coupon_results["generated"],
                "emails_sent": email_results["sent"],
                "emails_failed": email_results["failed"],
                "total_recipients": len(recipients),
                "successful_emails": successful_emails,
                "failed_emails": failed_emails,
                "failure_log_file": failure_log_file,
                "start_time": email_results["start_time"],
                "end_time": email_results["end_time"],
            }
        )

    except Exception as e:
        logger.error(f"Error in send_emails: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


# 21MS_FAREWELL BRANCH: New route for SMTP-based email sending
@app.route("/send-farewell-emails", methods=["POST"])
@admin_only
def send_farewell_emails():
    """21MS_FAREWELL BRANCH: Send coupon emails via SMTP. Does not require OAuth login.

    Request body (JSON):
    {"event_name": "21MS Farewell Party"}
    """
    if not all([coupon_manager, csv_manager]):
        return jsonify({"success": False, "error": "Services not initialized"}), 500

    try:
        data = request.get_json() or {}
        event_name = data.get("event_name", EVENT_NAME)

        recipients = csv_manager.read_recipients()
        if not recipients:
            return jsonify(
                {
                    "success": False,
                    "error": "No recipients found. Please upload a CSV file first.",
                }
            ), 400

        # Filter out recipients who already have coupon records (ANY status)
        # This prevents duplicate coupons when uploading new CSV with old names
        import csv as csv_module

        existing_emails = set()
        try:
            with open(csv_manager.coupons_file, "r", newline="", encoding="utf-8") as f:
                reader = csv_module.DictReader(f)
                for row in reader:
                    if row.get("email"):
                        existing_emails.add(row.get("email", "").lower())
        except FileNotFoundError:
            pass

        pending_recipients = []
        for r in recipients:
            email = r.get("email", "").lower()
            if email and email not in existing_emails:
                pending_recipients.append(r)

        if not pending_recipients:
            return jsonify(
                {
                    "success": False,
                    "error": "All recipients have already received their invitations.",
                }
            ), 400

        logger.info(
            f"Sending invitations to {len(pending_recipients)} unsent recipients"
        )

        smtp_mailer = SMTPMailer()

        coupon_results = coupon_manager.generate_coupons_batch(
            pending_recipients, event_name
        )

        if coupon_results["generated"] == 0:
            return jsonify(
                {"success": False, "error": "Failed to generate any coupons"}
            ), 500

        email_recipients = []
        for coupon in coupon_results["coupons"]:
            email_recipients.append(
                {
                    "name": coupon.get(
                        "name", coupon.get("email", "Guest").split("@")[0]
                    ),
                    "email": coupon["email"],
                    "coupon_id": coupon["coupon_id"],
                    "event_name": coupon["event_name"],
                    "qr_code_base64": coupon["qr_code_base64"],
                    "verification_code": coupon["verification_code"],
                    "attendee_name": coupon.get(
                        "name", coupon.get("email", "Guest").split("@")[0]
                    ),
                    "attendee_email": coupon["email"],
                    "event_date": EVENT_DATE,
                    "event_time": EVENT_TIME,
                    "event_venue": EVENT_VENUE,
                    "organizer_batch": ORGANIZER_BATCH,
                    "organizer_institution": ORGANIZER_INSTITUTION,
                }
            )

        # Build lookup for recipient options
        email_to_opts = {r.get("email", "").lower(): r for r in pending_recipients}

        def render_invitation(recipient, qr_src):
            opts = email_to_opts.get(recipient["attendee_email"].lower(), {})
            return render_template(
                "farewell/invitation.html",
                attendee_name=recipient["attendee_name"],
                attendee_email=recipient["attendee_email"],
                event_name=recipient["event_name"],
                event_date=recipient["event_date"],
                event_time=recipient["event_time"],
                event_venue=recipient["event_venue"],
                qr_code_base64=recipient["qr_code_base64"],
                qr_code_src=qr_src,
                verification_code=recipient["verification_code"],
                coupon_id=recipient["coupon_id"],
                organizer_batch=recipient["organizer_batch"],
                organizer_institution=recipient["organizer_institution"],
                include_qr=opts.get("include_qr", True),
            )

        subject = f"You're Invited! {event_name}"

        sent = 0
        failed = 0
        failed_list = []

        for i, recipient in enumerate(email_recipients, 1):
            logger.info(
                f"Sending email {i}/{len(email_recipients)} to {recipient['email']}"
            )

            try:
                # Determine if this recipient gets a QR gala entry pass
                r_opts = email_to_opts.get(recipient["attendee_email"].lower(), {})
                has_qr = r_opts.get("include_qr", True)
                if isinstance(has_qr, str):
                    has_qr = has_qr.lower() not in ("false", "0", "no")

                if has_qr:
                    # Gala dinner invitee: embed QR as CID image
                    qr_bytes = base64.b64decode(recipient["qr_code_base64"])
                    html_body = render_invitation(recipient, "cid:qrcode")
                else:
                    # Farewell-only invitee: no QR entry pass
                    qr_bytes = None
                    html_body = render_invitation(recipient, "")

                result = smtp_mailer.send_email(
                    to_email=recipient["email"],
                    to_name=recipient["attendee_name"],
                    subject=subject,
                    html_body=html_body,
                    qr_code_bytes=qr_bytes,
                )

                if result["success"]:
                    for coupon in coupon_results["coupons"]:
                        if coupon["email"] == recipient["email"]:
                            coupon_manager.mark_coupon_sent(coupon["coupon_id"])
                            break
                    sent += 1
                else:
                    failed += 1
                    failed_list.append(
                        {
                            "email": recipient["email"],
                            "error": result.get("error"),
                            "timestamp": datetime.now().isoformat(),
                        }
                    )

            except Exception as e:
                logger.error(f"Failed to send to {recipient['email']}: {str(e)}")
                failed += 1
                failed_list.append(
                    {
                        "email": recipient["email"],
                        "error": str(e),
                        "timestamp": datetime.now().isoformat(),
                    }
                )

            if i < len(email_recipients):
                time.sleep(1.0)

        failure_log_file = None
        if failed_list:
            failure_log_file = csv_manager.save_failed_emails(failed_list, event_name)

        return jsonify(
            {
                "success": True,
                "emails_sent": sent,
                "emails_failed": failed,
                "total_recipients": len(pending_recipients),
                "failed_list": failed_list,
                "failure_log_file": failure_log_file,
            }
        )

    except Exception as e:
        logger.error(f"Error in send_farewell_emails: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/verify-coupon", methods=["POST"])
def verify_coupon():
    """Verify QR coupon or verification code and mark as used"""
    # S-08: Rate limit by IP
    client_ip = request.remote_addr or "unknown"
    if not check_rate_limit(client_ip):
        logger.warning(f"Rate limit exceeded for {client_ip}")
        return jsonify(
            {
                "success": False,
                "error": "Too many attempts. Please try again later.",
                "error_code": "RATE_LIMITED",
            }
        ), 429

    if not coupon_manager:
        return jsonify(
            {"success": False, "error": "Coupon manager not initialized"}
        ), 500

    try:
        data = request.get_json()
        encrypted_data = data.get("encrypted_data")
        verification_code = data.get("verification_code")
        email = data.get("email")

        if not email:
            return jsonify(
                {
                    "success": False,
                    "error": "Email is required",
                    "error_code": "MISSING_EMAIL",
                }
            ), 400

        # Check if this is a verification code (6 digits) or encrypted data
        if (
            verification_code
            and len(verification_code) == 6
            and verification_code.isdigit()
        ):
            # Validate using verification code
            validation_result = coupon_manager.validate_coupon_by_code(
                verification_code, email
            )
        elif encrypted_data:
            # Validate using encrypted data (old method)
            validation_result = coupon_manager.validate_coupon(encrypted_data, email)
        else:
            return jsonify(
                {
                    "success": False,
                    "error": "Either verification_code (6 digits) or encrypted_data is required",
                    "error_code": "MISSING_DATA",
                }
            ), 400

        # S-09: Use atomic validate-and-mark for verification code path (TOCTOU safe)
        if (
            verification_code
            and len(verification_code) == 6
            and verification_code.isdigit()
        ):
            atomic_result = coupon_manager.validate_and_mark_used(
                verification_code, email
            )
            if not atomic_result.get("valid"):
                return jsonify(
                    {
                        "success": False,
                        "error": atomic_result.get("error", "Invalid coupon"),
                        "error_code": atomic_result.get("error_code", "INVALID"),
                    }
                )
            coupon_id = atomic_result["coupon_id"]
            validation_result = atomic_result
        else:
            # Encrypted data path (no TOCTOU fix needed - encrypted data is single-use)
            if not validation_result.get("valid"):
                return jsonify(
                    {
                        "success": False,
                        "error": validation_result.get("error", "Invalid coupon"),
                        "error_code": validation_result.get("error_code", "INVALID"),
                        "used_at": validation_result.get("used_at"),
                    }
                )
            coupon_id = validation_result["coupon_id"]
            if not coupon_manager.mark_coupon_used(coupon_id):
                return jsonify(
                    {
                        "success": False,
                        "error": "Failed to mark coupon as used",
                        "error_code": "UPDATE_FAILED",
                    }
                ), 500

        if coupon_id:
            # 21MS_FAREWELL BRANCH: Send thank you email via SMTP (no OAuth required)
            def send_thank_you_async():
                try:
                    smtp_mailer = SMTPMailer()

                    attendance_data = {
                        "attendee_name": validation_result.get(
                            "attendee_name", email.split("@")[0]
                        ),
                        "attendee_email": email,
                        "event_name": validation_result.get("event_name", EVENT_NAME),
                        "verification_code": validation_result.get(
                            "verification_code", ""
                        ),
                        "coupon_id": coupon_id,
                        "organizer_batch": ORGANIZER_BATCH,
                        "organizer_institution": ORGANIZER_INSTITUTION,
                    }

                    with app.app_context():
                        html_content = render_template(
                            "farewell/thank_you.html", **attendance_data
                        )

                    subject = f"Welcome to {attendance_data['event_name']}!"

                    result = smtp_mailer.send_email(
                        to_email=email,
                        to_name=attendance_data["attendee_name"],
                        subject=subject,
                        html_body=html_content,
                    )

                    if result["success"]:
                        logger.info(
                            f"Thank you email sent successfully to {email} via SMTP"
                        )
                    else:
                        logger.warning(
                            f"Failed to send thank you email to {email}: {result['error']}"
                        )

                except Exception as e:
                    logger.error(f"Error sending thank you email via SMTP: {str(e)}")
                    import traceback

                    logger.error(traceback.format_exc())

            # Start email sending in background thread
            email_thread = threading.Thread(target=send_thank_you_async)
            email_thread.daemon = True
            email_thread.start()

            # Return immediately without waiting for email
            return jsonify(
                {
                    "success": True,
                    "message": "Coupon verified and marked as used",
                    "coupon_id": coupon_id,
                    "email": validation_result["email"],
                    "event_name": validation_result["event_name"],
                    "created_at": validation_result["created_at"],
                    "thank_you_email": "sending",  # Indicate email is being sent in background
                }
            )
        else:
            return jsonify(
                {
                    "success": False,
                    "error": "Failed to mark coupon as used",
                    "error_code": "UPDATE_FAILED",
                }
            ), 500

    except Exception as e:
        logger.error(f"Error in verify_coupon: {str(e)}")
        return jsonify(
            {
                "success": False,
                "error": "System error during verification",
                "error_code": "SYSTEM_ERROR",
            }
        ), 500


@app.route("/coupon-status/<coupon_id>")
def coupon_status(coupon_id):
    """Get coupon status by ID"""
    if not coupon_manager:
        return jsonify(
            {"success": False, "error": "Coupon manager not initialized"}
        ), 500

    try:
        status_result = coupon_manager.get_coupon_status(coupon_id)

        if not status_result.get("found"):
            return jsonify(
                {
                    "success": False,
                    "error": status_result.get("error", "Coupon not found"),
                }
            ), 404

        return jsonify(
            {
                "success": True,
                "coupon_id": status_result["coupon_id"],
                "email": status_result["email"],
                "status": status_result["status"],
                "sent_at": status_result["sent_at"],
                "used_at": status_result["used_at"],
            }
        )

    except Exception as e:
        logger.error(f"Error getting coupon status: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/preview-csv", methods=["POST"])
@admin_only
def preview_csv():
    """Upload CSV and return its contents for preview with column mapping."""
    if not csv_manager:
        return jsonify({"success": False, "error": "CSV manager not initialized"}), 500
    try:
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file uploaded"}), 400
        file = request.files["file"]
        if not file.filename or not file.filename.lower().endswith(".csv"):
            return jsonify({"success": False, "error": "File must be a CSV"}), 400
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)
        import csv as csv_module

        rows = []
        headers = []
        raw = open(filepath, "r", encoding="utf-8-sig").read()
        reader = csv_module.DictReader(raw.splitlines())
        headers = reader.fieldnames or []
        for row in reader:
            rows.append({k: v for k, v in row.items() if k})
        return jsonify(
            {
                "success": True,
                "headers": headers,
                "rows": rows,
                "filepath": filepath,
                "total": len(rows),
            }
        )
    except Exception as e:
        logger.error(f"Error previewing CSV: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/confirm-upload", methods=["POST"])
@admin_only
def confirm_upload():
    """Confirm CSV upload with column mapping and per-recipient options."""
    if not csv_manager:
        return jsonify({"success": False, "error": "CSV manager not initialized"}), 500
    try:
        data = request.get_json()
        filepath = data.get("filepath", "")
        email_col = data.get("email_col", "")
        name_col = data.get("name_col", "")
        recipients_data = data.get("recipients", [])

        # S-10: Prevent path traversal - validate filepath is within uploads folder
        if not filepath or not os.path.exists(filepath):
            return jsonify({"success": False, "error": "Uploaded file not found"}), 400
        upload_dir = os.path.abspath(app.config["UPLOAD_FOLDER"])
        abs_path = os.path.abspath(filepath)
        if not abs_path.startswith(upload_dir):
            logger.warning(f"Path traversal attempt blocked: {filepath}")
            return jsonify({"success": False, "error": "Invalid file path"}), 400
        if not email_col:
            return jsonify(
                {"success": False, "error": "Email column must be selected"}
            ), 400

        import csv as csv_module

        valid_recipients = []
        invalid_count = 0
        errors = []

        raw = open(filepath, "r", encoding="utf-8-sig").read()
        reader = csv_module.DictReader(raw.splitlines())
        for i, row in enumerate(reader):
            email = row.get(email_col, "").strip().lower()
            if not email:
                invalid_count += 1
                continue
            if not csv_manager.validate_email_format(email):
                invalid_count += 1
                errors.append(f"Invalid email at row {i + 2}: {email}")
                continue
            name = row.get(name_col, "").strip() if name_col else ""
            if not name:
                name = email.split("@")[0]
            # Find per-recipient options
            recipient_opts = {}
            for rd in recipients_data:
                if rd.get("email", "").lower() == email:
                    recipient_opts = rd
                    break
            valid_recipients.append(
                {
                    "email": email,
                    "name": name,
                    "include_dinner": recipient_opts.get("include_dinner", True),
                    "include_lunch": recipient_opts.get("include_lunch", True),
                    "include_qr": recipient_opts.get("include_qr", True),
                }
            )

        if not valid_recipients:
            return jsonify(
                {
                    "success": False,
                    "error": "No valid email addresses found in CSV",
                    "details": errors,
                }
            ), 400

        # Write confirmed recipients to the CSV file used by the system
        with open(csv_manager.recipients_file, "w", newline="", encoding="utf-8") as f:
            writer = csv_module.DictWriter(
                f,
                fieldnames=[
                    "email",
                    "name",
                    "include_dinner",
                    "include_lunch",
                    "include_qr",
                ],
            )
            writer.writeheader()
            for r in valid_recipients:
                writer.writerow(r)

        # NEVER delete coupons.csv — existing coupon records must persist
        # New coupons will be generated only for NEW recipients on send

        logger.info(
            f"Confirmed {len(valid_recipients)} recipients (invalid: {invalid_count})"
        )

        return jsonify(
            {
                "success": True,
                "message": f"Confirmed {len(valid_recipients)} recipients ({invalid_count} skipped)",
                "total": len(valid_recipients),
                "invalid": invalid_count,
                "errors": errors[:5],
            }
        )
    except Exception as e:
        logger.error(f"Error confirming upload: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/preview-email", methods=["POST"])
@admin_only
def preview_email():
    """Render email preview HTML for a recipient. Accepts optional template_type param."""
    try:
        data = request.get_json()
        email = data.get("email", "")
        name = data.get("name", email.split("@")[0])
        code = data.get("verification_code", "123456")
        coupon_id = data.get("coupon_id", "preview-0000")
        template_type = data.get("template_type", "invitation")

        # Determine if this recipient gets a QR gala entry pass
        include_qr = data.get("include_qr", True)
        if isinstance(include_qr, str):
            include_qr = include_qr.lower() not in ("false", "0", "no")

        if include_qr:
            # Generate a QR for preview
            from src.coupons import CouponManager

            cm = CouponManager()
            qr = cm.create_qr_code('{"v":"' + code + '","e":"' + email + '"}')
            qr_src = "data:image/png;base64," + qr
        else:
            # Farewell-only: no QR or verification code
            qr = ""
            qr_src = ""
            code = ""

        ctx = {
            "attendee_name": name,
            "attendee_email": email,
            "event_name": EVENT_NAME,
            "event_date": EVENT_DATE,
            "event_time": EVENT_TIME,
            "event_venue": EVENT_VENUE,
            "qr_code_base64": qr,
            "qr_code_src": qr_src,
            "verification_code": code,
            "coupon_id": coupon_id,
            "organizer_batch": ORGANIZER_BATCH,
            "organizer_institution": ORGANIZER_INSTITUTION,
            "include_qr": include_qr,
        }
        tpl_path = f"farewell/{template_type}.html"
        try:
            html = render_template(tpl_path, **ctx)
        except Exception:
            html = render_template("farewell/invitation.html", **ctx)

        subject = f"You're Invited! {EVENT_NAME}"
        if template_type == "lunch":
            subject = f"Lunch Invitation - {EVENT_NAME}"
        elif template_type == "dinner":
            subject = f"Dinner Invitation - {EVENT_NAME}"

        return jsonify(
            {
                "success": True,
                "html": html,
                "subject": subject,
                "template": template_type,
            }
        )
    except Exception as e:
        logger.error(f"Error previewing email: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/preview-template", methods=["POST"])
@admin_only
def preview_template():
    """Render a snippet of the current template for live preview."""
    try:
        data = request.get_json()
        template_type = data.get("template_type", "invitation")
        content = data.get("content", "")

        # Validate the HTML is well-formed by wrapping in basic structure
        # S-13: Use SandboxedEnvironment to prevent SSTI
        from jinja2.sandbox import SandboxedEnvironment
        import traceback

        # Try to render with dummy data
        env = SandboxedEnvironment()
        try:
            tmpl = env.from_string(content)
            rendered = tmpl.render(
                attendee_name="Preview User",
                attendee_email="preview@example.com",
                event_name=EVENT_NAME,
                event_date=EVENT_DATE,
                event_time=EVENT_TIME,
                event_venue=EVENT_VENUE,
                qr_code_base64="",
                qr_code_src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                verification_code="123456",
                coupon_id="preview-0000",
                organizer_batch=ORGANIZER_BATCH,
                organizer_institution=ORGANIZER_INSTITUTION,
            )
            return jsonify({"success": True, "html": rendered})
        except Exception as e:
            return jsonify({"success": False, "error": f"Template error: {str(e)}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/upload-csv", methods=["POST"])
@admin_only
def upload_csv():
    """Handle CSV file uploads and validation"""
    if not csv_manager:
        return jsonify({"success": False, "error": "CSV manager not initialized"}), 500
    try:
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file uploaded"}), 400
        file = request.files["file"]
        if file.filename == "":
            return jsonify({"success": False, "error": "No file selected"}), 400
        if not file.filename or not file.filename.lower().endswith(".csv"):
            return jsonify({"success": False, "error": "File must be a CSV"}), 400
        data = request.form
        reset_coupons = data.get("reset_coupons", "false").lower() == "true"
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)
        validation_result = csv_manager.validate_recipients_file(filepath)
        if not validation_result["valid"]:
            os.remove(filepath)
            return jsonify(
                {
                    "success": False,
                    "error": "Invalid CSV file",
                    "details": validation_result,
                }
            ), 400
        backup_created = ""
        if reset_coupons and os.path.exists(csv_manager.coupons_file):
            backup_created = csv_manager.backup_current_data()
        shutil.move(filepath, csv_manager.recipients_file)
        coupons_reset = False
        if reset_coupons:
            coupons_reset = csv_manager.reset_coupons_for_fresh_upload()
        logger.info(
            f"CSV uploaded successfully. Reset coupons: {coupons_reset}, Backup: {backup_created}"
        )
        return jsonify(
            {
                "success": True,
                "message": "CSV file uploaded successfully",
                "total_rows": validation_result["total_rows"],
                "valid_emails": validation_result["valid_emails"],
                "invalid_emails": validation_result["invalid_emails"],
                "coupons_reset": coupons_reset,
                "backup_created": backup_created,
            }
        )
    except Exception as e:
        logger.error(f"Error uploading CSV: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/failed-emails-logs")
@admin_only
@login_required
def get_failed_emails_logs():
    """Get list of failed email log files"""
    try:
        logs_dir = "logs"
        if not os.path.exists(logs_dir):
            return jsonify({"success": True, "logs": []})

        log_files = []
        for filename in os.listdir(logs_dir):
            if filename.startswith("failed_emails_") and filename.endswith(".csv"):
                filepath = os.path.join(logs_dir, filename)
                stat = os.stat(filepath)
                log_files.append(
                    {
                        "filename": filename,
                        "filepath": filepath,
                        "size": stat.st_size,
                        "created": datetime.fromtimestamp(stat.st_ctime).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    }
                )

        # Sort by creation time, newest first
        log_files.sort(key=lambda x: x["created"], reverse=True)

        return jsonify({"success": True, "logs": log_files})

    except Exception as e:
        logger.error(f"Error getting failed email logs: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/download-failed-emails/<filename>")
@admin_only
def download_failed_emails(filename):
    """Download a specific failed emails log file"""
    try:
        # S-11: Prevent path traversal
        safe_name = secure_filename(filename)
        if not safe_name.startswith("failed_emails_") or not safe_name.endswith(".csv"):
            return jsonify({"error": "Invalid filename"}), 400

        logs_dir = os.path.abspath("logs")
        filepath = os.path.join(logs_dir, safe_name)
        if not filepath.startswith(logs_dir) or not os.path.exists(filepath):
            return jsonify({"error": "File not found"}), 404

        from flask import send_file

        return send_file(filepath, as_attachment=True, download_name=safe_name)

    except Exception as e:
        logger.error(f"Error downloading failed emails file: {str(e)}")
        return jsonify({"error": str(e)}), 500


# SQLite backup integrity check
@app.route("/backup-check")
@admin_only
def backup_check():
    """Verify CSV ↔ SQLite consistency and repair if needed."""
    if not csv_manager:
        return jsonify({"success": False, "error": "Not initialized"}), 500
    try:
        integrity = csv_manager.db.verify_integrity(csv_manager.coupons_file)
        if not integrity.get("match") and csv_manager.coupons_file:
            repaired = csv_manager.db.repair_from_csv(csv_manager.coupons_file)
            integrity["repaired"] = repaired
        return jsonify({"success": True, "integrity": integrity})
    except Exception as e:
        logger.error(f"Backup check error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500


# 21MS_FAREWELL BRANCH: New routes that don't require OAuth login
@app.route("/farewell-stats")
@admin_only
def get_farewell_stats():
    """Get system statistics - no authentication required for 21ms_farewell"""
    if not csv_manager:
        return jsonify({"success": False, "error": "CSV manager not initialized"}), 500
    try:
        coupon_stats = csv_manager.get_coupon_stats()
        recipients = csv_manager.read_recipients()
        return jsonify(
            {
                "success": True,
                "recipients_count": len(recipients),
                "coupon_stats": coupon_stats,
            }
        )
    except Exception as e:
        logger.error(f"Error getting stats: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/farewell-recipients")
@admin_only
def get_farewell_recipients():
    """Get detailed recipient list with coupon info - no auth required"""
    if not all([csv_manager, coupon_manager]):
        return jsonify({"success": False, "error": "Services not initialized"}), 500
    try:
        recipients = csv_manager.read_recipients()
        detailed_recipients = []
        import csv as csv_module

        for recipient in recipients:
            email = recipient["email"].lower()
            coupon_record = None
            try:
                with open(
                    csv_manager.coupons_file, "r", newline="", encoding="utf-8"
                ) as f:
                    reader = csv_module.DictReader(f)
                    for row in reader:
                        if row.get("email", "").lower() == email:
                            coupon_record = row
                            break
            except:
                pass
            status = "pending"
            coupon_id = None
            verification_code = None
            sent_at = None
            used_at = None
            if coupon_record:
                coupon_id = coupon_record.get("coupon_id")
                verification_code = coupon_record.get("verification_code")
                status = coupon_record.get("status", "generated")
                sent_at = coupon_record.get("sent_at")
                used_at = coupon_record.get("used_at")
            detailed_recipients.append(
                {
                    "email": recipient["email"],
                    "name": recipient.get("name", ""),
                    "include_qr": recipient.get("include_qr", True),
                    "status": status,
                    "coupon_id": coupon_id,
                    "verification_code": verification_code,
                    "sent_at": sent_at,
                    "used_at": used_at,
                }
            )
        return jsonify(
            {
                "success": True,
                "recipients": detailed_recipients,
                "total_count": len(detailed_recipients),
            }
        )
    except Exception as e:
        logger.error(f"Error getting recipients: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/farewell-coupons")
@admin_only
def get_farewell_coupons():
    """Get all coupon details for dashboard display"""
    if not csv_manager:
        return jsonify({"success": False, "error": "CSV manager not initialized"}), 500
    try:
        import csv as csv_module

        coupons = []
        with open(csv_manager.coupons_file, "r", newline="", encoding="utf-8") as f:
            reader = csv_module.DictReader(f)
            for row in reader:
                coupons.append(
                    {
                        "coupon_id": row.get("coupon_id", ""),
                        "email": row.get("email", ""),
                        "verification_code": row.get("verification_code", ""),
                        "status": row.get("status", "generated"),
                        "sent_at": row.get("sent_at", ""),
                        "used_at": row.get("used_at", ""),
                    }
                )
        return jsonify({"success": True, "coupons": coupons, "total": len(coupons)})
    except Exception as e:
        logger.error(f"Error getting coupons: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# SMTP Configuration routes
# ============================================================
SMTP_CONFIG_FILE = "smtp_config.json"


@app.route("/farewell-smtp-config", methods=["GET"])
@admin_only
def get_smtp_config():
    """Return current SMTP configuration (masking password)."""
    config = {}
    if os.path.exists(SMTP_CONFIG_FILE):
        try:
            with open(SMTP_CONFIG_FILE, "r") as f:
                config = json.load(f)
        except:
            pass
    # Return masked password
    masked = {
        "host": config.get("host", os.getenv("SMTP_HOST", "")),
        "port": config.get("port", int(os.getenv("SMTP_PORT", "587"))),
        "username": config.get("username", os.getenv("SMTP_USERNAME", "")),
        "password": "********"
        if config.get("password") or os.getenv("SMTP_PASSWORD")
        else "",
        "sender_name": config.get("sender_name", os.getenv("SMTP_SENDER_NAME", "")),
        "sender_email": config.get("sender_email", os.getenv("SMTP_SENDER_EMAIL", "")),
        "use_tls": config.get("use_tls", True),
    }
    return jsonify(
        {
            "success": True,
            "config": masked,
            "configured": bool(config.get("password") or os.getenv("SMTP_PASSWORD")),
        }
    )


@app.route("/farewell-smtp-config/test", methods=["POST"])
@admin_only
def test_smtp_config():
    """Test the current SMTP configuration."""
    try:
        mailer = SMTPMailer()
        result = mailer.test_connection()
        return jsonify(result)
    except EnvironmentError as e:
        return jsonify({"success": False, "message": str(e), "error": str(e)})
    except Exception as e:
        return jsonify({"success": False, "message": str(e), "error": str(e)})


@app.route("/farewell-smtp-config/upload", methods=["POST"])
@admin_only
def upload_smtp_config():
    """Upload SMTP configuration as a JSON file."""
    try:
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file uploaded"}), 400
        file = request.files["file"]
        if not file.filename or not file.filename.lower().endswith(".json"):
            return jsonify({"success": False, "error": "File must be a .json"}), 400
        content = file.read().decode("utf-8")
        config = json.loads(content)
        required = ["username", "password"]
        for key in required:
            if key not in config or not config[key]:
                return jsonify(
                    {"success": False, "error": f"Missing required field: {key}"}
                ), 400
        with open(SMTP_CONFIG_FILE, "w") as f:
            json.dump(
                {
                    "host": config.get("host", "smtp.gmail.com"),
                    "port": int(config.get("port", 587)),
                    "username": config["username"],
                    "password": config["password"],
                    "sender_name": config.get("sender_name", config["username"]),
                    "sender_email": config.get("sender_email", config["username"]),
                    "use_tls": config.get("use_tls", True),
                },
                f,
                indent=2,
            )
        logger.info(f"SMTP config uploaded via JSON for {config['username']}")
        return jsonify(
            {"success": True, "message": "SMTP config loaded from JSON file"}
        )
    except json.JSONDecodeError:
        return jsonify({"success": False, "error": "Invalid JSON format"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/farewell-smtp-config", methods=["POST"])
@admin_only
def save_smtp_config():
    """Save SMTP configuration. Handles masked password as 'keep existing'."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        new_password = data.get("password", "")

        # If password is masked (********), load existing password
        existing_config = {}
        if os.path.exists(SMTP_CONFIG_FILE):
            try:
                with open(SMTP_CONFIG_FILE, "r") as f:
                    existing_config = json.load(f)
            except:
                pass

        if new_password in ("********", "", "****") and existing_config.get("password"):
            new_password = existing_config["password"]

        if not new_password:
            new_password = os.getenv("SMTP_PASSWORD", "")

        config = {
            "host": data.get("host", "smtp.gmail.com"),
            "port": int(data.get("port", 587)),
            "username": data.get("username", ""),
            "password": new_password,
            "sender_name": data.get("sender_name", ""),
            "sender_email": data.get("sender_email", ""),
            "use_tls": data.get("use_tls", True),
        }
        if not config["username"] or not config["password"]:
            return jsonify(
                {"success": False, "error": "Username and password are required"}
            ), 400
        with open(SMTP_CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        logger.info(f"SMTP config saved for {config['username']}")
        return jsonify({"success": True, "message": "SMTP configuration saved"})
    except Exception as e:
        logger.error(f"Error saving SMTP config: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# Template management routes (Lunch, Dinner)
# ============================================================
TEMPLATES_DIR = "templates/farewell"
TEMPLATE_TYPES = ["invitation", "22ms_invitation", "mp_invitation", "lunch", "dinner"]


def get_template_path(template_type: str) -> str:
    """Get the file path for a template type."""
    if template_type == "invitation":
        return os.path.join(TEMPLATES_DIR, "invitation.html")
    elif template_type == "22ms_invitation":
        return os.path.join(TEMPLATES_DIR, "22ms_invitation.html")
    elif template_type == "mp_invitation":
        return os.path.join(TEMPLATES_DIR, "mp_invitation.html")
    elif template_type == "lunch":
        return os.path.join(TEMPLATES_DIR, "lunch.html")
    elif template_type == "dinner":
        return os.path.join(TEMPLATES_DIR, "dinner.html")
    return os.path.join(TEMPLATES_DIR, f"{template_type}.html")


@app.route("/farewell-templates", methods=["GET"])
@admin_only
def get_templates():
    """Return list of available templates."""
    templates = []
    for t in TEMPLATE_TYPES:
        path = get_template_path(t)
        exists = os.path.exists(path)
        templates.append(
            {
                "type": t,
                "name": t.capitalize(),
                "exists": exists,
                "path": path,
            }
        )
    return jsonify({"success": True, "templates": templates})


@app.route("/farewell-templates/<template_type>", methods=["GET"])
@admin_only
def get_template(template_type):
    """Return HTML content of a specific template."""
    if template_type not in TEMPLATE_TYPES:
        return jsonify(
            {"success": False, "error": f"Unknown template: {template_type}"}
        ), 400
    path = get_template_path(template_type)
    content = ""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    return jsonify({"success": True, "type": template_type, "content": content})


@app.route("/farewell-templates/<template_type>", methods=["POST"])
@admin_only
def save_template(template_type):
    """Save HTML content to a template file."""
    if template_type not in TEMPLATE_TYPES:
        return jsonify(
            {"success": False, "error": f"Unknown template: {template_type}"}
        ), 400
    try:
        data = request.get_json()
        content = data.get("content", "")
        if not content:
            return jsonify(
                {"success": False, "error": "Template content is empty"}
            ), 400
        path = get_template_path(template_type)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Template saved: {path}")
        return jsonify(
            {"success": True, "message": f"Template '{template_type}' saved"}
        )
    except Exception as e:
        logger.error(f"Error saving template: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/farewell-send-with-template", methods=["POST"])
@admin_only
def send_with_template():
    """Send invitations using a specific template type for each recipient."""
    if not all([coupon_manager, csv_manager]):
        return jsonify({"success": False, "error": "Services not initialized"}), 500
    try:
        data = request.get_json() or {}
        event_name = data.get("event_name", EVENT_NAME)
        template_type = data.get("template_type", "invitation")
        selected_emails = data.get("selected_emails", [])
        attachment_path = data.get("attachment_path")

        recipients = csv_manager.read_recipients()
        if not recipients:
            return jsonify({"success": False, "error": "No recipients found"}), 400

        if selected_emails:
            recipients = [
                r
                for r in recipients
                if r.get("email", "").lower() in {e.lower() for e in selected_emails}
            ]

        if not recipients:
            return jsonify({"success": False, "error": "No matching recipients"}), 400

        # Filter out recipients who already have coupon records
        import csv as csv_module

        existing_emails = set()
        try:
            with open(csv_manager.coupons_file, "r", newline="", encoding="utf-8") as f:
                reader = csv_module.DictReader(f)
                for row in reader:
                    if row.get("email"):
                        existing_emails.add(row.get("email", "").lower())
        except FileNotFoundError:
            pass

        new_recipients = [
            r for r in recipients if r.get("email", "").lower() not in existing_emails
        ]
        if not new_recipients:
            return jsonify(
                {
                    "success": False,
                    "error": "All selected recipients already have coupons",
                }
            ), 400

        # Build lookup for recipient options (include_qr etc.)
        recipient_opts = {r.get("email", "").lower(): r for r in new_recipients}

        smtp_mailer = SMTPMailer()
        coupon_results = coupon_manager.generate_coupons_batch(
            new_recipients, event_name
        )

        if coupon_results.get("generated", 0) == 0:
            return jsonify(
                {"success": False, "error": "Failed to generate coupons"}
            ), 500

        sent, failed, failed_list = 0, 0, []
        for coupon in coupon_results.get("coupons", []):
            email = coupon["email"]
            opts = recipient_opts.get(email.lower(), {})
            has_qr = opts.get("include_qr", True)
            if isinstance(has_qr, str):
                has_qr = has_qr.lower() not in ("false", "0", "no")

            if has_qr:
                qr_bytes = base64.b64decode(coupon["qr_code_base64"])
                qr_src = "cid:qrcode"
            else:
                qr_bytes = None
                qr_src = ""

            ctx = {
                "attendee_name": opts.get(
                    "name", coupon.get("name", email.split("@")[0])
                ),
                "attendee_email": email,
                "event_name": event_name,
                "event_date": EVENT_DATE,
                "event_time": EVENT_TIME,
                "event_venue": EVENT_VENUE,
                "qr_code_base64": coupon["qr_code_base64"] if has_qr else "",
                "qr_code_src": qr_src,
                "verification_code": coupon["verification_code"] if has_qr else "",
                "coupon_id": coupon["coupon_id"],
                "organizer_batch": ORGANIZER_BATCH,
                "organizer_institution": ORGANIZER_INSTITUTION,
                "include_qr": has_qr,
            }
            try:
                tpl = f"farewell/{template_type}.html"
                with app.app_context():
                    html_body = render_template(tpl, **ctx)
                result = smtp_mailer.send_email(
                    to_email=email,
                    to_name=ctx["attendee_name"],
                    subject=f"You're Invited! {event_name}",
                    html_body=html_body,
                    attachment_path=attachment_path
                    if os.path.exists(attachment_path or "")
                    else None,
                    qr_code_bytes=qr_bytes,
                )
                if result["success"]:
                    coupon_manager.mark_coupon_sent(coupon["coupon_id"])
                    sent += 1
                else:
                    failed += 1
                    failed_list.append(
                        {
                            "email": email,
                            "error": result.get("error"),
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
            except Exception as e:
                failed += 1
                failed_list.append(
                    {
                        "email": email,
                        "error": str(e),
                        "timestamp": datetime.now().isoformat(),
                    }
                )
                logger.error(f"Error sending to {email}: {str(e)}")

        return jsonify(
            {
                "success": True,
                "emails_sent": sent,
                "emails_failed": failed,
                "failed_list": failed_list,
                "total": len(coupon_results.get("coupons", [])),
            }
        )
    except Exception as e:
        logger.error(f"Error in send_with_template: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


# 21MS_FAREWELL BRANCH: Serve favicon
@app.route("/favicon.ico")
def favicon():
    """Serve favicon for browser tab."""
    from flask import send_from_directory

    return send_from_directory("static", "favicon.svg", mimetype="image/svg+xml")


if __name__ == "__main__":
    # Development server configuration
    debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    port = int(os.environ.get("PORT", 5000))
    ssl_enabled = os.environ.get("SSL_ENABLED", "false").lower() == "true"

    ssl_context = None
    protocol = "http"
    if ssl_enabled:
        cert_file = os.environ.get("SSL_CERT", "cert.pem")
        key_file = os.environ.get("SSL_KEY", "key.pem")
        if os.path.exists(cert_file) and os.path.exists(key_file):
            ssl_context = (cert_file, key_file)
            protocol = "https"
        else:
            print(f"[!] SSL cert files not found: {cert_file}, {key_file}")
            print(
                "[!] Falling back to HTTP (camera access may not work on remote devices)"
            )

    # Startup banner
    print()
    print("=" * 60)
    print("  21MS FAREWELL PARTY — Event Coupon System")
    print("=" * 60)
    print()
    print(f"  Server LAN IP : {SERVER_LAN_IP}")
    print(f"  Protocol       : {protocol.upper()}")
    print(f"  Port           : {port}")
    print()
    print("  ┌─ ADMIN (host machine only) ────────────────────┐")
    print(f"  │  {protocol}://localhost:{port}/sender")
    print(f"  │  {protocol}://127.0.0.1:{port}/sender")
    print("  └────────────────────────────────────────────────┘")
    print()
    print("  ┌─ SCANNER (share with staff devices) ──────────┐")
    print(f"  │  {protocol}://{SERVER_LAN_IP}:{port}/scanner")
    print("  │")
    if protocol == "https":
        print("  │  ⚠  Staff devices must accept the self-signed")
        print("  │     certificate warning to connect.")
    else:
        print("  │  ⚠  Camera access requires HTTPS on most")
        print("  │     browsers. Set SSL_ENABLED=true in .env")
    print("  └────────────────────────────────────────────────┘")
    print()
    print("  Access control: Admin routes blocked for remote IPs")
    print(f"  Allowed admin IPs: {ADMIN_ALLOWED_IPS}")
    print()
    print("=" * 60)
    print()

    app.run(host="0.0.0.0", port=port, debug=debug_mode, ssl_context=ssl_context)
