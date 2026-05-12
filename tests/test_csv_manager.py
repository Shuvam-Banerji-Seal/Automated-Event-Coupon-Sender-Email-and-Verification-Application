#!/home/shuvam/.global-pymaster/bin/python
"""test_csv_manager.py - Tests for CSV data operations."""

import os
import sys
import csv
import pytest
from datetime import datetime
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

from src.data import CSVManager, CouponRecord


@pytest.fixture
def csv_manager(tmp_path):
    coupons_file = str(tmp_path / "coupons.csv")
    recipients_file = str(tmp_path / "recipients.csv")
    cm = CSVManager(coupons_file=coupons_file, recipients_file=recipients_file)
    yield cm


@pytest.fixture
def sample_coupon():
    return CouponRecord(
        coupon_id="test-0001",
        email="test@example.com",
        encrypted_data="encrypted123",
        qr_code_data="qrpngbase64",
        verification_code="123456",
        status="generated",
    )


class TestCSVInit:
    def test_creates_coupons_file(self, tmp_path):
        f = str(tmp_path / "new_coupons.csv")
        cm = CSVManager(coupons_file=f)
        assert os.path.exists(f)

    def test_coupons_file_has_headers(self, csv_manager):
        with open(csv_manager.coupons_file, "r") as f:
            reader = csv.reader(f)
            headers = next(reader)
        expected = [
            "coupon_id",
            "email",
            "encrypted_data",
            "qr_code_data",
            "verification_code",
            "sent_at",
            "used_at",
            "status",
        ]
        assert headers == expected


class TestCouponCRUD:
    def test_save_coupon(self, csv_manager, sample_coupon):
        assert csv_manager.save_coupon(sample_coupon) is True

    def test_find_coupon(self, csv_manager, sample_coupon):
        csv_manager.save_coupon(sample_coupon)
        found = csv_manager.find_coupon("test-0001")
        assert found is not None
        assert found.coupon_id == "test-0001"
        assert found.email == "test@example.com"

    def test_find_missing_coupon(self, csv_manager):
        assert csv_manager.find_coupon("nonexistent") is None

    def test_find_by_verification_code(self, csv_manager, sample_coupon):
        csv_manager.save_coupon(sample_coupon)
        found = csv_manager.find_coupon_by_verification_code(
            "123456", "test@example.com"
        )
        assert found is not None
        assert found.coupon_id == "test-0001"

    def test_find_by_wrong_code(self, csv_manager, sample_coupon):
        csv_manager.save_coupon(sample_coupon)
        assert (
            csv_manager.find_coupon_by_verification_code("999999", "test@example.com")
            is None
        )

    def test_update_status_to_used(self, csv_manager, sample_coupon):
        csv_manager.save_coupon(sample_coupon)
        now = datetime.now().isoformat()
        assert csv_manager.update_coupon_status("test-0001", "used", now) is True
        found = csv_manager.find_coupon("test-0001")
        assert found.status == "used"
        assert found.used_at == now

    def test_update_status_to_sent(self, csv_manager, sample_coupon):
        csv_manager.save_coupon(sample_coupon)
        assert csv_manager.update_coupon_status("test-0001", "sent") is True
        found = csv_manager.find_coupon("test-0001")
        assert found.status == "sent"

    def test_update_nonexistent(self, csv_manager):
        assert csv_manager.update_coupon_status("ghost", "used") is False


class TestBatchSave:
    def test_save_batch(self, csv_manager):
        coupons = [
            CouponRecord(
                coupon_id=f"batch-{i}",
                email=f"user{i}@test.com",
                encrypted_data="e",
                qr_code_data="q",
                verification_code=f"{i:06d}",
                status="generated",
            )
            for i in range(10)
        ]
        assert csv_manager.save_coupons_batch(coupons) is True

    def test_batch_saved_records(self, csv_manager):
        coupons = [
            CouponRecord(
                coupon_id=f"batch-{i}",
                email=f"user{i}@test.com",
                encrypted_data="e",
                qr_code_data="q",
                verification_code=f"{i:06d}",
                status="generated",
            )
            for i in range(5)
        ]
        csv_manager.save_coupons_batch(coupons)
        stats = csv_manager.get_coupon_stats()
        assert stats["total"] == 5


class TestStats:
    def test_empty_stats(self, csv_manager):
        stats = csv_manager.get_coupon_stats()
        assert stats["total"] == 0
        assert stats["generated"] == 0

    def test_stats_counts(self, csv_manager):
        csv_manager.save_coupon(
            CouponRecord(
                coupon_id="s1",
                email="a@b.com",
                encrypted_data="e",
                qr_code_data="q",
                verification_code="000001",
                status="sent",
            )
        )
        csv_manager.save_coupon(
            CouponRecord(
                coupon_id="s2",
                email="b@b.com",
                encrypted_data="e",
                qr_code_data="q",
                verification_code="000002",
                status="used",
            )
        )
        csv_manager.save_coupon(
            CouponRecord(
                coupon_id="s3",
                email="c@b.com",
                encrypted_data="e",
                qr_code_data="q",
                verification_code="000003",
                status="generated",
            )
        )
        stats = csv_manager.get_coupon_stats()
        assert stats["total"] == 3
        assert stats["sent"] == 1
        assert stats["used"] == 1
        assert stats["generated"] == 1


class TestRecipients:
    def test_read_recipients_empty(self, csv_manager):
        assert csv_manager.read_recipients() == []

    def test_read_recipients(self, csv_manager):
        with open(csv_manager.recipients_file, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["email", "name"])
            w.writeheader()
            w.writerow({"email": "a@test.com", "name": "Alice"})
            w.writerow({"email": "b@test.com", "name": "Bob"})
        recipients = csv_manager.read_recipients()
        assert len(recipients) == 2
        assert recipients[0]["email"] == "a@test.com"

    def test_validate_email(self, csv_manager):
        assert csv_manager.validate_email_format("good@example.com") is True
        assert csv_manager.validate_email_format("bad-email") is False
        assert csv_manager.validate_email_format("") is False

    def test_validate_recipients_file(self, csv_manager):
        with open(csv_manager.recipients_file, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["email", "name"])
            w.writeheader()
            w.writerow({"email": "valid@test.com", "name": "Valid"})
            w.writerow({"email": "invalid-email", "name": "Bad"})
        result = csv_manager.validate_recipients_file(csv_manager.recipients_file)
        assert result["valid"] is True
        assert result["valid_emails"] == 1
        assert result["invalid_emails"] == 1
