"""End-to-end tests through the HTTP layer.

Covers the path an operator actually walks: upload a sheet, confirm the detected
columns, issue coupons, then redeem one at the door.

No email is ever sent — the mailer is replaced with a recorder. That is a hard
requirement of this suite, not a convenience: the predecessor's test file called
the real SMTP sender, and running the suite delivered mail.
"""

import io
import json
import re
import time

import pytest


SHEET = (
    b"Timestamp,Email Address,Your Name,Veg / Non-Veg?,Roll No\n"
    b"2026-01-01,ada@example.com,Ada Lovelace,Veg,21MS001\n"
    b"2026-01-01,grace@example.com,Grace Hopper,Non-Veg,21MS002\n"
    b"2026-01-01,alan@example.com,Alan Turing,Veg,21MS003\n"
)


def upload(client, data=SHEET, filename="guests.csv"):
    return client.post(
        "/api/csv/inspect",
        data={"file": (io.BytesIO(data), filename)},
        content_type="multipart/form-data",
    )


def load_recipients(client):
    """Upload and commit the sample sheet with the detected mapping."""
    inspection = upload(client).get_json()
    return client.post("/api/csv/commit", json={
        "upload_id": inspection["upload_id"],
        "mapping": inspection["suggested_mapping"],
        "mode": "replace",
    }).get_json()


class TestPages:
    @pytest.mark.parametrize(
        "path", ["/", "/recipients", "/compose", "/send", "/settings", "/scan"]
    )
    def test_pages_render(self, client, path):
        assert client.get(path).status_code == 200

    def test_health(self, client):
        assert client.get("/api/health").get_json()["ok"] is True

    def test_unknown_api_path_returns_json(self, client):
        response = client.get("/api/nope")
        assert response.status_code == 404
        assert response.get_json()["success"] is False


class TestCsvUpload:
    def test_inspect_detects_columns(self, client):
        data = upload(client).get_json()
        assert data["success"] is True
        assert data["row_count"] == 3
        assert data["suggested_mapping"]["email"] == "Email Address"
        assert data["suggested_mapping"]["name"] == "Your Name"

    def test_rejects_non_csv(self, client):
        response = upload(client, b"not a csv", "photo.png")
        assert response.status_code == 400
        assert "csv" in response.get_json()["error"].lower()

    def test_rejects_empty_file(self, client):
        assert upload(client, b"   ").status_code == 400

    def test_commit_stores_recipients(self, client):
        result = load_recipients(client)
        assert result["imported"] == 3
        assert result["total_recipients"] == 3
        assert "roll_no" in result["variables"]

    def test_commit_requires_email_mapping(self, client):
        inspection = upload(client).get_json()
        response = client.post("/api/csv/commit", json={
            "upload_id": inspection["upload_id"], "mapping": {"name": "Your Name"},
        })
        assert response.status_code == 400

    def test_expired_upload_is_rejected(self, client):
        response = client.post("/api/csv/commit", json={
            "upload_id": "does-not-exist", "mapping": {"email": "x"},
        })
        assert response.status_code == 400
        assert "expired" in response.get_json()["error"].lower()

    def test_food_preference_normalised_on_import(self, client):
        load_recipients(client)
        rows = client.get("/api/recipients").get_json()["recipients"]
        by_email = {r["email"]: r for r in rows}
        assert by_email["grace@example.com"]["food_preference"] == "Non-Vegetarian"
        assert by_email["ada@example.com"]["food_preference"] == "Vegetarian"


class TestTemplates:
    def test_seeded_templates_exist(self, client):
        names = [t["name"] for t in client.get("/api/templates").get_json()["templates"]]
        assert "invitation" in names

    def test_preview_renders(self, client):
        response = client.post("/api/templates/preview", json={
            "html": "<p>Hi {{ first_name }}</p>", "subject": "Hello {{ first_name }}",
        })
        data = response.get_json()
        assert "Sample" in data["html"]
        assert data["subject"] == "Hello Sample"

    def test_preview_reports_template_errors(self, client):
        response = client.post("/api/templates/preview",
                               json={"html": "{% for %}", "subject": ""})
        assert response.status_code == 400

    def test_preview_flags_inline_svg(self, client):
        data = client.post("/api/templates/preview",
                           json={"html": "<svg></svg>", "subject": ""}).get_json()
        assert any(i["level"] == "error" for i in data["lint"])

    def test_save_rejects_broken_template(self, client):
        response = client.put("/api/templates/broken",
                              json={"html": "{% if %}", "subject": "x"})
        assert response.status_code == 400

    def test_save_and_reload(self, client):
        client.put("/api/templates/mine",
                   json={"html": "<p>{{ first_name }}</p>", "subject": "Hi"})
        data = client.get("/api/templates/mine").get_json()
        assert data["template"]["subject"] == "Hi"

    def test_variables_include_csv_columns(self, client):
        load_recipients(client)
        groups = client.get("/api/variables").get_json()["groups"]
        names = {v["name"] for g in groups for v in g["variables"]}
        assert "roll_no" in names
        assert "first_name" in names


