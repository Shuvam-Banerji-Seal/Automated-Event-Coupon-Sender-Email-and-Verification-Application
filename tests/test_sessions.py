"""Meal sittings: several passes per attendee, one email, one counter each.

A single-sitting event gives each person one coupon. A two-day conference gives
them four, and every assumption that "a coupon is a person" has to be checked
again: who gets issued what, how many emails go out, which pass a door accepts,
and what the kitchen is told.
"""

import sqlite3

import pytest

from src.issuer import CouponIssuer
from src.store import CouponStore, MealSession, Recipient

ICOC = [
    MealSession(key="d1-lunch", day="Day 1", meal="Lunch",
                date="Tuesday, 22 September 2026", time="13:10 – 14:25",
                venue="R.N. Tagore Auditorium"),
    MealSession(key="d1-dinner", day="Day 1", meal="Dinner",
                date="Tuesday, 22 September 2026", time="19:30 onwards",
                venue="R.N. Tagore Auditorium"),
    MealSession(key="d2-lunch", day="Day 2", meal="Lunch",
                date="Wednesday, 23 September 2026", time="13:10 – 14:25",
                venue="R.N. Tagore Auditorium"),
    MealSession(key="d2-dinner", day="Day 2", meal="Conference Dinner",
                date="Wednesday, 23 September 2026", time="19:30 onwards",
                venue="RISE Foundation"),
]

PEOPLE = [
    Recipient(email="ada@example.com", name="Ada Lovelace",
              food_preference="Veg"),
    Recipient(email="alan@example.com", name="Alan Turing",
              food_preference="Non-Veg"),
]


@pytest.fixture
def store(tmp_path):
    s = CouponStore(str(tmp_path / "t.db"))
    yield s
    s.close()


@pytest.fixture
def conference(store):
    """A store with the ICOC sittings configured and both attendees issued."""
    store.set_meal_sessions(ICOC)
    CouponIssuer(store, "0" * 64).issue_batch(PEOPLE, event_name="ICOC")
    return store


class TestSessionModel:
    def test_key_is_normalised(self):
        assert MealSession(key="  Day 1 / LUNCH ").key == "day-1-lunch"

    def test_label_defaults_to_day_and_meal(self):
        assert MealSession(key="x", day="Day 2", meal="Lunch").label == "Day 2 · Lunch"

    def test_label_falls_back_to_the_key(self):
        assert MealSession(key="d1-lunch").label == "d1-lunch"

    def test_round_trips_through_settings(self, store):
        store.set_meal_sessions(ICOC)
        back = store.meal_sessions()
        assert [s.key for s in back] == [s.key for s in ICOC]
        assert back[3].venue == "RISE Foundation"

    def test_duplicate_keys_collapse(self, store):
        saved = store.set_meal_sessions(
            [MealSession(key="lunch"), MealSession(key="lunch", day="again")]
        )
        assert len(saved) == 1

    def test_corrupt_setting_does_not_break_the_event(self, store):
        store.set_setting("meal_sessions", "{not json")
        assert store.meal_sessions() == []
        assert len(store.issuing_sessions()) == 1

    def test_no_sessions_still_issues_one_pass(self, store):
        assert [s.key for s in store.issuing_sessions()] == [""]


class TestIssuing:
    def test_one_pass_per_person_per_sitting(self, conference):
        assert len(conference.coupons_for_email("ada@example.com")) == 4
        assert conference.count_coupons() == 8

    def test_passes_come_back_in_serving_order(self, conference):
        keys = [c.meal_key for c in conference.coupons_for_email("ada@example.com")]
        assert keys == ["d1-lunch", "d1-dinner", "d2-lunch", "d2-dinner"]

    def test_every_pass_has_its_own_code_and_token(self, conference):
        coupons = conference.coupons_for_email("ada@example.com")
        assert len({c.verification_code for c in coupons}) == 4
        assert len({c.qr_token for c in coupons}) == 4

    def test_the_label_is_frozen_onto_the_pass(self, conference):
        first = conference.coupons_for_email("ada@example.com")[0]
        assert first.meal_label == "Day 1 · Lunch"

    def test_reissuing_mints_nothing_new(self, conference):
        result = CouponIssuer(conference, "0" * 64).issue_batch(PEOPLE)
        assert result["issued_count"] == 0
        assert result["skipped_count"] == 8
        assert conference.count_coupons() == 8

    def test_a_sitting_added_later_reaches_everyone(self, conference):
        """Adding Day 3 must not skip people who already hold Day 1 and 2."""
        conference.set_meal_sessions([*ICOC, MealSession(key="d3-lunch", meal="Lunch")])
        result = CouponIssuer(conference, "0" * 64).issue_batch(PEOPLE)
        assert result["issued_count"] == 2
        assert len(conference.coupons_for_email("ada@example.com")) == 5

    def test_the_database_refuses_a_duplicate_pass(self, conference):
        """Two operators clicking Send at once must not double-issue."""
        existing = conference.coupons_for_email("ada@example.com")[0]
        with pytest.raises(sqlite3.IntegrityError), conference.write() as conn:
            conn.execute(
                "INSERT INTO coupons(coupon_id, email, verification_code,"
                " qr_token, meal_key, created_at) VALUES(?,?,?,?,?,?)",
                ("dup", existing.email, "999999", "ZZZZZZZZZZZZ",
                 existing.meal_key, "now"),
            )

    def test_recipients_missing_a_sitting_are_still_pending(self, store):
        store.set_meal_sessions(ICOC)
        store.replace_recipients(PEOPLE)
        assert len(store.recipients_without_coupons()) == 2
        CouponIssuer(store, "0" * 64).issue_batch(PEOPLE)
        assert store.recipients_without_coupons() == []
        store.set_meal_sessions([*ICOC, MealSession(key="d3-lunch")])
        assert len(store.recipients_without_coupons()) == 2


