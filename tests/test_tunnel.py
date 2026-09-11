"""Tests for public-tunnel helpers and the access rules that go with them."""

import socket

import pytest

from src.tunnel import (
    ZROK_HOST_SUFFIX, find_free_port, is_public_host, port_is_free,
)


class TestPublicHostDetection:
    """This predicate decides whether the console is reachable, so it must not
    be loose about what counts as the public address."""

    @pytest.mark.parametrize("host", [
        "abc123.shares.zrok.io",
        "abc123.shares.zrok.io:443",
        "ABC123.SHARES.ZROK.IO",
    ])
    def test_recognises_share_hosts(self, host):
        assert is_public_host(host) is True

    @pytest.mark.parametrize("host", [
        "127.0.0.1:5000", "localhost:5000", "10.20.82.147:5000", "", None,
    ])
    def test_local_hosts_are_not_public(self, host):
        assert is_public_host(host) is False

    def test_suffix_is_the_real_zrok_domain(self):
        assert ZROK_HOST_SUFFIX == ".shares.zrok.io"


class TestPorts:
    def test_reports_a_bound_port_as_busy(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            assert port_is_free(port) is False
        finally:
            sock.close()

    def test_reports_an_unbound_port_as_free(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        assert port_is_free(port) is True

    def test_finds_a_free_port(self):
        port = find_free_port(5400, span=40)
        assert port is not None
        assert port_is_free(port)


class TestOrphanReaping:
    """A crash must not leave a public address pointing at a dead port."""

    def test_no_pidfile_is_a_no_op(self, tmp_path):
        from src.tunnel import ZrokTunnel
        assert ZrokTunnel(log_dir=str(tmp_path)).reap_orphan() is False

    def test_unrelated_process_is_never_killed(self, tmp_path):
        """The recorded pid may have been recycled by something else entirely."""
        import os
        from src.tunnel import ZrokTunnel

        tunnel = ZrokTunnel(log_dir=str(tmp_path))
        # Our own pid: alive, but not a zrok share.
        (tmp_path / "zrok.pid").write_text(str(os.getpid()))
        assert tunnel.reap_orphan() is False
        assert not (tmp_path / "zrok.pid").exists()   # stale entry cleared

    def test_garbage_pidfile_is_cleared(self, tmp_path):
        from src.tunnel import ZrokTunnel

        tunnel = ZrokTunnel(log_dir=str(tmp_path))
        (tmp_path / "zrok.pid").write_text("not-a-number")
        assert tunnel.reap_orphan() is False

    def test_dead_pid_is_cleared(self, tmp_path):
        from src.tunnel import ZrokTunnel

        tunnel = ZrokTunnel(log_dir=str(tmp_path))
        (tmp_path / "zrok.pid").write_text("999999")
        assert tunnel.reap_orphan() is False
        assert not (tmp_path / "zrok.pid").exists()


class TestTunnelAccessRules:
    """The guard in app.py is what stops a public share exposing the console."""

    def test_console_is_refused_over_the_tunnel(self, client):
        response = client.get("/", headers={"Host": "abc123.shares.zrok.io"})
        assert response.status_code in (302, 403)

    def test_console_api_is_refused_over_the_tunnel(self, client):
        response = client.get("/api/overview",
                              headers={"Host": "abc123.shares.zrok.io"})
        assert response.status_code == 403

    def test_recipient_list_is_not_exposed(self, client):
        """The most sensitive endpoint: names and addresses of every guest."""
        response = client.get("/api/recipients",
                              headers={"Host": "abc123.shares.zrok.io"})
        assert response.status_code == 403
        assert b"@" not in response.data or b"error" in response.data

    def test_send_controls_are_refused(self, client):
        response = client.post("/api/send/start", json={"template": "invitation"},
                               headers={"Host": "abc123.shares.zrok.io"})
        assert response.status_code == 403

    def test_scanner_routes_reach_the_scanner_not_the_console(self, client,
                                                              monkeypatch):
        """Scanner paths are served (behind the PIN) rather than blocked.

        A 401 here is the PIN gate, not the tunnel guard — the distinction
        matters: the guard returns 403 and would mean the scanner is
        unreachable over the address it exists to serve.
        """
        monkeypatch.setattr(client.app_module, "SCANNER_PIN", "4417")
        page = client.get("/scan", headers={"Host": "abc123.shares.zrok.io"})
        assert page.status_code == 302
        assert "unlock" in page.headers["Location"]

        api = client.post("/api/scan", json={"payload": "000000"},
                          headers={"Host": "abc123.shares.zrok.io"})
        assert api.status_code == 401
        assert api.get_json()["error_code"] == "LOCKED"

    def test_scanner_works_once_unlocked(self, client, monkeypatch):
        monkeypatch.setattr(client.app_module, "SCANNER_PIN", "4417")
        client.post("/scan/unlock", data={"pin": "4417"},
                    headers={"Host": "abc123.shares.zrok.io"})
        response = client.post("/api/scan", json={"payload": "000000"},
                               headers={"Host": "abc123.shares.zrok.io"})
        assert response.status_code in (200, 400, 429)

    def test_static_assets_are_allowed(self, client):
        """The scanner is useless without its stylesheet and QR library."""
        response = client.get("/static/js/app.js",
                              headers={"Host": "abc123.shares.zrok.io"})
        assert response.status_code == 200

    def test_health_is_allowed(self, client):
        response = client.get("/api/health",
                              headers={"Host": "abc123.shares.zrok.io"})
        assert response.status_code == 200

    def test_console_still_works_locally(self, client):
        assert client.get("/api/overview").status_code == 200


class TestPinOverTunnel:
    """The PIN must be unskippable on the public address.

    zrok connects to the application from localhost, so every visitor from the
    internet arrives with remote_addr 127.0.0.1 — an address that is in
    ADMIN_IPS and would otherwise skip the PIN. Publishing the scanner would
    then hand an unauthenticated redemption endpoint to anyone with the URL.
    """

    @pytest.fixture
    def pinned(self, client, monkeypatch):
        monkeypatch.setattr(client.app_module, "SCANNER_PIN", "4417")
        return client

    def test_scanner_page_requires_the_pin(self, pinned):
        response = pinned.get("/scan", headers={"Host": "abc.shares.zrok.io"})
        assert response.status_code == 302
        assert "unlock" in response.headers["Location"]

    def test_scan_api_requires_the_pin(self, pinned):
        response = pinned.post("/api/scan", json={"payload": "123456"},
                               headers={"Host": "abc.shares.zrok.io"})
        assert response.status_code == 401
        assert response.get_json()["error_code"] == "LOCKED"

    def test_localhost_bypass_does_not_apply(self, pinned, monkeypatch):
        """The bypass that made this a hole: admin IP plus open-admin mode."""
        monkeypatch.setattr(client_module(pinned), "OPEN_ADMIN", True)
        response = pinned.get("/scan", headers={"Host": "abc.shares.zrok.io"})
        assert response.status_code == 302

    def test_unlock_page_stays_reachable(self, pinned):
        response = pinned.get("/scan/unlock", headers={"Host": "abc.shares.zrok.io"})
        assert response.status_code == 200

    def test_correct_pin_grants_access(self, pinned):
        pinned.post("/scan/unlock", data={"pin": "4417"},
                    headers={"Host": "abc.shares.zrok.io"})
        response = pinned.get("/scan", headers={"Host": "abc.shares.zrok.io"})
        assert response.status_code == 200

    def test_wrong_pin_is_refused(self, pinned):
        response = pinned.post("/scan/unlock", data={"pin": "0000"},
                               headers={"Host": "abc.shares.zrok.io"})
        assert response.status_code == 401

    def test_a_scanner_session_does_not_open_the_console(self, pinned):
        pinned.post("/scan/unlock", data={"pin": "4417"},
                    headers={"Host": "abc.shares.zrok.io"})
        response = pinned.get("/api/recipients",
                              headers={"Host": "abc.shares.zrok.io"})
        assert response.status_code == 403

    def test_public_access_without_a_pin_configured_is_refused(self, client,
                                                              monkeypatch):
        """Better to serve nothing than an open redemption endpoint."""
        monkeypatch.setattr(client.app_module, "SCANNER_PIN", "")
        response = client.post("/api/scan", json={"payload": "123456"},
                               headers={"Host": "abc.shares.zrok.io"})
        assert response.status_code == 401


def client_module(client):
    return client.app_module


class TestTunnelApi:
    def test_status_reports_the_environment(self, client):
        data = client.get("/api/tunnel").get_json()
        assert data["success"] is True
        assert "installed" in data["environment"]
        assert data["tunnel"]["running"] is False

    def test_starting_without_a_pin_is_refused(self, client):
        """An unprotected scanner on a public URL is the worst case."""
        response = client.post("/api/tunnel/start", json={})
        assert response.status_code == 400
        assert response.get_json()["error_code"] == "NO_PIN"

    def test_stop_is_safe_when_not_running(self, client):
        assert client.post("/api/tunnel/stop").get_json()["success"] is True

    def test_ports_endpoint_lists_availability(self, client):
        data = client.get("/api/ports").get_json()
        assert data["success"] is True
        assert any(p["current"] for p in data["ports"])