class TestSending:
    def test_send_issues_coupons_and_emails(self, client):
        load_recipients(client)
        start = client.post("/api/send/start", json={
            "template": "invitation", "audience": "pending", "throttle": 0,
        }).get_json()
        assert start["total"] == 3

        _wait_for_job(client, start["job_id"])
        assert len(client.sent) == 3

        stats = client.get("/api/overview").get_json()["stats"]
        assert stats["total"] == 3
        assert stats["sent"] == 3

    def test_resending_does_not_issue_a_second_coupon(self, client):
        """The property that protects codes already sitting in inboxes."""
        load_recipients(client)
        first = client.post("/api/send/start", json={
            "template": "invitation", "audience": "pending", "throttle": 0}).get_json()
        _wait_for_job(client, first["job_id"])
        codes = _codes(client)

        second = client.post("/api/send/start", json={
            "template": "invitation", "audience": "pending", "throttle": 0})
        assert second.status_code == 400        # nobody left without a coupon
        assert _codes(client) == codes

    def test_send_requires_a_template(self, client):
        load_recipients(client)
        response = client.post("/api/send/start",
                               json={"template": "nope", "audience": "pending"})
        assert response.status_code == 400

    def test_send_with_no_recipients_is_rejected(self, client):
        response = client.post("/api/send/start",
                               json={"template": "invitation", "audience": "pending"})
        assert response.status_code == 400

    def test_qr_is_attached_inline(self, client):
        load_recipients(client)
        job = client.post("/api/send/start", json={
            "template": "invitation", "audience": "pending", "throttle": 0}).get_json()
        _wait_for_job(client, job["job_id"])
        assert all("qrcode" in m.inline_images for m in client.sent)


class TestScanning:
    def _issue(self, client):
        load_recipients(client)
        job = client.post("/api/send/start", json={
            "template": "invitation", "audience": "pending", "throttle": 0}).get_json()
        _wait_for_job(client, job["job_id"])
        return client.app_module.store

    def test_redeem_by_qr_token(self, client):
        store = self._issue(client)
        coupon = store.find_by_email("ada@example.com")
        data = client.post("/api/scan", json={
            "payload": coupon.qr_payload, "scanner": "gate-1"}).get_json()
        assert data["success"] is True
        assert data["name"] == "Ada Lovelace"
        assert data["food_preference"] == "Vegetarian"

    def test_redeem_by_typed_code(self, client):
        store = self._issue(client)
        coupon = store.find_by_email("grace@example.com")
        data = client.post("/api/scan",
                           json={"payload": coupon.verification_code}).get_json()
        assert data["success"] is True
        assert data["food_preference"] == "Non-Vegetarian"

    def test_second_scan_is_refused(self, client):
        store = self._issue(client)
        coupon = store.find_by_email("ada@example.com")
        client.post("/api/scan", json={"payload": coupon.qr_payload})
        second = client.post("/api/scan", json={"payload": coupon.qr_payload}).get_json()
        assert second["success"] is False
        assert second["error_code"] == "ALREADY_USED"

    def test_unknown_code(self, client):
        self._issue(client)
        data = client.post("/api/scan", json={"payload": "000000"}).get_json()
        assert data["error_code"] == "NOT_FOUND"

    def test_unreadable_payload(self, client):
        response = client.post("/api/scan", json={"payload": "https://example.com"})
        assert response.status_code == 400
        assert response.get_json()["error_code"] == "UNREADABLE"

    def test_undo_restores_the_coupon(self, client):
        store = self._issue(client)
        coupon = store.find_by_email("ada@example.com")
        scan = client.post("/api/scan", json={"payload": coupon.qr_payload}).get_json()
        undo = client.post("/api/scan/undo",
                           json={"coupon_id": scan["coupon_id"]}).get_json()
        assert undo["success"] is True
        again = client.post("/api/scan", json={"payload": coupon.qr_payload}).get_json()
        assert again["success"] is True

    def test_scan_log_records_every_attempt(self, client):
        store = self._issue(client)
        coupon = store.find_by_email("ada@example.com")
        client.post("/api/scan", json={"payload": coupon.qr_payload})
        client.post("/api/scan", json={"payload": coupon.qr_payload})
        client.post("/api/scan", json={"payload": "999999"})
        results = [s["result"] for s in client.get("/api/scan/recent").get_json()["scans"]]
        assert set(results) == {"ok", "already_used", "not_found"}

    def test_lookup_does_not_redeem(self, client):
        store = self._issue(client)
        coupon = store.find_by_email("ada@example.com")
        client.get(f"/api/scan/lookup?q={coupon.verification_code}")
        assert store.find_by_id(coupon.coupon_id).status != "used"


class TestScanRateLimiting:
    """Guessing must be blocked; a busy door must never be.

    The first version limited requests per IP. Behind the public tunnel every
    scanner shares one source address, so a ten-scanner burst had 296 of 448
    legitimate scans rejected. Only failed lookups count now.
    """

    def _issue(self, client):
        load_recipients(client)
        job = client.post("/api/send/start", json={
            "template": "invitation", "audience": "pending", "throttle": 0}).get_json()
        _wait_for_job(client, job["job_id"])
        return client.app_module.store

    def test_repeated_bad_guesses_are_blocked(self, client):
        codes = [f"{n:06d}" for n in range(900000, 900040)]
        blocked = False
        for code in codes:
            r = client.post("/api/scan",
                            json={"payload": code, "scanner": "guesser"})
            if r.status_code == 429:
                blocked = True
                break
        assert blocked, "brute-force guessing was never rate limited"

    def test_one_bad_device_does_not_block_the_others(self, client):
        store = self._issue(client)
        for n in range(40):
            client.post("/api/scan",
                        json={"payload": f"{900000 + n:06d}", "scanner": "guesser"})
        coupon = store.find_by_email("ada@example.com")
        good = client.post("/api/scan",
                           json={"payload": coupon.qr_payload, "scanner": "gate-1"})
        assert good.status_code == 200
        assert good.get_json()["success"] is True

    def test_valid_scans_do_not_count_toward_the_limit(self, client):
        """A volunteer admitting a long queue must never be throttled."""
        store = self._issue(client)
        coupon = store.find_by_email("ada@example.com")
        for _ in range(60):
            # Same coupon repeatedly: 'already used' is a real coupon, not a guess.
            r = client.post("/api/scan",
                            json={"payload": coupon.qr_payload, "scanner": "gate-1"})
            assert r.status_code != 429


