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
set -a; source .env; set +a

[[ -n "${SECRET_KEY:-}" ]] || fail "SECRET_KEY is empty in .env"
[[ -n "${COUPON_SECRET_KEY:-}" ]] || fail "COUPON_SECRET_KEY is empty in .env"
ok "configuration loaded"

$PYTHON - <<'PY' || fail "missing dependencies — run: pip install -r requirements.txt"
import importlib, sys
missing = [m for m in ("flask", "qrcode", "cryptography", "dotenv", "PIL")
           if not importlib.util.find_spec(m)]
sys.exit(1 if missing else 0)
PY
ok "dependencies present"

PORT="${PORT:-5000}"
if command -v ss >/dev/null && ss -ltn "sport = :$PORT" 2>/dev/null | grep -q LISTEN; then
  fail "port $PORT is already in use. Stop the other server first."
fi

# The scanner needs https: browsers refuse camera access on a plain http origin
# that is not localhost, so without a certificate volunteers can only type codes.
if [[ "${SSL_ENABLED:-false}" == "true" ]]; then
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

[[ -n "${SCANNER_PIN:-}" ]] || warn "SCANNER_PIN is empty — anyone on this network can redeem coupons"

LAN_IP=$($PYTHON -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(('8.8.8.8',80));print(s.getsockname()[0]);s.close()" 2>/dev/null || echo 127.0.0.1)

echo
bold "Console   $SCHEME://127.0.0.1:$PORT/"
bold "Scanner   $SCHEME://$LAN_IP:$PORT/scan"
echo

mkdir -p logs data
if $BACKGROUND; then
  nohup $PYTHON app.py > logs/server.log 2>&1 &
  echo $! > .server.pid
  sleep 2
  ok "running in the background (pid $(cat .server.pid)), logging to logs/server.log"
  echo "   stop with: kill \$(cat .server.pid)"
else
  exec $PYTHON app.py
fi
