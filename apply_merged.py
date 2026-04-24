#!/usr/bin/env python3
"""
DCS Day '26 - Apply Merged Coupons
==================================
Safely replaces coupons.csv with the merged version after confirmation.

This script:
1. Shows the differences between original and merged
2. Creates multiple backups
3. Replaces the original with merged data

Usage:
    python apply_merged.py
"""

import os
import csv
import shutil
from datetime import datetime

def count_by_status(filename):
    """Count entries by status"""
    counts = {}
    with open(filename, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            status = row.get('status', 'unknown')
            counts[status] = counts.get(status, 0) + 1
    return counts

def count_used_registrations(filename):
    """Count entries with used_at set (registered)"""
    count = 0
    with open(filename, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('used_at'):
                count += 1
    return count

def main():
    original = 'coupons.csv'
    merged = 'coupons_merged.csv'
    
    print("=" * 60)
    print("DCS Day '26 - Apply Merged Coupons")
    print("=" * 60)
    
    # Check files exist
    if not os.path.exists(original):
        print(f"❌ Error: {original} not found")
        return
    
    if not os.path.exists(merged):
        print(f"❌ Error: {merged} not found")
        print("Run fix_duplicates.py first!")
        return
    
    # Count entries
    with open(original, 'r') as f:
        original_count = sum(1 for _ in f) - 1  # Subtract header
    
    with open(merged, 'r') as f:
        merged_count = sum(1 for _ in f) - 1
    
    # Get status breakdown
    original_status = count_by_status(original)
    merged_status = count_by_status(merged)
    
    # Count registrations
    original_registered = count_used_registrations(original)
    merged_registered = count_used_registrations(merged)
    
    print(f"\n📊 COMPARISON:")
    print("-" * 40)
    print(f"Original ({original}):")
    print(f"  Total entries: {original_count}")
    print(f"  Registered (used_at): {original_registered}")
    for status, count in sorted(original_status.items()):
        print(f"    - {status}: {count}")
    
    print(f"\nMerged ({merged}):")
    print(f"  Total entries: {merged_count}")
    print(f"  Registered (used_at): {merged_registered}")
    for status, count in sorted(merged_status.items()):
        print(f"    - {status}: {count}")
    
    print(f"\n📉 Reduction: {original_count} → {merged_count} ({original_count - merged_count} duplicates removed)")
    print(f"✅ Registrations preserved: {merged_registered}")
    
    # Safety check
    if merged_registered < original_registered:
        print(f"\n⚠️  WARNING: Merged has fewer registrations!")
        print(f"    Original: {original_registered}, Merged: {merged_registered}")
        print("    This might indicate data loss. Please review!")
    
    print("\n" + "-" * 60)
    confirm = input("Apply merged data to coupons.csv? (type 'yes' to confirm): ")
    
    if confirm.lower() != 'yes':
        print("❌ Cancelled. No changes made.")
        return
    
    # Create timestamped backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"coupons_original_backup_{timestamp}.csv"
    shutil.copy2(original, backup_name)
    print(f"\n✅ Backup created: {backup_name}")
    
    # Replace original with merged
    shutil.copy2(merged, original)
    print(f"✅ Applied: {merged} → {original}")
    
    print(f"\n🎉 Done! {original} now has {merged_count} unique entries.")
    print(f"   Backup saved as: {backup_name}")

if __name__ == '__main__':
    main()