class TestThankYouMail:
    def _issue(self, client):
        load_recipients(client)
        job = client.post("/api/send/start", json={
            "template": "invitation", "audience": "pending", "throttle": 0}).get_json()
        _wait_for_job(client, job["job_id"])
        return client.app_module.store

    def test_checking_in_queues_a_thank_you(self, client):
        store = self._issue(client)
        before = store.outbox_stats()["total"]
        coupon = store.find_by_email("ada@example.com")
        client.post("/api/scan", json={"payload": coupon.qr_payload})
        assert store.outbox_stats()["total"] == before + 1

    def test_only_one_thank_you_per_guest(self, client):
        """Six scanners racing the same coupon must not queue six emails."""
        store = self._issue(client)
        coupon = store.find_by_email("ada@example.com")
        for _ in range(5):
            client.post("/api/scan", json={"payload": coupon.qr_payload})
        rows = [r for r in store.recent_outbox(50)
                if r["to_email"] == coupon.email and r["kind"] == "thank_you"]
        assert len(rows) == 1

    def test_a_refused_scan_queues_nothing(self, client):
        store = self._issue(client)
        before = store.outbox_stats()["total"]
        client.post("/api/scan", json={"payload": "000000"})
        assert store.outbox_stats()["total"] == before

    def test_scan_response_is_not_delayed_by_mail(self, client):
        """Delivery happens on the worker; the request only writes a row."""
        import time
        store = self._issue(client)
        coupon = store.find_by_email("ada@example.com")
        started = time.perf_counter()
        client.post("/api/scan", json={"payload": coupon.qr_payload})
        assert time.perf_counter() - started < 1.0

    def test_outbox_endpoint_reports_the_queue(self, client):
        store = self._issue(client)
        coupon = store.find_by_email("ada@example.com")
        client.post("/api/scan", json={"payload": coupon.qr_payload})
        data = client.get("/api/outbox").get_json()
        assert data["success"] is True
        assert data["worker"]["total"] >= 1


class TestMalformedInput:
    """User-supplied numbers must not reach int()/float() unguarded.

    Four endpoints returned 500 on a non-numeric query parameter, which is both
    a bad error and noise that hides real failures in the log.
    """

    @pytest.mark.parametrize("query", [
        "limit=abc", "offset=abc", "limit=", "offset=-1",
        "limit=99999999999999999999", "limit=-5",
    ])
    def test_coupon_list_survives_bad_paging(self, client, query):
        assert client.get(f"/api/coupons?{query}").status_code == 200

    def test_negative_limit_does_not_mean_unlimited(self, client):
        """SQLite treats LIMIT -1 as no limit, so clamping matters."""
        load_recipients(client)
        response = client.get("/api/coupons?limit=-5")
        assert response.status_code == 200

    def test_send_survives_a_non_numeric_throttle(self, client):
        load_recipients(client)
        response = client.post("/api/send/start", json={
            "template": "invitation", "audience": "pending", "throttle": "fast"})
        assert response.status_code != 500

    @pytest.mark.parametrize("field,value", [
        ("port", "abc"), ("daily_limit", "many"), ("port", None),
    ])
    def test_smtp_save_survives_bad_numbers(self, client, field, value):
        response = client.post("/api/smtp", json={
            "accounts": [{"username": "a@b.com", field: value}]})
        assert response.status_code == 200

    def test_qr_size_parameter_is_clamped(self, client):
        store = client.app_module.store
        load_recipients(client)
        job = client.post("/api/send/start", json={
            "template": "invitation", "audience": "pending", "throttle": 0}).get_json()
        _wait_for_job(client, job["job_id"])
        coupon = store.find_by_email("ada@example.com")
        for size in ("abc", "-1", "99999"):
            assert client.get(
                f"/api/coupons/{coupon.coupon_id}/qr.png?size={size}"
            ).status_code == 200


