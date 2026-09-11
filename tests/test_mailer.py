"""Tests for MIME assembly, error classification and account rotation.

Nothing here opens a socket. The SMTP layer is faked so rotation behaviour can
be driven deterministically — including the failure modes that only appear
partway through a real five-hundred-message run.
"""

import json
import os

import pytest

from src.mailer import (
    Account, MailerPool, Message, _Campaign, _classify, build_mime, html_to_text,
)


@pytest.fixture
def pool(tmp_path):
    return MailerPool(
        config_file=str(tmp_path / "smtp.json"),
        counter_file=str(tmp_path / "counters.json"),
    )


class TestClassification:
    @pytest.mark.parametrize("error", [
        "550 5.4.5 Daily user sending quota exceeded",
        "421 4.7.0 Try again later",
        "452 4.2.2 Mailbox full",
        "Too many messages",
    ])
    def test_rate_limits(self, error):
        assert _classify(error) == "rate_limit"

    @pytest.mark.parametrize("error", [
        "535 Authentication failed",
        "Username and password not accepted",
        "5.7.8 Bad credentials",
    ])
    def test_auth_failures(self, error):
        assert _classify(error) == "auth"

    @pytest.mark.parametrize("error", [
        "550 5.1.1 No such user here",
        "Recipient address rejected",
        "Mailbox unavailable",
    ])
    def test_permanent_failures(self, error):
        """These must not rotate accounts — one bad address would burn the pool."""
        assert _classify(error) == "permanent"

    def test_unknown_is_transient(self):
        assert _classify("Connection reset by peer") == "transient"


class TestMime:
    def _message(self, **kw):
        defaults = dict(
            to_email="ada@example.com", to_name="Ada Lovelace",
            subject="You're invited", html="<h1>Hi</h1><p>Come along</p>",
        )
        defaults.update(kw)
        return Message(**defaults)

    def test_structure_is_alternative_with_text_first(self):
        """Mail clients pick the last part they understand; text must come first."""
        mime = build_mime(self._message(), Account(username="me@x.com"))
        types = [p.get_content_type() for p in mime.walk()]
        assert types[0] == "multipart/alternative"
        assert types[1] == "text/plain"
        assert "text/html" in types

    def test_always_has_a_plain_text_part(self):
        """HTML-only mail scores as spam and shows empty in text-only clients."""
        mime = build_mime(self._message(), Account(username="me@x.com"))
        text = [p for p in mime.walk() if p.get_content_type() == "text/plain"]
        assert text and text[0].get_content().strip()

    def test_inline_image_becomes_a_related_part(self):
        mime = build_mime(
            self._message(html='<img src="cid:qrcode">',
                          inline_images={"qrcode": b"\x89PNG\r\n\x1a\n"}),
            Account(username="me@x.com"),
        )
        assert "image/png" in [p.get_content_type() for p in mime.walk()]

    def test_cid_reference_is_rewritten_to_the_real_id(self):
        """A bare "cid:qrcode" is not globally unique; it must become a msgid."""
        mime = build_mime(
            self._message(html='<img src="cid:qrcode">',
                          inline_images={"qrcode": b"\x89PNG\r\n\x1a\n"}),
            Account(username="me@x.com"),
        )
        html = [p for p in mime.walk() if p.get_content_type() == "text/html"][0]
        body = html.get_content()
        assert "cid:qrcode" not in body
        assert "cid:" in body and "@" in body

    def test_sender_name_is_used(self):
        mime = build_mime(
            self._message(),
            Account(username="me@x.com", sender_name="Organising Team"),
        )
        assert mime["From"] == "Organising Team <me@x.com>"

    def test_missing_attachment_is_skipped_not_fatal(self):
        mime = build_mime(
            self._message(attachments=["/does/not/exist.pdf"]),
            Account(username="me@x.com"),
        )
        assert mime["Subject"] == "You're invited"

    def test_real_attachment_is_included(self, tmp_path):
        path = tmp_path / "schedule.pdf"
        path.write_bytes(b"%PDF-1.4 fake")
        mime = build_mime(
            self._message(attachments=[str(path)]), Account(username="me@x.com")
        )
        names = [p.get_filename() for p in mime.walk()]
        assert "schedule.pdf" in names


