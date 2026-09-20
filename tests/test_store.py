"""Tests for the SQLite store: atomicity, normalisation and QR payload size."""

import collections
import threading

import pytest

from src.store import (
    Coupon,
    CouponStore,
    Recipient,
    as_bool,
    first_name,
    food_colour,
    normalise_food,
    parse_scan,
    qr_payload,
)


@pytest.fixture
def store(tmp_path):
    """A store in a temp directory.

    Every test gets its own database file. The predecessor of this module
    hardcoded its database filename, so running the suite wiped the production
    database; passing a path explicitly is what prevents that, and these tests
    exist partly to keep that property.
    """
    s = CouponStore(str(tmp_path / "test.db"))
    yield s
    s.close()


def make_coupons(store, n, status="sent"):
    batch = []
    for i in range(n):
        batch.append(
            Coupon(
                coupon_id=f"c{i}",
                email=f"user{i}@example.com",
                verification_code=f"{i:06d}",
                qr_token=f"TOKEN{i:07d}",
                status=status,
            )
        )
    store.insert_coupons(batch)
    return batch


class TestRedeemAtomicity:
    def test_single_redeem_succeeds(self, store):
        make_coupons(store, 1)
        result = store.redeem(verification_code="000000")
        assert result["valid"] is True
        assert result["coupon"].status == "used"

    def test_second_redeem_is_rejected(self, store):
        make_coupons(store, 1)
        store.redeem(verification_code="000000")
        second = store.redeem(verification_code="000000")
        assert second["valid"] is False
        assert second["error_code"] == "ALREADY_USED"

    def test_unknown_code_is_not_found(self, store):
        assert store.redeem(verification_code="999999")["error_code"] == "NOT_FOUND"

    def test_revoked_coupon_cannot_be_redeemed(self, store):
        make_coupons(store, 1)
        store.revoke("c0")
        assert store.redeem(verification_code="000000")["error_code"] == "REVOKED"

    def test_concurrent_scans_redeem_each_coupon_exactly_once(self, store):
        """The property the old CSV implementation could not hold.

        Eight threads race to redeem the same 100 coupons. Exactly 100
        redemptions must succeed. Under the previous read-then-write design this
        reliably over-counted, letting one coupon through the door twice.
        """
        count = 100
        make_coupons(store, count)
        codes = [f"{i:06d}" for i in range(count)]

        results = collections.Counter()
        lock = threading.Lock()
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            local = collections.Counter()
            for code in codes:
                outcome = store.redeem(verification_code=code)
                local["ok" if outcome["valid"] else outcome["error_code"]] += 1
            with lock:
                results.update(local)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results["ok"] == count
        assert results["ALREADY_USED"] == count * 7
        used = store.conn.execute(
            "SELECT COUNT(*) c FROM coupons WHERE status = 'used'"
        ).fetchone()["c"]
        assert used == count

    def test_undo_returns_coupon_to_sent(self, store):
        make_coupons(store, 1)
        store.redeem(verification_code="000000")
        assert store.undo_redeem("c0") is True
        assert store.find_by_id("c0").status == "sent"
        assert store.find_by_id("c0").used_at is None

    def test_undo_on_unused_coupon_is_a_no_op(self, store):
        make_coupons(store, 1)
        assert store.undo_redeem("c0") is False

    def test_every_attempt_is_audited(self, store):
        make_coupons(store, 1)
        store.redeem(verification_code="000000", scanner="gate-1")
        store.redeem(verification_code="000000", scanner="gate-2")
        store.redeem(verification_code="123123", scanner="gate-1")
        scans = store.recent_scans()
        assert [s["result"] for s in scans] == ["not_found", "already_used", "ok"]


class TestTokens:
    def test_redeem_by_token(self, store):
        make_coupons(store, 1)
        assert store.redeem(qr_token="TOKEN0000000")["valid"] is True

    def test_token_lookup(self, store):
        make_coupons(store, 1)
        assert store.find_by_token("TOKEN0000000").coupon_id == "c0"

    def test_tokens_are_unique(self, store):
        """Enforced by the database, not by a check the caller could skip."""
        import sqlite3

        make_coupons(store, 1)
        with pytest.raises(sqlite3.IntegrityError):
            store.insert_coupons(
                [
                    Coupon(
                        coupon_id="dup",
                        email="x@y.com",
                        verification_code="111111",
                        qr_token="TOKEN0000000",
                    )
                ]
            )


class TestQRPayload:
    """The payload must stay small enough to scan off a damaged phone screen."""

    def test_payload_is_short(self):
        assert len(qr_payload("K7M2QX9RT4WD")) == 16

    def test_payload_length_is_independent_of_email(self):
        """The whole point of the token: a long address must not inflate the QR."""
        assert len(qr_payload("K7M2QX9RT4WD")) == len(qr_payload("AAAAAAAAAAAA"))

    def test_payload_stays_at_qr_version_1(self):
        import qrcode
        from qrcode.constants import ERROR_CORRECT_Q

        qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_Q, border=4)
        qr.add_data(qr_payload("K7M2QX9RT4WD"))
        qr.make(fit=True)
        assert qr.version == 1, (
            "QR grew past version 1 — modules shrink and scanning off cracked "
            "screens degrades. Do not add fields to the QR payload."
        )


