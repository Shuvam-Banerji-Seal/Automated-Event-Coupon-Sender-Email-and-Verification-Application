#!/home/shuvam/.global-pymaster/bin/python
"""send_test_emails.py
21MS Farewell Party — SMTP Test Script
Sends a real test invitation email to both TEST_EMAIL_1 and TEST_EMAIL_2.
Uses the actual farewell/invitation.html template with dummy data.
Usage: /home/shuvam/.global-pymaster/bin/python scripts/send_test_emails.py
Must be run from the repository root directory.
"""

import os
import sys
import base64
import io
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from src.smtp_mailer import SMTPMailer
from src.coupons import CouponManager
from src.data import CSVManager
from jinja2 import Environment, FileSystemLoader


def generate_test_qr_code() -> str:
    """Generate a real QR code for testing."""
    qr_data = '{"v":"123456","e":"test@example.com","p":"21MS-FAREWELL"}'
    manager = CouponManager()
    qr_code = manager.create_qr_code(qr_data)
    return qr_code  # Already base64-encoded string


def main():
    print("=" * 60)
    print("21MS Farewell Party — SMTP Test Script")
    print("=" * 60)

    required_vars = [
        "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD",
        "SMTP_SENDER_NAME", "SMTP_SENDER_EMAIL",
        "EVENT_NAME", "EVENT_DATE", "EVENT_TIME", "EVENT_VENUE",
        "TEST_EMAIL_1", "TEST_EMAIL_2",
    ]

    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        print(f"\n✗ ERROR: Missing required environment variables:")
        for v in missing:
            print(f"  - {v}")
        sys.exit(1)

    print("\n[1] Testing SMTP connection...")
    try:
        mailer = SMTPMailer()
    except EnvironmentError as e:
        print(f"\n✗ ERROR: {e}")
        sys.exit(1)

    conn_result = mailer.test_connection()
    if not conn_result["success"]:
        print(f"\n✗ SMTP Connection Failed: {conn_result['message']}")
        print("✗ SMTP test failed. Fix the error above before bulk sending.")
        sys.exit(1)
    print(f"✓ SMTP connection successful: {conn_result['message']}")

    template_dir = os.path.join(os.path.dirname(__file__), "..", "templates", "farewell")
    jinja_env = Environment(loader=FileSystemLoader(template_dir))
    invitation_template = jinja_env.get_template("invitation.html")

    qr_code_base64 = generate_test_qr_code()

    test_results = []
    test_emails = [
        (os.getenv("TEST_EMAIL_1"), "TEST_EMAIL_1"),
        (os.getenv("TEST_EMAIL_2"), "TEST_EMAIL_2"),
    ]

    for i, (test_email, label) in enumerate(test_emails, 1):
        print(f"\n[{i}] Sending test email to {test_email} ({label})...")

        dummy_data = {
            "attendee_name": f"Test Attendee ({i})",
            "attendee_email": test_email,
            "event_name": os.getenv("EVENT_NAME"),
            "event_date": os.getenv("EVENT_DATE"),
            "event_time": os.getenv("EVENT_TIME"),
            "event_venue": os.getenv("EVENT_VENUE"),
            "qr_code_base64": qr_code_base64,
            "verification_code": f"{123456 + i}",
            "coupon_id": f"test-coupon-{i:08d}",
            "organizer_batch": "22MS Batch",
            "organizer_institution": "IISER Kolkata",
        }

        try:
            html_body = invitation_template.render(**dummy_data)
            subject = f"You're Invited! {os.getenv('EVENT_NAME')}"
            result = mailer.send_email(
                to_email=test_email,
                to_name=dummy_data["attendee_name"],
                subject=subject,
                html_body=html_body,
            )

            if result["success"]:
                print(f"  ✓ SENT SUCCESSFULLY to {test_email}")
                test_results.append((label, test_email, "SUCCESS", None))
            else:
                print(f"  ✗ FAILED — {result['error']}")
                test_results.append((label, test_email, "FAILED", result["error"]))

        except Exception as e:
            print(f"  ✗ FAILED — {e}")
            test_results.append((label, test_email, "FAILED", str(e)))

        if i < len(test_emails):
            import time
            time.sleep(2)

    print("\n" + "=" * 60)
    print("21MS Farewell SMTP Test Results")
    print("=" * 60)

    all_success = True
    for label, email, status, error in test_results:
        if status == "SUCCESS":
            print(f"{label} ({email}): ✓ SENT SUCCESSFULLY")
        else:
            print(f"{label} ({email}): ✗ FAILED — {error}")
            all_success = False

    if all_success:
        print("\n✓ SMTP system is working. You may proceed with bulk sending.")
        sys.exit(0)
    else:
        print("\n✗ SMTP test failed. Fix the error above before bulk sending.")
        sys.exit(1)


if __name__ == "__main__":
    main()