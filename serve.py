#!/usr/bin/env python3
"""
Production entry point.

Runs the application under waitress instead of Flask's development server:
a real thread pool, connection limits, no interactive debugger, and no
auto-reloader executing the module twice.

**This application must run as a single process.** Several things live in
memory and are shared across requests rather than stored in the database:

* the send job registry, which the console polls for progress,
* parsed CSV uploads awaiting a confirmed column mapping,
* the zrok tunnel handle, and
* the outbox worker thread.

Under a multi-worker server each worker would hold its own copy, so polling a
send would hit a worker that has never heard of it, and every worker would run
its own outbox. waitress is single-process with a thread pool, which is exactly
the shape this needs. Do not swap it for `gunicorn -w 4`.

TLS: waitress does not terminate TLS. Two ways to get https, which phone
cameras require:

* the zrok share, which provides a publicly trusted certificate (preferred —
  Settings -> Go live), or
* `SSL_ENABLED=true`, which falls back to the built-in server with the
  self-signed pair, for a LAN-only event with no internet.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("coupons.serve")

THREADS = int(os.getenv("SERVER_THREADS", "16"))

# Reopening the public share after a restart is opt-in. Publishing to the
# internet should normally be a deliberate click, but a machine that reboots
# mid-event would otherwise leave every volunteer holding a dead link with
# nobody watching the console to notice.
AUTOSTART_TUNNEL = os.getenv("ZROK_AUTOSTART", "false").lower() in ("1", "true", "yes")

# Logs are appended to across restarts and nothing trims them. A week of idle
# running produced 1.3MB of application log and 10MB from zrok. Rotating once
# at startup bounds it without needing logrotate on a laptop.
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(8 * 1024 * 1024)))


def rotate_large_logs(directory: str = "logs") -> None:
    for name in ("server.log", "zrok.log"):
        path = os.path.join(directory, name)
        try:
            if os.path.getsize(path) > LOG_MAX_BYTES:
                os.replace(path, path + ".1")
                logger.info("Rotated %s (over %d bytes)", path, LOG_MAX_BYTES)
        except OSError:
            pass


def open_tunnel_later(tunnel, port: int, name: str) -> None:
    """Reopen the share once the server is actually accepting connections.

    zrok refuses to start against a port nothing is listening on, and starting
    takes some seconds, so this runs on a background thread rather than
    delaying startup.
    """
    def run():
        time.sleep(3)
        serving_https = os.getenv("SSL_ENABLED", "false").lower() in ("1", "true", "yes") \
            and os.path.exists("cert.pem")
        result = tunnel.start(port, backend_https=serving_https,
                              reserved_name=name or None)
        if result.get("success"):
            logger.info("Public share reopened at %s", result.get("url"))
        else:
            logger.error("Could not reopen the public share: %s",
                         result.get("error"))

    threading.Thread(target=run, name="tunnel-autostart", daemon=True).start()


def main() -> int:
    # Force the reloader off before importing the app: with FLASK_DEBUG left on,
    # module-level start-up would run twice and start two outbox workers.
    os.environ["FLASK_DEBUG"] = "false"

    rotate_large_logs()

    from app import (  # noqa: E402
        APP_PORT, SERVER_IP, SCANNER_PIN, app, event_settings, outbox, tunnel,
    )

    if AUTOSTART_TUNNEL:
        if not SCANNER_PIN:
            logger.error(
                "ZROK_AUTOSTART is on but SCANNER_PIN is not set — refusing to "
                "publish an unprotected scanner."
            )
        else:
            open_tunnel_later(tunnel, APP_PORT,
                              event_settings().get("zrok_name", ""))

    ssl_wanted = os.getenv("SSL_ENABLED", "false").lower() in ("1", "true", "yes")
    have_certs = os.path.exists("cert.pem") and os.path.exists("key.pem")

    if ssl_wanted and have_certs:
        # Werkzeug prints "development server" here. With debug off this is a
        # plain threaded WSGI server, and it sustained ~350 scans/sec with ten
        # concurrent scanners in testing — far past what a door produces. The
        # reason to accept it over waitress is resilience: it is the only way
        # to serve https on the local network without a reverse proxy, which is
        # what keeps phone cameras working if the venue has no internet and the
        # public share is unavailable.
        print(f"  Console   https://127.0.0.1:{APP_PORT}/")
        print(f"  Scanner   https://{SERVER_IP}:{APP_PORT}/scan")
        print("  TLS on, debug off. Serving locally so cameras work without")
        print("  internet. Set SSL_ENABLED=false to use waitress instead and")
        print("  rely on the public share for https.")
        app.run(host="0.0.0.0", port=APP_PORT, debug=False, threaded=True,
                ssl_context=("cert.pem", "key.pem"), use_reloader=False)
        return 0

    from waitress import serve  # noqa: E402

    if not SCANNER_PIN:
        logger.warning(
            "SCANNER_PIN is not set. Anyone who can reach this machine can "
            "redeem coupons, and the public share will refuse to start."
        )

    print(f"  Console   http://127.0.0.1:{APP_PORT}/")
    print(f"  Scanner   http://{SERVER_IP}:{APP_PORT}/scan")
    print(f"  Serving with waitress, {THREADS} threads, single process.")
    print("  Phone cameras need https: publish the scanner from Settings.")

    try:
        serve(
            app,
            host="0.0.0.0",
            port=APP_PORT,
            threads=THREADS,
            # An event is a burst of short requests; a generous backlog keeps a
            # rush at the door from being refused at the socket.
            backlog=256,
            connection_limit=200,
            channel_timeout=120,
            ident="Event Coupon System",
            # The send console polls progress; without this, an idle keep-alive
            # connection can hold a thread for the whole run.
            cleanup_interval=30,
        )
    except KeyboardInterrupt:
        pass
    finally:
        outbox.stop(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
