# Automated Event Coupon Sender - Repository Documentation

**Repository:** https://github.com/Shuvam-Banerji-Seal/Automated-Event-Coupon-Sender-Email-and-Verification-Application

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Repository Structure](#2-repository-structure)
3. [Branches](#3-branches)
4. [Technology Stack](#4-technology-stack)
5. [System Architecture](#5-system-architecture)
6. [Core Components](#6-core-components)
7. [Features](#7-features)
8. [Installation & Setup](#8-installation--setup)
9. [Configuration](#9-configuration)
10. [Usage Guide](#10-usage-guide)
11. [Routes Reference](#11-routes-reference)
12. [Data Storage](#12-data-storage)
13. [Security](#13-security)
14. [Deployment](#14-deployment)
15. [Utility Scripts](#15-utility-scripts)
16. [Troubleshooting](#16-troubleshooting)
17. [Contributing](#17-contributing)

---

## 1. Project Overview

### Purpose

A web-based application for event organizers to automate the process of generating, distributing, and verifying digital coupons/tickets via email. The system sends personalized QR code coupons to attendees and verifies them in real-time at events using a mobile-friendly web scanner.

### Core Workflow

```
Organizer Login (Google OAuth)
        │
        ▼
Upload Attendee CSV (email list)
        │
        ▼
Generate Unique Coupons + QR Codes
        │
        ▼
Send Emails via Gmail API (organizer's account)
        │
        ▼
Attendees Receive QR Code Emails
        │
        ▼
Event Day: Scan QR Codes at Entry
        │
        ▼
Real-time Verification → Thank You Email
```

### Event Types Supported

| Mode | Description | Use Case |
|------|-------------|----------|
| **Single QR** | One coupon per attendee | Simple events, entry passes |
| **Multi-QR** (dcs_day) | Three coupons per attendee (Registration, Lunch, Dinner) | Multi-session events with separate check-ins |

---

## 2. Repository Structure

```
/
│
├── app.py                          # Main Flask application (all routes)
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment template
├── .gitignore                      # Git ignore rules
│
├── src/                            # Core service modules
│   ├── __init__.py
│   ├── auth.py                     # Google OAuth + Gmail API
│   ├── coupons.py                  # Coupon generation + validation
│   ├── data.py                     # CSV management + file locking
│   └── encryption.py               # AES-256 Fernet encryption
│
├── templates/                      # Jinja2 HTML templates
│   ├── login.html                  # Login page
│   ├── login_error.html            # OAuth error page
│   ├── sender.html                 # Organizer dashboard
│   ├── scanner.html                # QR scanner interface
│   ├── invitation.html             # Coupon email (single QR)
│   ├── event.html                  # Alternative email template
│   ├── thank_you.html              # Post-verification email
│   ├── backup_scanner.html         # Debug scanner
│   └── dcs_day/                    # (dcs_day branch)
│       ├── invitation.html         # 3-QR invitation email
│       ├── thank_you_registration.html
│       ├── thank_you_lunch.html
│       └── thank_you_dinner.html
│
├── static/                         # Static assets
│   ├── attachments/                # Email attachments
│   │   └── DCS-Day-2026_Schedule.pdf
│   ├── css/
│   │   └── scanner.css             # Scanner styles
│   └── js/
│       └── scanner.js              # Scanner JavaScript
│
├── tests/                          # Test files
│   ├── __init__.py
│   ├── test_qr_recognition.py      # (empty)
│   └── test_scanner_improvements.py # (empty)
│
├── old_code/                       # Legacy/discarded code
│   ├── scanner_broken.html
│   ├── scanner_fixed.html
│   ├── distributed_architecture.md
│   └── mobile-*.py/js
│
├── dcs_day_brochure/               # React brochure generator (dcs_day branch)
│   ├── App.tsx
│   ├── index.tsx
│   ├── index.html
│   ├── constants.tsx
│   ├── types.ts
│   ├── package.json
│   ├── vite.config.ts
│   └── components/
│       ├── FrontCover.tsx
│       ├── InsideLeft.tsx
│       ├── InsideRight.tsx
│       ├── BackCover.tsx
│       ├── BrochurePage.tsx
│       └── Decorations.tsx
│
├── scripts/                        # Helper scripts
│   ├── start_with_ngrok.sh         # Ngrok tunnel startup
│   ├── start_https.py              # HTTPS server
│   ├── start_local_https.py        # Local HTTPS
│   ├── setup_ngrok.py              # Ngrok setup helper
│   ├── fix_duplicates.py           # Merge duplicate entries
│   ├── apply_merged.py             # Apply merged CSV
│   ├── fix_status.py               # Fix status field
│   ├── retry_emails.py             # Retry failed emails
│   ├── analyze_data.py             # Data analysis
│   ├── count_lunch_redeemed.py     # Count lunch verifications
│   └── count_dinner_redeemed.py    # Count dinner verifications
│
├── SYSTEM_DOCUMENTATION.md         # Main branch documentation
├── DCS_DAY_BRANCH_DOCUMENTATION.md # dcs_day branch documentation
├── README.md                       # User-facing README
├── SECURITY.md                     # Security policy
├── CONTRIBUTING.md                 # Contribution guide
└── LICENSE                         # MIT License
```

---

## 3. Branches

### main Branch

**Purpose:** Generic event coupon system with single QR code per attendee.

**Key Features:**
- Single coupon per attendee
- Basic invitation email
- Single thank you email template
- Google OAuth authentication
- Gmail API email sending

### dcs_day Branch

**Purpose:** Specialized deployment for DCS Day '26 (IISER Kolkata event).

**Key Features:**
- **3 QR codes per attendee:** Registration, Lunch, Dinner
- **Professional invitation email:** 3 tickets displayed (green/orange/purple themed)
- **3 Thank you templates:** Type-specific (registration/lunch/dinner)
- **Personalized emails:** Attendee name from CSV
- **PDF schedule attachment:** On registration verification
- **Code-only verification:** Email optional for faster scanning
- **Brochure generator app:** React + Vite for event PDF
- **Data utility scripts:** fix_duplicates, retry_emails, analyze_data, etc.
- **HTTPS server scripts:** For testing without ngrok

---

## 4. Technology Stack

### Backend

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.8+ | Runtime |
| Flask | 2.3.3 | Web framework |
| Jinja2 | 3.1.2 | Template engine |

### Security & Encryption

| Technology | Purpose |
|------------|---------|
| cryptography (Fernet) | AES-256 encryption |
| google-auth | OAuth 2.0 |
| google-api-python-client | Gmail API |

### QR Code Generation

| Technology | Purpose |
|------------|---------|
| qrcode[pil] | QR code generation |
| Pillow | Image processing |

### Frontend

| Technology | Purpose |
|------------|---------|
| HTML5 | Page structure |
| CSS3 | Styling (scanner interface) |
| JavaScript | Scanner logic, camera access |
| jsQR | Client-side QR detection |

### Email

| Technology | Purpose |
|------------|---------|
| Gmail API | Send emails from organizer's account |
| Google OAuth 2.0 | Secure authentication |

### Data Storage

| Technology | Purpose |
|------------|---------|
| CSV Files | Primary data storage |
| File Locking (fcntl) | Concurrent access safety |

### Optional (for scaling)

| Technology | Purpose |
|------------|---------|
| PostgreSQL (psycopg2-binary) | Production database |
| Redis | Session storage, caching |
| Flask-SocketIO | Real-time updates |
| Gunicorn | Production WSGI server |
| Eventlet | Async support |

---

## 5. System Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT LAYER                                   │
│                                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐ │
│  │   Organizer     │  │   Attendee      │  │   Event Staff              │ │
│  │   (Browser)     │  │   (Email)       │  │   (Mobile Scanner)         │ │
│  │                 │  │                 │  │                            │ │
│  │ • Upload CSV    │  │ • Receive QR    │  │ • Scan QR codes            │ │
│  │ • Send emails   │  │ • Show at event │  │ • Manual code entry        │ │
│  │ • View stats    │  │                 │  │ • Verify attendees         │ │
│  └────────┬────────┘  └────────┬────────┘  └─────────────┬───────────────┘ │
└───────────┼────────────────────┼──────────────────────────┼─────────────────┘
            │                    │                          │
            ▼                    ▼                          ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                            FLASK APPLICATION                                │
│                              app.py (~948 lines)                            │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ AUTHENTICATION ROUTES                    DATA ROUTES                  │  │
│  │ ─────────────────────                    ───────────                  │  │
│  │ /login → Google OAuth consent screen    /upload-csv                   │  │
│  │ /auth/callback → Token exchange         /stats                        │  │
│  │ /logout → Session clear                 /recipients                   │  │
│  │                                          /preview-send                │  │
│  │                                                                  │  │
│  │ ACTION ROUTES                      VERIFICATION ROUTES           │  │
│  │ ─────────────                      ───────────────────           │  │
│  │ /send-emails → Generate + Send     /scanner (GET)                 │  │
│  │ /verify-coupon → Validate QR       /verify-coupon (POST)          │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
        ▼                           ▼                           ▼
┌─────────────────────────────────┐ ┌─────────────────────────┐ ┌──────────────────────────┐
│         src/coupons.py          │ │      src/data.py        │ │      src/auth.py         │
│          (~519 lines)           │ │       (~576 lines)      │ │       (~325 lines)        │
├─────────────────────────────────┤ ├─────────────────────────┤ ├──────────────────────────┤
│ • generate_coupon_id()          │ │ • CSVManager class      │ │ • GoogleAuthService       │
│   UUID4 generation              │ │   - File locking        │ │   - OAuth URL generation  │
│                                 │ │   - CouponRecord        │ │   - Token exchange        │
│ • generate_verification_code()  │ │   - 14-column schema    │ │   - User info fetch       │
│   6-digit random                │ │                         │ │                           │
│                                 │ │ • find_coupon()         │ │ • GmailEmailService       │
│ • create_qr_code()              │ │ • find_coupon_by_code() │ │   - send_email()          │
│   Base64 PNG output             │ │ • update_status()       │ │   - send_batch_emails()   │
│                                 │ │ • read_recipients()     │ │   - PDF attachment        │
│ • generate_coupons_batch()      │ │                         │ │                           │
│   3 QRs for dcs_day             │ │ • save_organizer_creds()│ │ • create_credentials()    │
│                                 │ │   (for thank-you emails)│ │   from_session()          │
│ • validate_coupon_by_code()     │ │                         │ │                           │
│   qr_type aware                 │ │ • get_organizer_creds() │ │                           │
│                                 │ └─────────────────────────┘ └──────────────────────────┘
│ • mark_coupon_used()            │
│   type-specific timestamp       │
└─────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│       src/encryption.py         │
│          (~186 lines)           │
├─────────────────────────────────┤
│ • EncryptionService class       │
│   - AES-256 via Fernet          │
│   - PBKDF2 key derivation       │
│   - Email-based salt            │
│                                 │
│ • encrypt_coupon_data()         │
│   Adds timestamp + email_hash   │
│                                 │
│ • decrypt_coupon_data()         │
│   Validates email_hash          │
│                                 │
│ • validate_timestamp()          │
│   24-hour expiry check          │
└─────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                             DATA STORAGE                                    │
│                                                                             │
│  coupons.csv                    responses - Sheet1.csv    organizer_credentials.json│
│  ├─ 8 columns (main)            ├─ email                 ├─ user_info           │
│  └─ 14 columns (dcs_day)        └─ [name] (optional)     ├─ oauth_tokens        │
│                                                           └─ event_name         │
│  logs/                                                                   │
│  └─ failed_emails_*.csv                                                  │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Core Components

### 6.1 src/auth.py - Authentication & Email Service

**GoogleAuthService Class:**
```python
class GoogleAuthService:
    """Handles Google OAuth 2.0 authentication"""

    def __init__(self):
        self.client_id = os.getenv('GOOGLE_CLIENT_ID')
        self.client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        self.scopes = [
            'https://www.googleapis.com/auth/gmail.send',
            'https://www.googleapis.com/auth/userinfo.email',
            'https://www.googleapis.com/auth/userinfo.profile'
        ]

    def is_configured() -> bool
    def get_authorization_url(redirect_uri: str) -> (url, state)
    def exchange_code_for_tokens(code: str, state: str, redirect_uri: str) -> dict
    def get_user_info(credentials) -> dict
    def refresh_credentials(refresh_token: str) -> Optional[Credentials]
    def create_credentials_from_session(session_data: dict) -> Optional[Credentials]
```

**GmailEmailService Class:**
```python
class GmailEmailService:
    """Sends emails via Gmail API"""

    def __init__(self, credentials, sender_name=None)
    def _create_message(sender, to, subject, html) -> dict  # MIMEText + base64
    def send_email(sender, to, subject, html, attachment_path=None) -> EmailResult
    def send_batch_emails(sender, recipients, template_renderer, callback) -> dict
    def test_connection() -> bool
```

### 6.2 src/coupons.py - Coupon Management

**CouponManager Class:**
```python
class CouponManager:
    def __init__(self, secret_key=None, csv_manager=None)
    def generate_coupon_id() -> str  # UUID4
    def generate_verification_code() -> str  # 6 random digits
    def create_qr_code(data: str) -> str  # base64 PNG
    def generate_coupon(email, event_name) -> dict  # Single coupon (main)
    def generate_coupons_batch(recipients, event_name) -> dict  # Batch with 3 QRs (dcs_day)
    def validate_coupon(encrypted_data, email) -> dict  # Legacy method
    def validate_coupon_by_code(code, email=None, qr_type='registration') -> dict
    def mark_coupon_used(coupon_id, qr_type='registration') -> bool
    def mark_coupon_sent(coupon_id) -> bool
    def get_coupon_status(coupon_id) -> dict
```

### 6.3 src/data.py - CSV Management

**CouponRecord DataClass:**
```python
@dataclass
class CouponRecord:  # Main branch (8 fields)
    coupon_id: str
    email: str
    encrypted_data: str
    qr_code_data: str
    verification_code: str
    sent_at: Optional[str] = None
    used_at: Optional[str] = None
    status: str = 'generated'

@dataclass
class CouponRecord:  # dcs_day branch (14 fields)
    coupon_id: str
    email: str
    encrypted_data: str
    qr_code_data: str  # Registration QR
    verification_code: str
    lunch_qr_data: Optional[str] = None
    lunch_verification_code: Optional[str] = None
    lunch_used_at: Optional[str] = None
    dinner_qr_data: Optional[str] = None
    dinner_verification_code: Optional[str] = None
    dinner_used_at: Optional[str] = None
    sent_at: Optional[str] = None
    used_at: Optional[str] = None
    status: str = 'generated'
```

**CSVManager Class:**
```python
class CSVManager:
    def __init__(self, coupons_file='coupons.csv', recipients_file='responses - Sheet1.csv')

    # File operations with fcntl locking
    def _file_lock(file_path, mode) -> context manager
    def _initialize_coupons_file()
    def _ensure_verification_code_column()

    # Read operations
    def read_recipients() -> List[dict]  # {'email': ..., 'name': ...}
    def find_coupon(coupon_id) -> Optional[CouponRecord]
    def find_coupon_by_email(email) -> Optional[CouponRecord]
    def find_coupon_by_verification_code(code, email=None, qr_type='registration') -> Optional[CouponRecord]

    # Write operations
    def save_coupon(coupon: CouponRecord) -> bool
    def save_coupons_batch(coupons: List[CouponRecord]) -> bool
    def update_coupon_status(coupon_id, qr_type_or_status, used_at=None, sent_at=None) -> bool

    # Utility
    def get_coupon_stats() -> dict  # {'total', 'generated', 'sent', 'used'}
    def validate_recipients_file(file_path) -> dict
    def save_failed_emails(failed, event_name) -> str  # Returns log filename
    def save_organizer_credentials(user_info, oauth_tokens, event_name) -> bool
    def get_organizer_credentials() -> Optional[dict]
```

### 6.4 src/encryption.py - Encryption Service

**EncryptionService Class:**
```python
class EncryptionService:
    def __init__(self, secret_key=None)

    def _load_secret_key() -> str  # From COUPON_SECRET_KEY env
    def _derive_key(email: str, salt=None) -> bytes  # PBKDF2 + SHA256
    def _create_email_hash(email: str) -> str  # SHA256[:16]

    def encrypt_coupon_data(data: dict, email: str) -> str  # Returns base64
    def decrypt_coupon_data(encrypted_data: str, email: str) -> dict
    def validate_timestamp(data: dict, max_age_hours=24) -> bool
    def generate_secure_token(length=32) -> str
```

### 6.5 app.py - Flask Application

**Authentication Decorator:**
```python
def login_required(f):  # Redirects to /login if no 'user' in session
def get_current_user() -> dict  # Returns session.get('user')
```

**Key Routes:**
| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/login` | GET | No | Show login page |
| `/auth/callback` | GET | No | Handle OAuth callback |
| `/logout` | GET | No | Clear session |
| `/` | GET | Yes | Dashboard |
| `/sender` | GET | Yes | Dashboard (alias) |
| `/scanner` | GET | No | QR scanner interface |
| `/send-emails` | POST | Yes | Generate + send coupons |
| `/verify-coupon` | POST | No | Verify QR/code |
| `/coupon-status/<id>` | GET | No | Get coupon status |
| `/upload-csv` | POST | Yes | Upload CSV |
| `/stats` | GET | Yes | Get statistics |
| `/recipients` | GET | Yes | Get attendee list |

---

## 7. Features

### 7.1 Core Features

| Feature | Description |
|---------|-------------|
| **Google OAuth** | Secure login via Google account |
| **CSV Upload** | Batch upload attendee emails |
| **Unique Coupons** | UUID + 6-digit verification code per coupon |
| **QR Code Generation** | Unique QR code with embedded verification data |
| **Email Sending** | Send via organizer's Gmail account |
| **Real-time Verification** | Scan QR codes at event |
| **Manual Entry** | Enter 6-digit code if camera fails |
| **Status Tracking** | Track: generated → sent → used |
| **Thank You Emails** | Automatic email after verification |
| **Failed Email Logging** | Log failures for retry |

### 7.2 dcs_day Extended Features

| Feature | Description |
|---------|-------------|
| **3-QR System** | Registration, Lunch, Dinner passes |
| **Type-Specific Templates** | 3 thank you email templates |
| **Personalized Greetings** | "Dear [Name]" in emails |
| **PDF Schedule Attachment** | On registration verification |
| **Code-Only Verification** | Email optional for faster scanning |
| **Brochure Generator** | React app for event PDF |
| **Data Utilities** | Duplicate merge, retry, analysis |

### 7.3 Email Templates

**Main Branch:**
- `invitation.html` - Single ticket invitation
- `thank_you.html` - Post-verification thank you

**dcs_day Branch:**
- `invitation.html` - 3 tickets (Registration/Lunch/Dinner)
- `thank_you_registration.html` - Green theme, DCS Kit info, PDF
- `thank_you_lunch.html` - Orange theme, afternoon highlights
- `thank_you_dinner.html` - Purple theme, DJ Night info

---

## 8. Installation & Setup

### 8.1 Prerequisites

```bash
# Required
- Python 3.8+
- pip
- ngrok (for HTTPS + mobile testing)

# Optional (for production)
- PostgreSQL
- Redis
- Gunicorn
```

### 8.2 Installation Steps

```bash
# 1. Clone repository
git clone https://github.com/Shuvam-Banerji-Seal/Automated-Event-Coupon-Sender-Email-and-Verification-Application.git
cd automated-coupon-system

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or: .venv\Scripts\activate  # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create .env file
cp .env.example .env
# Edit .env with your values

# 5. Set up Google OAuth (see next section)
```

### 8.3 Google Cloud Console Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create new project
3. Enable **Gmail API**:
   - Navigate to APIs & Services → Library
   - Search "Gmail API" → Enable
4. Configure OAuth consent screen:
   - APIs & Services → OAuth consent screen
   - User Type: External
   - Fill app name, email
   - Add scopes: `../auth/gmail.send`, `../auth/userinfo.email`, `../auth/userinfo.profile`
5. Create OAuth 2.0 credentials:
   - APIs & Services → Credentials
   - Create Credentials → OAuth client ID
   - Application type: Web application
   - Add authorized redirect URIs:
     - `http://localhost:5000/auth/callback` (for development)
     - `https://your-ngrok-url/auth/callback` (for mobile testing)

### 8.4 Starting the Application

**Option A: With Ngrok (Recommended for mobile testing)**
```bash
# Terminal 1: Start ngrok
./start_with_ngrok.sh

# Terminal 2: Start Flask
python app.py

# Access via ngrok URL (shown in output)
```

**Option B: Local HTTPS (No ngrok)**
```bash
# Generate SSL and start
python start_https.py
# or
python start_local_https.py
```

**Option C: Local HTTP (No HTTPS - camera won't work)**
```bash
export GOOGLE_REDIRECT_URI=http://localhost:5000/auth/callback
python app.py
```

---

## 9. Configuration

### 9.1 Environment Variables (.env)

```bash
# Flask Configuration
SECRET_KEY=your-super-secret-key-at-least-32-characters
FLASK_DEBUG=True
PORT=5000

# Google OAuth (Required)
GOOGLE_CLIENT_ID=123456789.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCDPXxxxxxxxxxxxxxxxxxxxxx
GOOGLE_REDIRECT_URI=https://abc123def456.ngrok.io/auth/callback

# Encryption (Required)
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
COUPON_SECRET_KEY=your-32-byte-hex-key
```

### 9.2 CSV File Format

**responses - Sheet1.csv:**
```csv
email,name
attendee1@example.com,John Doe
attendee2@example.com,Jane Smith
```

**Note:** `name` column is optional but recommended for dcs_day (enables personalization).

### 9.3 Coupon CSV Schema

**Main Branch (8 columns):**
```csv
coupon_id,email,encrypted_data,qr_code_data,verification_code,sent_at,used_at,status
```

**dcs_day Branch (14 columns):**
```csv
coupon_id,email,encrypted_data,qr_code_data,verification_code,lunch_qr_data,lunch_verification_code,lunch_used_at,dinner_qr_data,dinner_verification_code,dinner_used_at,sent_at,used_at,status
```

---

## 10. Usage Guide

### 10.1 Organizer Workflow

1. **Login**
   - Navigate to application URL
   - Click "Login with Google"
   - Authorize the application

2. **Upload Attendees**
   - Click "Upload CSV" button
   - Select CSV with email column
   - Review validation results

3. **Preview Recipients** (Optional)
   - Click "Preview & Send"
   - Review recipient list
   - Remove any unwanted recipients

4. **Send Coupons**
   - Enter event name
   - Click "Send Event Tickets"
   - Wait for batch to complete
   - Monitor success/failure counts

5. **Monitor Statistics**
   - View dashboard stats
   - Track: Generated → Sent → Used
   - Check failed email logs if any

### 10.2 Event Day Verification

1. **Access Scanner**
   - Open `/scanner` on mobile device
   - Allow camera access when prompted

2. **Verify Attendees**
   - **Method A:** Scan QR code
   - **Method B:** Enter 6-digit code manually
   - Email is optional but adds security

3. **Confirmation**
   - Green success → Mark as verified
   - Red error → Check error message
   - Thank you email sent automatically

### 10.3 dcs_day Multi-QR Verification

For dcs_day events with 3 passes:

1. **Registration Pass** (8:30 AM)
   - Scan registration QR
   - DCS Kit collection

2. **Lunch Pass** (1:00 PM)
   - Scan lunch QR
   - Separate lunch verification

3. **Dinner Pass** (6:00 PM)
   - Scan dinner QR
   - DJ Night entry

Each verification sends a type-specific thank you email.

---

## 11. Routes Reference

### Authentication Routes

| Route | Method | Auth | Description |
|-------|--------|------|-------------|
| `/login` | GET | No | Show login page. Add `?start=true` to initiate OAuth |
| `/auth/callback` | GET | No | Handle Google OAuth callback |
| `/logout` | GET | No | Clear session, redirect to login |

### Dashboard Routes

| Route | Method | Auth | Description |
|-------|--------|------|-------------|
| `/` | GET | Yes | Redirect to sender dashboard |
| `/sender` | GET | Yes | Main organizer dashboard |
| `/scanner` | GET | No | QR scanner interface (public) |
| `/backup-scanner` | GET | No | Backup scanner for debugging |

### Data Routes

| Route | Method | Auth | Description |
|-------|--------|------|-------------|
| `/upload-csv` | POST | Yes | Upload attendee CSV |
| `/upload-status` | GET | Yes | Get CSV upload status |
| `/clear-csv` | POST | Yes | Clear CSV data |
| `/recipients` | GET | Yes | Get attendee list with status |
| `/stats` | GET | Yes | Get system statistics |
| `/preview-send` | POST | Yes | Preview before sending |
| `/failed-emails-logs` | GET | Yes | List failed email logs |
| `/download-failed-emails/<filename>` | GET | Yes | Download failure log |

### Action Routes

| Route | Method | Auth | Description |
|-------|--------|------|-------------|
| `/send-emails` | POST | Yes | Generate + send coupon emails |
| `/verify-coupon` | POST | No | Verify QR code or 6-digit code |
| `/coupon-status/<id>` | GET | No | Get coupon status by ID |
| `/backup-scan` | POST | No | Save backup scan data |

### Request/Response Examples

**POST /send-emails**
```json
// Request
{
  "event_name": "DCS Day 2026"
}

// Response
{
  "success": true,
  "sender_email": "organizer@gmail.com",
  "coupons_generated": 150,
  "emails_sent": 148,
  "emails_failed": 2,
  "failed_emails": [...]
}
```

**POST /verify-coupon**
```json
// Request (QR type verification)
{
  "verification_code": "123456",
  "email": "attendee@example.com",  // Optional for dcs_day
  "qr_type": "registration"  // dcs_day: 'registration', 'lunch', or 'dinner'
}

// Response (Success)
{
  "success": true,
  "message": "🎫 Registration verified successfully!",
  "coupon_id": "abc-123-def-456",
  "email": "attendee@example.com",
  "qr_type": "registration",
  "thank_you_email": "sending"
}

// Response (Already Used)
{
  "success": false,
  "error": "🎫 Registration pass has already been used",
  "error_code": "ALREADY_USED",
  "used_at": "2026-01-28T08:45:00+00:00"
}
```

---

## 12. Data Storage

### 12.1 CSV Files

| File | Purpose | Schema |
|------|---------|--------|
| `coupons.csv` | Coupon data | 8 or 14 columns |
| `responses - Sheet1.csv` | Attendee list | email, [name] |
| `organizer_credentials.json` | OAuth tokens | JSON |
| `logs/failed_emails_*.csv` | Failed emails | email, error, timestamp |

### 12.2 File Locking

All CSV read/write operations use `fcntl.flock()` for concurrent access safety:

```python
@contextmanager
def _file_lock(self, file_path, mode='r'):
    f = open(file_path, mode, newline='', encoding='utf-8')
    fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # Exclusive lock
    yield f
    fcntl.flock(f.fileno(), fcntl.LOCK_UN)  # Release
    f.close()
```

### 12.3 Backup Files

| Pattern | Created By |
|---------|------------|
| `coupons.csv.backup_*` | fix_duplicates.py |
| `coupons_backup_*.csv` | apply_merged.py |
| `backup_scans.csv` | backup-scanner |

---

## 13. Security

### 13.1 Built-in Security

| Feature | Implementation |
|---------|----------------|
| **Encryption** | AES-256 via Fernet (cryptography library) |
| **Key Derivation** | PBKDF2 with SHA256, 100k iterations |
| **Email-bound Keys** | Salt = SHA256(email)[:16] |
| **Timestamp Validation** | 24-hour coupon expiry |
| **OAuth 2.0** | Google-managed authentication |
| **Session Security** | Tokens in session, not persisted |
| **File Locking** | fcntl.flock for concurrent safety |

### 13.2 Production Recommendations

See `SECURITY.md` for comprehensive security guidelines:

- Use HTTPS/TLS in production
- Set `SESSION_COOKIE_SECURE = True`
- Use strong `SECRET_KEY` and `COUPON_SECRET_KEY`
- Migrate to PostgreSQL with encryption at rest
- Implement Redis for session storage
- Add rate limiting on verification endpoint
- Set up comprehensive audit logging

### 13.3 Environment Security

```bash
# Generate strong keys
SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
COUPON_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')

# Never commit .env
echo ".env" >> .gitignore
```

---

## 14. Deployment

### 14.1 Development Deployment

```bash
# With ngrok (recommended for mobile testing)
./start_with_ngrok.sh
# In another terminal:
python app.py
```

### 14.2 Production Deployment

```bash
# Using gunicorn
pip install gunicorn eventlet
gunicorn -k eventlet -w 1 app:app --bind 0.0.0.0:5000

# Or with Flask-SocketIO for real-time features
pip install flask-socketio
```

### 14.3 Docker Deployment (Future)

See `distributed_architecture.md` in `old_code/` for planned Docker/Kubernetes setup.

---

## 15. Utility Scripts

### 15.1 Data Management Scripts

| Script | Purpose |
|--------|---------|
| `fix_duplicates.py` | Merge duplicate entries by priority |
| `apply_merged.py` | Apply merged CSV to production |
| `fix_status.py` | Fix status field integrity |
| `analyze_data.py` | Analyze data integrity |
| `count_lunch_redeemed.py` | Count lunch verifications |
| `count_dinner_redeemed.py` | Count dinner verifications |

### 15.2 Email Scripts

| Script | Purpose |
|--------|---------|
| `retry_emails.py` | Help retry failed emails with secondary Gmail |

### 15.3 Server Scripts

| Script | Purpose |
|--------|---------|
| `start_with_ngrok.sh` | Start ngrok tunnel + update .env |
| `start_https.py` | HTTPS server with SSL generation |
| `start_local_https.py` | Simple ad-hoc HTTPS server |
| `setup_ngrok.py` | Ngrok installation helper |

### 15.4 fix_duplicates.py Workflow

```bash
# 1. Run duplicate analysis and merge
python fix_duplicates.py

# Output:
# - coupons_merged.csv (clean data)
# - unsent_recipients.csv (for retry)

# 2. Review merged data
cat coupons_merged.csv | head

# 3. Apply to production (with confirmation)
python apply_merged.py

# 4. Fix status field
python fix_status.py
```

---

## 16. Troubleshooting

### 16.1 Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| OAuth redirect_uri_mismatch | Ngrok URL changed | Update Google Cloud Console with new URL |
| Camera not working on mobile | Not HTTPS | Use ngrok or HTTPS server |
| Email sending fails | Token expired | Re-authenticate via login |
| Invalid QR code | Wrong format scan | Try manual 6-digit code entry |
| CSV upload fails | Missing 'email' column | Add header row with 'email' |

### 16.2 Debug Mode

```bash
export FLASK_DEBUG=True
python app.py
```

### 16.3 Ngrok Web Interface

Access `http://localhost:4040` to:
- View active tunnels
- Inspect HTTP requests/responses
- Debug OAuth flow

### 16.4 Log Files

Check application output for:
- OAuth errors
- Email sending failures
- CSV validation errors
- Coupon generation issues

---

## 17. Contributing

See `CONTRIBUTING.md` for contribution guidelines.

### Development Setup

```bash
# Fork and clone
git clone https://github.com/YOUR_USERNAME/Automated-Event-Coupon-Sender-Email-and-Verification-Application.git
cd automated-coupon-system

# Create feature branch
git checkout -b feature/your-feature-name

# Make changes and commit
git add .
git commit -m "Add your feature"

# Push and create PR
git push origin feature/your-feature-name
```

### Code Style

- Follow PEP 8
- Use meaningful variable/function names
- Add docstrings for complex functions
- Keep functions focused and small

### Testing

```bash
# Run tests (when implemented)
pytest tests/

# Manual testing
python app.py
# Navigate to http://localhost:5000
```

---

## Appendix A: QR Code Formats

### New Format (dcs_day)
```json
{"v": "123456", "e": "attendee@example.com", "t": "registration"}
```

### Legacy Format (main)
```json
{"coupon_id": "...", "email": "...", "encrypted_data": "...", "verification_code": "..."}
```

---

## Appendix B: Email Templates

| Template | Branch | Purpose |
|----------|--------|---------|
| `login.html` | Both | Login page with OAuth button |
| `invitation.html` | Both | Coupon email (single or 3-QR) |
| `event.html` | Main | Alternative coupon email |
| `thank_you.html` | Main | Single post-verification email |
| `thank_you_registration.html` | dcs_day | Registration verification |
| `thank_you_lunch.html` | dcs_day | Lunch verification |
| `thank_you_dinner.html` | dcs_day | Dinner verification |
| `backup_scanner.html` | dcs_day | Debug scanner |

---

## Appendix C: Branch Comparison

| Feature | main | dcs_day |
|---------|------|---------|
| Single QR per attendee | ✅ | ❌ |
| 3 QRs per attendee | ❌ | ✅ |
| Single thank you email | ✅ | ❌ |
| 3 type-specific thank you emails | ❌ | ✅ |
| Personalized greetings | ❌ | ✅ |
| PDF attachment | ❌ | ✅ |
| Brochure generator app | ❌ | ✅ |
| Code-only verification | ❌ | ✅ |
| Data utility scripts | ❌ | ✅ |
| HTTPS server scripts | ❌ | ✅ |

---

**Document Version:** 2.0
**Last Updated:** 2026-04-26
**Branches:** main, dcs_day