#!/bin/bash
# ============================================================
# 21MS Farewell Party - Server Startup Script
# ============================================================
# This script starts the Flask server with all checks.
# Usage: ./start_server.sh
# ============================================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
BOLD='\033[1m'

PYTHON="/home/shuvam/.global-pymaster/bin/python"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

echo -e "${BOLD}"
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║       21MS Farewell Party Server            ║"
echo "  ║      IISER Kolkata | The Class of 2027       ║"
echo "  ╚══════════════════════════════════════════════╝"
echo -e "${NC}"

# ---- Check Python ----
echo -e "${YELLOW}[1] Checking Python environment...${NC}"
if [ ! -f "$PYTHON" ]; then
    echo -e "${RED}  ✗ Python not found at $PYTHON${NC}"
    echo "    Please ensure /home/shuvam/.global-pymaster exists"
    exit 1
fi
echo -e "${GREEN}  ✓ Python: $($PYTHON --version)${NC}"

# ---- Check .env ----
echo -e "${YELLOW}[2] Checking configuration...${NC}"
if [ ! -f ".env" ]; then
    echo -e "${RED}  ✗ .env file not found!${NC}"
    echo "    Run: cp .env.example .env"
    echo "    Then edit .env with your credentials"
    exit 1
fi
echo -e "${GREEN}  ✓ .env file found${NC}"

# ---- Check SECRET_KEY ----
SECRET_KEY=$($PYTHON -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('SECRET_KEY', '')[:8])" 2>/dev/null)
if [ -z "$SECRET_KEY" ] || [ "$SECRET_KEY" = "your-sup" ]; then
    echo -e "${RED}  ✗ SECRET_KEY is not configured in .env${NC}"
    echo "    Generate one with:"
    echo "    $PYTHON -c \"import secrets; print(secrets.token_hex(32))\""
    exit 1
fi
echo -e "${GREEN}  ✓ SECRET_KEY configured${NC}"

# ---- Check COUPON_SECRET_KEY ----
COUPON_KEY=$($PYTHON -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('COUPON_SECRET_KEY', '')[:8])" 2>/dev/null)
if [ -z "$COUPON_KEY" ] || [ "$COUPON_KEY" = "your-32-" ]; then
    echo -e "${RED}  ✗ COUPON_SECRET_KEY is not configured in .env${NC}"
    echo "    Generate one with:"
    echo "    $PYTHON -c \"import secrets; print(secrets.token_hex(32))\""
    exit 1
fi
echo -e "${GREEN}  ✓ COUPON_SECRET_KEY configured${NC}"

# ---- Check SMTP Config ----
SMTP_USER=$($PYTHON -c "
import json, os
if os.path.exists('smtp_config.json'):
    with open('smtp_config.json') as f:
        c = json.load(f)
        print(c.get('username',''))
elif os.getenv('SMTP_USERNAME'):
    print(os.getenv('SMTP_USERNAME'))
" 2>/dev/null)
if [ -z "$SMTP_USER" ]; then
    echo -e "${YELLOW}  ⚠ SMTP not configured (will be set via UI)${NC}"
else
    echo -e "${GREEN}  ✓ SMTP configured for: $SMTP_USER${NC}"
fi

# ---- Check / Generate SSL Certs ----
echo -e "${YELLOW}[3] Checking SSL certificates...${NC}"
if [ ! -f "cert.pem" ] || [ ! -f "key.pem" ]; then
    echo -e "${YELLOW}  ⚠ Generating self-signed SSL certificates...${NC}"
    openssl req -x509 -newkey rsa:4096 -nodes \
        -out cert.pem -keyout key.pem \
        -days 365 \
        -subj "/C=IN/ST=WB/L=Kolkata/O=IISERK/OU=22MS/CN=localhost" \
        2>/dev/null
    chmod 600 key.pem
    echo -e "${GREEN}  ✓ SSL certificates generated${NC}"
else
    echo -e "${GREEN}  ✓ SSL certificates found${NC}"
fi

# ---- Verify dependencies ----
echo -e "${YELLOW}[4] Checking Python dependencies...${NC}"
MISSING=$($PYTHON -c "
deps = ['flask', 'jinja2', 'qrcode', 'PIL', 'cryptography', 'dotenv', 'requests']
missing = []
for d in deps:
    try:
        __import__(d)
    except ImportError:
        missing.append(d)
if missing:
    print(' '.join(missing))
" 2>/dev/null)
if [ -n "$MISSING" ]; then
    echo -e "${YELLOW}  ⚠ Missing packages: $MISSING${NC}"
    echo "    Installing..."
    uv pip install --python "$PYTHON" -r requirements_21ms.txt 2>&1 | tail -1
    echo -e "${GREEN}  ✓ Dependencies installed${NC}"
else
    echo -e "${GREEN}  ✓ All dependencies available${NC}"
fi

# ---- Kill existing server ----
echo -e "${YELLOW}[5] Checking for existing server...${NC}"
OLD_PIDS=$(lsof -ti:5000 2>/dev/null || true)
if [ -n "$OLD_PIDS" ]; then
    echo -e "${YELLOW}  ⚠ Stopping existing server(s)...${NC}"
    # Use fuser to kill ALL processes on port 5000
    fuser -k 5000/tcp 2>/dev/null || true
    # Wait until port is actually free
    for i in $(seq 1 10); do
        if ! lsof -ti:5000 >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    echo -e "${GREEN}  ✓ Stopped${NC}"
else
    echo -e "${GREEN}  ✓ No existing server${NC}"
fi

# ---- Start server ----
echo ""
echo -e "${BOLD}${GREEN}  Starting Flask server...${NC}"
echo ""

SSL_ENABLED=$($PYTHON -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('SSL_ENABLED', 'false'))" 2>/dev/null)

nohup "$PYTHON" app.py > /tmp/flask_server.log 2>&1 &
PID=$!

sleep 3

# Verify it started
if kill -0 "$PID" 2>/dev/null; then
    # Get IPs
    IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    [ -z "$IP" ] && IP="10.20.82.147"
    PROTO="http"
    [ "$SSL_ENABLED" = "true" ] && PROTO="https"

    echo ""
    echo -e "${BOLD}${GREEN}  ╔══════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${GREEN}  ║           SERVER IS RUNNING!               ║${NC}"
    echo -e "${BOLD}${GREEN}  ╚══════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${BOLD}Dashboard:${NC}  ${PROTO}://${IP}:5000/sender"
    echo -e "  ${BOLD}Scanner:${NC}    ${PROTO}://${IP}:5000/scanner"
    echo -e "  ${BOLD}Local:${NC}      ${PROTO}://localhost:5000/sender"
    echo ""
    echo -e "  ${YELLOW}Note:${NC} Self-signed cert will show a security warning."
    echo -e "  Click 'Advanced' → 'Proceed' to continue."
    echo ""
    echo -e "  ${BOLD}Stop server:${NC}  kill -9 $PID"
    echo -e "  ${BOLD}View logs:${NC}    tail -f /tmp/flask_server.log"
    echo ""
else
    echo -e "${RED}  ✗ Server failed to start!${NC}"
    echo "    Check logs: tail -50 /tmp/flask_server.log"
    exit 1
fi
