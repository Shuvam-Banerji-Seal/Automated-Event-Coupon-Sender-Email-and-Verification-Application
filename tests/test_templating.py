"""Tests for template rendering, variable discovery and email-HTML linting."""

import pytest

from src import templating as T


class TestRendering:
    def test_renders_variables(self):
        ctx = T.build_context(name="Ada Lovelace", email="ada@x.com",
                              verification_code="418206")
        html = T.render("Dear {{ first_name }}, code {{ verification_code }}", ctx)
        assert html == "Dear Ada, code 418206"

    def test_autoescapes_html_in_values(self):
        """A name from a CSV must not be able to inject markup into the email."""
        ctx = T.build_context(name="<script>alert(1)</script>", email="a@x.com")
        assert "<script>" not in T.render("{{ name }}", ctx)

    def test_syntax_error_is_readable(self):
        with pytest.raises(T.TemplateError) as exc:
            T.render("{% for x in %}", {})
        assert "Line 1" in str(exc.value)

    def test_subject_collapses_to_one_line(self):
        ctx = T.build_context(name="Ada", email="a@x.com")
        assert T.render_subject("Hello\n  {{ first_name }}  \n", ctx) == "Hello Ada"

    def test_subject_is_not_html_escaped(self):
        """Subjects are not HTML. An apostrophe must not arrive as "&#39;"."""
        ctx = T.build_context(name="Ada", email="a@x.com",
                              settings={"event_name": "Freshers' Welcome"})
        subject = T.render_subject("You're invited to {{ event_name }}", ctx)
        assert subject == "You're invited to Freshers' Welcome"
        assert "&#39;" not in subject

    def test_subject_still_blocks_header_injection(self):
        """Escaping is off, so collapsing newlines is what keeps headers safe."""
        subject = T.render_subject("A{{ x }}B", {"x": "\nBcc: evil@example.com"})
        assert "\n" not in subject and "\r" not in subject

    def test_html_body_is_still_escaped(self):
        """Turning off escaping for subjects must not affect the body."""
        ctx = T.build_context(name="<b>x</b>", email="a@x.com")
        assert "&lt;b&gt;" in T.render("<p>{{ name }}</p>", ctx)

    def test_sandbox_blocks_attribute_escape(self):
        """Templates are authored in the browser, so the sandbox is load-bearing."""
        with pytest.raises(T.TemplateError):
            T.render("{{ ''.__class__.__mro__ }}", {})

    def test_sandbox_blocks_config_access(self):
        with pytest.raises(T.TemplateError):
            T.render("{{ self.__init__.__globals__ }}", {})


class TestContext:
    def test_mapped_fields_win_over_csv_extras(self):
        """A sheet with its own 'email' column must not redirect the invitation."""
        ctx = T.build_context(
            name="Ada", email="real@x.com", extra={"email": "attacker@evil.com"}
        )
        assert ctx["email"] == "real@x.com"

    def test_food_colour_follows_preference(self):
        veg = T.build_context(food_preference="veg")
        non = T.build_context(food_preference="non-veg")
        assert veg["food_colour"] != non["food_colour"]
        assert veg["food_color"] == veg["food_colour"]

    def test_legacy_aliases_present(self):
        """Templates saved by the previous version use attendee_* names."""
        ctx = T.build_context(name="Ada", email="a@x.com")
        assert ctx["attendee_name"] == "Ada"
        assert ctx["attendee_email"] == "a@x.com"

    def test_qr_src_blank_when_no_pass_issued(self):
        assert T.build_context(include_qr=False, qr_code_src="cid:qrcode")["qr_code_src"] == ""

    def test_settings_do_not_clobber_recipient_fields(self):
        ctx = T.build_context(name="Ada", email="a@x.com",
                              settings={"name": "Event Name", "event_date": "15 May"})
        assert ctx["name"] == "Ada"
        assert ctx["event_date"] == "15 May"


class TestVariableDiscovery:
    def test_finds_used_variables(self):
        used = T.used_variables("{{ first_name }} {% if include_qr %}{{ code }}{% endif %}")
        assert set(used) == {"first_name", "include_qr", "code"}

    def test_catalogue_includes_csv_columns(self):
        groups = T.variable_catalogue(extra_columns=["roll_no", "department"])
        csv_group = [g for g in groups if g["group"] == "From your CSV"][0]
        assert {v["name"] for v in csv_group["variables"]} == {"roll_no", "department"}

    def test_catalogue_omits_csv_group_when_empty(self):
        assert all(g["group"] != "From your CSV" for g in T.variable_catalogue())

    def test_validate_warns_on_unknown_variable(self):
        result = T.validate("{{ first_name }} {{ typoo }}", ["first_name"])
        assert result["ok"] is True
        assert "typoo" in result["warnings"][0]

    def test_validate_reports_syntax_errors(self):
        result = T.validate("{% if %}", ["first_name"])
        assert result["ok"] is False
        assert result["errors"]


class TestEmailLint:
    def test_flags_inline_svg(self):
        """The failure that cost a whole send cycle on this project."""
        issues = T.lint_email_html("<svg><circle/></svg>")
        assert any(i["level"] == "error" and "svg" in i["message"].lower() for i in issues)

    def test_flags_script(self):
        assert any(i["level"] == "error" for i in T.lint_email_html("<script>x</script>"))

    def test_flags_flexbox(self):
        assert any("Flexbox" in i["message"] for i in T.lint_email_html(
            '<div style="display: flex">x</div>'))

    def test_flags_external_stylesheet(self):
        assert any("stylesheet" in i["message"] for i in T.lint_email_html(
            '<link rel="stylesheet" href="https://x/y.css">'))

    def test_flags_insecure_image(self):
        assert any("http" in i["message"] for i in T.lint_email_html(
            '<img src="http://x/y.png">'))

    def test_flags_gmail_clipping_size(self):
        assert any("102" in i["message"] or "clip" in i["message"].lower()
                   for i in T.lint_email_html("<p>" + "x" * 110_000 + "</p>"))

    def test_clean_html_passes(self):
        assert T.lint_email_html(
            '<table><tr><td style="color:#333">Hello</td></tr></table>') == []
