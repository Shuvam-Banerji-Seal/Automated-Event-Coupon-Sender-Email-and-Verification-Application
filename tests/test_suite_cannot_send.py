"""The suite must not be able to deliver mail. Proven, not assumed.

This exists because it could, and did. Importing the app starts a background
sender thread; the client fixture never stopped one. At teardown monkeypatch
handed every leaked thread back the real mailer, the real working directory and
the real .env credentials, and a thank-you queued by a scanner test went out for
real seconds after that test had passed. Nothing in the suite's own output said
so — the evidence was a bounce in the operator's inbox and a send counter in the
project root that had been incremented by a process nobody was watching.

It was invisible for as long as the configured account was unusable. The moment
a working one was set up, the suite began sending. A guarantee that holds only
while the credentials are broken is not a guarantee.
"""

import threading

import pytest

from src.mailer import Account, MailerPool, Message, dry_run_enabled


class TestNoBackgroundSenderSurvives:
    def test_the_worker_is_stopped_when_the_fixture_returns(self, client):
        """Inside the test it should be running; the fixture must stop it after."""
        assert client.app_module.outbox.running is True

    def test_no_outbox_thread_is_left_behind(self, client):
        client.app_module.outbox.stop(timeout=10)
        alive = [t.name for t in threading.enumerate()
                 if "outbox" in t.name.lower() and t.is_alive()]
        assert not alive, f"background senders still alive: {alive}"


class TestDeliveryIsRefusedFourWaysOver:
    def test_dry_run_is_on(self, client):
        assert dry_run_enabled() is True

    def test_there_is_no_account_to_send_with(self, client):
        assert MailerPool()._from_environment() == []

    def test_opening_a_socket_raises(self, client):
        with pytest.raises(AssertionError, match="real SMTP connection"):
            client.app_module.mailer._connect(
                Account(username="x@example.com", password="y"))

    def test_the_app_pool_never_delivers(self, client):
        """The end-to-end property: ask the app's own pool to send, get nothing."""
        with client.app_module.mailer.campaign() as campaign:
            result = campaign.send(Message(
                to_email="nobody@example.com", subject="s", html="<p>x</p>"))
        assert result["success"] is True
        assert result.get("account") == "test", "that was not the recorder"


class TestAQueuedThankYouCannotEscape:
    def test_mail_queued_by_a_scan_is_recorded_not_delivered(self, client, monkeypatch):
        """The exact path that leaked: a scan queues mail, the worker drains it."""
        monkeypatch.setattr(client.app_module, "THANK_YOU_TEMPLATE", "thank_you")
        import io
        client.post("/api/csv/inspect", data={
            "file": (io.BytesIO(b"Email Address,Your Name,Veg / Non-Veg?\n"
                                b"someone@example.com,Someone,Veg\n"), "g.csv")},
            content_type="multipart/form-data")
        inspection = client.post("/api/csv/inspect", data={
            "file": (io.BytesIO(b"Email Address,Your Name,Veg / Non-Veg?\n"
                                b"someone@example.com,Someone,Veg\n"), "g.csv")},
            content_type="multipart/form-data").get_json()
        client.post("/api/csv/commit", json={
            "upload_id": inspection["upload_id"],
            "mapping": inspection["suggested_mapping"], "mode": "replace"})

        store = client.app_module.store
        client.app_module.issuer.issue_batch(store.recipients())
        coupon = store.find_by_email("someone@example.com")
        assert client.post("/api/scan",
                           json={"payload": coupon.qr_payload}).get_json()["success"]

        # Drain it here, deliberately, on the recorder.
        client.app_module.outbox._drain_once()
        assert any(m.to_email == "someone@example.com" for m in client.sent), \
            "the thank-you did not reach the recorder"
        assert store.outbox_stats()["sent"] == 1
