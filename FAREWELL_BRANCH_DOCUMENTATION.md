# 21MS Farewell Party Branch Documentation

## Branch Purpose

This branch implements an **automated coupon/invitation dispersal system** for the **farewell party of the 21MS batch** at IISER Kolkata. The 21MS batch consists of students who took admission in 2021 and are now completing their BS-MS degree. The farewell party is organized by the **22MS batch**.

## What's Different from `main`

| Feature | `main` branch | `21ms_farewell` branch |
|---------|--------------|------------------------|
| **Email sending** | Gmail API (OAuth required) | SMTP (direct `.env` credentials) |
| **OAuth requirement** | Required for sending emails | Not required for sending (optional for login) |
| **QR system** | Single QR per attendee | Single QR per attendee (same as main) |
| **Email template** | Standard invitation | Handwriting-style farewell invitation |
| **Email template path** | `invitation.html` | `farewell/invitation.html` |
| **Thank you template** | `thank_you.html` | `farewell/thank_you.html` |
| **Font style** | Standard fonts | Caveat, Satisfy, Kalam (handwriting) |
| **Route** | `/send-emails` | `/send-farewell-emails` |

## Setup Instructions

### Python Environment

This branch uses the global Python managed by `uv` at `/home/shuvam/.global-pymaster`. Do NOT create a new virtual environment.

```bash
# Verify Python is accessible
/home/shuvam/.global-pymaster/bin/python --version

# Install dependencies
uv pip install --python /home/shuvam/.global-pymaster -r requirements_21ms.txt
```

### Environment Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
# Edit .env with your actual values
```

#### Required `.env` Variables

| Variable | Description |
|----------|-------------|
| `SMTP_HOST` | SMTP server (default: `smtp.gmail.com`) |
| `SMTP_PORT` | SMTP port (default: `587` for TLS) |
| `SMTP_USE_TLS` | Use TLS encryption (`True` or `False`) |
| `SMTP_USERNAME` | Your Gmail address |
| `SMTP_PASSWORD` | **16-character Gmail App Password** (NOT your regular password) |
| `SMTP_SENDER_NAME` | Display name in emails |
| `SMTP_SENDER_EMAIL` | Sender email address |
| `EVENT_NAME` | Event title |
| `EVENT_DATE` | Event date |
| `EVENT_TIME` | Event time |
| `EVENT_VENUE` | Event venue |
| `TEST_EMAIL_1` | First test email address |
| `TEST_EMAIL_2` | Second test email address |

#### Getting a Gmail App Password

1. Enable **2-Step Verification** on your Google Account
2. Go to **Security → 2-Step Verification → App passwords**
3. Create a new app password (select "Mail" as app, "Other" as device)
4. Copy the 16-character password (format: `xxxx xxxx xxxx xxxx`)

## How to Run Test Emails

```bash
# From the repository root directory
/home/shuvam/.global-pymaster/bin/python scripts/send_test_emails.py
```

This script will:
1. Verify all required environment variables are set
2. Test SMTP connection
3. Send a test invitation email to `TEST_EMAIL_1`
4. Wait 2 seconds
5. Send a test invitation email to `TEST_EMAIL_2`
6. Report results

Expected output on success:
```
============================================================
21MS Farewell SMTP Test Results
============================================================
TEST_EMAIL_1 (first@example.com): ✓ SENT SUCCESSFULLY
TEST_EMAIL_2 (second@example.com): ✓ SENT SUCCESSFULLY

✓ SMTP system is working. You may proceed with bulk sending.
============================================================
```

## How to Send Bulk Emails

### 1. Prepare your recipient list

Create a CSV file with recipients. The default location is managed by `CSVManager`. The CSV should have columns: `name`, `email` (at minimum).

### 2. Start the Flask app

```bash
/home/shuvam/.global-pymaster/bin/python app.py
```

### 3. Send emails via API

```bash
curl -X POST http://localhost:5000/send-farewell-emails \
  -H "Content-Type: application/json" \
  -d '{"event_name": "21MS Farewell Party"}'
