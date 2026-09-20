"""Shared test fixtures.

The `client` fixture builds a fully isolated application: its own database, its
own working directory, and a mailer that records instead of delivering. All
three matter — the predecessor of this suite sent real email and wiped the
production database when it ran.

A fourth thing matters just as much, and was missing: importing the app starts a
background sender thread, and the fixture has to stop it. It did not. Every test
left one running, and at teardown monkeypatch handed those threads back the real
mailer, the real working directory and the real .env credentials — so a
thank-you queued by a scanner test was delivered for real, seconds after the
test that queued it had passed. It stayed invisible only because the stored
account happened to be unusable; the moment a working one was configured, the
suite started sending.

So isolation here is layered, and no single layer is trusted:

  1. the worker is stopped and joined before the fixture returns
  2. MAIL_DRY_RUN is on, so delivery is refused even with a live account
  3. the SMTP credentials are blanked, so there is no account to send with
  4. the socket itself is blocked, so an attempt raises instead of connecting
"""

import importlib
import os
import sys
import threading

import pytest


@pytest.fixture(scope="session", autouse=True)
def _no_sender_outlives_the_session():
    """Fail the run if any background sender is still alive at the end.

    The per-test stop is the real fix; this is the alarm that goes off if some
    future change starts a sender the fixture does not know about. A leaked
    thread is silent — it sends after the test that created it has already
    reported success — so the suite has to check rather than assume.
    """
    yield
    alive = [t.name for t in threading.enumerate()
             if t.is_alive() and "outbox" in t.name.lower()]
    assert not alive, (
        "background sender(s) still running at the end of the session: "
        f"{alive}. They hold the real mailer and will deliver for real."
    )


@pytest.fixture(autouse=True)
def _hermetic_environment(monkeypatch):
    """Clear settings that would otherwise leak in from the developer's shell.

    MAIL_DRY_RUN in particular: with it exported, the mailer short-circuits and
    six rotation tests fail for reasons that have nothing to do with the code.
    A suite whose result depends on the surrounding shell cannot be trusted to
    say whether anything is broken. Tests that need these set them explicitly.

    Clearing a variable is not always enough: load_dotenv() resolves relative to
    the module that calls it, not the working directory, so a module reloaded
    during a test can pick the value straight back up out of the project's real
    .env. Tests that reload a module stub load_dotenv out as well.
    """
    for name in ("MAIL_DRY_RUN", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_HOST",
                 "SMTP_PORT", "SMTP_SENDER_NAME", "SMTP_SENDER_EMAIL",
                 "ZROK_RESERVED_NAME", "SCANNER_PIN", "THANK_YOU_TEMPLATE",
                 "TRUST_PROXY", "ADMIN_EXTRA_IPS", "ZROK_AUTOSTART"):
        monkeypatch.delenv(name, raising=False)


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
    # Pinned, not merely cleared. load_dotenv() reads the project's real .env
    # relative to app.py, and it does not override a variable that is already
    # set — so deleting these lets the operator's own configuration decide what
    # the suite asserts. Pointing THANK_YOU_TEMPLATE at the ICOC design, as a
    # live deployment does, silently broke a test about a *missing* template.
    monkeypatch.setenv("THANK_YOU_TEMPLATE", "thank_you")
    monkeypatch.setenv("EVENT_TIMEZONE", "Asia/Kolkata")
    # Layers 2 and 3. Scoped to this fixture rather than set globally: the
    # mailer's own rotation tests need dry run off to exercise the real send
    # path against a mocked socket.
    monkeypatch.setenv("MAIL_DRY_RUN", "true")
    monkeypatch.setenv("SMTP_USERNAME", "")
    monkeypatch.setenv("SMTP_PASSWORD", "")
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

    def _no_sockets(account):
        raise AssertionError(
            f"A test tried to open a real SMTP connection to {account.host}. "
            "Nothing in this suite may reach a mail server."
        )

    # Layer 4. The pool is the only thing that opens a socket, and the outbox
    # worker shares this instance, so this covers the background sender too.
    monkeypatch.setattr(app_module.mailer, "_connect", _no_sockets)

    try:
        with app_module.app.test_client() as test_client:
            test_client.app_module = app_module
            test_client.sent = sent
            yield test_client
    finally:
        # Layer 1, and the one that actually matters. Importing the app started
        # this thread; monkeypatch is about to give it back the real mailer and
        # the real working directory, so it has to be stopped first. Stop it
        # before anything else unwinds.
        app_module.outbox.stop(timeout=10)
        assert not app_module.outbox.running, (
            "the background sender outlived its test — it would send for real"
        )
        sys.modules.pop("app", None)