class TestHtmlToText:
    def test_strips_tags_and_keeps_words(self):
        assert html_to_text("<h1>Hi</h1><p>Come <b>along</b></p>") == "Hi\nCome along"

    def test_drops_script_and_style_content(self):
        text = html_to_text("<style>p{color:red}</style><script>x=1</script><p>Hi</p>")
        assert "color" not in text and "x=1" not in text
        assert "Hi" in text

    def test_decodes_entities(self):
        assert "Tom & Jerry" in html_to_text("<p>Tom &amp; Jerry</p>")


class TestDryRun:
    """MAIL_DRY_RUN must suppress delivery completely.

    A populated .env in the repo root is all it takes for an exploratory run to
    put real mail in real inboxes, so this switch has to be airtight.
    """

    def test_send_does_not_touch_smtp(self, pool, monkeypatch):
        monkeypatch.setenv("MAIL_DRY_RUN", "true")

        def explode(account):
            raise AssertionError("dry run opened an SMTP connection")

        pool._connect = explode
        pool.save_accounts([Account(username="a@x.com", password="p")])
        with pool.campaign(throttle=0) as campaign:
            result = campaign.send(
                Message(to_email="u@y.com", subject="s", html="<p>x</p>")
            )
        assert result["success"] is True
        assert result["dry_run"] is True

    def test_works_without_any_account_configured(self, pool, monkeypatch):
        monkeypatch.setenv("MAIL_DRY_RUN", "true")
        monkeypatch.delenv("SMTP_USERNAME", raising=False)
        with pool.campaign(throttle=0) as campaign:
            assert campaign.send(
                Message(to_email="u@y.com", subject="s", html="<p>x</p>")
            )["success"] is True

    def test_off_by_default(self, pool, monkeypatch):
        monkeypatch.delenv("MAIL_DRY_RUN", raising=False)
        from src.mailer import dry_run_enabled
        assert dry_run_enabled() is False


class TestAccounts:
    def test_falls_back_to_environment(self, pool, monkeypatch):
        monkeypatch.setenv("SMTP_USERNAME", "env@x.com")
        monkeypatch.setenv("SMTP_PASSWORD", "secret")
        accounts = pool.load_accounts()
        assert accounts[0].username == "env@x.com"

    def test_no_config_and_no_env_is_empty(self, pool, monkeypatch):
        monkeypatch.delenv("SMTP_USERNAME", raising=False)
        assert pool.load_accounts() == []

    def test_round_trip(self, pool):
        pool.save_accounts([Account(username="a@x.com", password="p", daily_limit=100)])
        loaded = pool.load_accounts()
        assert loaded[0].username == "a@x.com"
        assert loaded[0].daily_limit == 100

    def test_saved_file_is_owner_only(self, pool):
        """The file holds app passwords in clear text."""
        pool.save_accounts([Account(username="a@x.com", password="secret")])
        assert oct(os.stat(pool.config_file).st_mode)[-3:] == "600"

    def test_masked_status_hides_the_password(self, pool):
        pool.save_accounts([Account(username="a@x.com", password="secret")])
        row = pool.status()["accounts"][0]
        assert row["password"] == "********"
        assert row["has_password"] is True
        assert "secret" not in json.dumps(row)

    def test_counters_track_sends(self, pool):
        pool._bump("a@x.com", 5)
        assert pool.sent_today("a@x.com") == 5

    def test_counters_reset_on_a_new_day(self, pool):
        pool._bump("a@x.com", 5)
        with open(pool.counter_file, "w") as handle:
            json.dump({"date": "2020-01-01", "counts": {"a@x.com": 5}}, handle)
        assert pool.sent_today("a@x.com") == 0


class FakeServer:
    """Stand-in for smtplib.SMTP, scripted per test."""

    def __init__(self, fail_with=None, fail_times=0):
        self.fail_with = fail_with
        self.fail_times = fail_times
        self.sent = []
        self.quit_called = False

    def noop(self):
        return (250, b"OK")

    def send_message(self, mime):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise Exception(self.fail_with)
        self.sent.append(mime)

    def quit(self):
        self.quit_called = True


