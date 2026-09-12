"""
Public URL for the scanner, via zrok.

At an event the scanner has to run on volunteers' phones, and two things make
that awkward on a LAN: everyone must be on the same wifi, and browsers refuse
camera access over plain http, so a self-signed certificate has to be accepted
on every single phone.

A zrok share solves both. It gives a ``*.shares.zrok.io`` address with a real,
publicly trusted certificate, so the camera works with no warning and the phone
does not even need to be on the venue network.

That convenience is also the danger: the address is on the public internet. The
application refuses everything except scanner routes when a request arrives
through the tunnel (see ``public_host`` and the guard in ``app.py``), so the
operator console is never reachable from outside even while the tunnel is open.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import logging

logger = logging.getLogger(__name__)

# Any host ending in this is a zrok frontend rather than our own LAN address.
ZROK_HOST_SUFFIX = ".shares.zrok.io"

# zrok prints its endpoint inside a JSON log line, e.g.
#   {"msg":"access your zrok share at the following endpoints:\n abc123.shares.zrok.io"}
# Hyphens matter: a reserved name like "iiserkol-coupons" would otherwise be
# parsed as just "coupons", and every check would then run against the wrong
# address and report a 404 that looks like a backend fault.
_URL_RE = re.compile(r"([a-z0-9](?:[a-z0-9-]{4,62}))\.shares\.zrok\.io")

STARTUP_TIMEOUT = 45.0

# The share's pid is recorded so a restart can clean up after a crash.
#
# PR_SET_PDEATHSIG looks like the obvious way to tie the child's lifetime to
# ours, but it is the wrong tool here: the kernel tracks the creating *thread*,
# and the tunnel is started from a Flask request handler — the share would be
# killed the instant that request finished. A pidfile reaped at startup is
# deterministic and has no such trap.
PID_FILENAME = "zrok.pid"

# A share with no reserved name gets a fresh random subdomain every time it
# starts, so the address volunteers were given dies with any restart. A
# reserved name in the public namespace keeps one stable address across
# restarts — the thing you can print on a poster.
NAME_CONFLICT = "already in use by another share"
NAME_RETRIES = 5
NAME_RETRY_WAIT = 4.0


def find_zrok() -> Optional[str]:
    """Locate the zrok binary, including the usual per-user install path."""
    found = shutil.which("zrok")
    if found:
        return found
    for candidate in (
        os.path.expanduser("~/.local/bin/zrok"),
        os.path.expanduser("~/bin/zrok"),
        "/usr/local/bin/zrok",
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def port_is_free(port: int, host: str = "0.0.0.0") -> bool:
    """Whether a TCP port can be bound right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def port_owner(port: int) -> str:
    """Best-effort description of what is holding a port, for the UI."""
    try:
        out = subprocess.run(
            ["ss", "-ltnp", f"sport = :{port}"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        match = re.search(r'users:\(\("([^"]+)",pid=(\d+)', out)
        if match:
            return f"{match.group(1)} (pid {match.group(2)})"
    except (OSError, subprocess.SubprocessError):
        pass
    return "another process"


def find_free_port(start: int = 5000, span: int = 40) -> Optional[int]:
    for port in range(start, start + span):
        if port_is_free(port):
            return port
    return None


@dataclass
class TunnelState:
    """What the UI needs to know about the tunnel."""

    running: bool = False
    url: Optional[str] = None
    port: Optional[int] = None
    started_at: Optional[float] = None
    error: Optional[str] = None
    status: str = "stopped"          # stopped | starting | running | failed
    reserved_name: Optional[str] = None
    log_tail: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        uptime = time.time() - self.started_at if self.started_at else 0
        return {
            "running": self.running,
            "url": self.url,
            "scanner_url": f"{self.url}/scan" if self.url else None,
            "port": self.port,
            "status": self.status,
            "reserved_name": self.reserved_name,
            "stable": bool(self.reserved_name),
            "error": self.error,
            "uptime_seconds": round(uptime) if self.started_at else 0,
            "log_tail": self.log_tail[-12:],
        }


class ZrokTunnel:
    """Starts, watches and stops a ``zrok share public`` process."""

    def __init__(self, log_dir: str = "logs"):
        self.binary = find_zrok()
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self.log_path = os.path.join(log_dir, "zrok.log")
        self.pid_path = os.path.join(log_dir, PID_FILENAME)
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._state = TunnelState()
        self._reader: Optional[threading.Thread] = None

    # ------------------------------------------------------------ diagnostics

    def names(self) -> List[Dict[str, str]]:
        """Reserved names on this account, from ``zrok overview``."""
        if not self.binary:
            return []
        try:
            out = subprocess.run(
                [self.binary, "overview"], capture_output=True, text=True, timeout=25
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        rows = []
        for line in out.splitlines():
            if ".shares.zrok.io" not in line or "│" not in line:
                continue
            cells = [c.strip() for c in line.split("│") if c.strip()]
            if len(cells) >= 4 and cells[3].lower() == "true":
                rows.append({
                    "url": cells[0],
                    "name": cells[0].split(".")[0],
                    "in_use": cells[2] not in ("-", ""),
                })
        return rows

    def prune_stale_shares(self, port: int) -> int:
        """Delete share registrations left behind for this application's port.

        A share is a record on the zrok account, not just a local process.
        Killing the process — or restarting the machine — leaves the record,
        and they accumulate: enough of them and the controller starts refusing
        new shares with "invalid session", which looks nothing like the actual
        cause. This was diagnosed the hard way, with a share still registered
        against a test port from an earlier run blocking every new share.

        Only shares whose target is this port on this machine are removed, so
        anything else the operator uses zrok for is left alone.
        """
        if not self.binary:
            return 0
        try:
            out = subprocess.run(
                [self.binary, "overview"], capture_output=True, text=True, timeout=30
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return 0

        # `overview` groups shares under an environment header. Only act inside
        # the block for this host, so another machine's shares are untouched.
        host = socket.gethostname()
        mine = False
        targets = (f"localhost:{port}", f"127.0.0.1:{port}")
        tokens = []
        for line in out.splitlines():
            if line.startswith(">") or "envZId" in line:
                mine = host in line
                continue
            if not mine or "│" not in line:
                continue
            cells = [c.strip() for c in line.split("│") if c.strip()]
            if len(cells) >= 4 and any(t in cells[3] for t in targets):
                tokens.append(cells[0])

        removed = 0
        for token in tokens:
            try:
                result = subprocess.run(
                    [self.binary, "delete", "share", token],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0:
                    logger.warning("Removed a stale zrok share (%s)", token)
                    removed += 1
            except (OSError, subprocess.SubprocessError):
                pass
        return removed

    def ensure_name(self, name: str) -> Dict[str, Any]:
        """Reserve ``name`` if this account does not already hold it."""
        if not self.binary:
            return {"success": False, "error": "zrok is not installed."}
        if any(n["name"] == name for n in self.names()):
            return {"success": True, "created": False}
        try:
            result = subprocess.run(
                [self.binary, "create", "name", name],
                capture_output=True, text=True, timeout=40,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"success": False, "error": str(exc)}
        output = result.stdout + result.stderr
        if result.returncode != 0 or "[ERROR]" in output:
            detail = output.strip().splitlines()[-1] if output.strip() else "unknown error"
            if "already" in detail.lower() or "conflict" in detail.lower():
                return {
                    "success": False,
                    "error": f"The name '{name}' is taken by another zrok account. "
                             f"Pick a different one.",
                }
            return {"success": False, "error": detail[:300]}
        logger.info("Reserved zrok name %r", name)
        return {"success": True, "created": True}

    def environment(self) -> Dict[str, Any]:
        """Whether zrok is installed and the account environment is enabled.

        Reported to the UI so a missing step produces an instruction rather
        than a failed start with an opaque error.
        """
        if not self.binary:
            return {
                "installed": False, "enabled": False,
                "hint": "zrok is not installed. Get it from https://zrok.io "
                        "and put the binary on your PATH.",
            }
        try:
            result = subprocess.run(
                [self.binary, "status"], capture_output=True, text=True, timeout=20
            )
            output = result.stdout + result.stderr
            enabled = "Account Token" in output and "<<SET>>" in output
            return {
                "installed": True,
                "enabled": enabled,
                "version": self._version(),
                "hint": None if enabled else
                        "zrok is installed but this machine is not enabled. Run "
                        "`zrok enable <your-token>` in a terminal, then reload.",
            }
        except (OSError, subprocess.SubprocessError) as exc:
            return {"installed": True, "enabled": False, "hint": str(exc)}

    def _version(self) -> str:
        try:
            out = subprocess.run(
                [self.binary, "version"], capture_output=True, text=True, timeout=15
            ).stdout
            match = re.search(r"v[\d.]+", out)
            return match.group(0) if match else "unknown"
        except (OSError, subprocess.SubprocessError):
            return "unknown"

    # ----------------------------------------------------------------- state

    def state(self) -> TunnelState:
        with self._lock:
            # A share that died leaves a stale "running" flag otherwise.
            if self._process is not None and self._process.poll() is not None:
                if self._state.running:
                    self._state.running = False
                    self._state.status = "failed"
                    self._state.error = (
                        f"The zrok share stopped unexpectedly "
                        f"(exit code {self._process.returncode}). See logs/zrok.log."
                    )
                    logger.warning("zrok share exited: %s", self._process.returncode)
            return self._state

    # ----------------------------------------------------------------- start

    def start(self, port: int, basic_auth: Optional[str] = None,
              backend_https: bool = False,
              reserved_name: Optional[str] = None) -> Dict[str, Any]:
        """Open a public share pointing at ``port``.

        ``backend_https`` must match how the application is actually serving.
        zrok speaks plain http to its target by default, so pointing it at a
        TLS listener produces a share that starts cleanly, reports "live", and
        then answers every request with 502 — the worst kind of failure, since
        the console says everything is fine while volunteers hold a dead link.
        With TLS the target needs an explicit scheme, and --insecure because
        the certificate is self-signed.

        Blocks until zrok reports an endpoint or the timeout expires, so the UI
        can show the address immediately rather than polling for it.
        """
        with self._lock:
            if self._state.running and self._process and self._process.poll() is None:
                return {"success": True, "already_running": True,
                        **self._state.as_dict()}

        if not self.binary:
            return {"success": False,
                    "error": "zrok is not installed on this machine."}

        env = self.environment()
        if not env.get("enabled"):
            return {"success": False, "error": env.get("hint", "zrok is not enabled.")}

        if port_is_free(port):
            return {
                "success": False,
                "error": f"Nothing is listening on port {port}. Start the "
                         f"application first, then open the tunnel.",
            }

        if backend_https:
            target = f"https://localhost:{port}"
            command = [self.binary, "share", "public", target, "--headless",
                       "--insecure"]
        else:
            command = [self.binary, "share", "public", f"localhost:{port}",
                       "--headless"]
        if basic_auth:
            command += ["--basic-auth", basic_auth]
        if reserved_name:
            ready = self.ensure_name(reserved_name)
            if not ready["success"]:
                return {"success": False, "error": ready["error"]}
            # namespace:name — the bare name is read as a namespace token.
            command += ["-n", f"public:{reserved_name}"]

        logger.info("Starting zrok share for port %d", port)
        self.prune_stale_shares(port)

        attempts = NAME_RETRIES if reserved_name else 1
        for attempt in range(attempts):
            outcome = self._spawn(command, port, reserved_name, backend_https)
            if outcome is not None:
                return outcome
            # A share that has just stopped keeps its name for a couple of
            # seconds. Restarting the application lands inside that window, so
            # wait it out rather than failing the operator's first click.
            if attempt < attempts - 1:
                logger.info(
                    "Name %r is still held by the previous share; retrying",
                    reserved_name,
                )
                time.sleep(NAME_RETRY_WAIT)
        return {
            "success": False,
            "error": f"The name '{reserved_name}' is still attached to a share "
                     f"that has not finished shutting down. Wait a few seconds "
                     f"and try again.",
            "log_tail": self._log_tail(10),
        }

    def _spawn(self, command, port: int, reserved_name: Optional[str],
               backend_https: bool) -> Optional[Dict[str, Any]]:
        """One attempt. Returns None when the name was busy and a retry is due."""
        log_file = open(self.log_path, "w", encoding="utf-8")
        try:
            process = subprocess.Popen(
                command, stdout=log_file, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                # Its own session, so stopping the share never signals the
                # application that started it.
                start_new_session=True,
            )
        except OSError as exc:
            log_file.close()
            return {"success": False, "error": f"Could not start zrok: {exc}"}

        with self._lock:
            self._process = process
            self._state = TunnelState(status="starting", port=port,
                                      started_at=time.time(),
                                      reserved_name=reserved_name)
        self._write_pid(process.pid)

        url = self._await_url(process, STARTUP_TIMEOUT)
        log_file.close()

        if url is None:
            conflict = NAME_CONFLICT in self._raw_log()
            self.stop()
            if conflict and reserved_name:
                return None                     # caller retries
            return {
                "success": False,
                "error": "zrok did not report a public address within "
                         f"{int(STARTUP_TIMEOUT)}s. See logs/zrok.log.",
                "log_tail": self._log_tail(14),
            }

        reachable, detail = self._probe(url)
        if not reachable:
            self.stop()
            return {
                "success": False,
                "error": f"The share opened but does not serve traffic ({detail}). "
                         f"This usually means the backend scheme is wrong — the "
                         f"application is serving {'https' if backend_https else 'http'}.",
                "log_tail": self._log_tail(10),
            }

        with self._lock:
            self._state.running = True
            self._state.status = "running"
            self._state.url = url
            self._state.error = None
            self._state.log_tail = self._log_tail(6)

        logger.info("zrok share live at %s", url)
        return {"success": True, **self.state().as_dict()}

    def _probe(self, url: str, attempts: int = 4) -> tuple:
        """Fetch the health endpoint through the share before reporting success.

        A share whose target scheme is wrong starts perfectly and then 502s
        everything. Checking here turns that into an error the operator sees
        immediately, rather than a broken link handed to volunteers.
        """
        import urllib.error
        import urllib.request

        request = urllib.request.Request(
            f"{url}/api/health",
            headers={"skip_zrok_interstitial": "true",
                     "User-Agent": "coupon-system-selfcheck"},
        )
        last = "no response"
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    if response.status == 200:
                        return True, "ok"
                    last = f"HTTP {response.status}"
            except urllib.error.HTTPError as exc:
                last = f"HTTP {exc.code}"
            except Exception as exc:  # noqa: BLE001 - reported to the operator
                last = str(exc)[:80]
            time.sleep(1.5 * (attempt + 1))
        return False, last

    def _await_url(self, process: subprocess.Popen, timeout: float) -> Optional[str]:
        """Watch the log until zrok prints an endpoint, or give up."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if process.poll() is not None:
                return None
            try:
                with open(self.log_path, "r", encoding="utf-8") as handle:
                    content = handle.read()
            except OSError:
                content = ""
            match = _URL_RE.search(content)
            if match:
                # Give the data plane a moment to bind before declaring success;
                # the endpoint is printed slightly before it accepts traffic.
                time.sleep(2.0)
                return f"https://{match.group(0)}"
            if "invalid session" in content:
                logger.error("zrok reported an invalid session")
                return None
            if NAME_CONFLICT in content:
                return None
            time.sleep(0.4)
        return None

    def _raw_log(self) -> str:
        try:
            with open(self.log_path, "r", encoding="utf-8") as handle:
                return handle.read()
        except OSError:
            return ""

    def _log_tail(self, lines: int) -> List[str]:
        """Readable tail of the log — zrok writes JSON lines, so unwrap them."""
        try:
            with open(self.log_path, "r", encoding="utf-8") as handle:
                raw = handle.readlines()[-lines * 3:]
        except OSError:
            return []
        out: List[str] = []
        for line in raw:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                message = str(entry.get("msg", "")).replace("\n", " ").strip()
                if message:
                    out.append(f"{entry.get('level', 'info').lower()}: {message}")
            except ValueError:
                out.append(line)
        return out[-lines:]

    # --------------------------------------------------------------- pidfile

    def _write_pid(self, pid: int):
        try:
            with open(self.pid_path, "w", encoding="utf-8") as handle:
                handle.write(str(pid))
        except OSError:
            pass

    def _clear_pid(self):
        try:
            os.remove(self.pid_path)
        except OSError:
            pass

    def reap_orphan(self) -> bool:
        """Close a share left behind by a previous run.

        Called at startup. Without it a crash leaves a public address pointing
        at a port nothing answers on, with no console running to close it from.
        The command line is verified before signalling, because the recorded pid
        may since have been recycled by an unrelated process.
        """
        try:
            with open(self.pid_path, encoding="utf-8") as handle:
                pid = int(handle.read().strip())
        except (OSError, ValueError):
            return False

        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                cmdline = handle.read().decode(errors="replace")
        except OSError:
            self._clear_pid()
            return False

        if "zrok" not in cmdline or "share" not in cmdline:
            self._clear_pid()
            return False

        logger.warning(
            "Closing a zrok share left over from a previous run (pid %d)", pid
        )
        try:
            os.kill(pid, 15)
            for _ in range(20):
                time.sleep(0.25)
                if not os.path.exists(f"/proc/{pid}"):
                    break
            else:
                os.kill(pid, 9)
        except (ProcessLookupError, PermissionError):
            pass
        self._clear_pid()
        return True

    # ------------------------------------------------------------------ stop

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            process = self._process
            port = self._state.port
            self._process = None
            self._state = TunnelState(status="stopped")

        self._clear_pid()
        if process is None or process.poll() is not None:
            return {"success": True, "already_stopped": True}

        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        logger.info("zrok share stopped")
        if port:
            # A terminated share usually deregisters itself; a killed one does
            # not, and the record would block the next start.
            self.prune_stale_shares(port)
        return {"success": True}

    def __del__(self):
        try:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
        except Exception:  # noqa: BLE001 - interpreter shutdown
            pass


def is_public_host(host: str) -> bool:
    """Whether this request arrived through the public tunnel.

    Used to decide what a request is allowed to reach. Host is client-supplied,
    so this is only ever used to *restrict* access, never to grant it — a forged
    header can lock someone out of the console, which is harmless, but cannot
    let them in.
    """
    return ZROK_HOST_SUFFIX in (host or "").lower()