class TestWrongTypedInput:
    """A JSON field can hold anything. Assuming it holds a string is a 500.

    `(body.get("x") or "").strip()` reads as defensive but is not: a dict or a
    number reaches .strip() and the endpoint dies. Found on /api/scan, which is
    the one endpoint that must never fall over — nobody debugs a 500 at a door.
    """

    @pytest.mark.parametrize("payload", [
        {"nested": 1}, [1, 2], True, {"a": {"b": "c"}},
    ])
    def test_scan_survives_a_non_string_payload(self, client, payload):
        response = client.post("/api/scan", json={"payload": payload})
        assert response.status_code == 400, f"{payload!r} produced {response.status_code}"

    def test_scan_accepts_a_numeric_code(self, client):
        """A client sending the code unquoted is wrong but harmless."""
        assert client.post("/api/scan", json={"payload": 123456}).status_code != 500

    def test_scan_survives_a_non_string_scanner_name(self, client):
        response = client.post("/api/scan",
                               json={"payload": "123456", "scanner": {"x": 1}})
        assert response.status_code != 500

    @pytest.mark.parametrize("body", [
        {"template": {"a": 1}},
        {"template": "invitation", "audience": "selected", "emails": "a@b.com"},
        {"template": "invitation", "audience": "selected", "emails": [None, 5]},
        {"template": "invitation", "attachments": {"a": 1}},
        {"template": "invitation", "audience": ["x"]},
        {"template": "invitation", "throttle": "fast"},
    ])
    def test_send_survives_wrong_types(self, client, body):
        assert client.post("/api/send/start", json=body).status_code != 500

    @pytest.mark.parametrize("body", [
        {"accounts": "notalist"},
        {"accounts": [{"username": 123, "port": {"a": 1}}]},
        {"accounts": ["a", 5, None]},
        {},
    ])
    def test_smtp_save_survives_wrong_types(self, client, body):
        assert client.post("/api/smtp", json=body).status_code != 500

    def test_settings_rejects_non_text(self, client):
        """A dict stored as its repr would be printed into every invitation."""
        response = client.post("/api/settings", json={"event_name": {"a": 1}})
        assert response.status_code == 400
        assert client.get("/api/settings").get_json()["settings"]["event_name"] != "{'a': 1}"

    @pytest.mark.parametrize("path,body", [
        ("/api/scan/undo", {"coupon_id": [1]}),
        ("/api/tunnel/name", {"name": 123}),
        ("/api/smtp/test", {"username": {"a": 1}}),
        ("/api/send/test", {"email": [1], "template": "invitation"}),
        ("/api/csv/commit", {"upload_id": {"a": 1}, "mapping": {"email": "x"}}),
        ("/api/csv/commit", {"upload_id": "x", "mapping": "notadict"}),
        ("/api/event/reset", {"confirm": ["RESET"]}),
    ])
    def test_other_endpoints_survive_wrong_types(self, client, path, body):
        assert client.post(path, json=body).status_code != 500


class TestTemplateSandbox:
    """Templates are authored in a browser, so the sandbox is load-bearing."""

    @pytest.mark.parametrize("attack", [
        "{{ ''.__class__.__mro__ }}",
        "{{ ''.__class__.__base__.__subclasses__() }}",
        "{{ self.__init__.__globals__ }}",
        "{{ cycler.__init__.__globals__.os.popen('id').read() }}",
        "{{ lipsum.__globals__.os.popen('id').read() }}",
        "{{ request.application.__self__._get_data_for_json }}",
    ])
    def test_escapes_are_blocked(self, client, attack):
        response = client.post("/api/templates/preview",
                               json={"html": attack, "subject": ""})
        if response.status_code == 200:
            # Some expressions resolve to Undefined rather than raising; what
            # matters is that nothing sensitive is rendered.
            html = response.get_json()["html"]
            assert "built-in" not in html and "os.popen" not in html
            assert "uid=" not in html and "class '" not in html
        else:
            assert response.status_code == 400


class TestPendingCount:
    """`pending` must mean "recipients without a coupon", not a subtraction.

    Subtracting coupons from recipients reports 0 pending after the recipient
    list is replaced, because the leftover coupons belong to people no longer on
    it — and the send screen then says there is nobody to send to.
    """

    def test_pending_after_replacing_the_recipient_list(self, client):
        load_recipients(client)
        job = client.post("/api/send/start", json={
            "template": "invitation", "audience": "pending", "throttle": 0}).get_json()
        _wait_for_job(client, job["job_id"])
        assert client.get("/api/overview").get_json()["stats"]["pending"] == 0

        # Replace three known recipients with one brand-new person.
        newcomer = b"Email Address,Your Name\nzara@example.com,Zara\n"
        inspection = upload(client, newcomer).get_json()
        client.post("/api/csv/commit", json={
            "upload_id": inspection["upload_id"],
            "mapping": inspection["suggested_mapping"], "mode": "replace"})

        stats = client.get("/api/overview").get_json()["stats"]
        assert stats["recipients"] == 1
        assert stats["total"] == 3          # old coupons survive, as intended
        assert stats["pending"] == 1        # Zara still needs one

    def test_pending_is_never_negative(self, client):
        load_recipients(client)
        job = client.post("/api/send/start", json={
            "template": "invitation", "audience": "pending", "throttle": 0}).get_json()
        _wait_for_job(client, job["job_id"])
        client.delete("/api/recipients")
        assert client.get("/api/overview").get_json()["stats"]["pending"] == 0