class TestRotation:
    def _campaign(self, pool, accounts, servers):
        pool.save_accounts(accounts)
        campaign = _Campaign(pool, throttle=0)
        made = iter(servers)
        pool._connect = lambda account: next(made)
        return campaign

    def test_reuses_one_connection_across_messages(self, pool):
        """The change that removes a TLS handshake and login per message."""
        server = FakeServer()
        connects = []

        pool.save_accounts([Account(username="a@x.com", password="p")])
        campaign = _Campaign(pool, throttle=0)
        pool._connect = lambda account: (connects.append(account), server)[1]

        for i in range(5):
            campaign.send(Message(to_email=f"u{i}@y.com", subject="s", html="<p>x</p>"))

        assert len(server.sent) == 5
        assert len(connects) == 1, "reconnected instead of reusing the session"

    def test_rotates_to_the_next_account_on_rate_limit(self, pool):
        first = FakeServer(fail_with="550 5.4.5 quota exceeded", fail_times=99)
        second = FakeServer()
        campaign = self._campaign(
            pool,
            [Account(username="a@x.com", password="p"),
             Account(username="b@x.com", password="p")],
            [first, second],
        )
        result = campaign.send(Message(to_email="u@y.com", subject="s", html="<p>x</p>"))
        assert result["success"] is True
        assert result["account"] == "b@x.com"
        assert len(second.sent) == 1

    def test_permanent_failure_does_not_burn_the_pool(self, pool):
        """A bad recipient must fail that message only, leaving accounts usable."""
        server = FakeServer(fail_with="550 5.1.1 No such user", fail_times=1)
        campaign = self._campaign(
            pool,
            [Account(username="a@x.com", password="p"),
             Account(username="b@x.com", password="p")],
            [server, FakeServer()],
        )
        result = campaign.send(Message(to_email="ghost@y.com", subject="s", html="<p>x</p>"))
        assert result["success"] is False
        assert result["kind"] == "permanent"
        assert campaign.available is True

    def test_reports_failure_when_every_account_is_exhausted(self, pool):
        campaign = self._campaign(
            pool,
            [Account(username="a@x.com", password="p"),
             Account(username="b@x.com", password="p")],
            [FakeServer(fail_with="550 5.4.5 quota", fail_times=99),
             FakeServer(fail_with="550 5.4.5 quota", fail_times=99)],
        )
        result = campaign.send(Message(to_email="u@y.com", subject="s", html="<p>x</p>"))
        assert result["success"] is False
        assert campaign.available is False

    def test_accounts_at_their_daily_limit_are_skipped(self, pool):
        pool._bump("a@x.com", 500)
        second = FakeServer()
        campaign = self._campaign(
            pool,
            [Account(username="a@x.com", password="p", daily_limit=500),
             Account(username="b@x.com", password="p", daily_limit=500)],
            [second],
        )
        result = campaign.send(Message(to_email="u@y.com", subject="s", html="<p>x</p>"))
        assert result["account"] == "b@x.com"

    def test_accounts_without_a_password_are_ignored(self, pool):
        pool.save_accounts([Account(username="a@x.com", password="")])
        assert _Campaign(pool).accounts == []

    def test_send_many_reports_progress(self, pool):
        campaign = self._campaign(
            pool, [Account(username="a@x.com", password="p")], [FakeServer()]
        )
        seen = []
        summary = campaign.send_many(
            [Message(to_email=f"u{i}@y.com", subject="s", html="<p>x</p>")
             for i in range(3)],
            on_progress=seen.append,
        )
        assert summary["sent"] == 3
        assert [p["index"] for p in seen] == [1, 2, 3]

    def test_send_many_honours_a_stop_request(self, pool):
        campaign = self._campaign(
            pool, [Account(username="a@x.com", password="p")], [FakeServer()]
        )
        summary = campaign.send_many(
            [Message(to_email=f"u{i}@y.com", subject="s", html="<p>x</p>")
             for i in range(10)],
            should_stop=lambda: True,
        )
        assert summary["sent"] == 0