class TestRedeeming:
    def test_a_pass_works_at_its_own_sitting(self, conference):
        pass_ = conference.coupons_for_email("ada@example.com")[0]
        result = conference.redeem(qr_token=pass_.qr_token, expect_meal="d1-lunch")
        assert result["valid"] is True

    def test_a_pass_is_refused_at_another_sitting(self, conference):
        """The whole point: dinner's pass must not be burnt at lunch."""
        dinner = conference.coupons_for_email("ada@example.com")[1]
        result = conference.redeem(qr_token=dinner.qr_token, expect_meal="d1-lunch")
        assert result["valid"] is False
        assert result["error_code"] == "WRONG_MEAL"
        assert "Day 1 · Dinner" in result["error"]

    def test_a_refused_pass_is_still_good_for_its_own_sitting(self, conference):
        dinner = conference.coupons_for_email("ada@example.com")[1]
        conference.redeem(qr_token=dinner.qr_token, expect_meal="d1-lunch")
        again = conference.redeem(qr_token=dinner.qr_token, expect_meal="d1-dinner")
        assert again["valid"] is True, "a wrong-counter scan consumed the pass"

    def test_the_wrong_sitting_is_recorded(self, conference):
        dinner = conference.coupons_for_email("ada@example.com")[1]
        conference.redeem(qr_token=dinner.qr_token, expect_meal="d1-lunch")
        assert conference.recent_scans(limit=1)[0]["result"] == "wrong_meal"

    def test_no_sitting_selected_accepts_anything(self, conference):
        dinner = conference.coupons_for_email("ada@example.com")[1]
        assert conference.redeem(qr_token=dinner.qr_token)["valid"] is True

    def test_each_pass_is_still_single_use(self, conference):
        lunch = conference.coupons_for_email("ada@example.com")[0]
        assert conference.redeem(qr_token=lunch.qr_token, expect_meal="d1-lunch")["valid"]
        second = conference.redeem(qr_token=lunch.qr_token, expect_meal="d1-lunch")
        assert second["error_code"] == "ALREADY_USED"

    def test_using_lunch_leaves_dinner_alone(self, conference):
        coupons = conference.coupons_for_email("ada@example.com")
        conference.redeem(qr_token=coupons[0].qr_token, expect_meal="d1-lunch")
        for later in coupons[1:]:
            assert conference.find_by_id(later.coupon_id).status != "used"


class TestCounts:
    def test_stats_are_reported_per_sitting(self, conference):
        rows = {r["key"]: r for r in conference.meal_stats()}
        assert rows["d1-lunch"]["issued"] == 2
        assert rows["d1-lunch"]["veg"] == 1
        assert rows["d1-lunch"]["non_veg"] == 1
        assert rows["d1-lunch"]["used"] == 0

    def test_serving_moves_only_that_sitting(self, conference):
        lunch = conference.coupons_for_email("ada@example.com")[0]
        conference.redeem(qr_token=lunch.qr_token, expect_meal="d1-lunch")
        rows = {r["key"]: r for r in conference.meal_stats()}
        assert rows["d1-lunch"]["used"] == 1
        assert rows["d1-lunch"]["veg_used"] == 1
        assert rows["d1-dinner"]["used"] == 0

    def test_a_removed_sitting_still_reports_its_passes(self, conference):
        """Deleting a sitting must not make already-issued passes vanish."""
        conference.set_meal_sessions(ICOC[:2])
        rows = {r["key"]: r for r in conference.meal_stats()}
        assert rows["d2-lunch"]["issued"] == 2
        assert rows["d2-lunch"]["configured"] is False

    def test_grouping_gives_one_entry_per_person(self, conference):
        grouped = conference.coupons_by_email()
        assert set(grouped) == {"ada@example.com", "alan@example.com"}
        assert all(len(v) == 4 for v in grouped.values())

    def test_grouping_can_be_narrowed(self, conference):
        grouped = conference.coupons_by_email(["ADA@example.com"])
        assert list(grouped) == ["ada@example.com"]

    def test_recipient_rows_carry_every_pass(self, conference):
        conference.replace_recipients(PEOPLE)
        rows = {r["email"]: r for r in conference.recipients_with_status()}
        assert len(rows) == 2, "the coupon join fanned out into duplicate rows"
        assert rows["ada@example.com"]["coupon_count"] == 4


