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
        "include_qr": True,
        "food_preference": "Vegetarian",
        "food_color": "#2d8a3e",
        "first_name": "Test",
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

    def test_contains_attendee_email(self, jinja_env, sample_data):
        """Rendered HTML contains the attendee email."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "test@example.com" in html

    def test_greeting_uses_first_name(self, jinja_env, sample_data):
        """Greeting uses the first name (Dear Test, not Dear Test Attendee)."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "Dear <span" in html
        assert ">Test</span>," in html  # first name inside the styled span
        assert ">Test Attendee</span>," not in html
        # full name still appears as HOLDER
        assert "Test Attendee" in html

    def test_contains_qr_code_img_tag(self, jinja_env, sample_data):
        """Rendered HTML contains the QR <img> with the provided src."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "data:image/png;base64," in html
        assert "<img" in html
        assert "Freshers Entry QR Coupon" in html

    def test_contains_food_preference(self, jinja_env, sample_data):
        """Rendered HTML contains the attendee's food preference and color."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "Vegetarian" in html
        assert "#2d8a3e" in html

    def test_nonveg_food_icon(self, jinja_env, sample_data):
        """Non-Vegetarian preference renders crimson color and inline SVG triangle icon."""
        data = dict(sample_data, food_preference="Non-Vegetarian", food_color="#DC143C")
        template = jinja_env.get_template("invitation.html")
        html = template.render(**data)
        assert "Non-Vegetarian" in html
        assert "#DC143C" in html
        # Non-veg icon is an inline SVG polygon (red triangle)
        assert '<polygon points="14,2 26,24 2,24" fill="#DC143C"/>' in html
        # Veg icon (green circle) should NOT be present
        assert '<circle cx="14" cy="14" r="12" fill="#2d8a3e"/>' not in html

    def test_veg_food_icon(self, jinja_env, sample_data):
        """Vegetarian preference renders inline SVG green circle icon (no triangle)."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert '<circle cx="14" cy="14" r="12" fill="#2d8a3e"/>' in html
        assert '<polygon points="14,2 26,24 2,24"' not in html

    def test_contains_food_token(self, jinja_env, sample_data):
        """The QR coupon heading is 'Your Food Token'."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "Your Food Token" in html
        assert "Your Reaction Token" not in html

    def test_element_tiles_present(self, jinja_env, sample_data):
        """The K (19th), W (Wednesday) and Be (4 PM) tiles are present."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "POTASSIUM" in html
        assert "TUNGSTEN" in html
        assert "BERYLLIUM" in html
        assert "19" in html
        assert "WED" in html
        assert "4 PM" in html

    def test_no_base64_decorative_images(self, jinja_env, sample_data):
        """No base64 data-URI PNGs for decorative elements (only QR img uses src)."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        # Decorative elements are inline SVGs, not base64 PNGs
        assert "data:image/png;base64," not in html.replace(
            sample_data["qr_code_src"], ""
        )
        # Inline SVGs ARE present (header, atom, food icons, molecule, hex pattern)
        assert "<svg" in html
        # No <filter> or radialGradient (the old blur elements)
        assert "<filter" not in html
        assert "radialGradient" not in html

    def test_no_schedule_section(self, jinja_env, sample_data):
        """The agenda/schedule section is removed."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "REACTION SCHEDULE" not in html
        assert "Registration & Kit Collection" not in html

    def test_no_fake_contact_email(self, jinja_env, sample_data):
        """The non-existent dcs-freshers contact email is removed."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "dcs-freshers@iiserkol.ac.in" not in html
        assert "Questions?" not in html

    def test_no_broken_template_tags(self, jinja_env, sample_data):
        """Rendered HTML contains no {{ or }} (all variables substituted)."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "{{" not in html
        assert "}}" not in html

    def test_email_width_constraint(self, jinja_env, sample_data):
        """Rendered HTML contains max-width: 640px container."""
        template = jinja_env.get_template("invitation.html")
        html = template.render(**sample_data)
        assert "640px" in html or "max-width" in html


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
        assert "Test" in html  # first_name used in greeting
        assert "test@example.com" in html
        assert "123456" in html  # verification code

    def test_thank_you_no_broken_template_tags(self, jinja_env, sample_data):
        """Rendered thank_you contains no {{ or }} (all variables substituted)."""
        template = jinja_env.get_template("thank_you.html")
        html = template.render(**sample_data)
        assert "{{" not in html
        assert "}}" not in html
