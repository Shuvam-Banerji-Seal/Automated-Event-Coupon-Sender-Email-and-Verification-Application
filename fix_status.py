#!/usr/bin/env python3
"""
Fix data integrity issues in coupons.csv:
1. If used_at exists, status should be 'used' (regardless of sent_at)
2. If no used_at but sent_at exists, status should be 'sent'
3. If no used_at and no sent_at, status should be 'generated'

Also regenerate unsent_recipients.csv with ONLY truly unsent entries.
"""
import csv
import shutil
from datetime import datetime

# Create backup
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
backup_name = f'coupons_before_status_fix_{timestamp}.csv'
shutil.copy('coupons.csv', backup_name)
print(f"Created backup: {backup_name}")

# Read all data
with open('coupons.csv', 'r') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    rows = list(reader)

print(f"Total entries: {len(rows)}")

# Track fixes
fixes = {
    'used_at_to_used': 0,
    'sent_at_to_sent': 0,
    'to_generated': 0
}

# Fix status based on priority: used_at > sent_at > nothing
for row in rows:
    used_at = row.get('used_at', '').strip()
    sent_at = row.get('sent_at', '').strip()
    old_status = row.get('status', '')
    
    if used_at:
        # Has used_at -> status should be 'used'
        if old_status != 'used':
            row['status'] = 'used'
            fixes['used_at_to_used'] += 1
    elif sent_at:
        # Has sent_at but no used_at -> status should be 'sent'
        if old_status != 'sent':
            row['status'] = 'sent'
            fixes['sent_at_to_sent'] += 1
    else:
        # No used_at, no sent_at -> status should be 'generated'
        if old_status != 'generated':
            row['status'] = 'generated'
            fixes['to_generated'] += 1

print(f"\nFixes applied:")
print(f"  - Changed to 'used' (had used_at): {fixes['used_at_to_used']}")
print(f"  - Changed to 'sent' (had sent_at): {fixes['sent_at_to_sent']}")
print(f"  - Changed to 'generated' (nothing): {fixes['to_generated']}")

# Write fixed data
with open('coupons.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"\n✅ Fixed coupons.csv saved")

# Verify new status counts
status_count = {}
for row in rows:
    s = row.get('status', 'unknown')
    status_count[s] = status_count.get(s, 0) + 1

print(f"\nNew status breakdown:")
for s, c in sorted(status_count.items()):
    print(f"  {s}: {c}")

# Generate correct unsent_recipients.csv (ONLY status=generated, i.e., never sent)
unsent = [r for r in rows if r.get('status') == 'generated']
with open('unsent_recipients.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(unsent)

print(f"\n✅ Generated unsent_recipients.csv with {len(unsent)} truly unsent entries")

# List unsent emails
print(f"\n=== TRULY UNSENT EMAILS ===")
for i, r in enumerate(unsent):
    print(f"  {i+1}. {r.get('email')}")
