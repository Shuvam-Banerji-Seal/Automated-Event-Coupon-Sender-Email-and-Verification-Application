#!/usr/bin/env python3
"""
DCS Day '26 - Duplicate Detection and Smart Merge Script
=========================================================
This script:
1. Detects duplicate emails in coupons.csv
2. Merges duplicates smartly (preserving sent/used status over generated)
3. Creates a clean merged CSV
4. Identifies unsent unique recipients for retry
"""

import csv
import os
from datetime import datetime
from collections import defaultdict

COUPONS_FILE = 'coupons.csv'
BACKUP_FILE = f'coupons_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
MERGED_FILE = 'coupons_merged.csv'
UNSENT_FILE = 'unsent_recipients.csv'

def load_coupons():
    """Load all coupons from CSV"""
    coupons = []
    with open(COUPONS_FILE, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            coupons.append(row)
    return coupons

def analyze_duplicates(coupons):
    """Find and analyze duplicate emails"""
    email_groups = defaultdict(list)
    
    for i, coupon in enumerate(coupons):
        email = coupon.get('email', '').lower().strip()
        if email:
            email_groups[email].append((i, coupon))
    
    duplicates = {email: entries for email, entries in email_groups.items() if len(entries) > 1}
    unique = {email: entries[0] for email, entries in email_groups.items() if len(entries) == 1}
    
    return duplicates, unique

def get_priority(coupon):
    """
    Get priority score for a coupon entry.
    Higher priority = more important to keep.
    
    Priority order:
    1. Has used_at (registration used) - highest
    2. Has lunch_used_at or dinner_used_at
    3. Has sent_at (email was sent)
    4. Status is 'sent'
    5. Status is 'generated' - lowest
    """
    score = 0
    
    # Check if registration was used
    if coupon.get('used_at'):
        score += 1000
    
    # Check if lunch was used
    if coupon.get('lunch_used_at'):
        score += 500
        
    # Check if dinner was used
    if coupon.get('dinner_used_at'):
        score += 500
    
    # Check if email was sent
    if coupon.get('sent_at'):
        score += 100
    
    # Check status
    status = coupon.get('status', '').lower()
    if status == 'sent':
        score += 50
    elif status == 'used':
        score += 200
    elif status == 'generated':
        score += 1
    
    return score

def merge_duplicates(duplicates, unique):
    """
    Merge duplicate entries, keeping the most important one.
    For entries with same priority, prefer the one with more data filled.
    """
    merged = []
    merge_log = []
    
    # Add unique entries
    for email, (idx, coupon) in unique.items():
        merged.append(coupon)
    
    # Process duplicates
    for email, entries in duplicates.items():
        # Sort by priority (highest first)
        sorted_entries = sorted(entries, key=lambda x: get_priority(x[1]), reverse=True)
        
        # Keep the highest priority entry
        best_idx, best_coupon = sorted_entries[0]
        merged.append(best_coupon)
        
        # Log the merge
        priorities = [(get_priority(e[1]), e[1].get('status')) for e in sorted_entries]
        merge_log.append({
            'email': email,
            'kept_status': best_coupon.get('status'),
            'kept_used_at': best_coupon.get('used_at'),
            'kept_sent_at': best_coupon.get('sent_at'),
            'duplicate_count': len(entries),
            'priorities': priorities
        })
    
    return merged, merge_log

def find_unsent_recipients(merged):
    """Find recipients who have coupons generated but not sent"""
    unsent = []
    for coupon in merged:
        status = coupon.get('status', '').lower()
        sent_at = coupon.get('sent_at', '')
        
        # If status is 'generated' and no sent_at, it wasn't sent
        if status == 'generated' and not sent_at:
            unsent.append(coupon)
    
    return unsent

def save_merged_csv(merged, filename):
    """Save merged coupons to CSV"""
    if not merged:
        print("No data to save!")
        return
    
    fieldnames = merged[0].keys()
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged)
    
    print(f"Saved {len(merged)} entries to {filename}")

def save_unsent_csv(unsent, filename):
    """Save unsent recipients to CSV"""
    if not unsent:
        print("No unsent recipients!")
        return
    
    fieldnames = unsent[0].keys()
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unsent)
    
    print(f"Saved {len(unsent)} unsent recipients to {filename}")

def main():
    print("=" * 60)
    print("DCS Day '26 - Duplicate Detection & Merge Tool")
    print("=" * 60)
    
    # Load coupons
    coupons = load_coupons()
    print(f"\nTotal coupons loaded: {len(coupons)}")
    
    # Analyze duplicates
    duplicates, unique = analyze_duplicates(coupons)
    print(f"Unique emails: {len(unique)}")
    print(f"Duplicate emails: {len(duplicates)}")
    print(f"Total unique recipients: {len(unique) + len(duplicates)}")
    
    # Show duplicate details
    if duplicates:
        print("\n" + "-" * 60)
        print("DUPLICATE ENTRIES FOUND:")
        print("-" * 60)
        for email, entries in sorted(duplicates.items()):
            print(f"\n📧 {email} ({len(entries)} entries):")
            for idx, coupon in entries:
                status = coupon.get('status', 'N/A')
                sent_at = coupon.get('sent_at', 'Not sent')
                used_at = coupon.get('used_at', 'Not used')
                lunch = coupon.get('lunch_used_at', 'Not used')
                dinner = coupon.get('dinner_used_at', 'Not used')
                priority = get_priority(coupon)
                print(f"   Row {idx}: status={status}, sent={bool(sent_at)}, "
                      f"reg_used={bool(used_at)}, lunch={bool(lunch)}, dinner={bool(dinner)}, "
                      f"priority={priority}")
    
    # Merge duplicates
    print("\n" + "-" * 60)
    print("MERGING DUPLICATES...")
    print("-" * 60)
    merged, merge_log = merge_duplicates(duplicates, unique)
    print(f"Merged to {len(merged)} unique entries")
    
    # Save merged CSV
    save_merged_csv(merged, MERGED_FILE)
    
    # Find unsent recipients
    unsent = find_unsent_recipients(merged)
    print(f"\nUnsent recipients (generated but not sent): {len(unsent)}")
    save_unsent_csv(unsent, UNSENT_FILE)
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Original entries: {len(coupons)}")
    print(f"After merge: {len(merged)}")
    print(f"Duplicates removed: {len(coupons) - len(merged)}")
    print(f"Unsent (need retry): {len(unsent)}")
    
    # Count statuses
    status_counts = defaultdict(int)
    for coupon in merged:
        status_counts[coupon.get('status', 'unknown')] += 1
    
    print("\nStatus breakdown:")
    for status, count in sorted(status_counts.items()):
        print(f"  - {status}: {count}")
    
    print("\n✅ Files created:")
    print(f"  - {MERGED_FILE} (clean merged data)")
    print(f"  - {UNSENT_FILE} (for retry with new Gmail)")
    
    return merged, unsent

if __name__ == '__main__':
    main()
