"""Tests for the queued email sender."""

import time

import pytest

from src.mailer import Message
from src.outbox import MAX_ATTEMPTS, OutboxWorker
from src.store import CouponStore


@pytest.fixture
def store(tmp_path):
    s = CouponStore(str(tmp_path / "t.db"))
    yield s
    s.close()


class FakeCampaign:
    """Records sends; scripted to fail on demand."""

    def __init__(self, fail_with=None, fail_kind="transient", fail_times=0):
        self.sent = []
        self.fail_with = fail_with
        self.fail_kind = fail_kind
        self.fail_times = fail_times

    def send(self, message: Message):
        if self.fail_times > 0:
            self.fail_times -= 1
            return {"success": False, "to_email": message.to_email,
                    "error": self.fail_with, "kind": self.fail_kind}
        self.sent.append(message)
        return {"success": True, "to_email": message.to_email, "account": "test"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass


class FakePool:
    def __init__(self, campaign):
        self._campaign = campaign

    def campaign(self, **kwargs):
        return self._campaign


def worker(store, campaign):
    return OutboxWorker(store, FakePool(campaign), throttle=0)


class TestQueue:
    def test_enqueue_and_drain(self, store):
        store.enqueue_email("a@x.com", "Hi", "<p>Hi</p>", coupon_id="c1")
        campaign = FakeCampaign()
        worker(store, campaign)._drain_once()
        assert len(campaign.sent) == 1
        assert store.outbox_stats()["sent"] == 1

    def test_one_message_per_coupon(self, store):
        """Six scanners racing on the same coupon must not queue six emails."""
        first = store.enqueue_email("a@x.com", "Hi", "<p>x</p>", coupon_id="c1")
        second = store.enqueue_email("a@x.com", "Hi", "<p>x</p>", coupon_id="c1")
        assert first is not None
        assert second is None
        assert store.outbox_stats()["total"] == 1

    def test_messages_without_a_coupon_are_not_deduplicated(self, store):
        assert store.enqueue_email("a@x.com", "Hi", "<p>x</p>") is not None
        assert store.enqueue_email("a@x.com", "Hi", "<p>x</p>") is not None

    def test_claim_is_exclusive(self, store):
        """A second worker must not pick up rows the first already claimed."""
        for i in range(5):
            store.enqueue_email(f"u{i}@x.com", "Hi", "<p>x</p>")
        first = store.claim_emails(10)
        second = store.claim_emails(10)
        assert len(first) == 5
        assert second == []

    def test_nothing_to_do_is_cheap(self, store):
        assert worker(store, FakeCampaign())._drain_once() is False


class TestRetries:
    def test_transient_failure_is_retried_later(self, store):
        store.enqueue_email("a@x.com", "Hi", "<p>x</p>")
        campaign = FakeCampaign(fail_with="timeout", fail_times=1)
        worker(store, campaign)._drain_once()
        stats = store.outbox_stats()
        assert stats["queued"] == 1        # back on the queue
        assert stats["failed"] == 0

    def test_retry_is_not_immediate(self, store):
        store.enqueue_email("a@x.com", "Hi", "<p>x</p>")
        campaign = FakeCampaign(fail_with="timeout", fail_times=1)
        worker(store, campaign)._drain_once()
        # Backoff means it is not due yet, so a second pass finds nothing.
        assert store.claim_emails(10) == []

    def test_permanent_failure_is_not_retried(self, store):
        """A bad address would otherwise block the queue and burn quota."""
        store.enqueue_email("ghost@x.com", "Hi", "<p>x</p>")
        campaign = FakeCampaign(fail_with="550 5.1.1 No such user",
                                fail_kind="permanent", fail_times=1)
        worker(store, campaign)._drain_once()
        assert store.outbox_stats()["failed"] == 1
        assert store.outbox_stats()["queued"] == 0

    def test_gives_up_after_the_schedule_is_exhausted(self, store):
        row_id = store.enqueue_email("a@x.com", "Hi", "<p>x</p>")
        for _ in range(MAX_ATTEMPTS):
            store.finish_email(row_id, False, "timeout", retry_in=0)
            store.conn.execute(
                "UPDATE outbox SET status='queued', next_try_at=queued_at WHERE id=?",
                (row_id,))
            store.conn.commit()
        campaign = FakeCampaign(fail_with="timeout", fail_times=1)
        worker(store, campaign)._drain_once()
        assert store.outbox_stats()["failed"] == 1

    def test_operator_can_requeue_failures(self, store):
        store.enqueue_email("a@x.com", "Hi", "<p>x</p>")
        campaign = FakeCampaign(fail_with="550 5.1.1 No such user",
                                fail_kind="permanent", fail_times=1)
        worker(store, campaign)._drain_once()
        assert store.retry_failed_emails() == 1
        assert store.outbox_stats()["queued"] == 1


class TestCrashRecovery:
    def test_interrupted_messages_are_recovered(self, store):
        """A crash mid-send must not strand messages in 'sending' forever."""
        store.enqueue_email("a@x.com", "Hi", "<p>x</p>")
        store.claim_emails(10)                       # now 'sending'
        assert store.outbox_stats()["sending"] == 1
        assert store.requeue_stuck_emails(older_than_seconds=-1) == 1
        assert store.outbox_stats()["queued"] == 1

    def test_queue_survives_a_new_store_instance(self, store, tmp_path):
        store.enqueue_email("a@x.com", "Hi", "<p>x</p>")
        store.close()
        reopened = CouponStore(str(tmp_path / "t.db"))
        assert reopened.outbox_stats()["queued"] == 1
        reopened.close()


class TestWorkerLifecycle:
    def test_start_and_stop(self, store):
        w = worker(store, FakeCampaign())
        w.start()
        assert w.running is True
        w.stop(timeout=5)
        assert w.running is False

    def test_worker_drains_in_the_background(self, store):
        campaign = FakeCampaign()
        w = worker(store, campaign)
        w.start()
        store.enqueue_email("a@x.com", "Hi", "<p>x</p>")
        w.nudge()
        deadline = time.time() + 5
        while time.time() < deadline and not campaign.sent:
            time.sleep(0.05)
        w.stop(timeout=5)
        assert len(campaign.sent) == 1

    def test_worker_survives_a_broken_send(self, store):
        """The loop must never die — an event would silently stop sending."""
        class Exploding:
            def campaign(self, **kw):
                raise RuntimeError("boom")

        w = OutboxWorker(store, Exploding(), throttle=0)
        w.start()
        store.enqueue_email("a@x.com", "Hi", "<p>x</p>")
        w.nudge()
        time.sleep(0.4)
        assert w.running is True
        assert w.last_error == "boom"
        w.stop(timeout=5)


class TestResetClearsQueue:
    def test_reset_removes_queued_mail(self, store):
        """Otherwise a new event sends thank-yous for the previous one."""
        store.enqueue_email("a@x.com", "Hi", "<p>x</p>", coupon_id="c1")
        cleared = store.reset_event()
        assert cleared["outbox"] == 1
        assert store.outbox_stats()["total"] == 0
