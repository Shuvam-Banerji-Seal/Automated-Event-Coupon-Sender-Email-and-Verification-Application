import os
import ssl
from app import app

def run_https_server():
    """
    Run the Flask application with adhoc SSL context.
    This allows mobile devices to access the camera functionalities
    via HTTPS over the local network.
    """
    print("\n" + "="*60)
    print("STARTING IN LOCAL HTTPS MODE")
    print("="*60)
    print("1. Make sure your mobile device is on the SAME Wi-Fi network.")
    print("2. Find your computer's local IP address (e.g., 192.168.1.x or 10.0.0.x).")
    print("   - On Linux/Mac run: ip addr show | grep inet")
    print("   - On Windows run: ipconfig")
    print("3. On your mobile, visit: https://<YOUR_IP>:5000/scanner")
    print("4. You will see a 'Not Secure' warning. Click Advanced -> Proceed.")
    print("="*60 + "\n")

    # Set debug mode
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    port = int(os.environ.get('PORT', 5000))

    try:
        # Run with adhoc SSL context (requires: pip install pyopenssl)
        app.run(
            host='0.0.0.0',
            port=port,
            debug=debug_mode,
            ssl_context='adhoc'
        )
    except TypeError as e:
        if "ssl_context" in str(e):
             print("\nERROR: 'pyopenssl' is missing.")
             print("Please run: pip install pyopenssl\n")
        else:
            raise e
    except Exception as e:
        print(f"\nError starting server: {e}")
        print("Ensure you have 'pyopenssl' installed: pip install pyopenssl")

if __name__ == '__main__':
    run_https_server()
