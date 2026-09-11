"""End-to-end tests through the HTTP layer.

Covers the path an operator actually walks: upload a sheet, confirm the detected
columns, issue coupons, then redeem one at the door.

No email is ever sent — the mailer is replaced with a recorder. That is a hard
requirement of this suite, not a convenience: the predecessor's test file called
the real SMTP sender, and running the suite delivered mail.
"""

import importlib
import io
import os
import sys

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A fully isolated app instance.

    Every path the app writes to is redirected into a temp directory. The old
    suite wiped the production database precisely because this was not done.
    """
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("SECRET_KEY", "test-key-not-a-real-secret")
    monkeypatch.setenv("COUPON_SECRET_KEY", "0" * 64)
    monkeypatch.setenv("DISABLE_ADMIN_CHECK", "true")
    monkeypatch.setenv("SCANNER_PIN", "")
    monkeypatch.setenv("EVENT_NAME", "Test Event")
    monkeypatch.chdir(tmp_path)

    # Seed templates live next to the real app, not in the temp cwd.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    (tmp_path / "templates").mkdir(exist_ok=True)
    os.symlink(os.path.join(root, "templates", "seed"), tmp_path / "templates" / "seed")

    sys.modules.pop("app", None)
    app_module = importlib.import_module("app")
    app_module.app.config.update(TESTING=True)

    sent = []

    class Recorder:
        """Stands in for the SMTP pool; records instead of delivering."""

        accounts = [object()]
        available = True

        def send(self, message):
            sent.append(message)
            return {"success": True, "to_email": message.to_email, "account": "test"}

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(app_module.mailer, "campaign", lambda **kw: Recorder())
    monkeypatch.setattr(
        app_module.mailer, "status",
        lambda: {"accounts": [], "total_remaining": 500, "configured": True},
    )

    with app_module.app.test_client() as test_client:
        test_client.app_module = app_module
        test_client.sent = sent
        yield test_client

    sys.modules.pop("app", None)


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
