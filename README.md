# Automated Coupon System

This is a web-based application designed to automate the process of generating, distributing, and verifying event coupons. The system allows an event organizer to upload a list of attendees, send them unique QR code coupons via email, and then verify those coupons in real-time at the event using a web-based scanner.

The application is built with Flask and uses Google OAuth for secure authentication, allowing the organizer to send emails directly from their own Gmail account.

## Features

- **Secure User Authentication**: Users log in securely with their Google account using OAuth 2.0.
- **Bulk Email Distribution**: Upload a CSV file of recipient emails and send customized coupon emails to everyone in a single batch.
- **Unique QR Code Generation**: For each recipient, a unique, encrypted QR code is generated.
- **Real-time Coupon Verification**: A web-based scanner interface allows staff to verify coupons instantly using a smartphone or any device with a camera.
- **Status Tracking**: The system tracks the status of each coupon (generated, sent, used).
- **Thank You Emails**: Automatically sends a "Thank You" email to an attendee upon successful verification.
- **Error Logging**: Automatically logs any emails that fail to send for later review.
- **Easy Deployment with Ngrok**: Includes helper scripts to easily expose the local server to the internet for testing and live use.

## How It Works

1.  **Login**: The event organizer logs into the system using their Google account.
2.  **Upload Recipients**: The organizer uploads a CSV file containing the email addresses of all event attendees.
3.  **Send Coupons**: The organizer initiates the email campaign. The system generates a unique coupon and QR code for each recipient and sends it to them using the organizer's authenticated Gmail account.
4.  **Event Day Verification**: At the event, staff can access the `/scanner` URL from their mobile devices.
5.  **Scan & Verify**: When an attendee presents their QR code, the staff member scans it. The system validates the coupon in real-time and marks it as "used" to prevent re-use.
6.  **Post-Verification**: Upon successful verification, the system automatically sends a thank-you email to the attendee.

## Getting Started

### Prerequisites

- Python 3.8+
- `pip` for installing dependencies
- `ngrok` for exposing the local server (for Google OAuth and mobile testing)

### Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd automated_coupon_system
    ```

2.  **Create a virtual environment and activate it:**
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  **Install the required dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

### Configuration

1.  **Set up Google OAuth Credentials:**
    - Go to the [Google Cloud Console](https://console.cloud.google.com/).
    - Create a new project.
    - Navigate to "APIs & Services" > "Credentials".
    - Create an "OAuth client ID" for a "Web application".
    - Add `http://localhost:5000` to the "Authorized JavaScript origins".
    - Add `http://localhost:5000/auth/callback` to the "Authorized redirect URIs". You will update this later with your `ngrok` URL.
    - Download the client secret JSON file.

2.  **Create the `.env` file:**
    Create a file named `.env` in the root of the project. This file will hold all your secret keys and environment-specific settings.

    Below is the structure of the `.env` file. Fill in the values based on your setup.

    ```env
    # Flask Settings
    # ----------------
    # Set to True for development to enable debug mode, or False for production.
    FLASK_DEBUG=True
    # A long, random string used to secure sessions.
    SECRET_KEY=a-very-secret-key-that-you-should-change

    # Google OAuth Credentials
    # ------------------------
    # Get these from the Google Cloud Console after creating your OAuth client ID.
    GOOGLE_CLIENT_ID="YOUR_GOOGLE_CLIENT_ID.apps.googleusercontent.com"
    GOOGLE_CLIENT_SECRET="YOUR_GOOGLE_CLIENT_SECRET"
    # The initial redirect URI. The start_with_ngrok.sh script will update this automatically.
    GOOGLE_REDIRECT_URI="http://localhost:5000/auth/callback"

    # Encryption Key for Coupons
    # --------------------------
    # A 32-byte (64 hex characters) key for encrypting coupon data.
    # Generate a secure key and keep it safe.
    ENCRYPTION_KEY=your-32-byte-encryption-key-keep-safe
    ```

    **How to Generate Secure Keys:**

    -   **`SECRET_KEY`**: You can generate a suitable key in your terminal with:
        ```bash
        python -c 'import secrets; print(secrets.token_hex(24))'
        ```
    -   **`ENCRYPTION_KEY`**: This key **must** be 32 bytes long. Generate it with:
        ```bash
        python -c 'import secrets; print(secrets.token_hex(32))'
        ```


### Running the Application

1.  **Start `ngrok`:**
    To allow Google to redirect back to your local machine and to test on mobile, you need a public URL. This project is set up to work with `ngrok`.

    The included script simplifies this process. Run:
    ```bash
    ./start_with_ngrok.sh
    ```
    This will start an `ngrok` tunnel and display a public HTTPS URL (e.g., `https://<random-string>.ngrok.io`).

