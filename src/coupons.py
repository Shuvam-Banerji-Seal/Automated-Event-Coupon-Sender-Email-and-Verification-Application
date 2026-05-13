"""
Coupon Manager for the Email Coupon System.
Handles coupon generation, QR code creation, and validation.
"""

import uuid
import qrcode
import base64
import secrets
import string
from io import BytesIO
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import logging
import json

from src.encryption import EncryptionService
from src.data import CSVManager, CouponRecord


class CouponManager:
    """Manages coupon generation, encryption, and validation"""

    def __init__(
        self, secret_key: Optional[str] = None, csv_manager: Optional[CSVManager] = None
    ):
        self.encryption_service = EncryptionService(secret_key)
        self.csv_manager = csv_manager or CSVManager()
        self.logger = logging.getLogger(__name__)

    def validate_and_mark_used(
        self, verification_code: str, email: str
    ) -> Dict[str, Any]:
        """S-09: Atomic validate + mark used under a single CSV scan."""
        try:
            coupon_record = self.csv_manager.find_coupon_by_verification_code(
                verification_code, email
            )
            if not coupon_record:
                return {
                    "valid": False,
                    "error": "Invalid verification code or email",
                    "error_code": "NOT_FOUND",
                }
            if coupon_record.status == "used":
                return {
                    "valid": False,
                    "error": "This coupon has already been used",
                    "error_code": "ALREADY_USED",
                }
            if coupon_record.status in ("sent", "generated"):
                used_at = datetime.now(timezone.utc).isoformat()
                success = self.csv_manager.update_coupon_status(
                    coupon_record.coupon_id,
                    "used",
                    used_at=used_at,
                    if_current_status=coupon_record.status,
                )
                if success:
                    self.logger.info(
                        f"Coupon {coupon_record.coupon_id} validated and marked as used"
                    )
                    return {
                        "valid": True,
                        "coupon_id": coupon_record.coupon_id,
                        "email": email,
                        "event_name": "",
                        "created_at": coupon_record.sent_at or "",
                        "verification_code": verification_code,
                    }
                else:
                    # TOCTOU hit - another request marked it first
                    return {
                        "valid": False,
                        "error": "This coupon was just used by another request",
                        "error_code": "RACE_LOST",
                    }
            return {
                "valid": False,
                "error": f"Coupon status is '{coupon_record.status}', cannot be used",
                "error_code": "INVALID_STATUS",
            }
        except Exception as e:
            self.logger.error(f"Error in validate_and_mark_used: {str(e)}")
            return {
                "valid": False,
                "error": "System error during verification",
                "error_code": "SYSTEM_ERROR",
            }

    def generate_coupon_id(self) -> str:
        """Generate unique coupon ID using UUID4"""
        return str(uuid.uuid4())

    def generate_verification_code(self) -> str:
        """Generate 6-digit verification code using cryptographically secure RNG"""
        while True:
            code = "".join(secrets.choice(string.digits) for _ in range(6))
            # L-07: Check for collision with existing codes in CSV
            existing = self.csv_manager.find_coupon_by_verification_code(code, "")
            if not existing:
                return code

    def create_qr_code(self, data: str) -> str:
        """
        Generate QR code from data and return as base64 string

        Args:
            data: String data to encode in QR code

        Returns:
            Base64 encoded PNG image of QR code
        """
        try:
            # Create QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(data)
            qr.make(fit=True)

            # Create image
            img = qr.make_image(fill_color="black", back_color="white")

            # Convert to base64
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            img_str = base64.b64encode(buffer.getvalue()).decode()

            return img_str

        except Exception as e:
            self.logger.error(f"Error creating QR code: {str(e)}")
            raise

    def generate_coupon(
        self, email: str, event_name: str = "Special Event"
    ) -> Dict[str, Any]:
        """
        Generate a complete coupon with encrypted data, simple QR code, and 6-digit verification code

        Args:
            email: Recipient email address
            event_name: Name of the event for the coupon

        Returns:
            Dictionary containing coupon data
        """
        try:
            # Check if email already has a coupon — prevent duplicate generation
            existing_records = self.csv_manager.find_coupons_by_email(email.lower())
            if existing_records:
                existing = existing_records[-1]  # most recent entry
                self.logger.info(
                    f"Coupon already exists for {email}, returning existing"
                )
                return {
                    "success": True,
                    "coupon_id": existing.coupon_id,
                    "email": email,
                    "event_name": event_name,
                    "qr_code_base64": existing.qr_code_data,
                    "encrypted_data": existing.encrypted_data,
                    "verification_code": existing.verification_code,
                    "existing": True,
                }

            # Generate unique identifiers
            coupon_id = self.generate_coupon_id()
            verification_code = self.generate_verification_code()

            # Create coupon data
            coupon_data = {
                "coupon_id": coupon_id,
                "email": email.lower(),
                "event_name": event_name,
                "verification_code": verification_code,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "valid": True,
            }

            # Encrypt coupon data
            encrypted_data = self.encryption_service.encrypt_coupon_data(
                coupon_data, email
            )

            # Create SIMPLE QR code with just the verification code and email for fast scanning
            qr_data = {
                "v": verification_code,  # Short key for verification code
                "e": email.lower(),  # Short key for email
            }
            qr_code_base64 = self.create_qr_code(json.dumps(qr_data))

            # Create coupon record
            coupon_record = CouponRecord(
                coupon_id=coupon_id,
                email=email.lower(),
                encrypted_data=encrypted_data,
                qr_code_data=qr_code_base64,
                verification_code=verification_code,
                status="generated",
            )

            # Save to CSV
            if self.csv_manager.save_coupon(coupon_record):
                self.logger.info(
                    f"Generated coupon {coupon_id} for {email} with verification code {verification_code}"
                )

                return {
                    "coupon_id": coupon_id,
                    "email": email,
                    "event_name": event_name,
                    "qr_code_base64": qr_code_base64,
                    "encrypted_data": encrypted_data,
                    "verification_code": verification_code,
                    "success": True,
                }
            else:
                raise Exception("Failed to save coupon to database")

        except Exception as e:
            self.logger.error(f"Error generating coupon for {email}: {str(e)}")
            return {"success": False, "error": str(e)}

    def generate_coupons_batch(
        self, recipients: List[Dict[str, str]], event_name: str = "Special Event"
    ) -> Dict[str, Any]:
        """
        Generate coupons for multiple recipients

        Args:
            recipients: List of recipient dictionaries with 'email' key
            event_name: Name of the event

        Returns:
            Dictionary with generation results
        """
        results = {
            "total": len(recipients),
            "generated": 0,
            "failed": 0,
            "coupons": [],
            "errors": [],
        }

        coupon_records = []

        for recipient in recipients:
            email = recipient.get("email", "").strip()
            if not email:
                results["failed"] += 1
                results["errors"].append("Empty email address")
                continue

            try:
                # Generate coupon data
                # Generate unique identifiers
                coupon_id = self.generate_coupon_id()
                verification_code = self.generate_verification_code()

                coupon_data = {
                    "coupon_id": coupon_id,
                    "email": email.lower(),
                    "event_name": event_name,
                    "verification_code": verification_code,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "valid": True,
                }

                # Encrypt and create simple QR code
                encrypted_data = self.encryption_service.encrypt_coupon_data(
                    coupon_data, email
                )

                # Create SIMPLE QR code with just verification code and email
                qr_data = {
                    "v": verification_code,  # Short key for verification code
                    "e": email.lower(),  # Short key for email
                }
                qr_code_base64 = self.create_qr_code(json.dumps(qr_data))

                # Create record
                coupon_record = CouponRecord(
                    coupon_id=coupon_id,
                    email=email.lower(),
                    encrypted_data=encrypted_data,
                    qr_code_data=qr_code_base64,
                    verification_code=verification_code,
                    status="generated",
                )

                coupon_records.append(coupon_record)

                # Add to results
                results["coupons"].append(
                    {
                        "coupon_id": coupon_id,
                        "email": email,
                        "event_name": event_name,
                        "qr_code_base64": qr_code_base64,
                        "encrypted_data": encrypted_data,
                        "verification_code": verification_code,
                    }
                )

                results["generated"] += 1

            except Exception as e:
                results["failed"] += 1
                results["errors"].append(
                    f"Failed to generate coupon for {email}: {str(e)}"
                )
                self.logger.error(f"Error generating coupon for {email}: {str(e)}")

        # Save all coupons in batch
        if coupon_records:
            if not self.csv_manager.save_coupons_batch(coupon_records):
                self.logger.error("Failed to save coupon batch to database")
                # Note: coupons are still generated in memory, just not persisted

        self.logger.info(
            f"Generated {results['generated']} coupons, {results['failed']} failed"
        )
        return results

    def validate_coupon(self, encrypted_data: str, email: str) -> Dict[str, Any]:
        """
        Validate a coupon by decrypting and checking its status

        Args:
            encrypted_data: Encrypted coupon data from QR code
            email: Email address for validation

        Returns:
            Dictionary with validation results
        """
        try:
            # Decrypt coupon data
            decrypted_data = self.encryption_service.decrypt_coupon_data(
                encrypted_data, email
            )

            # Validate timestamp (24 hours validity)
            if not self.encryption_service.validate_timestamp(
                decrypted_data, max_age_hours=24
            ):
                return {
                    "valid": False,
                    "error": "Coupon has expired",
                    "error_code": "EXPIRED",
                }

            # Get coupon ID and check database status
            coupon_id = decrypted_data.get("coupon_id")
            if not coupon_id:
                return {
                    "valid": False,
                    "error": "Invalid coupon data",
                    "error_code": "INVALID_DATA",
                }

            # Check coupon record in database
            coupon_record = self.csv_manager.find_coupon(coupon_id)
            if not coupon_record:
                return {
                    "valid": False,
                    "error": "Coupon not found in database",
                    "error_code": "NOT_FOUND",
                }

            # Check if already used
            if coupon_record.status == "used":
                return {
                    "valid": False,
                    "error": "Coupon has already been used",
                    "error_code": "ALREADY_USED",
                    "used_at": coupon_record.used_at,
                }

            # Coupon is valid
            return {
                "valid": True,
                "coupon_id": coupon_id,
                "email": decrypted_data.get("email"),
                "event_name": decrypted_data.get("event_name"),
                "created_at": decrypted_data.get("created_at"),
                "status": coupon_record.status,
            }

        except ValueError as e:
            self.logger.warning(f"Coupon validation failed: {str(e)}")
            return {
                "valid": False,
                "error": "Invalid or corrupted coupon data",
                "error_code": "DECRYPTION_FAILED",
            }
        except Exception as e:
            self.logger.error(f"Unexpected error during coupon validation: {str(e)}")
            return {
                "valid": False,
                "error": "System error during validation",
                "error_code": "SYSTEM_ERROR",
            }

    def validate_coupon_by_code(
        self, verification_code: str, email: str
    ) -> Dict[str, Any]:
        """
        Validate a coupon using 6-digit verification code

        Args:
            verification_code: 6-digit verification code
            email: Email address for security verification

        Returns:
            Dictionary with validation result
        """
        try:
            # Find coupon by verification code and email
            coupon_record = self.csv_manager.find_coupon_by_verification_code(
                verification_code, email
            )

            if not coupon_record:
                return {
                    "valid": False,
                    "error": "Invalid verification code or email",
                    "error_code": "NOT_FOUND",
                }

            # L-02: Check expiry (48 hours from sent_at or 72 hours from generation)
            if coupon_record.sent_at:
                from datetime import timezone

                sent_dt = datetime.fromisoformat(coupon_record.sent_at)
                age_hours = (
                    datetime.now(timezone.utc) - sent_dt
                ).total_seconds() / 3600
                if age_hours > 48:
                    return {
                        "valid": False,
                        "error": "This coupon has expired",
                        "error_code": "EXPIRED",
                    }

            # Check if already used
            if coupon_record.status == "used":
                return {
                    "valid": False,
                    "error": "This coupon has already been used",
                    "error_code": "ALREADY_USED",
                    "used_at": coupon_record.used_at,
                }

            # Decrypt and validate the coupon data
            try:
                decrypted_data = self.encryption_service.decrypt_coupon_data(
                    coupon_record.encrypted_data, coupon_record.email
                )

                if decrypted_data and decrypted_data.get("valid", False):
                    return {
                        "valid": True,
                        "coupon_id": coupon_record.coupon_id,
                        "email": coupon_record.email,
                        "event_name": decrypted_data.get("event_name", "Event"),
                        "created_at": decrypted_data.get("created_at"),
                        "verification_code": verification_code,
                    }
                else:
                    return {
                        "valid": False,
                        "error": "Coupon data is invalid",
                        "error_code": "INVALID_DATA",
                    }

            except Exception as decrypt_error:
                self.logger.error(
                    f"Decryption failed for verification code {verification_code}: {str(decrypt_error)}"
                )
                return {
                    "valid": False,
                    "error": "Failed to decrypt coupon data",
                    "error_code": "DECRYPTION_FAILED",
                }

        except Exception as e:
            self.logger.error(
                f"Error validating verification code {verification_code}: {str(e)}"
            )
            return {
                "valid": False,
                "error": "System error during validation",
                "error_code": "SYSTEM_ERROR",
            }

    def mark_coupon_used(self, coupon_id: str) -> bool:
        """
        Mark a coupon as used

        Args:
            coupon_id: ID of the coupon to mark as used

        Returns:
            True if successfully marked as used, False otherwise
        """
        try:
            used_at = datetime.now(timezone.utc).isoformat()
            success = self.csv_manager.update_coupon_status(coupon_id, "used", used_at)

            if success:
                self.logger.info(f"Marked coupon {coupon_id} as used")
            else:
                self.logger.error(f"Failed to mark coupon {coupon_id} as used")

            return success

        except Exception as e:
            self.logger.error(f"Error marking coupon {coupon_id} as used: {str(e)}")
            return False

    def mark_coupon_sent(self, coupon_id: str) -> bool:
        """
        Mark a coupon as sent via email

        Args:
            coupon_id: ID of the coupon to mark as sent

        Returns:
            True if successfully marked as sent, False otherwise
        """
        try:
            sent_at = datetime.now(timezone.utc).isoformat()
            # Update the coupon record with sent timestamp
            coupon_record = self.csv_manager.find_coupon(coupon_id)
            if coupon_record:
                coupon_record.sent_at = sent_at
                coupon_record.status = "sent"
                success = self.csv_manager.update_coupon_status(
                    coupon_id, "sent", used_at=None, sent_at=sent_at
                )

                if success:
                    self.logger.info(f"Marked coupon {coupon_id} as sent")
                return success
            else:
                self.logger.error(f"Coupon {coupon_id} not found for marking as sent")
                return False

        except Exception as e:
            self.logger.error(f"Error marking coupon {coupon_id} as sent: {str(e)}")
            return False

    def get_coupon_status(self, coupon_id: str) -> Dict[str, Any]:
        """
        Get the current status of a coupon

        Args:
            coupon_id: ID of the coupon to check

        Returns:
            Dictionary with coupon status information
        """
        try:
            coupon_record = self.csv_manager.find_coupon(coupon_id)

            if not coupon_record:
                return {"found": False, "error": "Coupon not found"}

            return {
                "found": True,
                "coupon_id": coupon_record.coupon_id,
                "email": coupon_record.email,
                "status": coupon_record.status,
                "sent_at": coupon_record.sent_at,
                "used_at": coupon_record.used_at,
            }

        except Exception as e:
            self.logger.error(f"Error getting coupon status for {coupon_id}: {str(e)}")
            return {"found": False, "error": f"System error: {str(e)}"}
