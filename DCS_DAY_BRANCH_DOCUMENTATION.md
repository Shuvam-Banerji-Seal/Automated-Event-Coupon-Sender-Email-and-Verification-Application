# DCS Day '26 - Event Management System Documentation

**Branch:** `dcs_day`
**Event:** DCS Day 2026 - Annual Celebration of Science & Culture
**Date:** January 28, 2026
**Location:** R N Tagore Auditorium, IISER Kolkata

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [3-QR Code System](#3-3-qr-code-system)
4. [Complete Data Flow](#4-complete-data-flow)
5. [CSV Data Schema](#5-csv-data-schema-14-columns)
6. [Coupon Generation](#6-coupon-generation-srccouponspy)
7. [Verification API](#7-verification-api-verify-coupon)
8. [Thank You Email Templates](#8-thank-you-email-templates)
9. [Scanner Interface](#9-scanner-interface)
10. [Utility Scripts](#10-utility-scripts)
11. [Brochure App](#11-brochure-app)
12. [HTTPS Server Setup](#12-https-server-setup)
13. [Configuration](#13-configuration)
14. [Routes Reference](#14-routes-reference)
15. [Security](#15-security)
16. [Key Files Summary](#16-key-files-summary)

---

## 1. System Overview

This is a specialized event management system for **DCS Day '26** - an annual celebration at the Department of Chemical Sciences, IISER Kolkata.

### Core Innovation: 3-QR Code Per Attendee

Each attendee receives **THREE separate QR codes** for three different checkpoints:
- **Registration QR** (Green) - 8:30 AM
- **Lunch QR** (Orange) - 1:00 PM
- **Dinner QR** (Purple) - 6:00 PM

This allows tracking attendance at each event segment independently.

### Event Schedule Highlights

| Time | Event | Venue |
|------|-------|-------|
| 8:30 AM | Registration & Kit Distribution | Main Gate |
| 9:15 AM | Inaugural Session | R N Tagore Auditorium |
| 9:30 AM - 12:30 PM | Scientific Sessions (Talks) | R N Tagore Auditorium |
| 1:00 PM - 2:30 PM | Lunch & Poster Session | Lunch Area |
| 2:30 PM - 5:00 PM | Afternoon Sessions | R N Tagore Auditorium |
| 6:00 PM - 8:00 PM | Cultural Program | LHC Parking |
| 8:30 PM - 10:00 PM | DJ Night | LHC Parking |

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             FLASK APP (app.py)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│  AUTH ROUTES          DATA ROUTES              VERIFICATION ROUTES           │
│  ─────────────        ───────────              ────────────────────         │
│  /login               /                        /scanner                      │
│  /auth/callback       /sender                  /backup-scanner               │
│  /logout              /upload-csv              /verify-coupon                │
│                       /clear-csv               /coupon-status/<id>           │
│                       /stats                   /backup-scan (POST)           │
│                       /recipients                                            │
│                       /preview-send                                           │
│                       /send-emails                                            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
        ▼                           ▼                           ▼
┌───────────────────┐    ┌───────────────────┐    ┌───────────────────────────┐
│   src/coupons.py  │    │    src/data.py    │    │       src/auth.py         │
│                   │    │                   │    │                           │
│ - QR Generation   │    │ - CSV Manager     │    │ - GoogleAuthService       │
│ - 3 Codes per     │    │ - 14-Column CSV   │    │ - GmailEmailService       │
│   Attendee        │    │ - File Locking    │    │ - OAuth 2.0 Flow          │
│ - Validation      │    │ - CouponRecord    │    │ - Token Refresh           │
│ - Status Update   │    │   (3-QR schema)   │    │                           │
└───────────────────┘    └───────────────────┘    └───────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DATA STORAGE                                     │
│                                                                              │
│  coupons.csv              responses - Sheet1.csv    organizer_credentials.json│
│  (14 columns)             (email, [name])           (OAuth tokens)           │
│                                                                              │
│  logs/failed_emails_*.csv                                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 3-QR Code System

### 3.1 QR Code Data Structure

Each QR code contains compact JSON with type-tagged verification data:

```json
// Registration QR
{"v": "123456", "e": "attendee@iiserkol.ac.in", "t": "registration"}

// Lunch QR
{"v": "789012", "e": "attendee@iiserkol.ac.in", "t": "lunch"}

// Dinner QR
{"v": "345678", "e": "attendee@iiserkol.ac.in", "t": "dinner"}
```

| Field | Description | Example |
|-------|-------------|---------|
| `v` | 6-digit verification code | `"123456"` |
| `e` | Attendee email (lowercase) | `"attendee@iiserkol.ac.in"` |
| `t` | QR type: `registration`, `lunch`, or `dinner` | `"registration"` |

### 3.2 Visual Design

The invitation email displays three styled tickets:

| Type | Color | Emoji | Time | Content |
|------|-------|-------|------|---------|
| Registration | Green | 🎫 | 8:30 AM | "Collect your DCS Kit" |
| Lunch | Orange | 🍽️ | 1:00 PM | "Lunch & Poster Session" |
| Dinner | Purple | 🍱 | 6:00 PM | "Cultural Program & DJ Night" |

---

## 4. Complete Data Flow

```
┌────────────────────────────────────────────────────────────────────────────┐
│                           STEP 1: CSV UPLOAD                                 │
└────────────────────────────────────────────────────────────────────────────┘

Organizer Dashboard → Upload CSV
        │
        ▼
CSV Validation (email format check)
        │
        ▼
File saved: responses - Sheet1.csv
        │
        ▼
Backup created if requested (reset_coupons=true)
        │
        ▼

┌────────────────────────────────────────────────────────────────────────────┐
│                    STEP 2: COUPON GENERATION                                │
└────────────────────────────────────────────────────────────────────────────┘

User clicks "Send Coupons" → /send-emails (POST)
        │
        ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ For each recipient in CSV:                                                  │
│                                                                             │
│ 1. Generate coupon_id = UUID4()                                             │
│    Example: "a1b2c3d4-e5f6-7890-abcd-ef1234567890"                         │
│                                                                             │
│ 2. Generate THREE verification codes:                                       │
│    - reg_verification_code = "123456" (6 random digits)                     │
│    - lunch_verification_code = "789012" (6 random digits)                   │
│    - dinner_verification_code = "345678" (6 random digits)                  │
│                                                                             │
│ 3. Create coupon_data dict:                                                 │
│    {                                                                         │
│      'coupon_id': 'a1b2c3d4-...',                                           │
│      'email': 'attendee@iiserkol.ac.in',                                    │
│      'event_name': 'DCS Day 2026',                                          │
│      'verification_code': '123456',           <- Registration              │
│      'lunch_verification_code': '789012',     <- Lunch                      │
│      'dinner_verification_code': '345678',    <- Dinner                     │
│      'created_at': '2026-01-27T10:30:00+00:00',                            │
│      'valid': True                                                           │
│    }                                                                         │
│                                                                             │
│ 4. Encrypt with AES-256 (Fernet) → encrypted_data                          │
│                                                                             │
│ 5. Create THREE QR codes:                                                   │
│    - Registration: {"v": "123456", "e": "attendee@...", "t": "registration"}│
│    - Lunch: {"v": "789012", "e": "attendee@...", "t": "lunch"}              │
│    - Dinner: {"v": "345678", "e": "attendee@...", "t": "dinner"}            │
│                                                                             │
│ 6. Save CouponRecord to coupons.csv with all 14 columns                     │
└────────────────────────────────────────────────────────────────────────────┘
        │
        ▼

┌────────────────────────────────────────────────────────────────────────────┐
│                      STEP 3: EMAIL SENDING                                   │
└────────────────────────────────────────────────────────────────────────────┘

GmailEmailService.send_batch_emails()
        │
        ▼
For each recipient:
  - Render invitation.html with ALL 3 QR codes embedded
  - Attach DCS-Day-2026_Schedule.pdf (for registration verification emails)
  - Send via Gmail API from organizer's account
        │
        ▼
Mark coupons as 'sent' in CSV (sent_at timestamp)
        │
        ▼
Save organizer credentials to organizer_credentials.json
(for thank-you email sending during verification)
        │
        ▼

┌────────────────────────────────────────────────────────────────────────────┐
│                     STEP 4: QR VERIFICATION                                  │
└────────────────────────────────────────────────────────────────────────────┘

Event Staff opens scanner.html (HTTPS required for camera)
        │
        ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ METHOD A: Camera Scanning (Primary)                                          │
│                                                                             │
│ 1. jsQR library detects QR code from video feed                            │
│ 2. Parse QR JSON: {"v": "123456", "e": "attendee@...", "t": "registration"}│
│ 3. Extract: code = "123456", email = "attendee@...", type = "registration" │
│ 4. Call: verifyByCode(code, email, type)                                   │
└────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ METHOD B: Manual Code Entry (Fallback)                                       │
│                                                                             │
│ 1. Staff enters 6-digit code in Quick Code Entry panel                     │
│ 2. Email field is OPTIONAL (adds security if provided)                     │
│ 3. Call: verifyByCode(code, email=null, type)                              │
└────────────────────────────────────────────────────────────────────────────┘
        │
        ▼

┌────────────────────────────────────────────────────────────────────────────┐
│                    STEP 5: VERIFICATION API                                  │
└────────────────────────────────────────────────────────────────────────────┘

POST /verify-coupon
Body: { verification_code: "123456", email: "attendee@...", qr_type: "registration" }
        │
        ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ validate_coupon_by_code(code, email, qr_type)                               │
│                                                                             │
│ 1. Map qr_type to correct CSV column:                                       │
│    - 'registration' → check 'verification_code'                             │
│    - 'lunch' → check 'lunch_verification_code'                              │
│    - 'dinner' → check 'dinner_verification_code'                            │
│                                                                             │
│ 2. Find coupon where column matches code                                    │
│    - If email provided, validate email matches too                          │
│                                                                             │
│ 3. Check if this specific QR type was already used:                         │
│    - registration: check 'used_at'                                          │
│    - lunch: check 'lunch_used_at'                                           │
│    - dinner: check 'dinner_used_at'                                         │
│                                                                             │
│ 4. If already used → return ALREADY_USED error                              │
│                                                                             │
│ 5. Decrypt encrypted_data and validate timestamp (24hr expiry)             │
│                                                                             │
│ 6. Return validation result with coupon details                             │
└────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ mark_coupon_used(coupon_id, qr_type)                                        │
│                                                                             │
│ 1. Set used_at timestamp based on qr_type:                                  │
│    - 'registration' → row['used_at'] = now                                  │
│    - 'lunch' → row['lunch_used_at'] = now                                   │
│    - 'dinner' → row['dinner_used_at'] = now                                 │
│                                                                             │
│ 2. If ALL THREE timestamps exist:                                           │
│    row['status'] = 'used'                                                   │
└────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ Send Thank You Email (Async Background Thread)                              │
│                                                                             │
│ 1. Select template based on qr_type:                                        │
│    - 'registration' → thank_you_registration.html (Green, DCS Kit info)    │
│    - 'lunch' → thank_you_lunch.html (Orange, Afternoon highlights)         │
│    - 'dinner' → thank_you_dinner.html (Purple, DJ Night info)              │
│                                                                             │
│ 2. Render template with: {email, attendee_name, event_name, ...}          │
│                                                                             │
│ 3. Send via Gmail API using stored organizer credentials                   │
│                                                                             │
│ 4. For registration: attach DCS-Day-2026_Schedule.pdf                      │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. CSV Data Schema (14 columns)

**File:** `coupons.csv`

| # | Column | Type | Description |
|---|--------|------|-------------|
| 1 | `coupon_id` | string | UUID v4 - same for all 3 QR codes of one attendee |
| 2 | `email` | string | Attendee email address (lowercase) |
| 3 | `encrypted_data` | string | Base64 AES-256 encrypted JSON blob |
| 4 | `qr_code_data` | string | Registration QR code (base64 PNG) |
| 5 | `verification_code` | string | 6-digit registration code |
| 6 | `lunch_qr_data` | string | Lunch QR code (base64 PNG) |
| 7 | `lunch_verification_code` | string | 6-digit lunch code |
| 8 | `lunch_used_at` | string | ISO timestamp when lunch was verified |
| 9 | `dinner_qr_data` | string | Dinner QR code (base64 PNG) |
| 10 | `dinner_verification_code` | string | 6-digit dinner code |
| 11 | `dinner_used_at` | string | ISO timestamp when dinner was verified |
| 12 | `sent_at` | string | ISO timestamp when email was sent |
| 13 | `used_at` | string | ISO timestamp when registration was verified |
| 14 | `status` | string | `generated`, `sent`, or `used` |

### Status Logic

```python
# Status transitions:
generated → sent (when email sent successfully)
sent → used (when ALL THREE QR codes are verified)

# Individual QR type tracking:
# - used_at: set when registration QR is scanned
# - lunch_used_at: set when lunch QR is scanned
# - dinner_used_at: set when dinner QR is scanned

# Coupon is 'used' only when all three passes are verified
```

---

## 6. Coupon Generation (src/coupons.py)

### Key Classes and Methods

```python
class CouponManager:
    def __init__(self, secret_key, csv_manager):
        self.encryption_service = EncryptionService(secret_key)
        self.csv_manager = csv_manager

    def generate_coupon_id(self) -> str:
        """Generate UUID4 string"""
        return str(uuid.uuid4())

    def generate_verification_code(self) -> str:
        """Generate 6 random digits"""
        return ''.join(random.choices(string.digits, k=6))

    def create_qr_code(self, data: str) -> str:
        """Create QR code from JSON string, return base64 PNG"""
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        return base64.b64encode(buffer.getvalue()).decode()
```

### generate_coupons_batch() Flow

```python
def generate_coupons_batch(self, recipients: List[Dict], event_name: str) -> Dict:
    """
    For each recipient:
    1. Generate one coupon_id (UUID)
    2. Generate three verification codes (registration, lunch, dinner)
    3. Create coupon_data dict with all three codes
    4. Encrypt coupon_data → encrypted_data
    5. Create three QR codes with type tags:
       - {"v": reg_code, "e": email, "t": "registration"}
       - {"v": lunch_code, "e": email, "t": "lunch"}
       - {"v": dinner_code, "e": email, "t": "dinner"}
    6. Create CouponRecord with all 14 fields
    7. Save to CSV in batch
    """
```

### validate_coupon_by_code() Logic

```python
def validate_coupon_by_code(self, verification_code: str, email=None, qr_type='registration'):
    """
    1. Call csv_manager.find_coupon_by_verification_code(code, email, qr_type)
       - Maps qr_type to correct column: registration → 'verification_code', etc.
       - Returns coupon if code matches (and email matches if provided)

    2. Check type-specific used_at field:
       - registration: used_at
       - lunch: lunch_used_at
       - dinner: dinner_used_at
       If already set → return ALREADY_USED error

    3. Decrypt encrypted_data and validate timestamp (24hr expiry)

    4. Return validation result with coupon_id, email, event_name, qr_type
    """
```

### mark_coupon_used() Logic

```python
def mark_coupon_used(self, coupon_id: str, qr_type: str = 'registration') -> bool:
    """
    1. Generate used_at timestamp (UTC ISO format)
    2. Call csv_manager.update_coupon_status(coupon_id, qr_type, used_at)
       - Sets lunch_used_at/dinner_used_at/used_at based on qr_type
       - Sets status='used' only when ALL THREE used_at fields are populated
    3. Return success boolean
    """
```

---

## 7. Verification API (/verify-coupon)

### Endpoint Details

**Route:** `POST /verify-coupon`
**Auth Required:** None (public endpoint for scanner access)
**Content-Type:** `application/json`

### Request Body

```json
{
  "verification_code": "123456",      // Required: 6-digit code
  "email": "attendee@iiserkol.ac.in",  // Optional: adds security
  "qr_type": "registration"            // Required: 'registration', 'lunch', or 'dinner'
}
```

### Response (Success)

```json
{
  "success": true,
  "message": "🎫 Registration verified successfully!",
  "coupon_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "email": "attendee@iiserkol.ac.in",
  "event_name": "DCS Day 2026",
  "qr_type": "registration",
  "thank_you_email": "sending"
}
```

### Response (Already Used)

```json
{
  "success": false,
  "error": "🎫 Registration pass has already been used",
  "error_code": "ALREADY_USED",
  "used_at": "2026-01-28T08:45:00+00:00"
}
```

### Backend Flow (app.py lines 395-559)

```python
@app.route('/verify-coupon', methods=['POST'])
def verify_coupon():
    # 1. Extract request data
    data = request.get_json()
    verification_code = data.get('verification_code')
    email = data.get('email')
    qr_type = data.get('qr_type', 'registration')  # Default to registration

    # 2. Validate using verification code
    validation_result = coupon_manager.validate_coupon_by_code(
        verification_code, email, qr_type
    )

    # 3. Check validation success
    if not validation_result.get('valid'):
        return error response

    # 4. Mark coupon as used for this QR type
    coupon_id = validation_result['coupon_id']
    if coupon_manager.mark_coupon_used(coupon_id, qr_type):
        # 5. Send thank you email in background thread
        threading.Thread(target=send_thank_you_async).start()

        # 6. Return success response
        return jsonify({
            'success': True,
            'message': f'{type_labels[qr_type]} verified successfully!',
            'qr_type': qr_type,
            ...
        })
```

---

## 8. Thank You Email Templates

Three separate templates selected based on `qr_type`:

### Template Selection Map (app.py lines 479-492)

```python
template_map = {
    'registration': 'thank_you_registration.html',
    'lunch': 'thank_you_lunch.html',
    'dinner': 'thank_you_dinner.html'
}

subject_map = {
    'registration': f"🎫 Registration Confirmed - {event_name}",
    'lunch': f"🍽️ Lunch Verified - {event_name}",
    'dinner': f"🍱 Dinner Verified - {event_name}"
}
```

### Template Comparison

| Template | Theme | Header | Key Content | Special |
|----------|-------|--------|-------------|---------|
| `thank_you_registration.html` | Green 🎫 | "Registration Successful!" | DCS Kit info, schedule PDF attachment | Attaches PDF |
| `thank_you_lunch.html` | Orange 🍽️ | "Bon Appétit!" | Afternoon highlights, "Stay Tuned" | Highlights grid |
| `thank_you_dinner.html` | Purple 🍱 | "Enjoy Your Dinner!" | DJ Night, Food stalls, Feedback form | Has feedback link |

### Registration Template Highlights (thank_you_registration.html)

- Green gradient theme (#059669 → #10b981)
- "Dear {{ attendee_name }}" personalization
- DCS Kit collection reminder
- Attached PDF: DCS-Day-2026_Schedule.pdf
- Registration details section

### Lunch Template Highlights (thank_you_lunch.html)

- Orange gradient theme (#d97706 → #f59e0b)
- "Hope You Enjoyed Your Lunch"
- "Stay Tuned for More!" section
- Afternoon highlights grid (Posters, Cultural, Interactive)

### Dinner Template Highlights (thank_you_dinner.html)

- Purple gradient theme (#7c3aed → #8b5cf6)
- DJ Night banner with time (8:30 PM - 10:00 PM)
- Venue info (LHC Parking Area)
- Food stalls info (The Momo Club, opens 5 PM)
- Feedback form link (https://forms.gle/FFqY1XGeEYsr5rGS6)

---

## 9. Scanner Interface

### Files

- `templates/scanner.html` - Main scanner page
- `static/js/scanner.js` - Scanner JavaScript
- `static/css/scanner.css` - Scanner styles

### Scanner Modes

#### Camera Scanning (Primary)
- Uses `jsQR` library for client-side QR detection
- Requires HTTPS (camera API restriction)
- Shows video feed with targeting overlay
- Auto-detects QR type from `t` field in JSON

#### Manual Code Entry (Fallback)
- Quick Code Entry panel at bottom of page
- 6-digit code input
- Email field is OPTIONAL
- Type selector: Registration / Lunch / Dinner

### Verification Flow (scanner.js)

```javascript
// QR detected from camera
function handleQRDetection(qrData) {
    try {
        const data = JSON.parse(qrData);

        // New format: {v, e, t}
        if (data.v && data.t) {
            verifyByCode(data.v, data.e, data.t);
        }
        // Legacy format check
        else if (data.email && data.data) {
            verifyCoupon(data.data, data.email);
        }
    } catch (e) {
        showError('Invalid QR code format');
    }
}

// Manual code entry
function verifyByCodeManual() {
    const code = DOM.verificationCode.value.trim();
    const email = DOM.codeEmail?.value.trim() || null;  // Optional
    const type = DOM.typeSelector?.value || 'registration';

    if (code.length !== 6) {
        showError('Code must be 6 digits');
        return;
    }

    verifyByCode(code, email, type);
}

// API call
function verifyByCode(code, email, qrType) {
    fetch('/verify-coupon', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            verification_code: code,
            email: email,  // Can be null
            qr_type: qrType
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showSuccess(data.message, data.qr_type);
        } else {
            showError(data.error);
        }
    });
}
```

### Backup Scanner

`/backup-scanner` and `/backup-scan` endpoint allow recording failed scans to `backup_scans.csv` for debugging.

---

## 10. Utility Scripts

### fix_duplicates.py

Smart duplicate merging for corrupted or re-sent data.

**Purpose:** When the same email has multiple coupon entries (from re-sending), this script keeps the "best" one based on priority scoring.

**Priority Scoring:**
| Criteria | Points |
|----------|--------|
| Has `used_at` (registration used) | +1000 |
| Has `lunch_used_at` | +500 |
| Has `dinner_used_at` | +500 |
| Has `sent_at` | +100 |
| Status `sent` | +50 |
| Status `used` | +200 |
| Status `generated` | +1 |

**Output Files:**
- `coupons_merged.csv` - Clean data with duplicates merged
- `unsent_recipients.csv` - Entries generated but not sent (for retry)

### apply_merged.py

Safely applies the merged CSV back to production.

**Features:**
- Shows before/after comparison
- Creates timestamped backup
- Requires typing 'yes' to confirm (prevents accidental execution)

### fix_status.py

Fixes data integrity issues in coupons.csv.

**Logic:**
```python
if used_at exists:
    status = 'used'
elif sent_at exists:
    status = 'sent'
else:
    status = 'generated'
```

**Output:**
- Regenerates `unsent_recipients.csv`

### retry_emails.py

Helps retry sending to unsent recipients using a secondary Gmail account.

**Features:**
- Loads credentials from `.env2` file
- Shows unsent recipient list
- Provides manual instructions for using web interface with new credentials
- Can create `responses_unsent.csv` for easy upload

### analyze_data.py

Analyzes coupons.csv for data integrity issues.

**Checks:**
- Status breakdown counts
- Entries with `used_at` but wrong status
- Entries with `sent_at` but status not 'sent'
- Entries with no data filled in

### count_lunch_redeemed.py / count_dinner_redeemed.py

Simple scripts that count how many attendees redeemed each meal pass by counting non-null values in `lunch_used_at` / `dinner_used_at` columns.

---

## 11. Brochure App

### Location

`dcs_day_brochure/` - React + Vite application

### Purpose

Generates event brochures in A5 PDF format for DCS Day '26.

### Structure

```
dcs_day_brochure/
├── App.tsx              # Main app with PDF generation (html2pdf.js)
├── index.tsx            # React entry point
├── index.html           # HTML template with Tailwind CDN
├── constants.tsx        # Event data (speakers, organizers, schedule)
├── types.ts             # TypeScript interfaces
├── package.json
├── vite.config.ts
├── components/
│   ├── FrontCover.tsx   # Front page with event branding
│   ├── InsideLeft.tsx   # About + Research areas
│   ├── InsideRight.tsx  # Event highlights + Speakers
│   ├── BackCover.tsx    # Organizers + Contact + Sponsorship
│   ├── BrochurePage.tsx # A5 page wrapper
│   └── Decorations.tsx  # SVG decorations (hexagons, molecules)
├── dcsschedule.txt      # Event schedule text
├── metadata.json        # App metadata
└── README.md
```

### Features

- Download as PDF (using html2pdf.js)
- Print directly from browser
- A5 format (148mm × 210mm) optimized for printing
- IISER Kolkata + DCS logos from GitHub
- Full event schedule and speaker list

### Run Instructions

```bash
cd dcs_day_brochure
npm install
npm run dev
```

---

## 12. HTTPS Server Setup

### start_https.py

Full-featured HTTPS development server.

**Features:**
- Generates self-signed SSL certificate in `.ssl/` directory
- Supports `--port` and `--host` arguments
- Shows network access instructions
- VS Code port forwarding guidance
- Uses `use_reloader=False` to prevent interruptions during email sending

**Usage:**
```bash
python start_https.py
python start_https.py --port 5000
python start_https.py --host 0.0.0.0
```

### start_local_https.py

Simpler ad-hoc SSL server using `adhoc` context (requires pyopenssl).

---

## 13. Configuration

### Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `SECRET_KEY` | Yes | dev-secret... | Flask session security |
| `COUPON_SECRET_KEY` | Yes | - | AES-256 encryption key |
| `GOOGLE_CLIENT_ID` | Yes | - | Google OAuth Client ID |
| `GOOGLE_CLIENT_SECRET` | Yes | - | Google OAuth Client Secret |
| `GOOGLE_REDIRECT_URI` | Yes | - | OAuth callback URL (ngrok URL) |
| `FLASK_DEBUG` | No | False | Enable debug mode |
| `PORT` | No | 5000 | Server port |

### Additional Gmail Credentials (for retry_emails.py)

| Variable | File | Purpose |
|----------|------|---------|
| `GOOGLE_CLIENT_ID_2` | .env2 | Secondary account Client ID |
| `GOOGLE_CLIENT_SECRET_2` | .env2 | Secondary account Client Secret |

---

## 14. Routes Reference

### Authentication Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/login` | GET | No | Show login page, initiate OAuth if ?start=true |
| `/auth/callback` | GET | No | Handle Google OAuth callback |
| `/logout` | GET | No | Clear session, revoke token |

### Dashboard Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/` | GET | Required | Redirect to dashboard |
| `/sender` | GET | Required | Main dashboard (sender.html) |

### Scanner Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/scanner` | GET | No | QR scanner interface |
| `/backup-scanner` | GET | No | Backup scanner for debugging |
| `/backup-scan` | POST | No | Save backup scan data |

### Data Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/upload-csv` | POST | Required | Upload attendee CSV |
| `/upload-status` | GET | Required | Get CSV status |
| `/clear-csv` | POST | Required | Clear CSV data |
| `/recipients` | GET | Required | Get attendee list with status |
| `/stats` | GET | Required | Get system statistics |
| `/preview-send` | POST | Required | Preview before sending |

### Action Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/send-emails` | POST | Required | Generate & send coupon emails |
| `/verify-coupon` | POST | No | Verify QR code or 6-digit code |
| `/coupon-status/<id>` | GET | No | Get coupon status by ID |

### Utility Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/failed-emails-logs` | GET | Required | List failed email logs |
| `/download-failed-emails/<filename>` | GET | Required | Download log file |

---

## 15. Security

### Encryption (src/encryption.py)

- **Algorithm:** AES-256 via Fernet (symmetric)
- **Key Derivation:** PBKDF2 with SHA256, 100k iterations
- **Salt:** SHA256(email)[:16] for per-user key isolation
- **Timestamp Validation:** 24-hour coupon expiry
- **Email Hash Validation:** SHA256(email)[:16] embedded in encrypted data

### OAuth 2.0 (src/auth.py)

- **Flow:** Google OAuth 2.0 with offline access
- **Scopes:**
  - `https://www.googleapis.com/auth/gmail.send`
  - `https://www.googleapis.com/auth/userinfo.email`
  - `https://www.googleapis.com/auth/userinfo.profile`
- **Token Storage:** Session only (not persisted to disk)
- **Token Refresh:** Automatic refresh when access token expires

### File Locking (src/data.py)

- All CSV operations use `fcntl.flock()` for concurrent access safety
- Prevents data corruption from simultaneous reads/writes

### Scanner Security

- Email is OPTIONAL for verification code validation
- When email provided, validates code + email match
- When email not provided, validates code only (faster for day-of use)

---

## 16. Key Files Summary

### Core Application

| File | Lines | Purpose |
|------|-------|---------|
| `app.py` | ~948 | Main Flask application, all routes |
| `src/coupons.py` | ~519 | Coupon generation, validation, QR creation |
| `src/data.py` | ~576 | CSV management, file locking, CouponRecord |
| `src/auth.py` | ~325 | Google OAuth, Gmail API |
| `src/encryption.py` | ~186 | AES-256 Fernet encryption |

### Templates

| File | Purpose |
|------|---------|
| `templates/login.html` | Login page with Google OAuth |
| `templates/invitation.html` | Email template with 3 QR tickets (837 lines) |
| `templates/scanner.html` | QR scanner interface |
| `templates/sender.html` | Organizer dashboard |
| `templates/thank_you_registration.html` | Green, DCS Kit info, PDF attached |
| `templates/thank_you_lunch.html` | Orange, Afternoon highlights |
| `templates/thank_you_dinner.html` | Purple, DJ Night info |
| `templates/backup_scanner.html` | Backup scanner for debugging |

### Frontend Assets

| File | Purpose |
|------|---------|
| `static/js/scanner.js` | Camera access, QR detection, verification API |
| `static/css/scanner.css` | Scanner styling, animations |
| `static/attachments/DCS-Day-2026_Schedule.pdf` | Event schedule PDF attachment |

### Utility Scripts

| File | Purpose |
|------|---------|
| `fix_duplicates.py` | Merge duplicate entries smartly |
| `apply_merged.py` | Apply merged CSV to production |
| `fix_status.py` | Fix status field integrity |
| `retry_emails.py` | Help retry sending unsent emails |
| `analyze_data.py` | Analyze data integrity issues |
| `count_lunch_redeemed.py` | Count lunch verifications |
| `count_dinner_redeemed.py` | Count dinner verifications |

### Server Scripts

| File | Purpose |
|------|---------|
| `start_https.py` | Full-featured HTTPS server with SSL |
| `start_local_https.py` | Simple ad-hoc HTTPS server |

### Brochure App

| File | Purpose |
|------|---------|
| `dcs_day_brochure/App.tsx` | Main React app with PDF generation |
| `dcs_day_brochure/constants.tsx` | Event data (speakers, schedule) |
| `dcs_day_brochure/components/*.tsx` | Cover and content pages |

### Documentation

| File | Purpose |
|------|---------|
| `SYSTEM_DOCUMENTATION.md` | Main branch documentation |
| `IMPLEMENTATION_SUMMARY.md` | Changes summary for DCS Day |
| `CHANGES_OVERVIEW.md` | Key improvements overview |
| `DEPLOYMENT_CHECKLIST.md` | Deployment steps |
| `QUICK_START.md` | Quick start guide |
| `WHAT_CHANGED.txt` | Detailed change log |

---

## Appendix: QR Type Reference

| Type | CSV Column | Used At Column | Thank You Template | Emoji |
|------|------------|----------------|-------------------|-------|
| `registration` | `verification_code` | `used_at` | thank_you_registration.html | 🎫 |
| `lunch` | `lunch_verification_code` | `lunch_used_at` | thank_you_lunch.html | 🍽️ |
| `dinner` | `dinner_verification_code` | `dinner_used_at` | thank_you_dinner.html | 🍱 |

---

**Document Version:** 1.0
**Last Updated:** 2026-01-27
**Branch:** dcs_day