```

Or from the sender dashboard at `/sender.html`.

## Email Template Description

### Design Philosophy

The invitation email is designed to feel **warm and personal**, like a heartfelt farewell letter written by a junior who genuinely loves and respects their seniors.

### Fonts

| Font | Usage |
|------|-------|
| **Caveat** | Headings, event details, verification code |
| **Satisfy** | "You're Invited" hero text, signature |
| **Kalam** | Body copy, fine print |

### Color Palette

| Color | Hex | Usage |
|-------|-----|-------|
| Midnight Navy | `#1a1a2e` | Header/footer backgrounds |
| Gold/Amber | `#d4af37` | Accents, headings, verification code |
| Warm Cream | `#fef9f0` | Content backgrounds |
| Soft Rose | `#e8a0a0` | Highlights |

### Sections

1. **Header** — Dark navy banner with "You're Invited ✨" in Satisfy font
2. **Hero Message** — Personal message in Kalam font with warm closing
3. **Event Details** — Date, time, venue in Caveat font with gold borders
4. **QR Ticket** — Dashed border "tear-off ticket" style with QR code and verification code
5. **Footer** — Dark navy with institution name and organizing batch

### Email Constraints

- Max width: 600px (centered)
- All CSS must be inline (email clients strip `<style>` blocks)
- Uses HTML tables for email layout structure
- No JavaScript, iframes, or CSS Grid

## Troubleshooting

### SMTP Authentication Failed

**Error:** `535-5.7.8 Username and Password not accepted`

**Solutions:**
- Ensure you're using an **App Password**, not your regular Gmail password
- Verify 2-Step Verification is enabled on your Google account
- Check that `SMTP_PASSWORD` has no extra spaces

### Connection Timeout

**Error:** `SMTP connection timeout`

**Solutions:**
- Check your internet connection
- Verify `SMTP_HOST` is correct (default: `smtp.gmail.com`)
- Try a different `SMTP_PORT` (587 for TLS, 465 for SSL)

### Test Email Landed in Spam

**Solutions:**
- Add the sending email to your contacts
- Check if SPF/DKIM is configured for your domain
- The subject line "You're Invited!" is generally not flagged as spam

### Template Renders with `{{ }}` Visible

**Problem:** Raw Jinja2 tags visible in rendered email

**Solution:** Check that all template variables are provided when rendering. Common variables:
- `attendee_name`
- `attendee_email`
- `event_name`
- `event_date`
- `event_time`
- `event_venue`
- `qr_code_base64`
- `verification_code`
- `coupon_id`
- `organizer_batch`
- `organizer_institution`

### QR Code Not Scannable

**Solutions:**
- Ensure QR code image has sufficient contrast
- Don't resize the QR code below 200px width
- Test with multiple QR code scanner apps

## API Reference

### POST `/send-farewell-emails`

Send farewell party invitation emails via SMTP.

**Authentication:** None required (uses `.env` SMTP credentials)

**Request Body:**
```json
{
  "event_name": "21MS Farewell Party"
}
```

**Response:**
```json
{
  "success": true,
  "emails_sent": 45,
  "emails_failed": 2,
  "total_recipients": 47,
  "failed_list": [...]
}
```

## Files in This Branch

### New Files

| File | Description |
|------|-------------|
| `src/smtp_mailer.py` | SMTP email service class |
| `templates/farewell/invitation.html` | Handwriting-style invitation template |
| `templates/farewell/thank_you.html` | Post-verification thank you template |
| `scripts/send_test_emails.py` | Test email sender script |
| `tests/test_smtp_connection.py` | Unit tests for SMTPMailer |
| `tests/test_invitation_render.py` | Template rendering tests |
| `requirements_21ms.txt` | Branch-specific dependencies |
| `FAREWELL_BRANCH_DOCUMENTATION.md` | This documentation |

### Modified Files

| File | Changes |
|------|---------|
| `app.py` | Added `/send-farewell-emails` route, event config from env |
| `.env.example` | Added SMTP and event configuration template |

## Security Notes

- **Never commit `.env`** — it's in `.gitignore`
- **Never hardcode credentials** in any file
- The SMTP password is loaded from environment at runtime and not stored
- App passwords should be revoked after use if concerned about security

## Support

For issues with this branch, check:
1. All `.env` variables are correctly set
2. Gmail App Password is valid and 16 characters
3. Tests in `tests/` pass before sending bulk emails
4. The `templates/farewell/` directory exists with both templates