#!/home/shuvam/.global-pymaster/bin/python
"""send_test_emails.py
21MS Farewell Party - SMTP Test Script
Sends real test invitation emails to all TEST_EMAIL addresses.
Uses the actual farewell/invitation.html template with proper coupon generation.
Tests attachment support with a PDF schedule.
Usage: /home/shuvam/.global-pymaster/bin/python scripts/send_test_emails.py
Must be run from the repository root directory.
"""

import os
import sys
import time
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from src.smtp_mailer import SMTPMailer
from src.coupons import CouponManager
from src.data import CSVManager
from jinja2 import Environment, FileSystemLoader


def generate_coupon_and_render(email: str, name: str, index: int):
    """Generate a proper coupon and render invitation template."""
    manager = CouponManager()

    event_name = os.getenv("EVENT_NAME", "21MS Farewell Party")
    result = manager.generate_coupon(email, event_name)

    if not result.get('success'):
        raise Exception(f"Failed to generate coupon for {email}: {result.get('error')}")

    template_dir = os.path.join(os.path.dirname(__file__), "..", "templates", "farewell")
    jinja_env = Environment(loader=FileSystemLoader(template_dir))
    invitation_template = jinja_env.get_template("invitation.html")

    data = {
        "attendee_name": name,
        "attendee_email": email,
        "event_name": event_name,
        "event_date": os.getenv("EVENT_DATE", "To Be Announced"),
        "event_time": os.getenv("EVENT_TIME", "To Be Announced"),
        "event_venue": os.getenv("EVENT_VENUE", "IISER Kolkata Campus"),
        "qr_code_base64": result["qr_code_base64"],
        "verification_code": result["verification_code"],
        "coupon_id": result["coupon_id"],
        "organizer_batch": "22MS Batch",
        "organizer_institution": "IISER Kolkata",
    }

    html_body = invitation_template.render(**data)
    return html_body, result


def main():
    print("=" * 65)
    print("21MS Farewell Party - SMTP Test & Invitation Sender")
    print("=" * 65)

    required_vars = [
        "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD",
        "SMTP_SENDER_NAME", "SMTP_SENDER_EMAIL",
        "EVENT_NAME", "EVENT_DATE", "EVENT_TIME", "EVENT_VENUE",
        "TEST_EMAIL_1", "TEST_EMAIL_2", "TEST_EMAIL_3",
    ]

    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        print(f"\n[X] ERROR: Missing required environment variables:")
        for v in missing:
            print(f"    - {v}")
        sys.exit(1)

    # Check for test attachment
    attachment_path = "test_schedule.pdf"
    has_attachment = os.path.exists(attachment_path)
    if has_attachment:
        print(f"\n[+] Test attachment found: {attachment_path}")
    else:
        print(f"\n[!] Test attachment not found: {attachment_path}")
        print("    Will send without attachment.")

    print("\n[1] Testing SMTP connection...")
    try:
        mailer = SMTPMailer()
    except EnvironmentError as e:
        print(f"\n[X] ERROR: {e}")
        sys.exit(1)

    conn_result = mailer.test_connection()
    if not conn_result["success"]:
        print(f"\n[X] SMTP Connection Failed: {conn_result['message']}")
        sys.exit(1)
    print(f"[+] SMTP connection successful: {conn_result['message']}")

    test_emails = [
        (os.getenv("TEST_EMAIL_1"), "Test Attendee 1 (21MS)"),
        (os.getenv("TEST_EMAIL_2"), "Test Attendee 2 (21MS)"),
        (os.getenv("TEST_EMAIL_3"), "Test Attendee 3 (21MS)"),
    ]

    test_results = []
    subject = f"You're Invited! {os.getenv('EVENT_NAME')}"

    for i, (test_email, name) in enumerate(test_emails, 1):
        print(f"\n[{i}] Preparing invitation for {test_email}...")

        try:
            html_body, coupon_result = generate_coupon_and_render(test_email, name, i)
            print(f"    [+] Coupon generated: {coupon_result['coupon_id']}")
            print(f"    [+] Verification code: {coupon_result['verification_code']}")

            result = mailer.send_email(
                to_email=test_email,
                to_name=name,
                subject=subject,
                html_body=html_body,
                attachment_path=attachment_path if has_attachment else None,
            )

            if result["success"]:
                print(f"    [+] SENT SUCCESSFULLY to {test_email}")
                if has_attachment:
                    print(f"    [+] Attachment included: {attachment_path}")
                test_results.append((f"TEST_EMAIL_{i}", test_email, "SUCCESS", None, coupon_result['verification_code']))
            else:
                print(f"    [X] FAILED - {result['error']}")
                test_results.append((f"TEST_EMAIL_{i}", test_email, "FAILED", result["error"], None))

        except Exception as e:
            print(f"    [X] FAILED - {e}")
            test_results.append((f"TEST_EMAIL_{i}", test_email, "FAILED", str(e), None))

        if i < len(test_emails):
            time.sleep(2)

    print("\n" + "=" * 65)
    print("21MS Farewell SMTP Test Results")
    print("=" * 65)

    all_success = True
    for label, email, status, error, vcode in test_results:
        if status == "SUCCESS":
            print(f"{label} ({email}): [+] SENT - Code: {vcode}")
        else:
            print(f"{label} ({email}): [X] FAILED - {error}")
            all_success = False

    if all_success:
        print("\n[+] All invitations sent successfully!")
        print("[+] SMTP system is working. You may proceed with bulk sending.")
        print("[+] PDF attachment test: " + ("PASSED" if has_attachment else "SKIPPED (no PDF found)"))
        sys.exit(0)
    else:
        print("\n[X] Some invitations failed. Fix the errors above before bulk sending.")
        sys.exit(1)


if __name__ == "__main__":
    main()