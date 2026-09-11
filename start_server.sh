#!/usr/bin/env bash
# Start the coupon system.
#
#   ./start_server.sh            run in the foreground
#   ./start_server.sh --background   detach, logging to logs/server.log
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
BACKGROUND=false
[[ "${1:-}" == "--background" || "${1:-}" == "-b" ]] && BACKGROUND=true

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
warn() { printf '\033[33m!  %s\033[0m\n' "$1"; }
fail() { printf '\033[31mx  %s\033[0m\n' "$1" >&2; exit 1; }
ok()   { printf '\033[32mok\033[0m %s\n' "$1"; }

bold "Event Coupon System"

[[ -f .env ]] || fail ".env not found. Copy .env.example to .env and fill it in."

# Read one value from .env without letting the shell interpret it.
#
# `source .env` is the obvious thing and it is wrong: a Gmail app password is
# displayed as four space-separated words, so an unquoted SMTP_PASSWORD makes
# bash try to run the last three as a command and the script dies before it
# starts anything. Event names and venues have the same problem. The
# application itself reads .env with python-dotenv, which quotes correctly;
# this only extracts the few values the pre-flight checks need.
env_value() {
  local key="$1" line
  line=$(grep -m1 "^[[:space:]]*${key}=" .env 2>/dev/null) || return 0
  line="${line#*=}"
  # Strip one layer of matching quotes, and any trailing comment on a bare value.
  if [[ "$line" =~ ^\"(.*)\"[[:space:]]*$ ]] || [[ "$line" =~ ^\'(.*)\'[[:space:]]*$ ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
  else
    line="${line%%$'\r'}"
    printf '%s' "$line"
  fi
}

SECRET_KEY_VAL=$(env_value SECRET_KEY)
COUPON_KEY_VAL=$(env_value COUPON_SECRET_KEY)
PORT=$(env_value PORT); PORT="${PORT:-5000}"
SSL_ENABLED=$(env_value SSL_ENABLED)
SCANNER_PIN_VAL=$(env_value SCANNER_PIN)
DRY_RUN_VAL=$(env_value MAIL_DRY_RUN)

[[ -n "$SECRET_KEY_VAL" ]] || fail "SECRET_KEY is empty in .env"
[[ -n "$COUPON_KEY_VAL" ]] || fail "COUPON_SECRET_KEY is empty in .env"
ok "configuration loaded"

$PYTHON - <<'PY' || fail "missing dependencies — run: pip install -r requirements.txt"
# importlib.util is not imported by importing importlib alone on 3.12+.
import importlib.util, sys
missing = [m for m in ("flask", "qrcode", "cryptography", "dotenv", "PIL")
           if importlib.util.find_spec(m) is None]
if missing:
    print("missing: " + ", ".join(missing), file=sys.stderr)
sys.exit(1 if missing else 0)
PY
ok "dependencies present"

if command -v ss >/dev/null && ss -ltn "sport = :$PORT" 2>/dev/null | grep -q LISTEN; then
  fail "port $PORT is already in use. Stop the other server first."
fi

# The scanner needs https: browsers refuse camera access on a plain http origin
# that is not localhost, so without a certificate volunteers can only type codes.
if [[ "$SSL_ENABLED" == "true" ]]; then
  if [[ ! -f cert.pem || ! -f key.pem ]]; then
    warn "SSL_ENABLED=true but cert.pem/key.pem are missing — generating a self-signed pair"
    openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem \
      -days 365 -subj "/CN=coupon-system" 2>/dev/null
    chmod 600 key.pem
  fi
  ok "TLS enabled (self-signed — phones will show a warning to accept once)"
  SCHEME=https
else
  warn "SSL is off. Phone cameras will NOT work; only typed codes will."
  SCHEME=http
fi

FLASK_DEBUG_VAL=$(env_value FLASK_DEBUG)
ADMIN_OPEN_VAL=$(env_value DISABLE_ADMIN_CHECK)
if [[ "${FLASK_DEBUG_VAL,,}" == "true" && "${ADMIN_OPEN_VAL,,}" == "true" ]]; then
  printf '\033[31m!! FLASK_DEBUG and DISABLE_ADMIN_CHECK are both on.\033[0m\n'
  printf '   The interactive debugger is reachable from every device on this\n'
  printf '   network, which is remote code execution. Set FLASK_DEBUG=false.\n'
elif [[ "${FLASK_DEBUG_VAL,,}" == "true" ]]; then
  warn "FLASK_DEBUG is on — turn it off before a real event"
fi

[[ -n "$SCANNER_PIN_VAL" ]] || warn "SCANNER_PIN is empty — anyone on this network can redeem coupons"
if [[ "${DRY_RUN_VAL,,}" == "true" ]]; then
  warn "MAIL_DRY_RUN is on — no email will actually be delivered"
fi

LAN_IP=$($PYTHON -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(('8.8.8.8',80));print(s.getsockname()[0]);s.close()" 2>/dev/null || echo 127.0.0.1)

echo
bold "Console   $SCHEME://127.0.0.1:$PORT/"
bold "Scanner   $SCHEME://$LAN_IP:$PORT/scan"
echo

mkdir -p logs data

# serve.py runs the app without the development server or the auto-reloader.
# app.py directly remains the fallback for a checkout without waitress.
if [[ -f serve.py ]]; then
  ENTRY=serve.py
else
  ENTRY=app.py
  warn "serve.py missing — falling back to the development server"
fi

if $BACKGROUND; then
  nohup $PYTHON "$ENTRY" > logs/server.log 2>&1 &
  echo $! > .server.pid
  sleep 3
  if kill -0 "$(cat .server.pid)" 2>/dev/null; then
    ok "running in the background (pid $(cat .server.pid)) via $ENTRY"
    echo "   log:  logs/server.log"
    echo "   stop: kill \$(cat .server.pid)"
  else
    fail "the server exited immediately — see logs/server.log"
  fi
else
  exec $PYTHON "$ENTRY"
fi
