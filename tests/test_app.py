"""End-to-end tests through the HTTP layer.

Covers the path an operator actually walks: upload a sheet, confirm the detected
columns, issue coupons, then redeem one at the door.

No email is ever sent — the mailer is replaced with a recorder. That is a hard
requirement of this suite, not a convenience: the predecessor's test file called
the real SMTP sender, and running the suite delivered mail.
"""

import io

import pytest


SHEET = (
    b"Timestamp,Email Address,Your Name,Veg / Non-Veg?,Roll No\n"
    b"2026-01-01,ada@iiserkol.ac.in,Ada Lovelace,Veg,21MS001\n"
    b"2026-01-01,grace@iiserkol.ac.in,Grace Hopper,Non-Veg,21MS002\n"
    b"2026-01-01,alan@iiserkol.ac.in,Alan Turing,Veg,21MS003\n"
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
        assert by_email["grace@iiserkol.ac.in"]["food_preference"] == "Non-Vegetarian"
        assert by_email["ada@iiserkol.ac.in"]["food_preference"] == "Vegetarian"


class TestTemplates:
    def test_seeded_templates_exist(self, client):
        names = [t["name"] for t in client.get("/api/templates").get_json()["templates"]]
        assert "invitation" in names

    def test_preview_renders(self, client):
        response = client.post("/api/templates/preview", json={
            "html": "<p>Hi {{ first_name }}</p>", "subject": "Hello {{ first_name }}",
        })
        data = response.get_json()
        assert "Ada" in data["html"]
        assert data["subject"] == "Hello Ada"

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
        coupon = store.find_by_email("ada@iiserkol.ac.in")
        data = client.post("/api/scan", json={
            "payload": coupon.qr_payload, "scanner": "gate-1"}).get_json()
        assert data["success"] is True
        assert data["name"] == "Ada Lovelace"
        assert data["food_preference"] == "Vegetarian"

    def test_redeem_by_typed_code(self, client):
        store = self._issue(client)
        coupon = store.find_by_email("grace@iiserkol.ac.in")
        data = client.post("/api/scan",
                           json={"payload": coupon.verification_code}).get_json()
        assert data["success"] is True
        assert data["food_preference"] == "Non-Vegetarian"

    def test_second_scan_is_refused(self, client):
        store = self._issue(client)
        coupon = store.find_by_email("ada@iiserkol.ac.in")
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
        coupon = store.find_by_email("ada@iiserkol.ac.in")
        scan = client.post("/api/scan", json={"payload": coupon.qr_payload}).get_json()
        undo = client.post("/api/scan/undo",
                           json={"coupon_id": scan["coupon_id"]}).get_json()
        assert undo["success"] is True
        again = client.post("/api/scan", json={"payload": coupon.qr_payload}).get_json()
        assert again["success"] is True

    def test_scan_log_records_every_attempt(self, client):
        store = self._issue(client)
        coupon = store.find_by_email("ada@iiserkol.ac.in")
        client.post("/api/scan", json={"payload": coupon.qr_payload})
        client.post("/api/scan", json={"payload": coupon.qr_payload})
        client.post("/api/scan", json={"payload": "999999"})
        results = [s["result"] for s in client.get("/api/scan/recent").get_json()["scans"]]
        assert set(results) == {"ok", "already_used", "not_found"}

    def test_lookup_does_not_redeem(self, client):
        store = self._issue(client)
        coupon = store.find_by_email("ada@iiserkol.ac.in")
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
        coupon = store.find_by_email("ada@iiserkol.ac.in")
        good = client.post("/api/scan",
                           json={"payload": coupon.qr_payload, "scanner": "gate-1"})
        assert good.status_code == 200
        assert good.get_json()["success"] is True

    def test_valid_scans_do_not_count_toward_the_limit(self, client):
        """A volunteer admitting a long queue must never be throttled."""
        store = self._issue(client)
        coupon = store.find_by_email("ada@iiserkol.ac.in")
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
        coupon = store.find_by_email("ada@iiserkol.ac.in")
        client.post("/api/scan", json={"payload": coupon.qr_payload})
        assert store.outbox_stats()["total"] == before + 1

    def test_only_one_thank_you_per_guest(self, client):
        """Six scanners racing the same coupon must not queue six emails."""
        store = self._issue(client)
        coupon = store.find_by_email("ada@iiserkol.ac.in")
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
        coupon = store.find_by_email("ada@iiserkol.ac.in")
        started = time.perf_counter()
        client.post("/api/scan", json={"payload": coupon.qr_payload})
        assert time.perf_counter() - started < 1.0

    def test_outbox_endpoint_reports_the_queue(self, client):
        store = self._issue(client)
        coupon = store.find_by_email("ada@iiserkol.ac.in")
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
        coupon = store.find_by_email("ada@iiserkol.ac.in")
        for size in ("abc", "-1", "99999"):
            assert client.get(
                f"/api/coupons/{coupon.coupon_id}/qr.png?size={size}"
            ).status_code == 200


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
        newcomer = b"Email Address,Your Name\nzara@iiserkol.ac.in,Zara\n"
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
            "emails": ["ada@iiserkol.ac.in"], "throttle": 0})
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
        coupon = store.find_by_email("ada@iiserkol.ac.in")
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
    import time

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