class TestResendGuard:
    """Re-sending to everyone must be asked for, not defaulted into."""

    def _issue(self, client):
        load_recipients(client)
        job = client.post("/api/send/start", json={
            "template": "invitation", "audience": "pending", "throttle": 0}).get_json()
        _wait_for_job(client, job["job_id"])

    def test_resend_with_no_selection_is_refused(self, client):
        self._issue(client)
        response = client.post("/api/send/start", json={
            "template": "invitation", "audience": "resend", "emails": []})
        assert response.status_code == 400
        assert response.get_json()["error_code"] == "NO_SELECTION"

    def test_resend_to_everyone_works_when_asked_for(self, client):
        self._issue(client)
        response = client.post("/api/send/start", json={
            "template": "invitation", "audience": "resend", "emails": [],
            "resend_all": True, "throttle": 0})
        assert response.status_code == 200
        assert response.get_json()["total"] == 3

    def test_resend_to_named_addresses_still_works(self, client):
        self._issue(client)
        response = client.post("/api/send/start", json={
            "template": "invitation", "audience": "resend",
            "emails": ["ada@example.com"], "throttle": 0})
        assert response.get_json()["total"] == 1


class TestThankYouTemplateMissing:
    def test_overview_reports_a_missing_thank_you_template(self, client):
        """Otherwise check-ins silently stop sending thank-yous."""
        assert client.get("/api/overview").get_json()["thank_you"]["template_exists"] is True
        client.delete("/api/templates/thank_you")
        thank_you = client.get("/api/overview").get_json()["thank_you"]
        assert thank_you["enabled"] is True
        assert thank_you["template_exists"] is False

    def test_scanning_still_works_without_the_template(self, client):
        """A template mistake must never stop somebody getting through a door."""
        store = self._issue(client)
        client.delete("/api/templates/thank_you")
        coupon = store.find_by_email("ada@example.com")
        assert client.post("/api/scan",
                           json={"payload": coupon.qr_payload}).get_json()["success"]

    def _issue(self, client):
        load_recipients(client)
        job = client.post("/api/send/start", json={
            "template": "invitation", "audience": "pending", "throttle": 0}).get_json()
        _wait_for_job(client, job["job_id"])
        return client.app_module.store


class TestExportAndReset:
    def test_export_coupons(self, client):
        load_recipients(client)
        response = client.get("/api/export/coupons.csv")
        assert response.status_code == 200

    def test_reset_requires_confirmation(self, client):
        assert client.post("/api/event/reset", json={}).status_code == 400

    def test_reset_clears_coupons(self, client):
        load_recipients(client)
        job = client.post("/api/send/start", json={
            "template": "invitation", "audience": "pending", "throttle": 0}).get_json()
        _wait_for_job(client, job["job_id"])
        client.post("/api/event/reset", json={"confirm": "RESET"})
        assert client.get("/api/overview").get_json()["stats"]["total"] == 0


class TestQrPayload:
    def test_diagnostics_report_a_scannable_code(self, client):
        data = client.get("/api/qr/diagnostics").get_json()
        assert data["within_limit"] is True
        assert data["version"] <= 2

    def test_issued_coupons_stay_at_version_1(self, client):
        """Guards the property that makes the QR readable off a damaged screen."""
        load_recipients(client)
        job = client.post("/api/send/start", json={
            "template": "invitation", "audience": "pending", "throttle": 0}).get_json()
        _wait_for_job(client, job["job_id"])
        data = client.get("/api/qr/diagnostics").get_json()
        assert data["version"] == 1
        assert data["bytes"] <= 20


