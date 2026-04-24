#!/usr/bin/env python3
"""
HTTPS Development Server for DCS Day '26 Event System
=====================================================

This script starts Flask with SSL/TLS for secure camera access on mobile devices.
Camera APIs (getUserMedia) require HTTPS on non-localhost connections.

Usage:
    python start_https.py [--port PORT] [--host HOST]
    
Options:
    --port PORT    Port number (default: 5000)
    --host HOST    Host address (default: 0.0.0.0 for all interfaces)
    
For VS Code Port Forwarding:
    1. Run this script
    2. Open VS Code's "Ports" tab (View -> Open View -> Ports)
    3. Forward port 5000
    4. Set visibility to "Public" 
    5. Copy the forwarded URL (e.g., https://xxx.devtunnels.ms)
    6. Add this URL to Google OAuth Authorized redirect URIs:
       - https://xxx.devtunnels.ms/oauth2callback

Note: The self-signed certificate will show a browser warning.
      Click "Advanced" -> "Proceed anyway" to continue.
"""

import os
import sys
import ssl
import socket
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

def get_local_ip():
    """Get the local IP address for network access info."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def generate_ssl_context():
    """Generate an adhoc SSL context for development."""
    try:
        # Try using pyopenssl for adhoc SSL
        from werkzeug.serving import make_ssl_devcert
        cert_path = Path(__file__).parent / '.ssl'
        cert_path.mkdir(exist_ok=True)
        
        cert_file = cert_path / 'dev.crt'
        key_file = cert_path / 'dev.key'
        
        if not cert_file.exists() or not key_file.exists():
            print("🔐 Generating self-signed SSL certificate...")
            make_ssl_devcert(str(cert_path / 'dev'))
            print("✅ Certificate generated at .ssl/")
        
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert_file), str(key_file))
        return context
        
    except ImportError:
        # Fall back to adhoc (requires pyopenssl)
        print("📦 Using adhoc SSL (requires pyopenssl)")
        return 'adhoc'

def main():
    parser = argparse.ArgumentParser(description='Start HTTPS development server')
    parser.add_argument('--port', type=int, default=5000, help='Port number')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host address')
    args = parser.parse_args()
    
    # Import Flask app
    from app import app
    
    local_ip = get_local_ip()
    
    print("\n" + "="*60)
    print("🔐 DCS Day '26 - HTTPS Development Server")
    print("="*60)
    print(f"\n📍 Server Addresses:")
    print(f"   Local:    https://127.0.0.1:{args.port}")
    print(f"   Network:  https://{local_ip}:{args.port}")
    print(f"\n📱 For Mobile Testing:")
    print(f"   1. Connect phone to same WiFi network")
    print(f"   2. Open https://{local_ip}:{args.port}/scanner")
    print(f"   3. Accept the certificate warning")
    print(f"\n💡 For VS Code Port Forwarding:")
    print(f"   1. Open Ports tab in VS Code")
    print(f"   2. Forward port {args.port}")
    print(f"   3. Set visibility to 'Public'")
    print(f"   4. Use the forwarded URL for OAuth testing")
    print(f"\n🔑 Key URLs:")
    print(f"   Scanner:  /scanner")
    print(f"   Sender:   /sender")
    print(f"   OAuth:    /login")
    print("="*60 + "\n")
    
    try:
        ssl_ctx = generate_ssl_context()
        
        # Use use_reloader=False to prevent watchdog from interrupting email sending
        # The old_code folder keeps triggering reloads and interrupting batch operations
        app.run(
            host=args.host,
            port=args.port,
            ssl_context=ssl_ctx,
            debug=True,
            threaded=True,
            use_reloader=False  # Disable reloader to prevent interruption during email sending
        )
    except Exception as e:
        print(f"\n❌ Error starting server: {e}")
        print("\n💡 Try installing pyopenssl:")
        print("   pip install pyopenssl")
        sys.exit(1)

if __name__ == '__main__':
    main()
