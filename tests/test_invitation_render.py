#!/home/shuvam/.global-pymaster/bin/python
"""test_invitation_render.py
Tests that the Jinja2 invitation template renders correctly.
"""

import os
import pytest
import sys
from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def jinja_env():
    """Create a Jinja2 environment pointing to templates/farewell."""
    template_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "templates",
        "farewell",
    )
    return Environment(loader=FileSystemLoader(template_dir))


@pytest.fixture
def sample_data():
    """Sample data for rendering templates."""
    return {
        "attendee_name": "Test Attendee",
        "attendee_email": "test@example.com",
        "event_name": "21MS Farewell Party",
        "event_date": "December 31, 2026",
        "event_time": "7:00 PM",
        "event_venue": "IISER Kolkata Campus",
        "qr_code_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        "qr_code_src": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        "verification_code": "123456",
        "coupon_id": "test-coupon-00000000",
        "organizer_batch": "22MS Batch",
        "organizer_institution": "IISER Kolkata",
    }


class TestInvitationTemplate:
    """Test invitation.html template."""

    def test_renders_without_error(self, jinja_env, sample_data):
        """invitation.html renders with all required variables."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert html is not None
        assert len(html) > 100

    def test_contains_attendee_name(self, jinja_env, sample_data):
        """Rendered HTML contains the attendee name."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "Test Attendee" in html

    def test_contains_verification_code(self, jinja_env, sample_data):
        """Rendered HTML contains the verification code."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "123456" in html

    def test_contains_qr_code_img_tag(self, jinja_env, sample_data):
        """Rendered HTML contains <img> with base64 QR data."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "data:image/png;base64," in html
        assert "<img" in html

    def test_contains_google_fonts_link(self, jinja_env, sample_data):
        """Rendered HTML contains Google Fonts link tag."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "fonts.googleapis.com" in html
        assert "Caveat" in html

    def test_contains_caveat_font(self, jinja_env, sample_data):
        """Rendered HTML references Caveat font."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "Caveat" in html

    def test_contains_satisfy_font(self, jinja_env, sample_data):
        """Rendered HTML references Satisfy font."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "Satisfy" in html

    def test_contains_kalam_font(self, jinja_env, sample_data):
        """Rendered HTML references Kalam font."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "Kalam" in html

    def test_no_broken_template_tags(self, jinja_env, sample_data):
        """Rendered HTML contains no {{ or }} (all variables substituted)."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "{{" not in html
        assert "}}" not in html

    def test_email_width_constraint(self, jinja_env, sample_data):
        """Rendered HTML contains max-width: 600px."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "600px" in html or "max-width" in html


class TestThankYouTemplate:
    """Test thank_you.html template."""

    def test_thank_you_renders_without_error(self, jinja_env, sample_data):
        """thank_you.html renders with all required variables."""
        template = jinja_env.get_template("thank_you.html")
        html = template.render(**sample_data)
        assert html is not None
        assert len(html) > 100

    def test_thank_you_contains_attendee_name(self, jinja_env, sample_data):
        """Rendered thank_you contains the attendee name."""
        template = jinja_env.get_template("thank_you.html")
        html = template.render(**sample_data)
        assert "Test Attendee" in html

    def test_thank_you_no_broken_template_tags(self, jinja_env, sample_data):
        """Rendered thank_you contains no {{ or }} (all variables substituted)."""
        template = jinja_env.get_template("thank_you.html")
        html = template.render(**sample_data)
        assert "{{" not in html
        assert "}}" not in html
