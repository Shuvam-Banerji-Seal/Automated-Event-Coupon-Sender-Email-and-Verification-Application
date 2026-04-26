#!/home/shuvam/.global-pymaster/bin/python
"""test_smtp_connection.py
Unit tests for SMTPMailer.
Run with: /home/shuvam/.global-pymaster/bin/python -m pytest tests/test_smtp_connection.py -v
"""

import os
import pytest
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()
from src.smtp_mailer import SMTPMailer


class TestSMTPMailerInit:
    """Test SMTPMailer initialization."""

    def test_loads_from_env(self):
        """SMTPMailer initializes without error when env vars are set."""
        mailer = SMTPMailer()
        assert mailer.host == os.getenv("SMTP_HOST")
        assert mailer.port == int(os.getenv("SMTP_PORT", "587"))
        assert mailer.username == os.getenv("SMTP_USERNAME")
        assert mailer.sender_name == os.getenv("SMTP_SENDER_NAME")

    def test_raises_on_missing_env(self, monkeypatch):
        """SMTPMailer raises EnvironmentError when SMTP_USERNAME is missing."""
        monkeypatch.delenv("SMTP_USERNAME", raising=False)
        with pytest.raises(EnvironmentError) as exc_info:
            SMTPMailer()
        assert "SMTP_USERNAME" in str(exc_info.value)


class TestSMTPConnection:
    """Test SMTP connection testing."""

    def test_connection_returns_dict(self):
        """test_connection() returns dict with 'success' key."""
        mailer = SMTPMailer()
        result = mailer.test_connection()
        assert isinstance(result, dict)
        assert "success" in result

    def test_connection_success_structure(self):
        """On success, result contains host, port, username."""
        mailer = SMTPMailer()
        result = mailer.test_connection()
        if result["success"]:
            assert "host" in result
            assert "port" in result
            assert "username" in result
            assert result["host"] == mailer.host
            assert result["port"] == mailer.port

    def test_connection_failure_graceful(self):
        """On wrong credentials, returns success=False, not raises."""
        mailer = SMTPMailer()
        original_password = mailer.password
        mailer.password = "wrong_password"
        try:
            result = mailer.test_connection()
            assert result["success"] is False
            assert "message" in result
        finally:
            mailer.password = original_password


class TestSendEmail:
    """Test send_email method."""

    def test_send_returns_dict(self):
        """send_email() always returns a dict."""
        mailer = SMTPMailer()
        result = mailer.send_email(
            to_email="test@example.com",
            to_name="Test User",
            subject="Test Subject",
            html_body="<html><body>Test</body></html>",
        )
        assert isinstance(result, dict)

    def test_send_has_required_keys(self):
        """Result dict has success, to_email, message keys."""
        mailer = SMTPMailer()
        result = mailer.send_email(
            to_email="test@example.com",
            to_name="Test User",
            subject="Test Subject",
            html_body="<html><body>Test</body></html>",
        )
        assert "success" in result
        assert "to_email" in result
        assert "message" in result
        assert result["to_email"] == "test@example.com"


class TestSendBatch:
    """Test send_batch method."""

    def test_batch_summary_structure(self):
        """send_batch() returns total, sent, failed, failed_list, duration_seconds."""
        mailer = SMTPMailer()
        recipients = [
            {"email": "test1@example.com", "name": "Test One"},
        ]

        def fake_renderer(r):
            return "<html><body>Test</body></html>"

        result = mailer.send_batch(
            recipients=recipients,
            subject="Test Batch",
            template_renderer=fake_renderer,
            delay_seconds=0.01,
        )

        assert "total" in result
        assert "sent" in result
        assert "failed" in result
        assert "failed_list" in result
        assert "duration_seconds" in result
        assert result["total"] == 1

    def test_batch_delay_enforced(self):
        """Verify delay_seconds is respected between sends."""
        import time

        mailer = SMTPMailer()
        recipients = [
            {"email": "test1@example.com", "name": "Test One"},
            {"email": "test2@example.com", "name": "Test Two"},
        ]

        def fake_renderer(r):
            return "<html><body>Test</body></html>"

        delay = 0.5
        start = time.time()
        result = mailer.send_batch(
            recipients=recipients,
            subject="Test Batch",
            template_renderer=fake_renderer,
            delay_seconds=delay,
        )
        elapsed = time.time() - start

        assert elapsed >= delay * (len(recipients) - 1), "Delay not enforced between sends"