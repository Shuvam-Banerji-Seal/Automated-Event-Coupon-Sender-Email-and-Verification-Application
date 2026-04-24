# Quick Reference Guide - DCS Day '26 Updated Features

## 🎫 For Event Organizers

### Sending Invitations with Personalization

1. **Prepare your CSV file** with attendee emails and names:
   ```
   email,name
   john@example.com,John Smith
   jane@example.com,Jane Doe
   ```
   
   Column name can be: `name`, `attendee_name`, `attendee`, or `full_name`

2. **Upload to Scanner/Sender** and send invitations
   - Invitation emails will automatically include:
     - ✨ Personalized greeting: "Dear John Smith, You are Cordially Invited..."
     - 🎯 Complete 13-item event schedule with all times
     - 📱 QR code with 6-digit verification code
     - 🏢 Professional logo and branding

3. **Verify emails sent successfully**
   - Check thank you email configuration (already clean, no encrypted data shown)
   - Attendee names will appear in personalized thank you messages

---

## 📱 For Ticket Scanners (Event Day)

### Two Ways to Verify Tickets

#### **Method 1: Code Only (FASTEST)** ⚡
```
1. Look at ticket's 6-digit code (bottom right of QR section)
2. Open Scanner app
3. Enter 6-digit code in "Quick Code Entry" field
4. Click "Verify Ticket"
✅ Done! No email needed
```

#### **Method 2: Code + Email (EXTRA SECURE)**
```
1. Look at ticket's 6-digit code
2. Open Scanner app
3. Enter 6-digit code in "Quick Code Entry"
4. Optionally enter attendee email for extra verification
5. Click "Verify Ticket"
✅ Done! Code validated against email if provided
```

---

## 📧 Email Preview

### Invitation Email
**Subject:** Your Digital Coupon for DCS Day '26

```
┌─────────────────────────────────────────┐
│  [IISER Logo]  [DCS Logo]              │
│                                         │
│  DCS DAY '26  ✨                        │
│  January 28, 2026                      │
│                                         │
│  Dear John Smith,                      │
│  You are Cordially Invited...          │
│                                         │
│  ┌─ PROGRAMME SCHEDULE ─────────────┐  │
│  │ 08:30 AM - Registration          │  │
│  │ 09:15 AM - Inaugural Session     │  │
│  │ 09:30 AM - CRISPR-Cas9 (10 min)  │  │
│  │ 10:30 AM - Catalytic Alchemy     │  │
│  │ 10:50 AM - Tea Break             │  │
│  │ 11:10 AM - Single-Atom Catalysis │  │
│  │ ... (13 items total)             │  │
│  │ 06:00 PM - Cultural & Dinner     │  │
│  └──────────────────────────────────┘  │
│                                         │
│  [QR Code with 6-digit code]           │
│                                         │
└─────────────────────────────────────────┘
```

### Thank You Email
```
┌─────────────────────────────────────────┐
│  🎉 Thank You for Attending!            │
│                                         │
│  Dear John Smith,                       │
│  Thank you for attending DCS Day '26!   │
│                                         │
│  📋 Event Details                       │
│  ├─ Event: DCS Day '26                  │
│  ├─ Attendee: john@example.com          │
│  ├─ Date: 2026-01-28                    │
│  └─ Ticket ID: COUPON-XXX               │
│                                         │
│  ✅ NO encrypted data shown             │
│  ✨ Clean, professional design          │
│                                         │
└─────────────────────────────────────────┘
```

---

## ⚙️ Technical Details

### Security Model

**Code-Only Verification:**
- ✅ Fast (no email lookup)
- ✅ Mobile-friendly (no typing)
- ✅ Secure (6-digit code is unique)
- ⚠️ Can't verify attendee identity

**Email-Enhanced Verification:**
- ✅ Verifies both code AND email match
- ✅ Extra security layer
- ⚠️ Requires typing on mobile
- ✅ Best for high-security events

### QR Code Format

**New Compact Format:**
```json
{
  "v": "123456",
  "e": "john@example.com"
}
```
- `v` = 6-digit verification code
- `e` = attendee email

---

## 🔄 Data Flow

### Sending Invitations
```
CSV Upload
    ↓
Extract Names & Emails
    ↓
Generate Coupons (6-digit codes + encryption)
    ↓
Create QR codes with code + email
    ↓
Render invitation.html with:
  - attendee_name (personalization)
  - qr_code_base64 (scannable)
  - verification_code (manual entry)
  - complete_schedule (13 events)
    ↓
Send via Gmail API with organizer credentials
```

### Verifying Tickets (Day-of)
```
Scanner reads QR
    ↓
Extract 6-digit code (and optionally email)
    ↓
POST /verify-coupon
    ↓
Backend:
  - Find coupon by code (and email if provided)
  - Check if not already used
  - Mark as used
  - Extract attendee name
    ↓
Send thank_you.html email with:
  - attendee_name (personalized)
  - event details
  - clean, professional design
```

---

## 🆘 Troubleshooting

### Email Shows Generic Greeting
- **Issue:** "Dear Attendee" instead of "Dear John"
- **Solution:** Ensure CSV has column named: name, attendee_name, attendee, or full_name

### Code Verification Fails
- **Issue:** "Invalid verification code"
- **Solution:**
  1. Check code is exactly 6 digits
  2. Code is not already used
  3. Try with optional email for extra validation

### Email Not Sending
- **Issue:** Invitations or thank you emails not received
- **Solution:**
  1. Check Gmail API credentials in app
  2. Verify organizer has Gmail API enabled
  3. Check spam folder

### Schedule Shows Wrong Times
- **Issue:** Different times than expected
- **Solution:** Schedule is hardcoded in invitation.html. Update if timings change.

---

## 📊 Statistics During Event

### Scanner Dashboard Shows:
- **Verified Count:** ✅ Successful scans (tickets marked as used)
- **Failed Count:** ❌ Invalid codes or already used tickets
- **Total Scans:** 🔢 Total verification attempts
- **Last Scan:** Email of most recent verification

---

## 💡 Pro Tips

1. **Print ticket stubs for attendees:**
   - Include 6-digit code prominently on bottom
   - Make QR code scannable from 1-2 feet away

2. **Scanner setup:**
   - Test camera before event starts
   - Position camera to scan codes from waist height
   - Good lighting = faster scanning

3. **Backup method:**
   - Keep printed list of attendee emails
   - If QR codes don't scan, manually enter code + email

4. **Post-event:**
   - Check scan statistics dashboard
   - Download attendance records
   - No-show list (unverified attendees)

---

## 🚀 One-Day Deployment Checklist

- [ ] CSV ready with emails and names (any name column works)
- [ ] Send test invitation to yourself
- [ ] Verify personalized name appears
- [ ] Verify complete schedule displays
- [ ] Test code-only verification
- [ ] Test with email verification
- [ ] Check thank you email format
- [ ] Print ticket stubs with 6-digit codes
- [ ] Set up scanner on mobile device
- [ ] Test camera and QR scanning
- [ ] Monitor statistics during event

---

**Last Updated:** January 27, 2026  
**For Event:** DCS Day '26 - January 28, 2026  
**Location:** R N Tagore Auditorium, IISER Kolkata