2.  **Update Google Cloud Console:**
    - Go back to your Google Cloud project credentials.
    - Add the `ngrok` URL to your "Authorized redirect URIs". It should look like this: `https://<random-string>.ngrok.io/auth/callback`.

3.  **Start the Flask Application:**
    In a new terminal (while `ngrok` is still running), make sure your virtual environment is activated and run:
    ```bash
    python app.py
    ```

4.  **Access the Application:**
    Open your browser and navigate to the `ngrok` URL provided. You can now log in and start using the application.

## Project Structure

```
/
├── app.py # Main Flask application
├── coupon_manager.py # Handles coupon generation and validation
├── csv_manager.py # Manages data storage in CSV files
├── google_auth_service.py # Handles Google OAuth and Gmail API
├── encryption_service.py # Encrypts and decrypts coupon data
├── requirements.txt # Python dependencies
├── start_with_ngrok.sh # Script to start ngrok tunnel
├── templates/
│ ├── login.html
│ ├── sender.html # Main dashboard for sending coupons
│ └── scanner.html # QR code scanner interface
└── static/ # CSS and JavaScript files
```

---

## 21MS Farewell Party Branch (`21ms_farewell`)

This specialized branch is designed for the **21MS Farewell Party** at IISER Kolkata, organized by the **22MS Batch**. It replaces the Gmail API-based email sending with direct SMTP, features beautifully designed handwriting-style invitation emails, and includes comprehensive dashboard analytics.

### Key Differences from Main Branch

| Feature | Main Branch | 21ms_farewell Branch |
|---------|------------|---------------------|
| **Email Backend** | Gmail API (OAuth required) | SMTP (direct `.env` credentials) |
| **OAuth Requirement** | Required for sending | Optional (for login only) |
| **Email Templates** | Standard design | Handwriting-style (Caveat, Satisfy, Kalam fonts) |
| **Decorations** | Basic | SVG ornamental elements, Unicode characters |
| **Attachments** | Not supported | PDF attachment support |
| **Thank You Emails** | Gmail API async | SMTP async (no OAuth needed) |
| **Dashboard** | Basic stats | Detailed coupon table with codes & timestamps |

### 21ms_farewell Features

- **SMTP-Based Email Sending**: No Google OAuth required for sending invitations. Uses Gmail SMTP with App Passwords.
- **Beautiful Invitation Design**: Handwriting-font-styled emails with SVG decorative elements (stars, ornamental borders, corner flourishes) and Unicode characters. No emojis.
- **PDF Attachment Support**: Attach event schedules, brochures, or other PDFs to invitation emails.
- **Detailed Dashboard**: View all coupons with email addresses, verification codes, coupon IDs, statuses, sent timestamps, and used timestamps.
- **Automatic Thank You Emails**: Sends a warm thank-you email via SMTP when a QR code is scanned and verified at the event entrance.
- **CSV Integration**: Upload attendee lists via CSV, track status updates in real-time.
- **3 Test Email Support**: Built-in test script for verifying SMTP delivery to multiple test addresses.

### 21ms_farewell Setup

#### Step 1: Install dependencies

This branch uses `uv` with a global Python environment. Install all dependencies:

```bash
uv pip install --python /home/shuvam/.global-pymaster -r requirements_21ms.txt
```

#### Step 2: Set up Gmail SMTP (App Password)

**IMPORTANT:** You cannot use your regular Gmail password. You must create an **App Password**.

1. **Enable 2-Step Verification on your Google Account:**
   - Go to https://myaccount.google.com/security
   - Under "Signing in to Google", click **2-Step Verification**
   - Follow the prompts to enable it (requires a phone number)

2. **Generate an App Password:**
   - Go to https://myaccount.google.com/security
   - Under "Signing in to Google", click **App passwords**
   - You may need to sign in again
   - At the bottom, click **Select app** > choose **Mail**
   - Click **Select device** > choose **Other (Custom name)**
   - Type: `21MS Farewell Mailer`
   - Click **Generate**
   - Google will show a 16-character password like `abcd efgh ijkl mnop`
   - **Copy this password immediately** — you cannot view it again

3. **Troubleshooting SMTP:**
   - If you get "Username and Password not accepted", you are using your regular password instead of the App Password
   - If 2-Step Verification is disabled, App Passwords option will not appear
   - If you recently changed your Google password, old App Passwords may stop working — generate a new one

#### Step 3: Configure the `.env` file

```bash
cp .env.example .env
# Now edit .env with your details
```

**Fill in these required values in `.env`:**

