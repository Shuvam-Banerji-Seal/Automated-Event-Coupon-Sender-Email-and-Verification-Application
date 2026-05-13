#!/bin/bash
# Start zrok tunnel for the scanner page
# The tunnel only allows /scanner, /verify-coupon, /coupon-status
# Admin pages like /sender are blocked through the tunnel.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export PATH="$HOME/.local/bin:$PATH"

# Check zrok is installed
if ! command -v zrok &>/dev/null; then
    echo "Error: zrok not found in ~/.local/bin"
    echo "Install it from: https://github.com/openziti/zrok"
    exit 1
fi

# Kill existing tunnel
pkill -f "zrok share" 2>/dev/null

# Check Flask is running
if ! curl -s --max-time 2 http://localhost:5000/ > /dev/null 2>&1; then
    echo "Starting Flask server..."
    SSL_ENABLED=false nohup python3 app.py > /tmp/flask_server.log 2>&1 &
    sleep 3
fi

# Start tunnel
echo "Starting zrok tunnel..."
nohup zrok share public http://localhost:5000 --headless > /tmp/zrok_tunnel.log 2>&1 &
sleep 8

URL=$(grep -o "[a-z0-9]*\.shares\.zrok\.io" /tmp/zrok_tunnel.log 2>/dev/null | head -1)

if [ -n "$URL" ]; then
    echo ""
    echo "  Scanner:  https://$URL/scanner"
    echo "  (Admin pages are blocked through the tunnel)"
    echo ""
    echo "  Stop:  pkill -f 'zrok share'"
else
    echo "Tunnel might not be ready yet. Check: cat /tmp/zrok_tunnel.log"
fi
