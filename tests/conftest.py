"""Shared test fixtures.

The `client` fixture builds a fully isolated application: its own database, its
own working directory, and a mailer that records instead of delivering. All
three matter — the predecessor of this suite sent real email and wiped the
production database when it ran.
"""

import importlib
import os
import sys

import pytest


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


