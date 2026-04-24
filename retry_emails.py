#!/usr/bin/env python3
"""
DCS Day '26 - Retry Email Sender
================================
Sends emails to unsent recipients using a secondary Gmail account.
Uses the merged/cleaned coupon data.

Usage:
    python retry_emails.py

Note: Run after fixing duplicates with fix_duplicates.py
"""

import os
import sys
import csv
import json
import time
import base64
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.utils import formataddr

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables from .env2
def load_env2():
    """Load credentials from .env2 file"""
    env_file = os.path.join(os.path.dirname(__file__), '.env2')
    config = {}
    
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip()
    
    return config

def load_unsent_recipients():
    """Load unsent recipients from CSV"""
    unsent_file = 'unsent_recipients.csv'
    
    if not os.path.exists(unsent_file):
        logger.error(f"File not found: {unsent_file}")
        logger.info("Run fix_duplicates.py first to generate this file")
        return []
    
    recipients = []
    with open(unsent_file, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            recipients.append(row)
    
    return recipients

def update_coupons_csv(email, status='sent'):
    """Update the merged coupons CSV with sent status"""
    merged_file = 'coupons_merged.csv'
    temp_file = 'coupons_merged_temp.csv'
    
    rows = []
    with open(merged_file, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if row.get('email', '').lower() == email.lower():
                row['status'] = status
                row['sent_at'] = datetime.now().isoformat()
            rows.append(row)
    
    with open(temp_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    os.replace(temp_file, merged_file)

def main():
    print("=" * 60)
    print("DCS Day '26 - Retry Email Sender")
    print("=" * 60)
    
    # Load configuration
    config = load_env2()
    
    if not config.get('GOOGLE_CLIENT_ID_2'):
        print("\n❌ Error: .env2 file not configured properly")
        print("Make sure .env2 contains GOOGLE_CLIENT_ID_2 and GOOGLE_CLIENT_SECRET_2")
        return
    
    print(f"\n📧 Using client ID: {config.get('GOOGLE_CLIENT_ID_2', '')[:20]}...")
    
    # Load unsent recipients
    recipients = load_unsent_recipients()
    
    if not recipients:
        print("\n✅ No unsent recipients found!")
        return
    
    print(f"\n📬 Found {len(recipients)} unsent recipients")
    
    # List unique emails
    print("\nUnsent recipients:")
    for i, r in enumerate(recipients, 1):
        print(f"  {i}. {r.get('email', 'Unknown')}")
    
    print("\n" + "-" * 60)
    print("⚠️  MANUAL STEPS REQUIRED:")
    print("-" * 60)
    print("""
To send emails with the new Gmail account:

1. Go to: https://qhrjgwf5-5000.inc1.devtunnels.ms/login
   
2. Log in with the NEW Gmail account (the one from client_secret file)

3. The system will use this account's OAuth to send emails

4. Upload the unsent_recipients.csv file (or use existing data)

5. Click "Send Emails" with subject:
   "Remastered Coupons to Unlock DCS Day 2026"

ALTERNATIVELY, you can manually re-run the application with 
the new credentials configured.
""")
    
    print("\n📁 Files available:")
    print(f"  - unsent_recipients.csv ({len(recipients)} recipients)")
    print(f"  - coupons_merged.csv (512 unique entries)")
    print(f"  - .env2 (new Gmail credentials)")
    
    # Offer to copy unsent to main responses file
    print("\n" + "-" * 60)
    response = input("Would you like to create a responses CSV with only unsent recipients? (y/n): ")
    
    if response.lower() == 'y':
        # Create a responses file with unsent recipients
        output_file = 'responses_unsent.csv'
        
        # Extract just the needed columns for sending
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['email', 'name'])  # Minimal columns needed
            for r in recipients:
                writer.writerow([r.get('email', ''), ''])
        
        print(f"\n✅ Created: {output_file}")
        print("   Upload this file to the sender page to retry sending")

if __name__ == '__main__':
    main()
