#!/usr/bin/env python3
"""
Email Coupon System - Flask Application
Main application entry point with integrated services
"""

import os
import logging
import time
import threading
import shutil
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import secrets
import logging
import time
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import secrets

# Import our services
from src.coupons import CouponManager
from src.data import CSVManager
from src.auth import GoogleAuthService, GmailEmailService

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask application
app = Flask(__name__)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize services
try:
    csv_manager = CSVManager()
    coupon_manager = CouponManager(csv_manager=csv_manager)
    google_auth_service = GoogleAuthService()
    logger.info("Services initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize services: {str(e)}")
    csv_manager = None
    coupon_manager = None
    google_auth_service = None

# Authentication helper functions
def login_required(f):
    """Decorator to require Google authentication"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_current_user():
    """Get current authenticated user from session"""
    return session.get('user')

# Authentication routes
@app.route('/login')
def login():
    """Show login page or initiate Google OAuth login"""
    # Check if this is a logout redirect - always show login page
    if request.args.get('logged_out') == 'true':
        # Force clear session again to be safe
        session.clear()
        return render_template('login.html')
    
    # If user is already logged in, redirect to dashboard
    if 'user' in session:
        return redirect(url_for('dashboard'))
    
    # If OAuth is initiated (has 'start' parameter), begin OAuth flow
    if request.args.get('start') == 'true':
        if not google_auth_service or not google_auth_service.is_configured():
            return render_template('login_error.html', 
                                 error="Google OAuth is not configured. Please check your environment variables.")
        
        try:
            # Use configured redirect URI from .env, fallback to dynamic detection
            configured_redirect_uri = os.getenv('GOOGLE_REDIRECT_URI')
            if configured_redirect_uri:
                redirect_uri = configured_redirect_uri
            else:
                # Fallback to dynamic detection
                current_host = request.host
                redirect_uri = f"http://{current_host}/auth/callback"
            
            authorization_url, state = google_auth_service.get_authorization_url(redirect_uri)
            session['oauth_state'] = state
            session['oauth_redirect_uri'] = redirect_uri  # Store for callback
            return redirect(authorization_url)
        except Exception as e:
            logger.error(f"Error initiating OAuth: {e}")
            return render_template('login_error.html', error=str(e))
    
    # Show login page
    return render_template('login.html')

@app.route('/auth/callback')
def auth_callback():
    """Handle Google OAuth callback"""
    if not google_auth_service:
        return render_template('login_error.html', error="Google OAuth service not available")
    
    try:
        # Get authorization code from callback
        authorization_code = request.args.get('code')
        state = request.args.get('state')
        
        if not authorization_code:
            return render_template('login_error.html', error="Authorization code not received")
        
        # Verify state parameter
        if state != session.get('oauth_state'):
            return render_template('login_error.html', error="Invalid state parameter")
        
        # Get the redirect URI used for this OAuth flow
        redirect_uri = session.get('oauth_redirect_uri')
        
        # Exchange code for tokens
        token_data = google_auth_service.exchange_code_for_tokens(authorization_code, state, redirect_uri)
        
        # Store user data in session
        session['user'] = token_data['user_info']
        session['oauth_tokens'] = {
            'access_token': token_data['access_token'],
            'refresh_token': token_data['refresh_token'],
            'token_uri': token_data['token_uri'],
            'client_id': token_data['client_id'],
            'client_secret': token_data['client_secret'],
            'scopes': token_data['scopes']
        }
        
        # Save organizer credentials immediately so thank you emails work
        # (Previously was only saved when sending emails)
        csv_manager.save_organizer_credentials(
            token_data['user_info'], 
            session['oauth_tokens'], 
            "Unlock DCS Day 2026!!"
        )
        logger.info(f"Saved organizer credentials for {token_data['user_info']['email']}")
        
        # Clear state and redirect URI
        session.pop('oauth_state', None)
        session.pop('oauth_redirect_uri', None)
        
        logger.info(f"User {token_data['user_info']['email']} logged in successfully")
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        logger.error(f"Error in OAuth callback: {e}")
        return render_template('login_error.html', error=str(e))

@app.route('/logout')
def logout():
    """Logout user and clear session"""
    user_email = session.get('user', {}).get('email', 'Unknown')
    
    # Try to revoke Google OAuth token if available
    try:
        if google_auth_service and 'credentials' in session:
            credentials_data = session.get('credentials')
            if credentials_data and 'token' in credentials_data:
                google_auth_service.revoke_token(credentials_data['token'])
                logger.info(f"Revoked OAuth token for {user_email}")
    except Exception as e:
        logger.warning(f"Could not revoke OAuth token: {e}")
    
    # Clear all session data
    session.clear()
    logger.info(f"User {user_email} logged out")
    
    # Redirect to login with logout success parameter
    response = redirect(url_for('login', logged_out='true'))
    
    # Add headers to prevent caching and force fresh login
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['Clear-Site-Data'] = '"cache", "cookies", "storage"'
    
    return response

# Main routes
@app.route('/')
@login_required
def dashboard():
    """Main dashboard route - requires authentication"""
    user = get_current_user()
    return render_template('sender.html', user=user)

@app.route('/sender')
@login_required
def sender():
    """Sender interface route - requires authentication"""
    user = get_current_user()
    return render_template('sender.html', user=user)

@app.route('/scanner')
def scanner():
    """QR scanner interface route - no authentication required"""
    return render_template('scanner.html')

@app.route('/backup-scanner')
def backup_scanner():
    """Backup QR scanner - records QR data locally when main verification fails"""
    return render_template('backup_scanner.html')

@app.route('/backup-scan', methods=['POST'])
def backup_scan():
    """Receive backup scan data and save to CSV"""
    try:
        data = request.get_json()
        backup_file = 'backup_scans.csv'
        
        # Check if file exists to determine if we need headers
        file_exists = os.path.exists(backup_file)
        
        with open(backup_file, 'a', newline='', encoding='utf-8') as f:
            import csv
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['timestamp', 'email', 'verification_code', 'coupon_id', 'type', 'raw_qr_data'])
            writer.writerow([
                data.get('timestamp', ''),
                data.get('email', ''),
                data.get('verificationCode', ''),
                data.get('couponId', ''),
                data.get('type', ''),
                data.get('qrData', '')
            ])
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Backup scan error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# API endpoints
@app.route('/send-emails', methods=['POST'])
@login_required
def send_emails():
    """Send email campaign with coupon generation using authenticated user's Gmail"""
    if not all([coupon_manager, csv_manager, google_auth_service]):
        return jsonify({'success': False, 'error': 'Services not initialized'}), 500
    
    try:
        # Get current user and their OAuth tokens
        user = get_current_user()
        oauth_tokens = session.get('oauth_tokens')
        
        if not user or not oauth_tokens:
            return jsonify({'success': False, 'error': 'User not authenticated'}), 401
        
        # Create Gmail service with user's credentials and display name
        credentials = google_auth_service.create_credentials_from_session(oauth_tokens)
        if not credentials:
            return jsonify({'success': False, 'error': 'Failed to create credentials'}), 401
        
        # Get user's display name for email From header (shows name instead of roll number)
        sender_name = user.get('name', '')  # From Google OAuth profile
        gmail_service = GmailEmailService(credentials, sender_name=sender_name)
        
        data = request.get_json()
        event_name = data.get('event_name', 'Special Event')
        
        # Read recipients from CSV
        recipients = csv_manager.read_recipients()
        if not recipients:
            return jsonify({'success': False, 'error': 'No recipients found'}), 400
        
        # Generate coupons for all recipients
        logger.info(f"Generating coupons for {len(recipients)} recipients")
        coupon_results = coupon_manager.generate_coupons_batch(recipients, event_name)
        
        if coupon_results['generated'] == 0:
            return jsonify({'success': False, 'error': 'Failed to generate any coupons'}), 500
        
        # Prepare email data with coupon information (3 QR codes)
        email_recipients = []
        for coupon in coupon_results['coupons']:
            # Find attendee name from recipients data
            attendee_name = None
            for recipient in recipients:
                if recipient.get('email', '').lower() == coupon['email'].lower():
                    # Try different possible column names for name
                    attendee_name = (recipient.get('name') or 
                                     recipient.get('attendee_name') or 
                                     recipient.get('attendee') or 
                                     recipient.get('full_name'))
                    break
            
            email_recipients.append({
                'email': coupon['email'],
                'coupon_id': coupon['coupon_id'],
                'event_name': coupon['event_name'],
                'attendee_name': attendee_name,
                # Registration QR (primary)
                'qr_code_base64': coupon['qr_code_base64'],
                'verification_code': coupon['verification_code'],
                # Lunch QR
                'lunch_qr_base64': coupon.get('lunch_qr_base64'),
                'lunch_verification_code': coupon.get('lunch_verification_code'),
                # Dinner QR
                'dinner_qr_base64': coupon.get('dinner_qr_base64'),
                'dinner_verification_code': coupon.get('dinner_verification_code'),
                # Use event_name directly as the subject (user-specified)
                'subject': event_name
            })
        
        # Send emails with progress tracking using Gmail API
        def progress_callback(progress):
            logger.info(f"Gmail email progress: {progress['current']}/{progress['total']}")
        
        # Create template renderer function
        def template_renderer(template_name, context):
            return render_template(template_name, **context)
        
        sender_email = user['email']
        logger.info(f"Sending emails from {sender_email} to {len(email_recipients)} recipients via Gmail API")
        
        email_results = gmail_service.send_batch_emails(
            sender_email, 
            email_recipients, 
            template_renderer,
            progress_callback
        )
        
        # Update coupon status for successfully sent emails
        successful_emails = []
        failed_emails = []
        
        for result in email_results['results']:
            if result.success:
                successful_emails.append(result.recipient)
                # Find the coupon for this recipient and mark as sent
                for coupon in coupon_results['coupons']:
                    if coupon['email'] == result.recipient:
                        coupon_manager.mark_coupon_sent(coupon['coupon_id'])
                        break
            else:
                failed_emails.append({
                    'email': result.recipient,
                    'error': result.error_message,
                    'timestamp': result.timestamp
                })
        
        # Save failed emails to CSV if any failures occurred
        failure_log_file = None
        if failed_emails:
            failure_log_file = csv_manager.save_failed_emails(failed_emails, event_name)
            logger.warning(f"Saved {len(failed_emails)} failed emails to {failure_log_file}")
        
        # Save organizer credentials for thank you emails during verification
        csv_manager.save_organizer_credentials(user, oauth_tokens, event_name)
        
        # Update OAuth tokens in session if they were refreshed
        updated_credentials = gmail_service.credentials
        if updated_credentials.token != oauth_tokens.get('access_token'):
            session['oauth_tokens']['access_token'] = updated_credentials.token
        
        return jsonify({
            'success': True,
            'sender_email': sender_email,
            'coupons_generated': coupon_results['generated'],
            'emails_sent': email_results['sent'],
            'emails_failed': email_results['failed'],
            'total_recipients': len(recipients),
            'successful_emails': successful_emails,
            'failed_emails': failed_emails,
            'failure_log_file': failure_log_file,
            'start_time': email_results['start_time'],
            'end_time': email_results['end_time']
        })
        
    except Exception as e:
        logger.error(f"Error in send_emails: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/verify-coupon', methods=['POST'])
def verify_coupon():
    """Verify QR coupon or verification code and mark as used"""
    if not coupon_manager:
        return jsonify({'success': False, 'error': 'Coupon manager not initialized'}), 500
    
    try:
        data = request.get_json()
        encrypted_data = data.get('encrypted_data')
        verification_code = data.get('verification_code')
        email = data.get('email')
        qr_type = data.get('qr_type', 'registration')  # registration, lunch, or dinner
        
        # Debug logging
        logger.info(f"Verification request: code={verification_code}, email={email}, type={qr_type}")
        
        # Check if this is a verification code (6 digits) or encrypted data
        if verification_code and len(verification_code) == 6 and verification_code.isdigit():
            # Validate using verification code with QR type
            validation_result = coupon_manager.validate_coupon_by_code(verification_code, email, qr_type)
        elif encrypted_data:
            # Validate using encrypted data (old method) - email required
            if not email:
                return jsonify({
                    'success': False, 
                    'error': 'Email is required for encrypted coupon verification',
                    'error_code': 'MISSING_EMAIL'
                }), 400
            validation_result = coupon_manager.validate_coupon(encrypted_data, email)
        else:
            return jsonify({
                'success': False, 
                'error': 'Either verification_code (6 digits) or encrypted_data is required',
                'error_code': 'MISSING_DATA'
            }), 400
        
        if not validation_result.get('valid'):
            logger.warning(f"Validation failed: {validation_result.get('error')}")
            return jsonify({
                'success': False,
                'error': validation_result.get('error', 'Invalid coupon'),
                'error_code': validation_result.get('error_code', 'INVALID'),
                'used_at': validation_result.get('used_at')
            })
        
        # Mark coupon as used based on QR type
        coupon_id = validation_result['coupon_id']
        attendee_email = validation_result.get('email', email)  # Use found email or provided email
        verified_qr_type = validation_result.get('qr_type', qr_type)  # Type from validation
        
        logger.info(f"Marking coupon {coupon_id} {verified_qr_type} as used")
        
        # Get attendee name from coupon record
        coupon_record = csv_manager.find_coupon_by_email(attendee_email)
        attendee_name = coupon_record.attendee_name if coupon_record and hasattr(coupon_record, 'attendee_name') else None
        
        if coupon_manager.mark_coupon_used(coupon_id, verified_qr_type):
            # Send thank you email asynchronously using organizer's Gmail API credentials
            def send_thank_you_async():
                try:
                    # Get stored organizer credentials
                    organizer_data = csv_manager.get_organizer_credentials()
                    
                    if organizer_data and google_auth_service:
                        # Create Gmail service with organizer's credentials
                        credentials = google_auth_service.create_credentials_from_session(organizer_data['oauth_tokens'])
                        if credentials:
                            # Get organizer's display name for thank you email
                            organizer_name = organizer_data['user_info'].get('name', '')
                            gmail_service = GmailEmailService(credentials, sender_name=organizer_name)
                            
                            # Prepare thank you email data
                            attendance_data = {
                                'email': attendee_email,
                                'attendee_name': attendee_name,
                                'event_name': validation_result.get('event_name', 'Event'),
                                'attendance_date': time.strftime('%Y-%m-%d %H:%M:%S'),
                                'coupon_id': coupon_id,
                                'organizer_name': organizer_data['user_info'].get('name', 'Event Team'),
                                'organizer_email': organizer_data['user_info'].get('email', 'Event Team'),
                                'current_date': time.strftime('%Y-%m-%d %H:%M:%S'),
                                'qr_type': verified_qr_type
                            }
                            
                            # Choose template and subject based on QR type
                            template_map = {
                                'registration': 'thank_you_registration.html',
                                'lunch': 'thank_you_lunch.html',
                                'dinner': 'thank_you_dinner.html'
                            }
                            subject_map = {
                                'registration': f"🎫 Registration Confirmed - {attendance_data['event_name']}",
                                'lunch': f"🍽️ Lunch Verified - {attendance_data['event_name']}",
                                'dinner': f"🍱 Dinner Verified - {attendance_data['event_name']}"
                            }
                            
                            template_name = template_map.get(verified_qr_type, 'thank_you.html')
                            subject = subject_map.get(verified_qr_type, f"Thank you for attending {attendance_data['event_name']}!")
                            
                            # Render appropriate thank you email template
                            with app.app_context():
                                html_content = render_template(template_name, **attendance_data)
                            
                            sender_email = organizer_data['user_info']['email']
                            
                            # For registration, attach the PDF schedule
                            attachment_path = None
                            if verified_qr_type == 'registration':
                                pdf_path = os.path.join(app.root_path, 'static', 'attachments', 'DCS-Day-2026_Schedule.pdf')
                                if os.path.exists(pdf_path):
                                    attachment_path = pdf_path
                                    logger.info(f"Attaching PDF schedule: {pdf_path}")
                            
                            # Send via Gmail API using organizer's credentials
                            email_result = gmail_service.send_email(sender_email, email, subject, html_content, attachment_path)
                            
                            if email_result.success:
                                logger.info(f"Thank you email ({verified_qr_type}) sent successfully to {email} via Gmail API from organizer {sender_email}")
                            else:
                                logger.warning(f"Failed to send thank you email to {email}: {email_result.error_message}")
                        else:
                            logger.warning("Could not create Gmail credentials from stored organizer data")
                    else:
                        logger.warning("No organizer credentials stored - cannot send thank you email")
                        
                except Exception as e:
                    logger.error(f"Error sending thank you email via organizer Gmail API: {str(e)}")
                    import traceback
                    logger.error(traceback.format_exc())
            
            # Start email sending in background thread
            email_thread = threading.Thread(target=send_thank_you_async)
            email_thread.daemon = True
            email_thread.start()
            
            # Return immediately without waiting for email
            type_labels = {
                'registration': '🎫 Registration',
                'lunch': '🍽️ Lunch',
                'dinner': '🍱 Dinner'
            }
            return jsonify({
                'success': True,
                'message': f'{type_labels.get(verified_qr_type, verified_qr_type)} verified successfully!',
                'coupon_id': coupon_id,
                'email': validation_result['email'],
                'event_name': validation_result['event_name'],
                'created_at': validation_result['created_at'],
                'qr_type': verified_qr_type,
                'thank_you_email': 'sending'  # Indicate email is being sent in background
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to mark coupon as used',
                'error_code': 'UPDATE_FAILED'
            }), 500
            
    except Exception as e:
        logger.error(f"Error in verify_coupon: {str(e)}")
        return jsonify({
            'success': False, 
            'error': 'System error during verification',
            'error_code': 'SYSTEM_ERROR'
        }), 500

@app.route('/coupon-status/<coupon_id>')
def coupon_status(coupon_id):
    """Get coupon status by ID"""
    if not coupon_manager:
        return jsonify({'success': False, 'error': 'Coupon manager not initialized'}), 500
    
    try:
        status_result = coupon_manager.get_coupon_status(coupon_id)
        
        if not status_result.get('found'):
            return jsonify({
                'success': False,
                'error': status_result.get('error', 'Coupon not found')
            }), 404
        
        return jsonify({
            'success': True,
            'coupon_id': status_result['coupon_id'],
            'email': status_result['email'],
            'status': status_result['status'],
            'sent_at': status_result['sent_at'],
            'used_at': status_result['used_at']
        })
        
    except Exception as e:
        logger.error(f"Error getting coupon status: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/upload-csv', methods=['POST'])
@login_required
def upload_csv():
    """Handle CSV file uploads and validation"""
    if not csv_manager:
        return jsonify({'success': False, 'error': 'CSV manager not initialized'}), 500
    
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        if not file.filename or not file.filename.lower().endswith('.csv'):
            return jsonify({'success': False, 'error': 'File must be a CSV'}), 400
        
        # Get upload options
        data = request.form
        reset_coupons = data.get('reset_coupons', 'false').lower() == 'true'
        
        # Save uploaded file
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Validate the CSV file
        validation_result = csv_manager.validate_recipients_file(filepath)
        
        if not validation_result['valid']:
            os.remove(filepath)  # Clean up invalid file
            return jsonify({
                'success': False,
                'error': 'Invalid CSV file',
                'details': validation_result
            }), 400
        
        # Create backup of existing data if requested
        backup_created = ""
        if reset_coupons and os.path.exists(csv_manager.coupons_file):
            backup_created = csv_manager.backup_current_data()
        
        # If valid, replace the current recipients file
        shutil.move(filepath, csv_manager.recipients_file)
        
        # Reset coupons if requested (for fresh campaign)
        coupons_reset = False
        if reset_coupons:
            coupons_reset = csv_manager.reset_coupons_for_fresh_upload()
        
        logger.info(f"CSV uploaded successfully. Reset coupons: {coupons_reset}, Backup: {backup_created}")
        
        return jsonify({
            'success': True,
            'message': 'CSV file uploaded successfully',
            'total_rows': validation_result['total_rows'],
            'valid_emails': validation_result['valid_emails'],
            'invalid_emails': validation_result['invalid_emails'],
            'coupons_reset': coupons_reset,
            'backup_created': backup_created
        })
        
    except Exception as e:
        logger.error(f"Error uploading CSV: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/upload-status')
@login_required
def get_upload_status():
    """Get current upload and CSV status"""
    if not csv_manager:
        return jsonify({'success': False, 'error': 'CSV manager not initialized'}), 500
    
    try:
        status = csv_manager.get_upload_status()
        return jsonify({
            'success': True,
            **status
        })
        
    except Exception as e:
        logger.error(f"Error getting upload status: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/clear-csv', methods=['POST'])
@login_required
def clear_csv():
    """Clear the current CSV data and reset coupons for a fresh upload"""
    if not csv_manager:
        return jsonify({'success': False, 'error': 'CSV manager not initialized'}), 500
    
    try:
        # Create backup before clearing
        backup_file = None
        if os.path.exists(csv_manager.recipients_file):
            backup_file = csv_manager.backup_current_data()
        
        # Remove the recipients file
        if os.path.exists(csv_manager.recipients_file):
            os.remove(csv_manager.recipients_file)
            logger.info(f"Removed recipients file: {csv_manager.recipients_file}")
        
        # Reset the coupons file (create fresh with headers only)
        csv_manager.reset_coupons_for_fresh_upload()
        logger.info("Reset coupons file for fresh upload")
        
        return jsonify({
            'success': True,
            'message': 'CSV data cleared successfully. You can now upload a new file.',
            'backup_created': backup_file
        })
        
    except Exception as e:
        logger.error(f"Error clearing CSV: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/stats')
@login_required
def get_stats():
    """Get system statistics - requires authentication"""
    if not csv_manager:
        return jsonify({'success': False, 'error': 'CSV manager not initialized'}), 500
    
    try:
        coupon_stats = csv_manager.get_coupon_stats()
        recipients = csv_manager.read_recipients()
        user = get_current_user()
        
        return jsonify({
            'success': True,
            'recipients_count': len(recipients),
            'coupon_stats': coupon_stats,
            'user_email': user.get('email') if user else None
        })
        
    except Exception as e:
        logger.error(f"Error getting stats: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/recipients')
@login_required
def get_recipients():
    """Get detailed recipient list with status markers"""
    if not all([csv_manager, coupon_manager]):
        return jsonify({'success': False, 'error': 'Services not initialized'}), 500
    
    try:
        # Get all recipients from CSV
        recipients = csv_manager.read_recipients()
        
        # Get all coupons to match with recipients
        coupon_stats = csv_manager.get_coupon_stats()
        
        # Create detailed recipient list with status
        detailed_recipients = []
        
        for recipient in recipients:
            email = recipient['email'].lower()
            
            # Find matching coupon for this recipient
            coupon_record = None
            try:
                # This is a simplified approach - in a real system you'd want a more efficient lookup
                import csv as csv_module
                with open(csv_manager.coupons_file, 'r', newline='', encoding='utf-8') as f:
                    reader = csv_module.DictReader(f)
                    for row in reader:
                        if row.get('email', '').lower() == email:
                            coupon_record = row
                            break
            except:
                pass
            
            # Determine status
            status = 'pending'  # Default status
            coupon_id = None
            sent_at = None
            used_at = None
            
            if coupon_record:
                coupon_id = coupon_record.get('coupon_id')
                status = coupon_record.get('status', 'generated')
                sent_at = coupon_record.get('sent_at')
                used_at = coupon_record.get('used_at')
            
            detailed_recipients.append({
                'email': recipient['email'],
                'status': status,
                'coupon_id': coupon_id,
                'sent_at': sent_at,
                'used_at': used_at
            })
        
        return jsonify({
            'success': True,
            'recipients': detailed_recipients,
            'total_count': len(detailed_recipients)
        })
        
    except Exception as e:
        logger.error(f"Error getting recipients: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/preview-send', methods=['POST'])
@login_required
def preview_send():
    """Preview the list of recipients before sending emails"""
    if not csv_manager:
        return jsonify({'success': False, 'error': 'CSV manager not initialized'}), 500
    
    try:
        data = request.get_json()
        event_name = data.get('event_name', 'Special Event')
        
        # Read recipients from CSV
        recipients = csv_manager.read_recipients()
        if not recipients:
            return jsonify({'success': False, 'error': 'No recipients found'}), 400
        
        # Filter out recipients who already have tickets (optional)
        include_existing = data.get('include_existing', True)
        
        preview_recipients = []
        for recipient in recipients:
            email = recipient['email'].lower()
            
            # Check if recipient already has a ticket
            has_ticket = False
            ticket_status = 'new'
            
            try:
                import csv as csv_module
                with open(csv_manager.coupons_file, 'r', newline='', encoding='utf-8') as f:
                    reader = csv_module.DictReader(f)
                    for row in reader:
                        if row.get('email', '').lower() == email:
                            has_ticket = True
                            ticket_status = row.get('status', 'generated')
                            break
            except:
                pass
            
            # Include based on filter
            if include_existing or not has_ticket:
                preview_recipients.append({
                    'email': recipient['email'],
                    'has_existing_ticket': has_ticket,
                    'ticket_status': ticket_status
                })
        
        return jsonify({
            'success': True,
            'event_name': event_name,
            'recipients': preview_recipients,
            'total_count': len(preview_recipients),
            'new_recipients': len([r for r in preview_recipients if not r['has_existing_ticket']]),
            'existing_recipients': len([r for r in preview_recipients if r['has_existing_ticket']])
        })
        
    except Exception as e:
        logger.error(f"Error previewing send: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/failed-emails-logs')
@login_required
def get_failed_emails_logs():
    """Get list of failed email log files"""
    try:
        logs_dir = 'logs'
        if not os.path.exists(logs_dir):
            return jsonify({'success': True, 'logs': []})
        
        log_files = []
        for filename in os.listdir(logs_dir):
            if filename.startswith('failed_emails_') and filename.endswith('.csv'):
                filepath = os.path.join(logs_dir, filename)
                stat = os.stat(filepath)
                log_files.append({
                    'filename': filename,
                    'filepath': filepath,
                    'size': stat.st_size,
                    'created': datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
                })
        
        # Sort by creation time, newest first
        log_files.sort(key=lambda x: x['created'], reverse=True)
        
        return jsonify({
            'success': True,
            'logs': log_files
        })
        
    except Exception as e:
        logger.error(f"Error getting failed email logs: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/download-failed-emails/<filename>')
@login_required
def download_failed_emails(filename):
    """Download a specific failed emails log file"""
    try:
        # Security check: ensure filename is safe
        if not filename.startswith('failed_emails_') or not filename.endswith('.csv'):
            return jsonify({'error': 'Invalid filename'}), 400
        
        filepath = os.path.join('logs', filename)
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404
        
        from flask import send_file
        return send_file(filepath, as_attachment=True, download_name=filename)
        
    except Exception as e:
        logger.error(f"Error downloading failed emails file: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    # Development server configuration
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    port = int(os.environ.get('PORT', 5000))
    
    # Exclude old_code, logs, and other non-essential directories from watchdog
    # to prevent server reload during long operations
    import sys
    if debug_mode:
        # Use extra_files and exclude patterns for watchdog
        extra_dirs = ['templates', 'static', 'src']
        extra_files = []
        for extra_dir in extra_dirs:
            if os.path.isdir(extra_dir):
                for dirname, dirs, files in os.walk(extra_dir):
                    for filename in files:
                        filename = os.path.join(dirname, filename)
                        if os.path.isfile(filename):
                            extra_files.append(filename)
        
        app.run(
            host='0.0.0.0',
            port=port,
            debug=True,
            extra_files=extra_files,
            use_reloader=True,
            reloader_type='stat'  # Use stat reloader instead of watchdog to avoid issues
        )
    else:
        app.run(
            host='0.0.0.0',
            port=port,
            debug=False
        )