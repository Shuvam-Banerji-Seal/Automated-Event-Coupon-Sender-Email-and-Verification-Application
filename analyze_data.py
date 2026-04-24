#!/usr/bin/env python3
"""Analyze coupons.csv for data integrity issues"""
import csv

# Analyze coupons.csv
with open('coupons.csv', 'r') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

print(f"Total entries: {len(rows)}")

# Count by status
status_count = {}
for row in rows:
    s = row.get('status', 'unknown')
    status_count[s] = status_count.get(s, 0) + 1

print(f"\nStatus breakdown:")
for s, c in status_count.items():
    print(f"  '{s}': {c}")

# Find inconsistencies: used_at exists but status is NOT 'used'
inconsistent = []
for row in rows:
    used_at = row.get('used_at', '')
    status = row.get('status', '')
    if used_at and status != 'used':
        inconsistent.append({
            'email': row.get('email'),
            'used_at': used_at,
            'status': status,
            'sent_at': row.get('sent_at', '')
        })

print(f"\n=== INCONSISTENCIES: used_at exists but status != 'used' ===")
print(f"Count: {len(inconsistent)}")
for i, r in enumerate(inconsistent[:15]):
    print(f"  {i+1}. {r['email']}: status='{r['status']}', has_sent_at={bool(r['sent_at'])}")

# Find truly unsent: status=generated AND no used_at
truly_unsent = [r for r in rows if r.get('status') == 'generated' and not r.get('used_at')]
print(f"\n=== TRULY UNSENT (status=generated, no used_at) ===")
print(f"Count: {len(truly_unsent)}")
for i, r in enumerate(truly_unsent[:15]):
    print(f"  {i+1}. {r.get('email')}")

# Count registered users
registered = [r for r in rows if r.get('used_at')]
print(f"\n=== REGISTERED (has used_at) ===")
print(f"Count: {len(registered)}")

# Find entries that REGISTERED but have status other than 'used' 
registered_wrong_status = [r for r in rows if r.get('used_at') and r.get('status') != 'used']
print(f"\n=== REGISTERED BUT WRONG STATUS ===")
print(f"Count: {len(registered_wrong_status)}")
if registered_wrong_status:
    print("These need to be fixed!")
    for i, r in enumerate(registered_wrong_status[:20]):
        print(f"  {i+1}. {r.get('email')}: status='{r.get('status')}'")