class TestThankYouIsSentOnce:
    def test_one_message_per_attendee_not_per_pass(self, conference):
        """Four meals over two days must not mean four thank-you emails."""
        email = "ada@example.com"
        first = conference.enqueue_email(email, "Thanks", "<p>x</p>",
                                         coupon_id="c1", dedupe_key=email)
        second = conference.enqueue_email(email, "Thanks", "<p>x</p>",
                                          coupon_id="c2", dedupe_key=email)
        assert first is not None
        assert second is None
        assert conference.outbox_stats()["total"] == 1

    def test_the_coupon_key_still_works_for_single_sittings(self, store):
        assert store.enqueue_email("a@x.com", "Hi", "<p>x</p>", coupon_id="c1")
        assert store.enqueue_email("a@x.com", "Hi", "<p>x</p>", coupon_id="c1") is None


class TestMigrationFromV1:
    """A database written before sittings existed has to open and keep working.

    An event mid-flight cannot be asked to reissue: the codes are already in
    people's inboxes.
    """

    @pytest.fixture
    def legacy_db(self, tmp_path):
        path = str(tmp_path / "old.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE coupons (
                coupon_id TEXT PRIMARY KEY, email TEXT NOT NULL, name TEXT DEFAULT '',
                verification_code TEXT NOT NULL, qr_token TEXT NOT NULL DEFAULT '',
                food_preference TEXT NOT NULL DEFAULT 'Vegetarian',
                include_qr INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'generated', event_name TEXT DEFAULT '',
                encrypted_data TEXT DEFAULT '', extra TEXT DEFAULT '{}',
                created_at TEXT, sent_at TEXT, used_at TEXT);
            CREATE UNIQUE INDEX ix_coupons_code ON coupons(verification_code);
            CREATE TABLE outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT, to_email TEXT NOT NULL,
                to_name TEXT DEFAULT '', subject TEXT NOT NULL, html TEXT NOT NULL,
                kind TEXT DEFAULT 'thank_you', coupon_id TEXT,
                status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT DEFAULT '', queued_at TEXT NOT NULL,
                next_try_at TEXT NOT NULL, sent_at TEXT);
            CREATE UNIQUE INDEX ix_outbox_once
                ON outbox(coupon_id, kind) WHERE coupon_id IS NOT NULL;
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO settings VALUES('schema_version','1');
            INSERT INTO coupons(coupon_id, email, name, verification_code, qr_token,
                                status, created_at)
              VALUES('old-1','ada@x.com','Ada','111111','TOKENTOKEN01','sent','2026-01-01');
            INSERT INTO outbox(to_email, subject, html, coupon_id, queued_at, next_try_at)
              VALUES('ada@x.com','Thanks','<p>x</p>','old-1','2026-01-01','2026-01-01');
        """)
        conn.commit()
        conn.close()
        return path

    def test_it_opens_and_gains_the_new_columns(self, legacy_db):
        store = CouponStore(legacy_db)
        try:
            columns = {r["name"] for r in store.conn.execute("PRAGMA table_info(coupons)")}
            assert {"meal_key", "meal_label", "meal_order"} <= columns
            assert store.get_setting("schema_version") == "2"
        finally:
            store.close()

    def test_an_already_mailed_coupon_still_redeems(self, legacy_db):
        store = CouponStore(legacy_db)
        try:
            assert store.redeem(verification_code="111111")["valid"] is True
        finally:
            store.close()

    def test_queued_mail_keeps_its_once_only_guarantee(self, legacy_db):
        store = CouponStore(legacy_db)
        try:
            assert store.enqueue_email("ada@x.com", "Thanks", "<p>x</p>",
                                       coupon_id="old-1") is None
        finally:
            store.close()

    def test_sittings_can_be_turned_on_afterwards(self, legacy_db):
        store = CouponStore(legacy_db)
        try:
            store.set_meal_sessions(ICOC)
            CouponIssuer(store, "0" * 64).issue_batch(
                [Recipient(email="new@x.com", name="New")]
            )
            assert len(store.coupons_for_email("new@x.com")) == 4
            # The legacy coupon keeps the blank key and is untouched.
            assert store.find_by_id("old-1").meal_key == ""
        finally:
            store.close()