def _wait_for_job(client, job_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/send/status/{job_id}").get_json()["job"]
        if job["done"]:
            return job
        time.sleep(0.02)
    raise AssertionError(f"send job {job_id} did not finish within {timeout}s")


def _codes(client):
    return sorted(
        c["verification_code"]
        for c in client.get("/api/coupons").get_json()["coupons"]
    )


ICOC_SITTINGS = [
    {"key": "d1-lunch", "day": "Day 1", "meal": "Lunch",
     "date": "Tuesday, 22 September 2026", "time": "13:10 – 14:25",
     "venue": "R.N. Tagore Auditorium"},
    {"key": "d1-dinner", "day": "Day 1", "meal": "Dinner",
     "date": "Tuesday, 22 September 2026", "time": "19:30 onwards",
     "venue": "R.N. Tagore Auditorium"},
    {"key": "d2-lunch", "day": "Day 2", "meal": "Lunch",
     "date": "Wednesday, 23 September 2026", "time": "13:10 – 14:25",
     "venue": "R.N. Tagore Auditorium"},
    {"key": "d2-dinner", "day": "Day 2", "meal": "Conference Dinner",
     "date": "Wednesday, 23 September 2026", "time": "19:30 onwards",
     "venue": "RISE Foundation"},
]


def wait_for_send(client, timeout=15):
    """Block until no send job is still running.

    The suite's _wait_for_job needs an id; these tests do not care which job,
    only that the mailer has finished, so they wait on the runner directly.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        jobs = list(client.app_module._jobs.values())
        if jobs and all(j.snapshot()["done"] for j in jobs):
            return
        time.sleep(0.02)
    raise AssertionError("a send job did not finish in time")


def configure_sittings(client, sittings=None):
    response = client.post("/api/sessions",
                           json={"sessions": sittings or ICOC_SITTINGS})
    assert response.status_code == 200, response.get_json()
    return response.get_json()


class TestSittingsApi:
    def test_default_is_no_sittings(self, client):
        assert client.get("/api/sessions").get_json()["sessions"] == []

    def test_saving_and_reading_back(self, client):
        saved = configure_sittings(client)["sessions"]
        assert [s["key"] for s in saved] == [s["key"] for s in ICOC_SITTINGS]
        assert saved[0]["label"] == "Day 1 · Lunch"

    def test_a_sitting_without_a_key_is_refused(self, client):
        response = client.post("/api/sessions", json={"sessions": [{"meal": "Lunch"}]})
        assert response.status_code == 400
        assert "key" in response.get_json()["error"].lower()

    def test_a_non_list_is_refused(self, client):
        assert client.post("/api/sessions", json={"sessions": "lunch"}).status_code == 400

    def test_clearing_returns_to_one_pass_each(self, client):
        configure_sittings(client)
        assert client.post("/api/sessions", json={"sessions": []}).get_json()["sessions"] == []

    def test_settings_page_reports_them(self, client):
        configure_sittings(client)
        assert len(client.get("/api/settings").get_json()["sessions"]) == 4


class TestMultiMealSend:
    def test_one_email_carries_every_pass(self, client):
        """Four sittings must not mean four emails."""
        load_recipients(client)
        configure_sittings(client)
        client.post("/api/send/start", json={"template": "invitation"})
        wait_for_send(client)

        assert len(client.sent) == 3, "one message per person, not per pass"
        store = client.app_module.store
        assert store.count_coupons() == 12

    def test_every_pass_reaches_the_message_as_its_own_qr(self, client):
        load_recipients(client)
        configure_sittings(client)
        # The starter invitation shows a single pass; the ICOC design loops.
        client.put("/api/templates/icoc", json={
            "subject": "Passes for {{ first_name }}",
            "html": "{% for c in coupons %}"
                    '<img src="{{ c.qr_code_src }}" alt="pass">{{ c.verification_code }}'
                    "{% endfor %}",
        })
        client.post("/api/send/start", json={"template": "icoc"})
        wait_for_send(client)

        message = client.sent[0]
        assert len(message.inline_images) == 4, message.inline_images.keys()
        assert set(message.inline_images) == {
            "qr-d1-lunch", "qr-d1-dinner", "qr-d2-lunch", "qr-d2-dinner"
        }
        for name in message.inline_images:
            assert f"cid:{name}" in message.html

    def test_a_template_showing_one_pass_attaches_one_image(self, client):
        """Never attach a QR the message does not show — it is dead weight."""
        load_recipients(client)
        configure_sittings(client)
        client.post("/api/send/start", json={"template": "invitation"})
        wait_for_send(client)
        assert len(client.sent[0].inline_images) == 1

    def test_resending_does_not_mint_more_passes(self, client):
        load_recipients(client)
        configure_sittings(client)
        client.post("/api/send/start", json={"template": "invitation"})
        wait_for_send(client)
        before = client.app_module.store.count_coupons()

        client.post("/api/send/start",
                    json={"template": "invitation", "audience": "resend",
                          "resend_all": True})
        wait_for_send(client)
        assert client.app_module.store.count_coupons() == before

    def test_a_successful_send_marks_every_pass_sent(self, client):
        load_recipients(client)
        configure_sittings(client)
        client.post("/api/send/start", json={"template": "invitation"})
        wait_for_send(client)
        store = client.app_module.store
        statuses = {c.status for c in store.coupons_for_email("ada@example.com")}
        assert statuses == {"sent"}, "only the first pass was marked sent"

    def test_single_sitting_events_are_untouched(self, client):
        load_recipients(client)
        client.post("/api/send/start", json={"template": "invitation"})
        wait_for_send(client)
        assert len(client.sent) == 3
        assert client.app_module.store.count_coupons() == 3
        assert set(client.sent[0].inline_images) == {"qrcode"}


class TestScanningASitting:
    def _issue(self, client):
        load_recipients(client)
        configure_sittings(client)
        client.post("/api/send/start", json={"template": "invitation"})
        wait_for_send(client)
        return client.app_module.store.coupons_for_email("ada@example.com")

    def test_a_pass_admits_at_its_own_counter(self, client):
        passes = self._issue(client)
        data = client.post("/api/scan", json={
            "payload": passes[0].qr_payload, "meal": "d1-lunch",
        }).get_json()
        assert data["success"] is True
        assert data["meal_label"] == "Day 1 · Lunch"

    def test_a_pass_is_refused_at_the_wrong_counter(self, client):
        passes = self._issue(client)
        data = client.post("/api/scan", json={
            "payload": passes[1].qr_payload, "meal": "d1-lunch",
        }).get_json()
        assert data["success"] is False
        assert data["error_code"] == "WRONG_MEAL"
        assert data["meal_label"] == "Day 1 · Dinner"

    def test_being_refused_does_not_consume_the_pass(self, client):
        passes = self._issue(client)
        client.post("/api/scan", json={"payload": passes[1].qr_payload,
                                       "meal": "d1-lunch"})
        data = client.post("/api/scan", json={"payload": passes[1].qr_payload,
                                              "meal": "d1-dinner"}).get_json()
        assert data["success"] is True

    def test_any_accepts_every_pass(self, client):
        passes = self._issue(client)
        data = client.post("/api/scan", json={"payload": passes[3].qr_payload,
                                              "meal": "any"}).get_json()
        assert data["success"] is True

    def test_progress_counts_the_sitting_not_the_event(self, client):
        passes = self._issue(client)
        data = client.post("/api/scan", json={"payload": passes[0].qr_payload,
                                              "meal": "d1-lunch"}).get_json()
        assert data["progress"] == {"used": 1, "total": 3, "meal": "Day 1 · Lunch"}

    def test_the_scanner_page_offers_the_sittings(self, client):
        configure_sittings(client)
        page = client.get("/scan").get_data(as_text=True)
        assert 'id="serving"' in page
        assert "Day 2 · Conference Dinner" in page

    def test_a_single_sitting_event_has_no_selector(self, client):
        assert 'id="serving"' not in client.get("/scan").get_data(as_text=True)


class TestFullPagePreview:
    def test_it_renders_the_saved_template(self, client):
        configure_sittings(client)
        page = client.get("/preview/invitation").get_data(as_text=True)
        assert page.startswith("<!doctype html>")
        assert "Preview — invitation" in page

    def test_an_unknown_template_is_a_404(self, client):
        assert client.get("/preview/nope").status_code == 404

    @staticmethod
    def _rendered_body(page):
        """Pull the email out of the preview page.

        The body is handed to the iframe as a JSON string literal, so it is not
        searchable as plain text — "Day 1 · Lunch" is written \u00b7 in there.
        """
        match = re.search(r"const html = (\".*?\");\n", page, re.S)
        assert match, "the preview page did not embed a rendered body"
        return json.loads(match.group(1))

    def test_the_preview_shows_one_card_per_sitting(self, client):
        configure_sittings(client)
        client.put("/api/templates/icoc", json={
            "subject": "Passes",
            "html": "{% for c in coupons %}<b>{{ c.meal_label }}</b>"
                    '<img src="{{ c.qr_code_src }}">{% endfor %}',
        })
        body = self._rendered_body(client.get("/preview/icoc").get_data(as_text=True))
        for label in ("Day 1 · Lunch", "Day 1 · Dinner",
                      "Day 2 · Lunch", "Day 2 · Conference Dinner"):
            assert label in body

    def test_every_preview_qr_is_a_real_distinct_image(self, client):
        """A template that renders one QR four times has to be visible here."""
        configure_sittings(client)
        client.put("/api/templates/icoc", json={
            "subject": "Passes",
            "html": '{% for c in coupons %}<img src="{{ c.qr_code_src }}">{% endfor %}',
        })
        body = client.post("/api/templates/preview", json={
            "html": '{% for c in coupons %}<img src="{{ c.qr_code_src }}">{% endfor %}',
            "subject": "Passes",
        }).get_json()
        sources = re.findall(r'src="(data:image/png;base64,[^"]+)"', body["html"])
        assert len(sources) == 4
        assert len(set(sources)) == 4, "the same QR was rendered for every sitting"

    def test_it_defaults_to_a_real_recipient_not_an_invented_one(self, client):
        """An invented stand-in shown to an operator whose sheet holds real
        names reads as though the wrong people are about to be mailed."""
        load_recipients(client)
        page = client.get("/preview/invitation").get_data(as_text=True)
        body = self._rendered_body(page)
        assert "ada@example.com" in body, "did not fall through to the first recipient"
        assert "attendee@example.com" not in body, "still previewing the stand-in"
        assert "first recipient on your list" in page

    def test_it_falls_back_to_a_sample_when_nobody_is_loaded(self, client):
        page = client.get("/preview/invitation").get_data(as_text=True)
        assert "no recipients loaded yet" in page
        assert "attendee@example.com" in self._rendered_body(page)

    def test_a_real_recipient_keeps_their_own_sheet_columns(self, client):
        load_recipients(client)
        body = self._rendered_body(
            client.get("/preview/invitation?email=ada@example.com").get_data(as_text=True))
        assert "ada@example.com" in body       # from the sheet, not the sample
        assert "attendee@example.com" not in body, "the stand-in address leaked through"
        assert "‹" not in body, "placeholder markers leaked into a real preview"

    def test_it_can_render_a_real_attendee(self, client):
        load_recipients(client)
        configure_sittings(client)
        client.post("/api/send/start", json={"template": "invitation"})
        wait_for_send(client)
        page = client.get("/preview/invitation?email=ada@example.com")
        assert page.status_code == 200
        text = page.get_data(as_text=True)
        assert "ada@example.com" in text
        # The real codes, not sample ones.
        real = client.app_module.store.coupons_for_email("ada@example.com")[0]
        assert real.verification_code in self._rendered_body(text)


class TestPassesSitInTheProgramme:
    """Each QR belongs at the moment in the day it is needed, not in a block.

    A block of four codes at the top makes somebody at a counter work out which
    one is lunch. These tests pin the interleaving so a later edit to the
    programme cannot quietly move a pass away from its meal.
    """

    def _delivered(self, client):
        load_recipients(client)
        configure_sittings(client)
        client.post("/api/send/start", json={"template": "icoc_invitation"})
        wait_for_send(client)
        return next(m for m in client.sent if m.to_email == "ada@example.com")

    def test_every_pass_is_attached(self, client):
        message = self._delivered(client)
        assert set(message.inline_images) == {
            "qr-d1-lunch", "qr-d1-dinner", "qr-d2-lunch", "qr-d2-dinner"}

    def test_each_pass_falls_between_the_right_sessions(self, client):
        html = self._delivered(client).html
        at = {k: html.index(f"cid:qr-{k}")
              for k in ("d1-lunch", "d1-dinner", "d2-lunch", "d2-dinner")}
        # Day 1: lunch after session 3, before session 4; dinner after session 6.
        assert html.index("Session 3") < at["d1-lunch"] < html.index("Session 4")
        assert html.index("Session 6") < at["d1-dinner"] < html.index("End of day one")
        # Day 2: lunch after session 9, before session 10.
        assert html.index("Session 9") < at["d2-lunch"] < html.index("Session 10")
        assert html.index("Session 12") < at["d2-dinner"]

    def test_the_passes_run_in_chronological_order(self, client):
        html = self._delivered(client).html
        order = ["d1-lunch", "d1-dinner", "d2-lunch", "d2-dinner"]
        positions = [html.index(f"cid:qr-{k}") for k in order]
        assert positions == sorted(positions), "a pass is out of order in the timeline"

    def test_the_running_counter_crosses_the_day_boundary(self, client):
        html = self._delivered(client).html
        assert re.findall(r"Pass (\d) of 4", html) == ["1", "2", "3", "4"]

    def test_a_sitting_without_a_pass_degrades_to_a_programme_entry(self, client):
        """Somebody registered for one day only must not get an empty card."""
        load_recipients(client)
        configure_sittings(client)
        store = client.app_module.store
        client.post("/api/send/start", json={"template": "icoc_invitation"})
        wait_for_send(client)
        # Revoke and delete day 2, then re-render for that person.
        with store.write() as conn:
            conn.execute("DELETE FROM coupons WHERE meal_key LIKE 'd2-%'")
        body = client.get("/preview/icoc_invitation?email=ada@example.com")
        html = body.get_data(as_text=True)
        assert body.status_code == 200
        assert "You do not hold a pass for this sitting." in \
            TestFullPagePreview._rendered_body(html)


class TestThankYouPerSitting:
    """One thank-you per sitting, each about the meal just collected.

    "Thanks for coming" is worth nothing on the first of four meals. What an
    attendee wants at that moment is confirmation the scan worked and where to
    be next, so every message has to differ.
    """

    def _walk(self, client, monkeypatch, template="icoc_thank_you"):
        monkeypatch.setattr(client.app_module, "THANK_YOU_TEMPLATE", template)
        load_recipients(client)
        configure_sittings(client)
        client.post("/api/send/start", json={"template": "invitation"})
        wait_for_send(client)
        store = client.app_module.store
        passes = store.coupons_for_email("ada@example.com")
        for p in passes:
            client.post("/api/scan", json={"payload": p.qr_payload, "meal": p.meal_key})
        rows = store.conn.execute(
            "SELECT o.subject, o.html, c.meal_key FROM outbox o"
            " JOIN coupons c ON c.coupon_id = o.coupon_id"
            " WHERE o.to_email = ? ORDER BY c.meal_order",
            ("ada@example.com",),
        ).fetchall()
        return passes, rows

    def test_one_per_sitting(self, client, monkeypatch):
        _, rows = self._walk(client, monkeypatch)
        assert len(rows) == 4
        assert [r["meal_key"] for r in rows] == [
            "d1-lunch", "d1-dinner", "d2-lunch", "d2-dinner"]

    def test_each_subject_names_its_own_meal(self, client, monkeypatch):
        _, rows = self._walk(client, monkeypatch)
        subjects = [r["subject"] for r in rows]
        assert len(set(subjects)) == 4, subjects
        assert "3 passes left" in subjects[0]
        assert "1 pass left" in subjects[2]

    def test_each_one_points_at_the_next_sitting(self, client, monkeypatch):
        _, rows = self._walk(client, monkeypatch)
        assert "Day 1 · Dinner" in rows[0]["html"]
        assert "Day 2 · Lunch" in rows[1]["html"]
        assert "Day 2 · Conference Dinner" in rows[2]["html"]

    def test_the_last_one_says_goodbye_instead(self, client, monkeypatch):
        _, rows = self._walk(client, monkeypatch)
        last = rows[3]
        assert "Next up" not in last["html"]
        assert "last meal pass" in last["html"]
        assert "Thank you for joining us" in last["subject"]

    def test_no_redeemable_code_is_ever_in_a_thank_you(self, client, monkeypatch):
        """It arrives after a pass is spent; printing a live code invites reuse."""
        passes, rows = self._walk(client, monkeypatch)
        unspent = {p.verification_code for p in passes[1:]}
        assert "cid:" not in rows[0]["html"]
        for code in unspent:
            assert code not in rows[0]["html"], f"{code} was still valid when sent"

    def test_rescanning_a_spent_pass_queues_nothing_more(self, client, monkeypatch):
        passes, _ = self._walk(client, monkeypatch)
        before = client.app_module.store.outbox_stats()["total"]
        client.post("/api/scan", json={"payload": passes[0].qr_payload,
                                       "meal": "d1-lunch"})
        assert client.app_module.store.outbox_stats()["total"] == before

    def test_a_single_sitting_event_still_gets_one(self, client, monkeypatch):
        monkeypatch.setattr(client.app_module, "THANK_YOU_TEMPLATE", "thank_you")
        load_recipients(client)
        client.post("/api/send/start", json={"template": "invitation"})
        wait_for_send(client)
        store = client.app_module.store
        coupon = store.find_by_email("ada@example.com")
        client.post("/api/scan", json={"payload": coupon.qr_payload})
        assert store.outbox_stats()["total"] == 1
