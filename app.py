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
from src.smtp_mailer import SMTPMailer  # 21MS_FAREWELL BRANCH

# Load environment variables
load_dotenv()

# 21MS_FAREWELL BRANCH: Load event config from environment
EVENT_NAME = os.getenv('EVENT_NAME', '21MS Farewell Party')
EVENT_DATE = os.getenv('EVENT_DATE', 'To Be Announced')
EVENT_TIME = os.getenv('EVENT_TIME', 'To Be Announced')
EVENT_VENUE = os.getenv('EVENT_VENUE', 'IISER Kolkata Campus')
ORGANIZER_BATCH = '22MS Batch'
ORGANIZER_INSTITUTION = 'IISER Kolkata'

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
    session.clear()
    logger.info(f"User {user_email} logged out")
    return redirect(url_for('login'))

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
        
        # Create Gmail service with user's credentials
        credentials = google_auth_service.create_credentials_from_session(oauth_tokens)
        if not credentials:
            return jsonify({'success': False, 'error': 'Failed to create credentials'}), 401
        
        gmail_service = GmailEmailService(credentials)
        
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
        
        # Prepare email data with coupon information
        email_recipients = []
        for coupon in coupon_results['coupons']:
            email_recipients.append({
                'email': coupon['email'],
                'coupon_id': coupon['coupon_id'],
                'event_name': coupon['event_name'],
                'qr_code_base64': coupon['qr_code_base64'],
                'verification_code': coupon['verification_code'],  # Include 6-digit code
                'subject': f'Your Digital Coupon for {event_name}'
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

# 21MS_FAREWELL BRANCH: New route for SMTP-based email sending
@app.route('/send-farewell-emails', methods=['POST'])
def send_farewell_emails():
    """21MS_FAREWELL BRANCH: Send coupon emails via SMTP. Does not require OAuth login.

    Request body (JSON):
    {"event_name": "21MS Farewell Party"}
    """
    if not all([coupon_manager, csv_manager]):
        return jsonify({'success': False, 'error': 'Services not initialized'}), 500

    try:
        data = request.get_json() or {}
        event_name = data.get('event_name', EVENT_NAME)

        recipients = csv_manager.read_recipients()
        if not recipients:
            return jsonify({'success': False, 'error': 'No recipients found'}), 400

        pending_recipients = [r for r in recipients if r.get('status') == 'generated']
        if not pending_recipients:
            return jsonify({'success': False, 'error': 'No pending recipients to send'}), 400

        logger.info(f"Generating coupons for {len(pending_recipients)} pending recipients")

        smtp_mailer = SMTPMailer()

        coupon_results = coupon_manager.generate_coupons_batch(pending_recipients, event_name)

        if coupon_results['generated'] == 0:
            return jsonify({'success': False, 'error': 'Failed to generate any coupons'}), 500

        email_recipients = []
        for coupon in coupon_results['coupons']:
            email_recipients.append({
                'name': coupon.get('name', coupon.get('email', 'Guest').split('@')[0]),
                'email': coupon['email'],
                'coupon_id': coupon['coupon_id'],
                'event_name': coupon['event_name'],
                'qr_code_base64': coupon['qr_code_base64'],
                'verification_code': coupon['verification_code'],
                'attendee_name': coupon.get('name', coupon.get('email', 'Guest').split('@')[0]),
                'attendee_email': coupon['email'],
                'event_date': EVENT_DATE,
                'event_time': EVENT_TIME,
                'event_venue': EVENT_VENUE,
                'organizer_batch': ORGANIZER_BATCH,
                'organizer_institution': ORGANIZER_INSTITUTION,
            })

        def render_invitation(recipient):
            return render_template(
                'farewell/invitation.html',
                attendee_name=recipient['attendee_name'],
                attendee_email=recipient['attendee_email'],
                event_name=recipient['event_name'],
                event_date=recipient['event_date'],
                event_time=recipient['event_time'],
                event_venue=recipient['event_venue'],
                qr_code_base64=recipient['qr_code_base64'],
                verification_code=recipient['verification_code'],
                coupon_id=recipient['coupon_id'],
                organizer_batch=recipient['organizer_batch'],
                organizer_institution=recipient['organizer_institution'],
            )

        subject = f"You're Invited! {event_name}"

        sent = 0
        failed = 0
        failed_list = []

        for i, recipient in enumerate(email_recipients, 1):
            logger.info(f"Sending email {i}/{len(email_recipients)} to {recipient['email']}")

            try:
                html_body = render_invitation(recipient)
                result = smtp_mailer.send_email(
                    to_email=recipient['email'],
                    to_name=recipient['attendee_name'],
                    subject=subject,
                    html_body=html_body,
                )

                if result['success']:
                    for coupon in coupon_results['coupons']:
                        if coupon['email'] == recipient['email']:
                            coupon_manager.mark_coupon_sent(coupon['coupon_id'])
                            break
                    sent += 1
                else:
                    failed += 1
                    failed_list.append({'email': recipient['email'], 'error': result.get('error')})

            except Exception as e:
                logger.error(f"Failed to send to {recipient['email']}: {str(e)}")
                failed += 1
                failed_list.append({'email': recipient['email'], 'error': str(e)})

            if i < len(email_recipients):
                time.sleep(1.0)

        failure_log_file = None
        if failed_list:
            failure_log_file = csv_manager.save_failed_emails(failed_list, event_name)

        return jsonify({
            'success': True,
            'emails_sent': sent,
            'emails_failed': failed,
            'total_recipients': len(pending_recipients),
            'failed_list': failed_list,
            'failure_log_file': failure_log_file,
        })

    except Exception as e:
        logger.error(f"Error in send_farewell_emails: {str(e)}")
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
        
        if not email:
            return jsonify({
                'success': False, 
                'error': 'Email is required',
                'error_code': 'MISSING_EMAIL'
            }), 400
        
        # Check if this is a verification code (6 digits) or encrypted data
        if verification_code and len(verification_code) == 6 and verification_code.isdigit():
            # Validate using verification code
            validation_result = coupon_manager.validate_coupon_by_code(verification_code, email)
        elif encrypted_data:
            # Validate using encrypted data (old method)
            validation_result = coupon_manager.validate_coupon(encrypted_data, email)
        else:
            return jsonify({
                'success': False, 
                'error': 'Either verification_code (6 digits) or encrypted_data is required',
                'error_code': 'MISSING_DATA'
            }), 400
        
        if not validation_result.get('valid'):
            return jsonify({
                'success': False,
                'error': validation_result.get('error', 'Invalid coupon'),
                'error_code': validation_result.get('error_code', 'INVALID'),
                'used_at': validation_result.get('used_at')
            })
        
        # Mark coupon as used
        coupon_id = validation_result['coupon_id']
        if coupon_manager.mark_coupon_used(coupon_id):
            # 21MS_FAREWELL BRANCH: Send thank you email via SMTP (no OAuth required)
            def send_thank_you_async():
                try:
                    smtp_mailer = SMTPMailer()

                    attendance_data = {
                        'attendee_name': validation_result.get('attendee_name', email.split('@')[0]),
                        'attendee_email': email,
                        'event_name': validation_result.get('event_name', EVENT_NAME),
                        'verification_code': validation_result.get('verification_code', ''),
                        'coupon_id': coupon_id,
                        'organizer_batch': ORGANIZER_BATCH,
                        'organizer_institution': ORGANIZER_INSTITUTION,
                    }

                    with app.app_context():
                        html_content = render_template('farewell/thank_you.html', **attendance_data)

                    subject = f"Welcome to {attendance_data['event_name']}!"

                    result = smtp_mailer.send_email(
                        to_email=email,
                        to_name=attendance_data['attendee_name'],
                        subject=subject,
                        html_body=html_content,
                    )

                    if result['success']:
                        logger.info(f"Thank you email sent successfully to {email} via SMTP")
                    else:
                        logger.warning(f"Failed to send thank you email to {email}: {result['error']}")

                except Exception as e:
                    logger.error(f"Error sending thank you email via SMTP: {str(e)}")
                    import traceback
                    logger.error(traceback.format_exc())

            # Start email sending in background thread
            email_thread = threading.Thread(target=send_thank_you_async)
            email_thread.daemon = True
            email_thread.start()
            
            # Return immediately without waiting for email
            return jsonify({
                'success': True,
                'message': 'Coupon verified and marked as used',
                'coupon_id': coupon_id,
                'email': validation_result['email'],
                'event_name': validation_result['event_name'],
                'created_at': validation_result['created_at'],
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

# 21MS_FAREWELL BRANCH: New routes that don't require OAuth login
@app.route('/farewell-stats')
def get_farewell_stats():
    """Get system statistics - no authentication required for 21ms_farewell"""
    if not csv_manager:
        return jsonify({'success': False, 'error': 'CSV manager not initialized'}), 500
    try:
        coupon_stats = csv_manager.get_coupon_stats()
        recipients = csv_manager.read_recipients()
        return jsonify({
            'success': True,
            'recipients_count': len(recipients),
            'coupon_stats': coupon_stats,
        })
    except Exception as e:
        logger.error(f"Error getting stats: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/farewell-recipients')
def get_farewell_recipients():
    """Get detailed recipient list with coupon info - no auth required"""
    if not all([csv_manager, coupon_manager]):
        return jsonify({'success': False, 'error': 'Services not initialized'}), 500
    try:
        recipients = csv_manager.read_recipients()
        detailed_recipients = []
        import csv as csv_module
        for recipient in recipients:
            email = recipient['email'].lower()
            coupon_record = None
            try:
                with open(csv_manager.coupons_file, 'r', newline='', encoding='utf-8') as f:
                    reader = csv_module.DictReader(f)
                    for row in reader:
                        if row.get('email', '').lower() == email:
                            coupon_record = row
                            break
            except:
                pass
            status = 'pending'
            coupon_id = None
            verification_code = None
            sent_at = None
            used_at = None
            if coupon_record:
                coupon_id = coupon_record.get('coupon_id')
                verification_code = coupon_record.get('verification_code')
                status = coupon_record.get('status', 'generated')
                sent_at = coupon_record.get('sent_at')
                used_at = coupon_record.get('used_at')
            detailed_recipients.append({
                'email': recipient['email'],
                'status': status,
                'coupon_id': coupon_id,
                'verification_code': verification_code,
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

@app.route('/farewell-coupons')
def get_farewell_coupons():
    """Get all coupon details for dashboard display"""
    if not csv_manager:
        return jsonify({'success': False, 'error': 'CSV manager not initialized'}), 500
    try:
        import csv as csv_module
        coupons = []
        with open(csv_manager.coupons_file, 'r', newline='', encoding='utf-8') as f:
            reader = csv_module.DictReader(f)
            for row in reader:
                coupons.append({
                    'coupon_id': row.get('coupon_id', ''),
                    'email': row.get('email', ''),
                    'verification_code': row.get('verification_code', ''),
                    'status': row.get('status', 'generated'),
                    'sent_at': row.get('sent_at', ''),
                    'used_at': row.get('used_at', ''),
                })
        return jsonify({
            'success': True,
            'coupons': coupons,
            'total': len(coupons)
        })
    except Exception as e:
        logger.error(f"Error getting coupons: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    # Development server configuration
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    port = int(os.environ.get('PORT', 5000))
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug_mode
    )