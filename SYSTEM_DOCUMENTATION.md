# Automated Event Coupon Sender - System Documentation

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Directory Structure](#3-directory-structure)
4. [Flask Application (app.py)](#4-flask-application-apppy)
5. [Google OAuth & Gmail Service (src/auth.py)](#5-google-oauth--gmail-service-srcauthpy)
6. [Coupon Management (src/coupons.py)](#6-coupon-management-srccouponspy)
7. [Encryption Service (src/encryption.py)](#7-encryption-service-srcencryptionpy)
8. [CSV Data Management (src/data.py)](#8-csv-data-management-srcdatapy)
9. [Ngrok Integration](#9-ngrok-integration)
10. [Email Templates](#10-email-templates)
11. [QR Scanner (scanner.html)](#11-qr-scanner-scannerhtml)
12. [Security Features](#12-security-features)
13. [Configuration Variables](#13-configuration-variables-env)
14. [Typical Workflow Diagram](#14-typical-workflow-diagram)
15. [Environment Setup](#15-environment-setup)
16. [Key Files Reference](#16-key-files-reference)
17. [Improvement Suggestions](#17-improvement-suggestions)

---

## 1. Project Overview

**Project Name:** Automated Event Coupon Sender Email and Verification Application

**Purpose:** A web-based application for event organizers to manage digital coupons and verify attendees at events.

### Core Workflow:
1. Organizer uploads attendee list via CSV
2. System generates unique encrypted digital coupons with QR codes
3. Personalized emails with coupons sent to all attendees via Gmail API
4. Staff verifies coupons in real-time using QR scanner
5. Automatic sending of post-verification thank you emails

### Technology Stack:
- **Backend:** Flask (Python)
- **Authentication:** Google OAuth 2.0
- **Email:** Gmail API (sends from organizer's own Gmail)
- **Database:** CSV files (coupons.csv, responses - Sheet1.csv)
- **Encryption:** AES-256 via Fernet (cryptography library)
- **QR Codes:** qrcode library with PIL
- **Frontend:** HTML5, CSS3, JavaScript (vanilla)
- **Tunneling:** ngrok for public URL and mobile testing

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CLIENT LAYER                                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐ │
│  │   Organizer     │  │   Attendee      │  │   Event Staff              │ │
│  │   (Browser)     │  │   (Email)       │  │   (Mobile Scanner)         │ │
│  └────────┬────────┘  └────────┬────────┘  └─────────────┬──────────────┘ │
└───────────┼────────────────────┼──────────────────────────┼────────────────┘
            │                    │                          │
            ▼                    ▼                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           WEB LAYER (Flask)                                  │
│                                                                              │
│  /login ──────► Google OAuth 2.0 ──────► /auth/callback                      │
│  / ───────────► Dashboard (sender.html) - Auth Required                      │
│  /sender ─────► Event Management Interface - Auth Required                   │
│  /scanner ────► QR Scanner Interface - Public Access                         │
│  /send-emails ─► Generate & Send Coupons - Auth Required                     │
│  /verify-coupon ─► Verify QR/Code - Public Access                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
            │                    │                          │
            ▼                    ▼                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SERVICE LAYER (src/)                               │
│                                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │   auth.py    │  │  coupons.py  │  │   data.py    │  │  encryption.py   │ │
│  │  Google OAuth │  │ Coupon Gen   │  │  CSV Manager │  │  AES-256 Fernet  │ │
│  │  Gmail API    │  │ QR Generation │  │  File Locking│  │  Key Derivation  │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
            │                    │                          │
            ▼                    ▼                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA LAYER                                         │
│                                                                              │
│  coupons.csv              responses - Sheet1.csv     organizer_credentials.json│
│  ├─ coupon_id            └─ email                    └─ OAuth tokens         │
│  ├─ email                                            └─ User info           │
│  ├─ encrypted_data                                     └─ Event name        │
│  ├─ qr_code_data                                                        logs/
│  ├─ verification_code                                    └─ failed_emails_*.csv
│  ├─ sent_at
│  ├─ used_at
│  └─ status
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Directory Structure

```
/
├── app.py                          # Main Flask application entry point
├── setup_ngrok.py                  # Ngrok installation helper
├── start_with_ngrok.sh             # Bash script to start ngrok tunnel
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment variables template
│
├── src/                            # Core application modules
│   ├── __init__.py                 # Package marker
│   ├── auth.py                     # Google OAuth & Gmail API service
│   ├── coupons.py                  # Coupon generation & validation
│   ├── data.py                     # CSV file management with file locking
│   └── encryption.py               # AES-256 encryption using Fernet
│
├── templates/                      # HTML templates (Jinja2)
│   ├── login.html                  # Login page with Google OAuth
│   ├── login_error.html            # Authentication error page
│   ├── sender.html                 # Main dashboard for organizers
│   ├── scanner.html                # QR code scanner interface
│   ├── event.html                  # Email template for coupons
│   └── thank_you.html              # Post-verification thank you email
│
├── tests/                          # Test files
│   ├── __init__.py                 # Package marker
│   ├── test_qr_recognition.py      # QR recognition tests (empty)
│   └── test_scanner_improvements.py# Scanner tests (empty)
│
└── old_code/                       # Legacy/discarded code
    ├── scanner_broken.html         # Previous broken implementation
    ├── scanner_fixed.html          # Fixed scanner
    ├── distributed_architecture.md # Architecture planning docs
    └── mobile-*.py/js              # Mobile-specific solutions
```

---

## 4. Flask Application (app.py)

### 4.1 Configuration

```python
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file upload
app.config['UPLOAD_FOLDER'] = 'uploads'
```

### 4.2 Service Initialization

```python
csv_manager = CSVManager()
coupon_manager = CouponManager(csv_manager=csv_manager)
google_auth_service = GoogleAuthService()
```

### 4.3 Route Overview

| Route | Auth | Purpose |
|-------|------|---------|
| `/login` | No | Show login page or initiate OAuth |
| `/auth/callback` | No | Handle OAuth callback |
| `/logout` | No | Clear session |
| `/` | Yes | Dashboard |
| `/sender` | Yes | Event management interface |
| `/scanner` | No | QR scanner interface |
| `/send-emails` | POST, Yes | Generate & send coupon emails |
| `/verify-coupon` | POST, No | Verify QR code or 6-digit code |
| `/coupon-status/<id>` | No | Get coupon status |
| `/upload-csv` | POST, Yes | Upload attendee CSV |
| `/stats` | Yes | Get system statistics |
| `/recipients` | Yes | Get attendee list with status |
| `/preview-send` | POST, Yes | Preview recipients before sending |
| `/failed-emails-logs` | Yes | List failed email log files |
| `/download-failed-emails/...` | Yes | Download specific log file |

### 4.4 Authentication Flow

```
User visits /login
        │
        ▼
┌───────────────────┐
│ Check session for │
│ 'user' key        │
└─────────┬─────────┘
          │
    ┌─────┴─────┐
    │           │
Session exists    No session
    │           │
    ▼           ▼
Redirect to    Show login.html
/dashboard     with Google OAuth button
        │
        ▼
User clicks button (?start=true)
        │
        ▼
┌─────────────────────────────────────┐
│ google_auth_service.get_authorization_url(redirect_uri)
│ Returns: authorization_url, state   │
└─────────────────┬───────────────────┘
                  │
                  ▼
User redirected to Google, consents, returned to /auth/callback
        │
        ▼
┌─────────────────────────────────────┐
│ google_auth_service.exchange_code_for_tokens(code, state, redirect)
│ Returns: access_token, refresh_token, user_info
└─────────────────┬───────────────────┘
                  │
                  ▼
Session stored:
- session['user'] = {email, name, picture, id}
- session['oauth_tokens'] = {access_token, refresh_token, token_uri, client_id, client_secret, scopes}
        │
        ▼
Redirect to / (dashboard)
```

### 4.5 Send Emails Flow

```python
@app.route('/send-emails', methods=['POST'])
def send_emails():
    # 1. Get user and OAuth tokens from session
    user = get_current_user()
    oauth_tokens = session.get('oauth_tokens')

    # 2. Create Gmail service with user's credentials
    credentials = google_auth_service.create_credentials_from_session(oauth_tokens)
    gmail_service = GmailEmailService(credentials)

    # 3. Read recipients from CSV
    recipients = csv_manager.read_recipients()

    # 4. Generate coupons for all recipients
    coupon_results = coupon_manager.generate_coupons_batch(recipients, event_name)

    # 5. Send emails via Gmail API
    email_results = gmail_service.send_batch_emails(
        sender_email=user['email'],
        recipients=email_recipients,
        template_renderer=render_template,
        progress_callback=log_progress
    )

    # 6. Mark successfully sent coupons
    for result in email_results['results']:
        if result.success:
            mark_coupon_sent(coupon['coupon_id'])

    # 7. Save failed emails to log
    if failed_emails:
        csv_manager.save_failed_emails(failed_emails, event_name)

    # 8. Save organizer credentials for thank-you emails
    csv_manager.save_organizer_credentials(user, oauth_tokens, event_name)
```

### 4.6 Coupon Verification Flow

```python
@app.route('/verify-coupon', methods=['POST'])
def verify_coupon():
    data = request.get_json()

    # Two verification methods:
    # 1. 6-digit verification code + email (new coupons)
    # 2. encrypted_data + email (legacy coupons)

    if verification_code and len(verification_code) == 6:
        validation_result = coupon_manager.validate_coupon_by_code(verification_code, email)
    else:
        validation_result = coupon_manager.validate_coupon(encrypted_data, email)

    if validation_result['valid']:
        # Mark as used
        coupon_manager.mark_coupon_used(coupon_id)

        # Send thank you email in background thread
        threading.Thread(target=send_thank_you_async).start()

    return jsonify({
        'success': True,
        'message': 'Coupon verified and marked as used',
        'thank_you_email': 'sending'  # Indicates async email
    })
```

---

## 5. Google OAuth & Gmail Service (src/auth.py)

### 5.1 GoogleAuthService

Handles Google OAuth 2.0 authentication and token management.

**OAuth 2.0 Scopes:**
- `https://www.googleapis.com/auth/gmail.send` - Send emails on behalf of user
- `https://www.googleapis.com/auth/userinfo.email` - Read user's email address
- `https://www.googleapis.com/auth/userinfo.profile` - Read user's profile info

**Key Methods:**

| Method | Purpose |
|--------|---------|
| `is_configured()` | Returns True if CLIENT_ID and CLIENT_SECRET are set |
| `get_authorization_url(redirect_uri)` | Generates OAuth consent screen URL with state parameter |
| `exchange_code_for_tokens(code, state, redirect)` | Exchanges authorization code for access/refresh tokens |
| `get_user_info(credentials)` | Fetches user profile from Google OAuth2 API |
| `refresh_credentials(refresh_token)` | Uses refresh token to get new access token |
| `create_credentials_from_session(session_data)` | Rebuilds google.oauth2.credentials.Credentials from session |

**Token Exchange Process:**
```python
# Manual token exchange (not using google_auth_oauthlib.flow)
response = requests.post('https://oauth2.googleapis.com/token', data={
    'code': authorization_code,
    'client_id': self.client_id,
    'client_secret': self.client_secret,
    'redirect_uri': current_redirect_uri,
    'grant_type': 'authorization_code'
})
token_response = response.json()

# Create Credentials object
credentials = Credentials(
    token=token_response.get('access_token'),
    refresh_token=token_response.get('refresh_token'),
    token_uri='https://oauth2.googleapis.com/token',
    client_id=self.client_id,
    client_secret=self.client_secret,
    scopes=self.scopes
)
```

### 5.2 GmailEmailService

Sends emails via Gmail API using OAuth2 credentials.

**Key Methods:**

| Method | Purpose |
|--------|---------|
| `_create_message(sender, to, subject, html)` | Creates MIMEText message, base64 encodes it |
| `send_email(sender, recipient, subject, html)` | Sends single email via Gmail API |
| `send_batch_emails(sender, recipients, template_renderer, callback)` | Sends to multiple with progress tracking |
| `test_connection()` | Verifies Gmail API connectivity |

**Email Sending Process:**
```python
def send_email(sender_email, recipient, subject, html_content):
    # 1. Refresh credentials if expired
    if self.credentials.expired:
        self.credentials.refresh(Request())

    # 2. Build Gmail service
    service = build('gmail', 'v1', credentials=self.credentials)

    # 3. Create message
    message = MIMEMultipart('alternative')
    message['to'] = recipient
    message['from'] = sender_email
    message['subject'] = subject
    html_part = MIMEText(html_content, 'html')
    message.attach(html_part)

    # 4. Base64url encode
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

    # 5. Send via Gmail API
    result = service.users().messages().send(
        userId='me',
        body={'raw': raw_message}
    ).execute()
```

**Batch Email Sending:**
```python
def send_batch_emails(sender_email, recipients, template_renderer, callback):
    for i, recipient_data in enumerate(recipients):
        # Render email content using template
        html_content = template_renderer('event.html', recipient_data)

        # Send individual email
        result = self.send_email(sender_email, recipient_email, subject, html_content)

        # Call progress callback
        if callback:
            callback({'current': i+1, 'total': len(recipients), ...})

        # Delay to avoid Gmail rate limiting
        time.sleep(0.1)
```

---

## 6. Coupon Management (src/coupons.py)

### 6.1 Coupon Generation Flow

```
User clicks send button → POST /send-emails
        │
        ▼
csv_manager.read_recipients()
        │
        ▼
coupon_manager.generate_coupons_batch(recipients, event_name)
        │
        ▼
For each recipient:
  1. Generate coupon_id: str(uuid.uuid4())  # e.g., 'abc-123-def-456'
  2. Generate verification_code: ''.join(random.choices(string.digits, k=6))  # e.g., '123456'
  3. Create coupon_data dict
  4. Encrypt via encryption_service.encrypt_coupon_data(coupon_data, email)
  5. Create QR code with JSON: {'v': '123456', 'e': 'email@example.com'}
  6. Save CouponRecord to CSV
        │
        ▼
GmailEmailService.send_batch_emails(...)
        │
        ▼
For each email:
  1. Render event.html with qr_code_base64 and verification_code
  2. Send via Gmail API
  3. Mark coupon as 'sent' on success
  4. Log failures to logs/failed_emails_TIMESTAMP.csv
        │
        ▼
Save organizer credentials to organizer_credentials.json
(for sending thank-you emails during verification)
```

### 6.2 QR Code Data Structure

**Current format (new coupons):**
```json
{
  v: '123456',           // 6-digit verification code
  e: 'attendee@example.com'  // recipient email (lowercase)
}
```
This data is JSON-serialized before encoding in QR code.

**Legacy format (old coupons):**
```json
{
  coupon_id: 'uuid',
  email: 'attendee@example.com',
  encrypted_data: 'base64-encrypted-string',
  verification_code: '123456'
}
```

### 6.3 Coupon Status States

| Status | Description |
|--------|-------------|
| `generated` | Coupon created, email not yet sent |
| `sent` | Email sent to recipient |
| `used` | Coupon verified at event |
| `expired` | Coupon past 24-hour validity (future) |

### 6.4 Key Methods

| Method | Purpose |
|--------|---------|
| `generate_coupon_id()` | Returns UUID4 string |
| `generate_verification_code()` | Returns random 6-digit string |
| `create_qr_code(data)` | Creates QR code, returns base64 PNG |
| `generate_coupon(email, event_name)` | Creates single coupon |
| `generate_coupons_batch(recipients, event_name)` | Creates multiple coupons |
| `validate_coupon(encrypted_data, email)` | Validates legacy QR method |
| `validate_coupon_by_code(code, email)` | Validates 6-digit code method |
| `mark_coupon_used(coupon_id)` | Updates status to 'used' with timestamp |
| `mark_coupon_sent(coupon_id)` | Updates status to 'sent' with timestamp |
| `get_coupon_status(coupon_id)` | Returns coupon status details |

---

## 7. Encryption Service (src/encryption.py)

### 7.1 Encryption Algorithm

**Method:** AES-256 via Fernet (symmetric encryption)

Fernet guarantees:
- Message confidentiality using AES-256-CBC
- Message authenticity using HMAC-SHA256
- Timestamp validation

### 7.2 Key Derivation

```python
def _derive_key(self, email: str, salt: bytes = None) -> bytes:
    if salt is None:
        # Use email hash as salt for consistency
        salt = hashlib.sha256(email.lower().encode()).digest()[:16]

    # Combine secret key with email for key derivation
    password = f'{self.secret_key}:{email.lower()}'.encode()

    # PBKDF2 with 100,000 iterations
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password))
    return key
```

**Why email-based key derivation?**
- Same email always produces same encryption key
- Different emails produce completely different keys
- Even if secret_key leaks, attacker cannot decrypt without knowing the email address

### 7.3 Encrypted Data Structure

```python
{
    'coupon_id': 'abc-123-def-456',
    'email': 'attendee@example.com',       # stored in lowercase
    'event_name': 'Tech Conference 2024',
    'verification_code': '123456',
    'created_at': '2024-01-15T10:30:00+00:00',
    'valid': True,
    'timestamp': '2024-01-15T10:30:00+00:00',  # UTC when encrypted
    'email_hash': 'a1b2c3d4e5f6g7h8'            # SHA256(email)[:16]
}
```

### 7.4 Validation Process

```python
def decrypt_coupon_data(self, encrypted_data: str, email: str) -> Dict:
    # 1. Decode base64
    encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())

    # 2. Derive key using email and decrypt
    key = self._derive_key(email)
    fernet = Fernet(key)
    decrypted_bytes = fernet.decrypt(encrypted_bytes)

    # 3. Parse JSON
    data = json.loads(decrypted_bytes.decode())

    # 4. Verify email hash
    expected_hash = self._create_email_hash(email)
    if data.get('email_hash') != expected_hash:
        raise ValueError('Email hash validation failed')

    # 5. Verify email field matches
    if data.get('email', '').lower() != email.lower():
        raise ValueError('Email validation failed')

    return data

def validate_timestamp(self, data: Dict, max_age_hours: int = 24) -> bool:
    # Parse timestamp and check if within acceptable age
    timestamp = datetime.fromisoformat(data.get('timestamp').replace('Z', '+00:00'))
    now = datetime.now(timezone.utc)
    age_hours = (now - timestamp).total_seconds() / 3600
    return 0 <= age_hours <= max_age_hours
```

### 7.5 Key Methods

| Method | Purpose |
|--------|---------|
| `encrypt_coupon_data(data, email)` | Encrypts coupon dict, adds timestamp and email_hash |
| `decrypt_coupon_data(encrypted_data, email)` | Decrypts, validates email hash, returns dict |
| `validate_timestamp(data, max_age_hours)` | Checks if coupon is within 24-hour validity |
| `generate_secure_token(length)` | Generates cryptographically random token |

---

## 8. CSV Data Management (src/data.py)

### 8.1 CouponRecord Data Class

```python
@dataclass
class CouponRecord:
    coupon_id: str                    # UUID4
    email: str                        # lowercase email
    encrypted_data: str               # base64 AES-256 encrypted
    qr_code_data: str                 # base64 PNG QR code
    verification_code: str            # 6-digit code
    sent_at: Optional[str] = None     # ISO timestamp when email sent
    used_at: Optional[str] = None     # ISO timestamp when verified
    status: str = 'generated'         # generated/sent/used/expired

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict):
        return cls(**data)
```

### 8.2 File Structure

**coupons.csv:**
```csv
coupon_id,email,encrypted_data,qr_code_data,verification_code,sent_at,used_at,status
abc-123-def-456,attendee@example.com,gAAAAABh...,iVBORw0KGgo...,123456,2024-01-15T10:30:00+00:00,,sent
def-789-ghi-012,another@example.com,gAAAAABh...,,654321,,,generated
```

**responses - Sheet1.csv:**
```csv
email
attendee1@example.com
attendee2@example.com
```

**organizer_credentials.json:**
```json
{
  'user_info': {
    'email': 'organizer@gmail.com',
    'name': 'Event Organizer',
    'picture': 'https://...',
    'id': '123456789'
  },
  'oauth_tokens': {
    'access_token': 'ya29...',
    'refresh_token': '1//0g...',
    'token_uri': 'https://oauth2.googleapis.com/token',
    'client_id': '123.apps.googleusercontent.com',
    'client_secret': 'GOCDPX...',
    'scopes': ['https://www.googleapis.com/auth/gmail.send', ...]
  },
  'event_name': 'Tech Conference 2024',
  'saved_at': '2024-01-15T10:30:00+00:00'
}
```

### 8.3 File Locking Mechanism

All CSV operations use `fcntl.flock()` for concurrent access protection:

```python
@contextmanager
def _file_lock(self, file_path: str, mode: str = 'r'):
    f = open(file_path, mode, newline='', encoding='utf-8')
    fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # Exclusive lock - blocks others
    yield f
    fcntl.flock(f.fileno(), fcntl.LOCK_UN)  # Release lock
    f.close()
```

**Why file locking?**
- Prevents race conditions when multiple users access simultaneously
- Ensures data integrity during read-write operations
- Works across processes on Unix/Linux systems

### 8.4 Key Methods

| Method | Purpose |
|--------|---------|
| `read_recipients()` | Returns list of {email} dicts from CSV |
| `save_coupon(coupon)` | Appends single coupon to CSV |
| `save_coupons_batch(coupons)` | Appends multiple coupons efficiently |
| `find_coupon(coupon_id)` | Returns CouponRecord by ID or None |
| `find_coupon_by_verification_code(code, email)` | Security check - finds by code AND email |
| `update_coupon_status(coupon_id, status, used_at)` | Updates status, optionally sets used_at |
| `get_coupon_stats()` | Returns counts: total, generated, sent, used |
| `validate_recipients_file(file_path)` | Validates CSV structure and email formats |
| `save_failed_emails(failed_emails, event_name)` | Writes failures to logs/failed_emails_*.csv |
| `save_organizer_credentials(user_info, tokens, event)` | Persists OAuth tokens for thank-you emails |
| `get_organizer_credentials()` | Loads stored credentials for verification emails |

---

## 9. Ngrok Integration

### 9.1 Purpose

1. **HTTPS for mobile camera access:** Browsers require HTTPS for `getUserMedia()` API (camera access)
2. **Google OAuth redirect URI:** Must be a public HTTPS URL registered in Google Cloud Console
3. **Mobile testing:** Access scanner from any device connected to internet
4. **Real device QA:** Test on actual phones/tablets, not just browser emulators

### 9.2 Startup Script (start_with_ngrok.sh)

```bash
#!/bin/bash
# Start ngrok tunnel to port 5000
ngrok http 5000 --log=stdout > ngrok.log 2>&1 &
NGROK_PID=$!

# Wait for tunnel to initialize
sleep 3

# Query ngrok API for public HTTPS URL
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c '
import sys, json
data = json.load(sys.stdin)
for tunnel in data['tunnels']:
    if tunnel['proto'] == 'https':
        print(tunnel['public_url'])
')

# Update .env with new redirect URI
python3 -c '
import os
with open(env_path, r) as f:
    content = f.read()
# Replace GOOGLE_REDIRECT_URI line
'

# Output instructions
echo 'NEXT STEPS:'
echo '1. Update Google Console with: $NGROK_URL/auth/callback'
echo '2. Start Flask: python app.py'
echo '3. Access from any device: $NGROK_URL'
```

### 9.3 Network Flow

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         DEVELOPER'S MACHINE                                 │
│                                                                             │
│   start_with_ngrok.sh                                                       │
│        │                                                                    │
│        ▼                                                                    │
│   ┌─────────────────────────────┐                                          │
│   │  ngrok process              │                                          │
│   │  listening on localhost     │                                          │
│   │  port 5000                  │                                          │
│   └──────────────┬──────────────┘                                          │
│                  │                                                           │
│   Flask app ◄────┼─────► port 5000                                          │
│                  │                                                           │
│   Ngrok tunnel ◄─┘                                                           │
│        │                                                                    │
│        ▼                                                                    │
│   ┌─────────────────────────────┐                                          │
│   │  Creates public HTTPS URL   │                                          │
│   │  e.g., https://abc123.ngrok.io                                          │
│   └──────────────┬──────────────┘                                          │
└──────────────────┼──────────────────────────────────────────────────────────┘
                   │
                   │ HTTPS traffic
                   ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                            INTERNET                                         │
└──────────────────┬──────────────────────────────────────────────────────────┘
                   │
          ┌────────┴────────┐
          │                 │
          ▼                 ▼
    ┌──────────┐     ┌──────────┐
    │Organizer │     │ Attendee │
    │ Browser  │     │  Device  │
    └──────────┘     └──────────┘
```

### 9.4 Google Cloud Console Setup

For OAuth to work, you must register the ngrok URL:

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Navigate to: **APIs & Services → Credentials**
3. Click on your **OAuth 2.0 Client ID**
4. Under **Authorized redirect URIs**, add:
   ```
   https://abc123def456.ngrok.io/auth/callback
   ```
   (Use YOUR actual ngrok URL from start_with_ngrok.sh output)
5. Click **Save**

**Important:** Every time you restart ngrok, you get a NEW URL. You must:
1. Update `.env` with new `GOOGLE_REDIRECT_URI` (handled automatically by script)
2. Update Google Cloud Console with new authorized redirect URI

### 9.5 Ngrok Web Interface

Ngrok provides a local web interface at `http://localhost:4040` for:
- Viewing active tunnels
- Inspecting HTTP requests/responses
- Debugging OAuth flow
- Replaying requests

---

## 10. Email Templates

### 10.1 event.html (Coupon Email)

The email sent to attendees containing their QR code and verification code.

**Design Features:**
- Gradient header with event name
- Large, prominent 6-digit verification code
- Embedded QR code image (base64 PNG)
- Coupon ID reference number
- Step-by-step usage instructions
- 24-hour validity notice
- Mobile-responsive layout

**Key Template Variables:**
```html
{{ event_name }}           -- Event title
{{ email }}                -- Recipient email
{{ qr_code_base64 }}       -- Base64 encoded QR image
{{ verification_code }}    -- 6-digit code
{{ coupon_id }}            -- UUID reference
```

**Email Preview:**
```
┌─────────────────────────────────────────────┐
│ 🎉 Tech Conference 2024                     │
│ Your Digital Coupon is Ready!               │
├─────────────────────────────────────────────┤
│ Hello attendee@example.com!                 │
│                                             │
│ ┌─────────────────────────────────────────┐ │
│ │ Your Digital Coupon                      │ │
│ │                                         │ │
│ │   🔢 Verification Code                  │ │
│ │   ╔═══════════════════════════╗         │ │
│ │   ║       1 2 3 4 5 6         ║         │ │
│ │   ╚═══════════════════════════╝         │ │
│ │                                         │ │
│ │   [QR Code Image]                       │ │
│ │                                         │ │
│ │   Coupon ID: abc-123-def-456            │ │
│ └─────────────────────────────────────────┘ │
│                                             │
│ 📱 How to Use Your Coupon                   │
│ • Easy: Tell staff your 6-digit code        │
│ • Alt: Show QR code for scanning            │
│ • Save this email or screenshot             │
│                                             │
│ 💡 Quick Tip: Just tell staff: 123456       │
├─────────────────────────────────────────────┤
│ This coupon is valid for 24 hours           │
└─────────────────────────────────────────────┘
```

### 10.2 thank_you.html (Post-Verification Email)

Sent automatically after a coupon is verified at the event.

**Key Template Variables:**
```html
{{ email }}                -- Attendee email
{{ attendee_name }}        -- Attendee name (if available)
{{ event_name }}           -- Event title
{{ attendance_date }}      -- When coupon was verified
{{ coupon_id }}            -- UUID reference
{{ organizer_name }}       -- Organizer's name
{{ organizer_email }}      -- Organizer's email
{{ current_date }}         -- Email sent timestamp
```

---

## 11. QR Scanner (scanner.html)

### 11.1 Camera Access Strategy

The scanner implements multiple fallback strategies for camera access:

**Primary Method:**
```javascript
navigator.mediaDevices.getUserMedia({
    video: { facingMode: 'environment' }
})
```

**Fallback Methods:**
1. Simple fallback: `{ video: true }` without constraints
2. Back camera priority: Enumerate devices, filter by 'back'/'rear' labels
3. Manual camera selector: Let user pick from available devices
4. Manual entry: Fallback to 6-digit code + email form

### 11.2 QR Detection Process

Using `jsQR` library for client-side detection:

```javascript
// 1. Capture frame from video element
canvas.width = video.videoWidth;
canvas.height = video.videoHeight;
context.drawImage(video, 0, 0);

// 2. Extract image data
const imageData = context.getImageData(0, 0, canvas.width, canvas.height);

// 3. Detect QR code
const code = jsQR(imageData.data, canvas.width, canvas.height);

// 4. If found, parse JSON data
if (code) {
    const data = JSON.parse(code.data);
    // data = { v: '123456', e: 'attendee@example.com' }
}
```

### 11.3 Dual Verification Methods

| Method | Input | Security Validation |
|--------|-------|---------------------|
| QR Scan | Scanned JSON: `{'v': '123456', 'e': 'email@example.com'}` | Code + Email match in DB |
| Manual Code | 6-digit code + email in form | Code + Email combination |
| Legacy QR | Encrypted blob + email | Decrypt and validate expiry |

### 11.4 Scanner UI Features

- **Real-time camera feed** with scanning overlay and corner markers
- **Status indicator** showing scanning/success/error states
- **Debug info panel** for troubleshooting camera issues
- **Manual entry fallback** when camera unavailable
- **Keyboard shortcuts** (Spacebar for manual capture)
- **Mobile-optimized** with back camera preference

### 11.5 Verification Flow

```
User scans QR → handleQRDetection(qrData)
        │
        ▼
Check if data is JSON with 'v' and 'e' keys
        │
        ├── Yes (new format) → validate_coupon_by_code(v, e)
        │
        └── No (legacy format) → validate_coupon(encrypted_data, email)
        │
        ▼
POST /verify-coupon
        │
        ▼
┌─────────────────────────────────────────┐
│ Server validates:                       │
│ 1. Find coupon by verification_code     │
│ 2. Match email in database              │
│ 3. Check status != 'used'               │
│ 4. Decrypt and validate timestamp       │
└─────────────────┬───────────────────────┘
                  │
                  ▼
Mark coupon as 'used' in CSV
        │
        ▼
Send thank_you.html email via background thread
(using stored organizer credentials from organizer_credentials.json)
        │
        ▼
Return success to scanner → Show confirmation modal
```

---

## 12. Security Features

| Feature | Implementation | Purpose |
|---------|---------------|---------|
| Google OAuth 2.0 | Google-managed authentication | Secure identity verification |
| AES-256 Encryption | Fernet symmetric encryption | Protect coupon data |
| Per-user key derivation | PBKDF2 with email-based salt | Email-bound encryption |
| Email hash validation | SHA256(email)[:16] in encrypted data | Verify email matches |
| 6-digit verification | Random digits for human use | Quick verification |
| Timestamp expiry | 24-hour validity check | Prevent replay attacks |
| File locking | fcntl.flock on CSV operations | Prevent race conditions |
| Session-only tokens | OAuth tokens in session, not persisted | Limit token exposure |
| HTTPS requirement | ngrok tunnel for mobile | Camera API requires HTTPS |

---

## 13. Configuration Variables (.env)

| Variable | Required | Purpose | Example |
|----------|----------|---------|---------|
| `SECRET_KEY` | Yes | Flask session security | `dev-secret-key-change-in-production` |
| `FLASK_DEBUG` | No | Enable debug mode | `True` or `False` |
| `PORT` | No | Server port (default 5000) | `5000` |
| `GOOGLE_CLIENT_ID` | Yes | OAuth 2.0 Client ID | `123.apps.googleusercontent.com` |
| `GOOGLE_CLIENT_SECRET` | Yes | OAuth 2.0 Client Secret | `GOCDPXxxxxxxxxxx` |
| `GOOGLE_REDIRECT_URI` | Yes | OAuth callback URL | `https://abc123.ngrok.io/auth/callback` |
| `COUPON_SECRET_KEY` | Yes | Encryption master key | `your-32-char-secret-key!` |

---

## 14. Typical Workflow Diagram

```
┌────────────────────────────────────────────────────────────────────────────┐
│                      COMPLETE SYSTEM WORKFLOW                               │
└────────────────────────────────────────────────────────────────────────────┘

╔══════════════════════════════════════════════════════════════════════════╗
║ 1. SETUP PHASE                                                             ║
╠══════════════════════════════════════════════════════════════════════════╣
│                                                                             │
│   Developer Machine                                                         │
│        │                                                                   │
│        ├── Install ngrok → ./start_with_ngrok.sh                           │
│        │         │                                                         │
│        │         ▼                                                         │
│        │   Ngrok provides public HTTPS URL                                 │
│        │   e.g., https://abc123def456.ngrok.io                             │
│        │         │                                                         │
│        │         ▼                                                         │
│        │   Script auto-updates .env                                        │
│        │         │                                                         │
│        │         ▼                                                         │
│        │   Google Cloud Console ← Add redirect URI                         │
│        │         │                                                         │
│        │         ▼                                                         │
│        └── Configure .env with all variables                               │
│                  │                                                          │
│                  ▼                                                          │
│            python app.py ← Flask starts on port 5000                       │
│                                                                            │
╚══════════════════════════════════════════════════════════════════════════╝

                                   │
                                   ▼

╔══════════════════════════════════════════════════════════════════════════╗
║ 2. ORGANIZER LOGIN PHASE                                                   ║
╠══════════════════════════════════════════════════════════════════════════╣
│                                                                             │
│   Browser → https://abc123.ngrok.io/                                       │
│        │                                                                   │
│        ▼                                                                   │
│   /login page → Click 'Login with Google'                                  │
│        │                                                                   │
│        ▼                                                                   │
│   Google OAuth consent screen → User logs in                               │
│        │                                                                   │
│        ▼                                                                   │
│   Redirected to /auth/callback with ?code=xxx&state=yyy                    │
│        │                                                                   │
│        ▼                                                                   │
│   Tokens exchanged → Session stored                                        │
│        │                                                                   │
│        ▼                                                                   │
│   Redirect to / → Dashboard visible                                        │
│                                                                            │
╚══════════════════════════════════════════════════════════════════════════╝

                                   │
                                   ▼

╔══════════════════════════════════════════════════════════════════════════╗
║ 3. ATTENDEE UPLOAD PHASE                                                   ║
╠══════════════════════════════════════════════════════════════════════════╣
│                                                                             │
│   Dashboard → Click 'Upload Attendee List'                                 │
│        │                                                                   │
│        ▼                                                                   │
│   Select CSV file with 'email' column                                      │
│        │                                                                   │
│        ▼                                                                   │
│   POST /upload-csv → File validated                                        │
│        │                                                                   │
│        ▼                                                                   │
│   CSV saved to 'responses - Sheet1.csv'                                    │
│                                                                            │
╚══════════════════════════════════════════════════════════════════════════╝

                                   │
                                   ▼

╔══════════════════════════════════════════════════════════════════════════╗
║ 4. COUPON GENERATION PHASE                                                 ║
╠══════════════════════════════════════════════════════════════════════════╣
│                                                                             │
│   Dashboard → Enter event name → Click 'Send Coupons'                      │
│        │                                                                   │
│        ▼                                                                   │
│   POST /preview-send → Confirmation dialog shows                           │
│        │                                                                   │
│        ▼                                                                   │
│   User confirms → POST /send-emails                                        │
│        │                                                                   │
│        ▼                                                                   │
│   ┌──────────────────────────────────────────────────────────────────┐    │
│   │ For each recipient:                                               │    │
│   │   1. Generate UUID coupon_id                                      │    │
│   │   2. Generate 6-digit verification_code                           │    │
│   │   3. Create coupon_data dict with encryption                      │    │
│   │   4. Encrypt via AES-256 (key derived from email)                 │    │
│   │   5. Create QR code with JSON: {v, e}                             │    │
│   │   6. Save CouponRecord to coupons.csv                             │    │
│   └──────────────────────────────────────────────────────────────────┘    │
│        │                                                                   │
│        ▼                                                                   │
│   ┌──────────────────────────────────────────────────────────────────┐    │
│   │ For each recipient:                                               │    │
│   │   1. Render event.html template with QR code                      │    │
│   │   2. Send via Gmail API using organizer's account                 │    │
│   │   3. Mark coupon status as 'sent' on success                      │    │
│   │   4. Log failures to logs/failed_emails_TIMESTAMP.csv            │    │
│   └──────────────────────────────────────────────────────────────────┘    │
│        │                                                                   │
│        ▼                                                                   │
│   Organizer credentials saved to organizer_credentials.json                │
│   (for sending thank-you emails during verification)                       │
│                                                                            │
╚══════════════════════════════════════════════════════════════════════════╝

                                   │
                                   ▼

╔══════════════════════════════════════════════════════════════════════════╗
║ 5. ATTENDEE EMAIL PHASE                                                    ║
╠══════════════════════════════════════════════════════════════════════════╣
│                                                                             │
│   Attendee receives email with subject: 'Your Digital Coupon for Event'    │
│        │                                                                   │
│        ▼                                                                   │
│   Email contains:                                                          │
│   ├── QR code image (base64 embedded)                                      │
│   ├── 6-digit verification code                                            │
│   ├── Coupon ID                                                             │
│   └── Event name and instructions                                           │
│                                                                            │
╚══════════════════════════════════════════════════════════════════════════╝

                                   │
                                   ▼

╔══════════════════════════════════════════════════════════════════════════╗
║ 6. VERIFICATION PHASE (Event Day)                                          ║
╠══════════════════════════════════════════════════════════════════════════╣
│                                                                             │
│   Event staff opens scanner on mobile:                                     │
│   https://abc123.ngrok.io/scanner                                          │
│        │                                                                   │
│        ▼                                                                   │
│   Camera access granted (HTTPS required)                                   │
│        │                                                                   │
│        ▼                                                                   │
│   ┌──────────────────────────────────────────────────────────────────┐    │
│   │ OPTION A: Scan QR Code                                            │    │
│   │   └── jsQR detects code → extracts {v: '123456', e: 'email'}     │    │
│   │                                                                     │    │
│   │ OPTION B: Manual 6-digit code                                      │    │
│   │   └── Staff types code + attendee email into form                 │    │
│   └──────────────────────────────────────────────────────────────────┘    │
│        │                                                                   │
│        ▼                                                                   │
│   POST /verify-coupon                                                      │
│        │                                                                   │
│        ▼                                                                   │
│   ┌──────────────────────────────────────────────────────────────────┐    │
│   │ Server validates:                                                  │    │
│   │   1. Find coupon by verification_code                              │    │
│   │   2. Match email (case-insensitive)                                │    │
│   │   3. Check status != 'used' (prevent replay)                       │    │
│   │   4. Decrypt and verify timestamp within 24 hours                  │    │
│   │   5. Mark status as 'used', record used_at timestamp               │    │
│   └──────────────────────────────────────────────────────────────────┘    │
│        │                                                                   │
│        ▼                                                                   │
│   Background thread:                                                       │
│   └── Load organizer_credentials.json                                      │
│       └── Send thank_you.html to attendee via Gmail API                   │
│                                                                            │
╚══════════════════════════════════════════════════════════════════════════╝

                                   │
                                   ▼

╔══════════════════════════════════════════════════════════════════════════╗
║ 7. STATUS TRACKING                                                         ║
╠══════════════════════════════════════════════════════════════════════════╣
│                                                                             │
│   Organizer dashboard shows real-time stats:                               │
│   ├── Total attendees uploaded                                             │
│   ├── Tickets generated (coupons created)                                  │
│   ├── Tickets sent (emails delivered)                                      │
│   └── Tickets used (attendees verified)                                    │
│                                                                            │
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## 15. Environment Setup

### 15.1 Prerequisites

```bash
# Clone repository
git clone <repository-url>
cd event-coupon-system

# Install dependencies
pip install -r requirements.txt
```

### 15.2 Google Cloud Console Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create new project or select existing
3. Enable **Gmail API**:
   - Navigate to **APIs & Services → Library**
   - Search for 'Gmail API'
   - Click **Enable**
4. Configure OAuth consent screen:
   - **APIs & Services → OAuth consent screen**
   - User Type: External
   - Fill app name, email
   - Scopes: email, profile, gmail.send
   - Add test users for development
5. Create OAuth 2.0 credentials:
   - **APIs & Services → Credentials**
   - Click **Create Credentials → OAuth client ID**
   - Application type: Web application
   - Name: Event Coupon System
   - Add authorized redirect URIs (see Ngrok section)
6. Copy **Client ID** and **Client Secret** to .env

### 15.3 Quick Start Commands

**For mobile testing (recommended):**
```bash
# Terminal 1: Start ngrok tunnel
./start_with_ngrok.sh

# Terminal 2: Start Flask app
python app.py

# Access from any device using shown URL
```

**For local development only:**
```bash
# Set redirect URI to localhost
export GOOGLE_REDIRECT_URI=http://localhost:5000/auth/callback

# Start Flask
python app.py

# Open browser to http://localhost:5000
```

### 15.4 Required Environment Variables

Create a `.env` file (see `.env.example`):

```bash
SECRET_KEY=your-super-secret-key-at-least-32-chars
FLASK_DEBUG=True
PORT=5000

# Google OAuth (from Google Cloud Console)
GOOGLE_CLIENT_ID=123456789.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCDPXxxxxxxxxxxxxxxxxxxxxx
GOOGLE_REDIRECT_URI=https://abc123def456.ngrok.io/auth/callback

# Encryption (generate with: python -c import secrets; print(secrets.token_hex(32)))
COUPON_SECRET_KEY=your-32-character-secret-key-here
```

---

## 16. Key Files Reference

| File | Lines | Key Classes/Functions | Purpose |
|------|-------|----------------------|---------|
| `app.py` | 755 | Flask app, login_required decorator | Main application with all routes |
| `src/auth.py` | 325 | GoogleAuthService, GmailEmailService, EmailResult | OAuth and email sending |
| `src/coupons.py` | 466 | CouponManager | Coupon generation, QR creation, validation |
| `src/data.py` | 501 | CSVManager, CouponRecord | CSV operations with file locking |
| `src/encryption.py` | 186 | EncryptionService | AES-256 Fernet encryption |
| `templates/event.html` | 202 | Template | Coupon email to attendees |
| `templates/thank_you.html` | ~50 | Template | Post-verification email |
| `templates/scanner.html` | ~1600 | Template, JS | QR scanner with camera access |
| `templates/sender.html` | ~1500 | Template, JS | Organizer dashboard UI |
| `templates/login.html` | ~150 | Template | Login page with OAuth button |
| `start_with_ngrok.sh` | 78 | Bash script | Ngrok tunnel startup |
| `setup_ngrok.py` | ~150 | Python script | Ngrok installation helper |

---

## 17. Improvement Suggestions

### 17.1 Architecture & Infrastructure

**Database Migration:**
- Current CSV storage has limitations:
  - No concurrent write safety on Windows
  - No query capabilities
  - No relationship between data
- **Suggestion:** Migrate to SQLite (simple, file-based, no server needed) or PostgreSQL (production)
- Benefits: ACID compliance, better performance, proper indexing

**Real-time Synchronization:**
- Currently, different scanner devices don't see each other's verifications in real-time
- **Suggestion:** Add WebSocket support or polling for live updates
- Could use Flask-SocketIO or simple polling endpoint

**Email Queue System:**
- Emails sent synchronously in batch can timeout
- **Suggestion:** Implement message queue (Celery + Redis) for email sending
- Benefits: Better reliability, retry logic, rate limiting

### 17.2 Security Enhancements

**Current weaknesses:**
1. Session tokens stored server-side in memory (lost on restart)
2. No rate limiting on verification endpoint (brute force risk)
3. Organizer credentials stored in plaintext JSON file
4. No audit logging of who verified which coupon

**Suggestions:**
```python
# Rate limiting for verification
from flask_limiter import Limiter
limiter = Limiter(app, key_func=get_remote_address)

@app.route('/verify-coupon', methods=['POST'])
@limiter.limit('10 per minute')  # Max 10 verifications per minute per IP
def verify_coupon():
    ...

# Encrypt organizer credentials file
# Use python-dotenv with encryption or hashi-vault

# Add audit log
import audit
audit.log_verification(coupon_id, scanner_device, timestamp)
```

### 17.3 QR Code Improvements

**Current:** QR contains `{v: code, e: email}` - simple but limited

**Suggestions:**
1. **Include event ID in QR** to support multiple events
2. **Add HMAC signature** to QR data to prevent forgery
3. **Include timestamp** in QR to validate freshness
4. **QR code error correction:** Increase from L to M or H for damaged codes

```python
# Improved QR data structure
qr_data = {
    'c': coupon_id,           # coupon ID (shorter key)
    'e': email_hash[:8],      # partial email hash (privacy)
    't': int(time.time()),    # timestamp for freshness
    's': hmac.new(secret, json.dumps({...}), sha256).hexdigest()[:8]  # signature
}
```

### 17.4 Mobile Scanner Improvements

**Current issues in scanner.html:**
- ~1600 lines of JavaScript - hard to maintain
- Multiple camera access methods (complex)
- No offline capability

**Suggestions:**
1. **PWA (Progressive Web App):** Cache scanner for offline use
2. **Service Worker:** Background sync when back online
3. **Web Workers:** Move QR detection to background thread
4. **Refactor JS:** Break into modules (camera.js, scanner.js, api.js)

### 17.5 Email System Improvements

**Current:** Uses organizer's personal Gmail (rate limited, requires OAuth refresh)

**Suggestions:**
1. **Use SendGrid/AWS SES:** Dedicated email service, higher limits
2. **Email templates:** Store in database, allow editing
3. **Send status tracking:** Webhook for delivery confirmation
4. **Preview emails:** Preview before sending campaign

```python
# Example: Use bulk email service
from sendgrid import SendGridAPIClient
sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))

message = Mail(
    from_email='events@organizer.com',
    to_emails=recipient,
    subject=f'Your Digital Coupon for {event_name}',
    html_content=rendered_template
)
response = sg.send(message)
```

### 17.6 User Experience

**Dashboard improvements:**
1. **Real-time updates:** Use Server-Sent Events (SSE) for live stats
2. **Progress indicator:** Show email sending progress with estimated time
3. **CSV preview:** Show first few rows before confirming upload
4. **Search/filter attendees:** Large lists need filtering

**Scanner improvements:**
1. **Sound effects:** Audio feedback on successful/failed scan
2. **Haptic feedback:** Vibration on mobile for scan result
3. **Batch verification mode:** Scan multiple tickets quickly
4. **Statistics view:** Show total scanned, remaining

### 17.7 Testing & Reliability

**Current state:** Empty test files, no CI/CD

**Suggestions:**
```python
# tests/test_coupons.py
def test_coupon_generation():
    manager = CouponManager(csv_manager=mock_csv)
    result = manager.generate_coupon('test@example.com', 'Test Event')
    assert result['success'] == True
    assert len(result['verification_code']) == 6

def test_email_validation():
    csv = CSVManager()
    assert csv.validate_email_format('test@example.com') == True
    assert csv.validate_email_format('invalid-email') == False
```

**Add to CI/CD pipeline:**
- GitHub Actions for automated testing
- Lint (ruff/black) and type checking (mypy)
- Deploy to staging server on PR

### 17.8 Scalability

**Current limits:**
- Single Flask process
- CSV files on local disk
- Gmail API rate limits (500/day personal, 2000/day enterprise)

**For higher scale:**
1. **Containerize:** Docker + Kubernetes
2. **Database:** PostgreSQL with connection pooling
3. **Caching:** Redis for session and rate limiting
4. **Email service:** SendGrid, Mailgun, or AWS SES
5. **Background jobs:** Celery + Redis for email sending

---

## Appendix: Troubleshooting

### OAuth Redirect URI Mismatch
**Error:** `redirect_uri_mismatch`
**Fix:** Ensure Google Cloud Console redirect URI matches exactly (including https:// and trailing slashes)

### Camera Not Working on Mobile
**Fix:**
1. Ensure HTTPS (ngrok URL, not localhost)
2. Allow camera permission in browser
3. Try 'Simple Camera Access' button
4. Use manual 6-digit code entry as fallback

### Gmail API Rate Limit
**Error:** `User rate limit exceeded`
**Fix:** Wait 24 hours or use service account for bulk sending

### Ngrok URL Expired
**Problem:** Each ngrok restart = new URL
**Fix:** Script automatically updates .env, but must also update Google Cloud Console

---

*Document generated: 2026-04-24*
*Last updated: 2026-04-24*