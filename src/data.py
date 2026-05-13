"""
CSV Manager for the Email Coupon System.
Handles reading and writing coupon data with file locking for concurrent access.
"""

import csv
import os
import fcntl
import json
import sqlite3
import threading
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
from contextlib import contextmanager
import logging


@dataclass
class CouponRecord:
    """Data structure for coupon records in CSV"""

    coupon_id: str
    email: str
    encrypted_data: str
    qr_code_data: str
    verification_code: str  # 6-digit verification code
    sent_at: Optional[str] = None
    used_at: Optional[str] = None
    status: str = "generated"  # generated, sent, used, expired

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for CSV writing"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CouponRecord":
        """Create from dictionary loaded from CSV"""
        return cls(**data)


class SQLiteBackup:
    """SQLite database that mirrors coupons.csv as a secondary backup.

    The CSV is always the primary store. Every CSV write operation also
    syncs to this SQLite database for redundancy and faster reads.
    """

    DB_FILE = "coupons_backup.db"

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or self.DB_FILE
        self.lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        """Create the coupons table if it doesn't exist."""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS coupons (
                        coupon_id TEXT PRIMARY KEY,
                        email TEXT NOT NULL,
                        encrypted_data TEXT,
                        qr_code_data TEXT,
                        verification_code TEXT,
                        sent_at TEXT,
                        used_at TEXT,
                        status TEXT DEFAULT 'generated'
                    )
                """)
                conn.commit()
            finally:
                conn.close()

    def upsert_coupon(self, row: Dict[str, str]) -> bool:
        """Insert or replace a coupon record in SQLite."""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO coupons
                    (coupon_id, email, encrypted_data, qr_code_data,
                     verification_code, sent_at, used_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        row.get("coupon_id", ""),
                        row.get("email", ""),
                        row.get("encrypted_data", ""),
                        row.get("qr_code_data", ""),
                        row.get("verification_code", ""),
                        row.get("sent_at"),
                        row.get("used_at"),
                        row.get("status", "generated"),
                    ),
                )
                conn.commit()
                return True
            except Exception as e:
                logging.getLogger(__name__).error(f"SQLite upsert error: {e}")
                return False
            finally:
                conn.close()

    def upsert_batch(self, rows: List[Dict[str, str]]) -> bool:
        """Insert or replace multiple coupon records in SQLite."""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO coupons
                    (coupon_id, email, encrypted_data, qr_code_data,
                     verification_code, sent_at, used_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    [
                        (
                            r.get("coupon_id", ""),
                            r.get("email", ""),
                            r.get("encrypted_data", ""),
                            r.get("qr_code_data", ""),
                            r.get("verification_code", ""),
                            r.get("sent_at"),
                            r.get("used_at"),
                            r.get("status", "generated"),
                        )
                        for r in rows
                    ],
                )
                conn.commit()
                return True
            except Exception as e:
                logging.getLogger(__name__).error(f"SQLite batch upsert error: {e}")
                return False
            finally:
                conn.close()

    def sync_from_csv(self, csv_file: str) -> int:
        """Sync all data from a CSV file into SQLite. Returns count of records synced."""
        count = 0
        try:
            with open(csv_file, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            if rows:
                self.upsert_batch(rows)
                count = len(rows)
        except FileNotFoundError:
            pass
        except Exception as e:
            logging.getLogger(__name__).error(f"SQLite sync error: {e}")
        return count

    def verify_integrity(self, csv_file: str) -> Dict[str, Any]:
        """Compare SQLite data with CSV and report differences."""
        result = {
            "csv_count": 0,
            "db_count": 0,
            "match": False,
            "missing_in_db": [],
            "missing_in_csv": [],
        }
        try:
            # Count CSV
            with open(csv_file, "r", newline="", encoding="utf-8") as f:
                csv_rows = list(csv.DictReader(f))
            result["csv_count"] = len(csv_rows)
            csv_ids = {r["coupon_id"] for r in csv_rows if r.get("coupon_id")}

            # Count DB
            conn = sqlite3.connect(self.db_path)
            try:
                db_rows = conn.execute(
                    "SELECT coupon_id, email, status FROM coupons"
                ).fetchall()
                result["db_count"] = len(db_rows)
                db_ids = {r[0] for r in db_rows}
            finally:
                conn.close()

            result["missing_in_db"] = list(csv_ids - db_ids)
            result["missing_in_csv"] = list(db_ids - csv_ids)
            result["match"] = csv_ids == db_ids
        except Exception as e:
            result["error"] = str(e)
        return result

    def repair_from_csv(self, csv_file: str) -> Dict[str, Any]:
        """Repair SQLite database by re-syncing full CSV data."""
        synced = self.sync_from_csv(csv_file)
        return {"synced": synced, "status": "repaired" if synced > 0 else "no_data"}


class CSVManager:
    """Manages CSV file operations with file locking for concurrent access"""

    def __init__(
        self,
        coupons_file: str = "coupons.csv",
        recipients_file: str = "responses - Sheet1.csv",
    ):
        self.coupons_file = coupons_file
        self.recipients_file = recipients_file
        self.logger = logging.getLogger(__name__)
        self.db = SQLiteBackup()

        # Ensure coupons file exists with headers
        self._initialize_coupons_file()

        # Sync existing CSV data to SQLite backup on startup
        synced = self.db.sync_from_csv(self.coupons_file)
        if synced > 0:
            self.logger.info(f"SQLite backup synced: {synced} records")

    def _initialize_coupons_file(self):
        """Initialize coupons CSV file with headers if it doesn't exist"""
        if not os.path.exists(self.coupons_file):
            headers = [
                "coupon_id",
                "email",
                "encrypted_data",
                "qr_code_data",
                "verification_code",
                "sent_at",
                "used_at",
                "status",
            ]
            with open(self.coupons_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
            self.logger.info(f"Created coupons file: {self.coupons_file}")
        else:
            # Check if verification_code column exists, add if missing
            self._ensure_verification_code_column()

    def _ensure_verification_code_column(self):
        """Ensure verification_code column exists in existing CSV file"""
        try:
            import tempfile
            import shutil

            # Read existing data
            with open(self.coupons_file, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames

                if not fieldnames:
                    self.logger.warning(
                        "CSV file has no headers, recreating with proper structure"
                    )
                    self._create_empty_coupons_file()
                    return

                # Clean fieldnames - remove empty strings and extra spaces
                clean_fieldnames = [f.strip() for f in fieldnames if f.strip()]
                expected_fieldnames = [
                    "coupon_id",
                    "email",
                    "encrypted_data",
                    "qr_code_data",
                    "verification_code",
                    "sent_at",
                    "used_at",
                    "status",
                ]

                # Check if structure needs fixing
                needs_fixing = (
                    set(clean_fieldnames) != set(expected_fieldnames)
                    or len(clean_fieldnames) != len(expected_fieldnames)
                    or clean_fieldnames != expected_fieldnames
                )

                if needs_fixing:
                    self.logger.info(
                        f"Fixing CSV structure. Current: {clean_fieldnames}, Expected: {expected_fieldnames}"
                    )
                    self._fix_csv_structure(expected_fieldnames)

        except Exception as e:
            self.logger.error(f"Error updating CSV structure: {str(e)}")
            # Recreate file if severely corrupted
            self._create_empty_coupons_file()

    def _create_empty_coupons_file(self):
        """Create a new empty coupons file with proper headers"""
        headers = [
            "coupon_id",
            "email",
            "encrypted_data",
            "qr_code_data",
            "verification_code",
            "sent_at",
            "used_at",
            "status",
        ]
        with open(self.coupons_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
        self.logger.info(
            f"Created new coupons file with proper headers: {self.coupons_file}"
        )

    def _fix_csv_structure(self, expected_fieldnames):
        """Fix CSV structure to match expected format"""
        import tempfile
        import shutil

        try:
            # Read existing data
            with open(self.coupons_file, "r", newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                all_rows = list(reader)

            if not all_rows:
                self._create_empty_coupons_file()
                return

            # Create temp file with correct structure
            with tempfile.NamedTemporaryFile(
                mode="w", delete=False, newline="", encoding="utf-8"
            ) as temp_f:
                writer = csv.writer(temp_f)
                writer.writerow(expected_fieldnames)

                # Process data rows (skip header)
                data_rows = all_rows[1:] if len(all_rows) > 1 else []
                for row in data_rows:
                    # Ensure row has exactly 8 columns
                    clean_row = (row + [""] * 8)[:8]
                    writer.writerow(clean_row)

                temp_filename = temp_f.name

            # Replace original file
            shutil.move(temp_filename, self.coupons_file)
            self.logger.info("Fixed CSV structure successfully")

        except Exception as e:
            self.logger.error(f"Error fixing CSV structure: {str(e)}")
            self._create_empty_coupons_file()

    @contextmanager
    def _file_lock(self, file_path: str, mode: str = "r"):
        """Context manager for file locking"""
        try:
            f = open(file_path, mode, newline="", encoding="utf-8")
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            yield f
        except Exception as e:
            self.logger.error(f"File lock error for {file_path}: {str(e)}")
            raise
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                f.close()
            except:
                pass

    def read_recipients(self) -> List[Dict[str, str]]:
        """Read recipient data from CSV file (all columns). Converts boolean strings."""
        recipients = []
        try:
            with self._file_lock(self.recipients_file, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("email"):
                        recipient = {}
                        for k, v in row.items():
                            if not k:
                                continue
                            v = v.strip()
                            # Convert 'True'/'False' strings to Python booleans
                            if v.lower() == "true":
                                recipient[k] = True
                            elif v.lower() == "false":
                                recipient[k] = False
                            else:
                                recipient[k] = v
                        recipients.append(recipient)

            self.logger.info(
                f"Read {len(recipients)} recipients from {self.recipients_file}"
            )
            return recipients

        except FileNotFoundError:
            self.logger.error(f"Recipients file not found: {self.recipients_file}")
            return []
        except Exception as e:
            self.logger.error(f"Error reading recipients: {str(e)}")
            return []

    def save_coupon(self, coupon: CouponRecord) -> bool:
        """Save a single coupon record to CSV"""
        try:
            with self._file_lock(self.coupons_file, "a") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "coupon_id",
                        "email",
                        "encrypted_data",
                        "qr_code_data",
                        "verification_code",
                        "sent_at",
                        "used_at",
                        "status",
                    ],
                )
                writer.writerow(coupon.to_dict())

            self.logger.info(f"Saved coupon {coupon.coupon_id} for {coupon.email}")
            # Sync to SQLite backup
            self.db.upsert_coupon(coupon.to_dict())
            return True

        except Exception as e:
            self.logger.error(f"Error saving coupon {coupon.coupon_id}: {str(e)}")
            return False

    def save_coupons_batch(self, coupons: List[CouponRecord]) -> bool:
        """Save multiple coupon records in batch"""
        try:
            with self._file_lock(self.coupons_file, "a") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "coupon_id",
                        "email",
                        "encrypted_data",
                        "qr_code_data",
                        "verification_code",
                        "sent_at",
                        "used_at",
                        "status",
                    ],
                )
                for coupon in coupons:
                    writer.writerow(coupon.to_dict())

            self.logger.info(f"Saved {len(coupons)} coupons in batch")
            # Sync to SQLite backup
            self.db.upsert_batch([c.to_dict() for c in coupons])
            return True

        except Exception as e:
            self.logger.error(f"Error saving coupon batch: {str(e)}")
            return False

    def find_coupon(self, coupon_id: str) -> Optional[CouponRecord]:
        """Find a coupon by ID"""
        try:
            with self._file_lock(self.coupons_file, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("coupon_id") == coupon_id:
                        return CouponRecord.from_dict(row)

            return None

        except Exception as e:
            self.logger.error(f"Error finding coupon {coupon_id}: {str(e)}")
            return None

    def find_coupon_by_verification_code(
        self, verification_code: str, email: Optional[str] = None
    ) -> Optional[CouponRecord]:
        """Find a coupon by verification code. If email is provided, also match email."""
        try:
            with self._file_lock(self.coupons_file, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("verification_code") == verification_code:
                        if (
                            email is None
                            or row.get("email", "").lower() == email.lower()
                        ):
                            return CouponRecord.from_dict(row)

            return None

        except Exception as e:
            self.logger.error(f"Error finding coupon by verification code: {str(e)}")
            return None

    def update_coupon_status(
        self,
        coupon_id: str,
        status: str,
        used_at: Optional[str] = None,
        sent_at: Optional[str] = None,
        if_current_status: Optional[str] = None,
    ) -> bool:
        """Update coupon status and timestamps.

        Args:
            coupon_id: ID of coupon to update
            status: New status value
            used_at: Optional used timestamp
            sent_at: Optional sent timestamp
            if_current_status: If set, only update when current status matches (TOCTOU guard)
        """
        try:
            # Read all coupons
            coupons = []
            updated = False

            with self._file_lock(self.coupons_file, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("coupon_id") == coupon_id:
                        # S-09: TOCTOU guard - skip if current status doesn't match precondition
                        if if_current_status and row.get("status") != if_current_status:
                            coupons.append(row)
                            continue
                        row["status"] = status
                        if used_at:
                            row["used_at"] = used_at
                        if sent_at:
                            row["sent_at"] = sent_at
                        updated = True
                    coupons.append(row)

            if not updated:
                self.logger.warning(f"Coupon {coupon_id} not found for status update")
                return False

            # Write back all coupons
            with self._file_lock(self.coupons_file, "w") as f:
                if coupons:
                    writer = csv.DictWriter(f, fieldnames=coupons[0].keys())
                    writer.writeheader()
                    writer.writerows(coupons)

            self.logger.info(f"Updated coupon {coupon_id} status to {status}")
            # Sync updated row to SQLite backup
            for row in coupons:
                if row.get("coupon_id") == coupon_id:
                    self.db.upsert_coupon(row)
                    break
            return True

        except Exception as e:
            self.logger.error(f"Error updating coupon {coupon_id}: {str(e)}")
            return False

    def get_coupon_stats(self) -> Dict[str, int]:
        """Get statistics about coupon usage"""
        stats = {"total": 0, "generated": 0, "sent": 0, "used": 0, "expired": 0}

        try:
            with self._file_lock(self.coupons_file, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    stats["total"] += 1
                    status = row.get("status", "generated")
                    if status in stats:
                        stats[status] += 1

            return stats

        except Exception as e:
            self.logger.error(f"Error getting coupon stats: {str(e)}")
            return stats

    def validate_email_format(self, email: str) -> bool:
        """Basic email format validation"""
        import re

        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return re.match(pattern, email.strip()) is not None

    def validate_recipients_file(self, file_path: str) -> Dict[str, Any]:
        """Validate recipients CSV file and return statistics"""
        result = {
            "valid": False,
            "total_rows": 0,
            "valid_emails": 0,
            "invalid_emails": 0,
            "errors": [],
        }

        try:
            with open(file_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)

                if not reader.fieldnames or "email" not in reader.fieldnames:
                    result["errors"].append("CSV must have 'email' column")
                    return result

                for i, row in enumerate(reader, 1):
                    result["total_rows"] += 1
                    email = row.get("email", "").strip()

                    if not email:
                        result["invalid_emails"] += 1
                        continue

                    if self.validate_email_format(email):
                        result["valid_emails"] += 1
                    else:
                        result["invalid_emails"] += 1
                        result["errors"].append(
                            f"Invalid email format at row {i}: {email}"
                        )

            result["valid"] = result["valid_emails"] > 0

        except Exception as e:
            result["errors"].append(f"Error reading file: {str(e)}")

        return result

    def reset_coupons_for_fresh_upload(self):
        """Reset coupons file when uploading a fresh recipients CSV"""
        try:
            self.logger.info("Resetting coupons for fresh recipients upload")
            self._create_empty_coupons_file()
            return True
        except Exception as e:
            self.logger.error(f"Error resetting coupons file: {str(e)}")
            return False

    def backup_current_data(self, backup_suffix: Optional[str] = None) -> str:
        """Create a backup of current coupons data"""
        try:
            if backup_suffix is None:
                from datetime import datetime

                backup_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")

            backup_filename = f"{self.coupons_file}.backup_{backup_suffix}"

            if os.path.exists(self.coupons_file):
                import shutil

                shutil.copy2(self.coupons_file, backup_filename)
                self.logger.info(f"Created backup: {backup_filename}")
                return backup_filename
            else:
                self.logger.warning("No existing coupons file to backup")
                return ""

        except Exception as e:
            self.logger.error(f"Error creating backup: {str(e)}")
            return ""

    def get_upload_status(self) -> Dict[str, Any]:
        """Get current status of CSV files for upload management"""
        status = {
            "recipients_file_exists": os.path.exists(self.recipients_file),
            "coupons_file_exists": os.path.exists(self.coupons_file),
            "recipients_count": 0,
            "coupons_count": 0,
            "last_coupon_generated": None,
            "csv_structure_valid": False,
        }

        try:
            # Check recipients
            if status["recipients_file_exists"]:
                recipients = self.read_recipients()
                status["recipients_count"] = len(recipients)

            # Check coupons
            if status["coupons_file_exists"]:
                with open(self.coupons_file, "r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    if reader.fieldnames:
                        expected_headers = [
                            "coupon_id",
                            "email",
                            "encrypted_data",
                            "qr_code_data",
                            "verification_code",
                            "sent_at",
                            "used_at",
                            "status",
                        ]
                        status["csv_structure_valid"] = (
                            list(reader.fieldnames) == expected_headers
                        )

                        rows = list(reader)
                        status["coupons_count"] = len(rows)

                        if rows:
                            # Get the most recent coupon
                            last_row = rows[-1]
                            status["last_coupon_generated"] = {
                                "email": last_row.get("email"),
                                "verification_code": last_row.get("verification_code"),
                                "status": last_row.get("status"),
                            }

        except Exception as e:
            self.logger.error(f"Error getting upload status: {str(e)}")

        return status

    def save_failed_emails(
        self, failed_emails: List[Dict[str, str]], event_name: str
    ) -> Optional[str]:
        """
        Save failed email information to a CSV file

        Args:
            failed_emails: List of failed email dictionaries with 'email', 'error', 'timestamp'
            event_name: Name of the event for filename

        Returns:
            Path to the created failure log file
        """
        try:
            # Create logs directory if it doesn't exist
            os.makedirs("logs", exist_ok=True)

            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_event_name = "".join(
                c for c in event_name if c.isalnum() or c in (" ", "-", "_")
            ).rstrip()
            safe_event_name = safe_event_name.replace(" ", "_")

            filename = f"logs/failed_emails_{safe_event_name}_{timestamp}.csv"

            # Write failed emails to CSV (create file directly without file lock since it's a new file)
            with open(filename, "w", newline="", encoding="utf-8") as f:
                fieldnames = ["email", "error_message", "timestamp", "event_name"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)

                writer.writeheader()
                for failed_email in failed_emails:
                    writer.writerow(
                        {
                            "email": failed_email["email"],
                            "error_message": failed_email["error"],
                            "timestamp": failed_email["timestamp"],
                            "event_name": event_name,
                        }
                    )

            self.logger.info(f"Saved {len(failed_emails)} failed emails to {filename}")
            return filename

        except Exception as e:
            self.logger.error(f"Error saving failed emails: {str(e)}")
            return None

    def save_organizer_credentials(
        self, user_info: Dict[str, Any], oauth_tokens: Dict[str, Any], event_name: str
    ) -> bool:
        """Save organizer's credentials for sending thank you emails"""
        try:
            organizer_data = {
                "user_info": user_info,
                "oauth_tokens": oauth_tokens,
                "event_name": event_name,
                "saved_at": datetime.now().isoformat(),
            }

            with open("organizer_credentials.json", "w") as f:
                json.dump(organizer_data, f, indent=2)

            self.logger.info(
                f"Saved organizer credentials for {user_info.get('email')} for event: {event_name}"
            )
            return True

        except Exception as e:
            self.logger.error(f"Error saving organizer credentials: {str(e)}")
            return False

    def get_organizer_credentials(self) -> Optional[Dict[str, Any]]:
        """Retrieve stored organizer credentials"""
        try:
            if not os.path.exists("organizer_credentials.json"):
                return None

            with open("organizer_credentials.json", "r") as f:
                return json.load(f)

        except Exception as e:
            self.logger.error(f"Error loading organizer credentials: {str(e)}")
            return None
