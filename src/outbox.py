"""
Background email sender.

Thank-you messages are triggered by a scan, and a scan happens while somebody
is standing at a door waiting to be let in. Sending must therefore never happen
in the request: SMTP to Gmail takes one to three seconds, and with six scanners
working a queue that would be six seconds of latency piling up on every
volunteer's phone.

The previous version spawned a thread per scan. With several hundred guests
arriving over half an hour that is several hundred threads, each opening its own
authenticated SMTP connection — which is both slow and the kind of pattern that
gets an account rate-limited.

Here a scan writes one row and returns. A single worker drains the queue on one
held-open connection, retries transient failures with backoff, and gives up on
permanent ones. Because the queue is a database table, messages survive a
restart: a crash mid-event loses nothing.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

from src.mailer import MailerPool, Message, _classify
from src.store import CouponStore

logger = logging.getLogger(__name__)

# Backoff between attempts. A transient Gmail hiccup clears in seconds; a
# sustained one means waiting is better than hammering. Past the last entry the
# message is marked failed and left for the operator to retry from the console.
RETRY_SCHEDULE = (30, 120, 600, 1800)
MAX_ATTEMPTS = len(RETRY_SCHEDULE)

IDLE_SLEEP = 2.0
BATCH_SIZE = 10


class OutboxWorker:
    """Drains the outbox on a single background thread."""

    def __init__(
        self,
        store: CouponStore,
        mailer: MailerPool,
        throttle: float = 0.5,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.store = store
        self.mailer = mailer
        self.throttle = throttle
        self.on_error = on_error
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self.started_at: Optional[float] = None
        self.processed = 0
        self.failed = 0
        self.last_error: Optional[str] = None

    # ------------------------------------------------------------- lifecycle

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        # Anything left mid-flight by a previous crash goes back on the queue.
        recovered = self.store.requeue_stuck_emails()
        if recovered:
            logger.info("Recovered %d interrupted messages", recovered)
        self._stop.clear()
        self.started_at = time.time()
        self._thread = threading.Thread(
            target=self._run, name="outbox", daemon=True
        )
        self._thread.start()
        logger.info("Outbox worker started")

    def stop(self, timeout: float = 10.0):
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        logger.info("Outbox worker stopped")

    def nudge(self):
        """Wake the worker immediately instead of waiting out the idle sleep."""
        self._wake.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> Dict[str, Any]:
        stats = self.store.outbox_stats()
        return {
            "running": self.running,
            "processed": self.processed,
            "failed": self.failed,
            "last_error": self.last_error,
            "uptime_seconds": round(time.time() - self.started_at)
            if self.started_at else 0,
            **stats,
        }

    # ------------------------------------------------------------------ loop

    def _run(self):
        while not self._stop.is_set():
            try:
                sent_any = self._drain_once()
            except Exception as exc:  # noqa: BLE001 - the worker must not die
                logger.exception("Outbox worker error")
                self.last_error = str(exc)
                if self.on_error:
                    self.on_error(str(exc))
                sent_any = False
            if not sent_any:
                # Sleep until woken by a new message or the stop signal.
                self._wake.wait(timeout=IDLE_SLEEP)
                self._wake.clear()

    def _drain_once(self) -> bool:
        batch = self.store.claim_emails(BATCH_SIZE)
        if not batch:
            return False

        # One connection for the whole batch rather than one per message.
        with self.mailer.campaign(throttle=self.throttle) as campaign:
            for row in batch:
                if self._stop.is_set():
                    # Put the untouched remainder back before shutting down.
                    self.store.finish_email(row["id"], False, "shutting down",
                                            retry_in=5)
                    continue
                self._send_row(campaign, row)
        return True

    def _send_row(self, campaign, row: Dict[str, Any]):
        message = Message(
            to_email=row["to_email"],
            to_name=row["to_name"] or "",
            subject=row["subject"],
            html=row["html"],
            meta={"outbox_id": row["id"], "kind": row["kind"]},
        )
        result = campaign.send(message)

        if result["success"]:
            self.store.finish_email(row["id"], True)
            self.store.log_send(
                row["to_email"], row["coupon_id"], row["kind"], row["subject"],
                True, account=result.get("account", ""),
            )
            self.processed += 1
            return

        error = result.get("error", "unknown error")
        kind = result.get("kind") or _classify(error)
        attempts = row["attempts"]

        # A bad address will never succeed, so retrying wastes quota and delays
        # everyone behind it in the queue.
        if kind == "permanent" or attempts >= MAX_ATTEMPTS:
            self.store.finish_email(row["id"], False, error)
            self.store.log_send(
                row["to_email"], row["coupon_id"], row["kind"], row["subject"],
                False, error, result.get("account", ""),
            )
            self.failed += 1
            self.last_error = error
            logger.warning("Giving up on %s: %s", row["to_email"], error)
        else:
            delay = RETRY_SCHEDULE[min(attempts, len(RETRY_SCHEDULE) - 1)]
            self.store.finish_email(row["id"], False, error, retry_in=delay)
            logger.info(
                "Retrying %s in %ds (attempt %d): %s",
                row["to_email"], delay, attempts + 1, error,
            )