class TestParseScan:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("EC1:K7M2QX9RT4WD", {"token": "K7M2QX9RT4WD", "code": None, "email": None}),
            ("ec1:k7m2qx9rt4wd", {"token": "K7M2QX9RT4WD", "code": None, "email": None}),
            ("418206", {"token": None, "code": "418206", "email": None}),
            ("  418206  ", {"token": None, "code": "418206", "email": None}),
            ("", {"token": None, "code": None, "email": None}),
            ("random text", {"token": None, "code": None, "email": None}),
        ],
    )
    def test_formats(self, raw, expected):
        assert parse_scan(raw) == expected

    def test_legacy_json_payload_still_parses(self):
        """Coupons issued by the previous version must keep working."""
        parsed = parse_scan('{"v":"418206","e":"ada@example.com"}')
        assert parsed["code"] == "418206"
        assert parsed["email"] == "ada@example.com"

    def test_malformed_legacy_json_falls_back_to_regex(self):
        assert parse_scan('{"v":"418206","e":}')["code"] == "418206"


class TestNormalisation:
    @pytest.mark.parametrize(
        "raw", ["non-veg", "Non Veg", "NONVEG", "n", "chicken", "Non-Vegetarian"]
    )
    def test_non_veg_spellings(self, raw):
        assert normalise_food(raw) == "Non-Vegetarian"

    @pytest.mark.parametrize("raw", ["veg", "Vegetarian", "V", "", None, "unknown"])
    def test_defaults_to_vegetarian(self, raw):
        assert normalise_food(raw) == "Vegetarian"

    def test_colours_differ(self):
        assert food_colour("Vegetarian") != food_colour("Non-Vegetarian")

    @pytest.mark.parametrize(
        "raw,expected",
        [("TRUE", True), ("no", False), ("1", True), ("0", False), ("", True), (None, True)],
    )
    def test_as_bool(self, raw, expected):
        assert as_bool(raw) is expected

    def test_first_name(self):
        assert first_name("Shuvam Banerji Seal") == "Shuvam"
        assert first_name("", "ada@x.com") == "ada"
        assert first_name("", "") == "Guest"


class TestRecipients:
    def test_replace_is_wholesale(self, store):
        store.replace_recipients([Recipient(email="a@x.com")])
        store.replace_recipients([Recipient(email="b@x.com")])
        assert [r.email for r in store.recipients()] == ["b@x.com"]

    def test_replacing_recipients_does_not_touch_coupons(self, store):
        """Uploading a new list must never invalidate issued coupons."""
        make_coupons(store, 3)
        store.replace_recipients([Recipient(email="someone-else@x.com")])
        assert store.stats()["total"] == 3

    def test_emails_are_lowercased(self, store):
        store.replace_recipients([Recipient(email="  ADA@X.COM ")])
        assert store.recipients()[0].email == "ada@x.com"

    def test_extra_columns_survive(self, store):
        store.replace_recipients(
            [Recipient(email="a@x.com", extra={"roll_no": "21MS001"})]
        )
        assert store.recipients()[0].extra["roll_no"] == "21MS001"
        assert "roll_no" in store.recipient_columns()

    def test_recipients_without_coupons(self, store):
        store.replace_recipients(
            [Recipient(email="user0@example.com"), Recipient(email="new@x.com")]
        )
        make_coupons(store, 1)
        pending = store.recipients_without_coupons()
        assert [r.email for r in pending] == ["new@x.com"]

    def test_status_join_is_one_query(self, store):
        store.replace_recipients([Recipient(email="user0@example.com", name="Ada")])
        make_coupons(store, 1)
        rows = store.recipients_with_status()
        assert rows[0]["status"] == "sent"
        assert rows[0]["verification_code"] == "000000"


class TestStats:
    def test_counts_by_status(self, store):
        make_coupons(store, 5)
        store.redeem(verification_code="000000")
        stats = store.stats()
        assert stats["total"] == 5
        assert stats["used"] == 1
        assert stats["sent"] == 4

    def test_mark_sent_skips_used_coupons(self, store):
        make_coupons(store, 2, status="generated")
        store.redeem(verification_code="000000")
        store.mark_sent(["c0", "c1"])
        assert store.find_by_id("c0").status == "used"
        assert store.find_by_id("c1").status == "sent"


class TestExportAndReset:
    def test_export_round_trips(self, store, tmp_path):
        make_coupons(store, 3)
        out = tmp_path / "out.csv"
        assert store.export_coupons_csv(str(out)) == 3
        assert "verification_code" in out.read_text().splitlines()[0]

    def test_reset_clears_event_but_can_keep_recipients(self, store):
        store.replace_recipients([Recipient(email="a@x.com")])
        make_coupons(store, 2)
        store.reset_event(keep_recipients=True)
        assert store.stats()["total"] == 0
        assert store.recipient_count() == 1