```env
# Flask Configuration
SECRET_KEY=your-super-secret-key-minimum-32-characters-long
FLASK_DEBUG=True
PORT=5000

# Coupon Encryption Key — generate with:
# /home/shuvam/.global-pymaster/bin/python -c "import secrets; print(secrets.token_hex(32))"
COUPON_SECRET_KEY=PASTE_YOUR_GENERATED_KEY_HERE

# SMTP Configuration — use your Gmail and the 16-char App Password
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=True
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=xxxx xxxx xxxx xxxx    # <-- 16-char App Password (spaces optional)
SMTP_SENDER_NAME=22MS Batch, IISER Kolkata
SMTP_SENDER_EMAIL=your-email@gmail.com

# Event Details
EVENT_NAME=21MS Farewell Party
EVENT_DATE=To Be Announced
EVENT_VENUE=IISER Kolkata Campus
EVENT_TIME=To Be Announced

# Test Email Addresses (for testing before bulk send)
TEST_EMAIL_1=first-test-email@example.com
TEST_EMAIL_2=second-test-email@example.com
TEST_EMAIL_3=third-test-email@example.com

# Google OAuth (optional — only if you want organizer login)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:5000/auth/callback
```

**NEVER commit the `.env` file.** It is already in `.gitignore`.

#### Step 4: Test SMTP before sending

Run the test script to verify your SMTP credentials work and that emails actually deliver:

```bash
/home/shuvam/.global-pymaster/bin/python scripts/send_test_emails.py
```

Expected output if successful:
```
=================================================================
21MS Farewell Party - SMTP Test & Invitation Sender
=================================================================
[+] Test attachment found: test_schedule.pdf

[1] Testing SMTP connection...
[+] SMTP connection successful: Connected to smtp.gmail.com:587

[1] Preparing invitation for first-test-email@example.com...
    [+] Coupon generated: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    [+] Verification code: 123456
    [+] SENT SUCCESSFULLY to first-test-email@example.com
    [+] Attachment included: test_schedule.pdf
...
```

**Check the inboxes of your test emails.** If emails land in spam:
- Add the sender email to contacts
- The subject line "You're Invited! 21MS Farewell Party" should not trigger spam filters

#### Step 5: Start the server

```bash
/home/shuvam/.global-pymaster/bin/python app.py
```

The server will start on `http://localhost:5000`

#### Step 6: Use the web dashboard

1. **Open the Event Manager:** `http://localhost:5000/sender`
2. **Upload your attendee CSV:** Click "Upload Attendee List" and select a CSV file with at minimum an `email` column. Optional: add a `name` column.
3. **Send invitations:** Enter the event name, optionally attach a PDF schedule, then click "Send Farewell Invitations"
4. **Track progress:** The dashboard shows a detailed table with all coupons, verification codes, sent timestamps, and used timestamps

**CSV format example:**
```csv
email,name
21ms001@iiserkol.ac.in,Rahul Sharma
21ms002@iiserkol.ac.in,Priya Das
```

#### Step 7: Event day — QR scanning

1. Open `http://localhost:5000/scanner` on a mobile device or laptop with camera
2. Scan attendee QR codes at the entrance
3. The system validates the coupon, marks it as "used", and automatically sends a thank-you email
4. If camera doesn't work, use the manual "6-Digit Code Verification" section at the bottom of the scanner page

#### Step 8: Stop the server

Press `Ctrl+C` in the terminal running the Flask app.

### API Endpoints (21ms_farewell)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/send-farewell-emails` | POST | None | Send invitations via SMTP |
| `/farewell-stats` | GET | None | Get event statistics |
| `/farewell-recipients` | GET | None | Get detailed recipient list |
| `/farewell-coupons` | GET | None | Get all coupon details |
| `/verify-coupon` | POST | None | Verify QR/code & send thank-you email |
| `/scanner` | GET | None | QR scanner interface |

### Email Template Design

The invitation email uses a nostalgic, warm aesthetic:
- **Fonts**: Caveat (headings), Satisfy (hero text), Kalam (body copy)
- **Colors**: Midnight navy (#1a1a2e), gold/amber (#d4af37), warm cream (#fef9f0)
- **Decorations**: SVG stars, ornamental lines, corner flourishes, scissors icon for ticket section
- **QR Code**: Centered in a decorative frame with verification code prominently displayed
- **No emojis**: All decorations use SVG or Unicode characters for maximum email client compatibility

### File Structure (21ms_farewell additions)

```
├── src/smtp_mailer.py              # SMTP email service
├── templates/farewell/
│   ├── invitation.html             # Handwriting-style invitation
│   └── thank_you.html              # Post-verification thank you
├── scripts/send_test_emails.py     # Test email sender (3 addresses + attachment)
├── tests/test_smtp_connection.py   # SMTP unit tests
├── tests/test_invitation_render.py # Template rendering tests
├── requirements_21ms.txt           # Branch dependencies
└── FAREWELL_BRANCH_DOCUMENTATION.md # Detailed branch docs
```
