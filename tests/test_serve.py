"""Tests for the production entry point's helpers.

serve.py had no coverage: it is short, but what it does — deciding whether to
publish the scanner to the internet, and trimming logs — is exactly the kind of
thing that should not be discovered to be wrong during an event.
"""

import importlib

import pytest


def _reload(monkeypatch, tmp_path):
    """Reload serve.py without .env repopulating the environment.

    load_dotenv() resolves relative to serve.py rather than the working
    directory, so chdir does not isolate it: a value in the project's real .env
    silently wins over a variable the test just cleared.
    """
    monkeypatch.chdir(tmp_path)
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    import serve as module
    monkeypatch.setattr(module, "load_dotenv", lambda *a, **k: False, raising=False)
    return importlib.reload(module)


@pytest.fixture
def serve(monkeypatch, tmp_path):
    return _reload(monkeypatch, tmp_path)


class TestLogRotation:
    """A week of idle running produced 10MB of zrok log and 1.3MB of app log,
    appended across restarts with nothing trimming them."""

    def test_rotates_a_large_log(self, serve, tmp_path):
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "server.log").write_bytes(b"x" * (serve.LOG_MAX_BYTES + 1))
        serve.rotate_large_logs("logs")
        assert (logs / "server.log.1").exists()
        assert not (logs / "server.log").exists()

    def test_leaves_a_small_log_alone(self, serve, tmp_path):
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "server.log").write_bytes(b"x" * 100)
        serve.rotate_large_logs("logs")
        assert (logs / "server.log").exists()
        assert not (logs / "server.log.1").exists()

    def test_missing_log_is_not_an_error(self, serve, tmp_path):
        (tmp_path / "logs").mkdir()
        serve.rotate_large_logs("logs")        # must not raise

    def test_missing_directory_is_not_an_error(self, serve):
        serve.rotate_large_logs("no-such-directory")

    def test_rotates_the_zrok_log_too(self, serve, tmp_path):
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "zrok.log").write_bytes(b"y" * (serve.LOG_MAX_BYTES + 1))
        serve.rotate_large_logs("logs")
        assert (logs / "zrok.log.1").exists()


class TestTunnelAutostart:
    def test_off_by_default(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ZROK_AUTOSTART", raising=False)
        assert _reload(monkeypatch, tmp_path).AUTOSTART_TUNNEL is False

    @pytest.mark.parametrize("value,expected", [
        ("true", True), ("1", True), ("yes", True),
        ("false", False), ("", False), ("no", False),
    ])
    def test_reads_the_flag(self, monkeypatch, tmp_path, value, expected):
        monkeypatch.setenv("ZROK_AUTOSTART", value)
        assert _reload(monkeypatch, tmp_path).AUTOSTART_TUNNEL is expected

    def test_opens_against_the_right_scheme(self, serve, monkeypatch):
        """zrok speaks plain http to its target unless told otherwise; pointing
        it at a TLS listener yields a share that reports live and 502s."""
        monkeypatch.setenv("SSL_ENABLED", "true")
        (serve.os.path.exists("cert.pem") or open("cert.pem", "w").write("x"))
        calls = {}

        class FakeTunnel:
            def start(self, port, backend_https=False, reserved_name=None):
                calls.update(port=port, backend_https=backend_https,
                             reserved_name=reserved_name)
                return {"success": True, "url": "https://x.shares.zrok.io"}

        serve.open_tunnel_later(FakeTunnel(), 5000, "my-name")
        deadline = serve.time.time() + 10
        while serve.time.time() < deadline and "port" not in calls:
            serve.time.sleep(0.1)
        assert calls.get("backend_https") is True
        assert calls.get("reserved_name") == "my-name"
        assert calls.get("port") == 5000
