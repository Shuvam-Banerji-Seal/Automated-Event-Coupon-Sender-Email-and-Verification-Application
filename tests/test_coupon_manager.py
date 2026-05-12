#!/home/shuvam/.global-pymaster/bin/python
"""test_coupon_manager.py - Tests for coupon generation, validation, QR codes."""

import os
import sys
import pytest
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

from src.coupons import CouponManager
from src.data import CSVManager


@pytest.fixture
def csv_manager(tmp_path):
    cm = CSVManager(coupons_file=str(tmp_path / "test_coupons.csv"))
    yield cm


@pytest.fixture
def coupon_manager(csv_manager):
    return CouponManager(csv_manager=csv_manager)


class TestCouponID:
    def test_generates_uuid(self, coupon_manager):
        cid = coupon_manager.generate_coupon_id()
        assert isinstance(cid, str)
        assert len(cid) == 36  # UUID4 format
        assert "-" in cid

    def test_unique_ids(self, coupon_manager):
        ids = {coupon_manager.generate_coupon_id() for _ in range(100)}
        assert len(ids) == 100


class TestVerificationCode:
    def test_six_digits(self, coupon_manager):
        code = coupon_manager.generate_verification_code()
        assert len(code) == 6
        assert code.isdigit()

    def test_unique_codes(self, coupon_manager):
        codes = {coupon_manager.generate_verification_code() for _ in range(200)}
        assert len(codes) > 180  # Some collision possible but unlikely


class TestQRCode:
    def test_create_qr_returns_string(self, coupon_manager):
        qr = coupon_manager.create_qr_code("test data")
        assert isinstance(qr, str)
        assert len(qr) > 100

    def test_create_qr_is_base64(self, coupon_manager):
        import base64

        qr = coupon_manager.create_qr_code("test data")
        try:
            decoded = base64.b64decode(qr)
            # Check PNG header
            assert decoded[:8] == b"\x89PNG\r\n\x1a\n"
        except Exception:
            pytest.fail("QR code is not valid base64 PNG")

    def test_create_qr_varied_data(self, coupon_manager):
        qr1 = coupon_manager.create_qr_code('{"v":"123456","e":"a@b.com"}')
        qr2 = coupon_manager.create_qr_code('{"v":"999999","e":"x@y.com"}')
        assert qr1 != qr2  # Different data should produce different QR codes


class TestGenerateCoupon:
    def test_generates_successfully(self, coupon_manager):
        result = coupon_manager.generate_coupon("test@example.com", "Test Event")
        assert result["success"] is True
        assert result["email"] == "test@example.com"
        assert result["event_name"] == "Test Event"
        assert len(result["verification_code"]) == 6
        assert len(result["coupon_id"]) == 36
        assert len(result["qr_code_base64"]) > 100

    def test_handles_empty_email(self, coupon_manager):
        """Empty email still generates but with empty email field."""
        result = coupon_manager.generate_coupon("", "Test")
        assert result["success"] is True

    def test_preserves_email_case(self, coupon_manager):
        """Email is stored as-is in return, lowercased internally for records."""
        result = coupon_manager.generate_coupon("UPPER@EXAMPLE.COM", "Test")
        assert result["email"] == "UPPER@EXAMPLE.COM"


class TestValidateCoupon:
    def test_validate_by_code(self, coupon_manager, csv_manager):
        result = coupon_manager.generate_coupon("validate@test.com", "Validation Test")
        code = result["verification_code"]
        validation = coupon_manager.validate_coupon_by_code(code, "validate@test.com")
        assert validation["valid"] is True
        assert validation["email"] == "validate@test.com"

    def test_validate_wrong_code(self, coupon_manager):
        result = coupon_manager.generate_coupon("wrong@test.com", "Test")
        validation = coupon_manager.validate_coupon_by_code("000000", "wrong@test.com")
        assert validation["valid"] is False

    def test_validate_wrong_email(self, coupon_manager):
        result = coupon_manager.generate_coupon("right@test.com", "Test")
        validation = coupon_manager.validate_coupon_by_code(
            result["verification_code"], "wrong@test.com"
        )
        assert validation["valid"] is False

    def test_validate_and_mark_used(self, coupon_manager):
        result = coupon_manager.generate_coupon("used@test.com", "Used Test")
        assert coupon_manager.mark_coupon_used(result["coupon_id"]) is True
        validation = coupon_manager.validate_coupon_by_code(
            result["verification_code"], "used@test.com"
        )
        assert validation["valid"] is False
        assert "already" in validation.get("error", "").lower()

    def test_mark_coupon_sent(self, coupon_manager):
        result = coupon_manager.generate_coupon("sent@test.com", "Sent Test")
        assert coupon_manager.mark_coupon_sent(result["coupon_id"]) is True


class TestCouponBatch:
    def test_generate_batch(self, coupon_manager):
        recipients = [
            {"email": "batch1@test.com"},
            {"email": "batch2@test.com"},
            {"email": "batch3@test.com"},
        ]
        results = coupon_manager.generate_coupons_batch(recipients, "Batch Test")
        assert results["generated"] == 3
        assert len(results["coupons"]) == 3
        emails = [c["email"] for c in results["coupons"]]
        assert "batch1@test.com" in emails
