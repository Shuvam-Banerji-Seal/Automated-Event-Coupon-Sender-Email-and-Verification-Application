"""
Google OAuth Authentication Service for Email Coupon System
Handles Google OAuth login and Gmail API integration
"""

import os
import json
import logging
from typing import Dict, Optional, Any
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
import smtplib
from dataclasses import dataclass

@dataclass
class EmailResult:
    """Result of email sending operation"""
    success: bool
    recipient: str
    error_message: Optional[str] = None
    timestamp: Optional[str] = None
import time

logger = logging.getLogger(__name__)

class GoogleAuthService:
    """Handles Google OAuth authentication and Gmail API operations"""
    
    def __init__(self):
        self.client_id = os.getenv('GOOGLE_CLIENT_ID')
        self.client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        self.redirect_uri = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:5000/auth/callback')
        
        # OAuth 2.0 scopes for Gmail sending
        self.scopes = [
            'https://www.googleapis.com/auth/gmail.send',
            'https://www.googleapis.com/auth/userinfo.email',
            'https://www.googleapis.com/auth/userinfo.profile'
        ]
        
        if not self.client_id or not self.client_secret:
            logger.warning("Google OAuth credentials not configured")
    
    def is_configured(self) -> bool:
        """Check if Google OAuth is properly configured"""
        return bool(self.client_id and self.client_secret)
    
    def get_authorization_url(self, redirect_uri: Optional[str] = None) -> str:
        """Generate Google OAuth authorization URL"""
        if not self.is_configured():
            raise ValueError("Google OAuth not configured")
        
        # Use provided redirect_uri or fall back to default
        current_redirect_uri = redirect_uri or self.redirect_uri
        
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [current_redirect_uri]
                }
            },
            scopes=self.scopes
        )
        flow.redirect_uri = current_redirect_uri
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='select_account consent'
        )
        
        return authorization_url, state
    
    def exchange_code_for_tokens(self, authorization_code: str, state: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
        """Exchange authorization code for access tokens"""
        if not self.is_configured():
            raise ValueError("Google OAuth not configured")
        
        try:
            # Manual token exchange to avoid scope validation issues
            import requests
            
            # Use provided redirect_uri or fall back to default
            current_redirect_uri = redirect_uri or self.redirect_uri
            
            token_data = {
                'code': authorization_code,
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'redirect_uri': current_redirect_uri,
                'grant_type': 'authorization_code'
            }
            
            # Exchange authorization code for tokens
            response = requests.post('https://oauth2.googleapis.com/token', data=token_data)
            response.raise_for_status()
            token_response = response.json()
            
            # Create credentials object
            credentials = Credentials(
                token=token_response.get('access_token'),
                refresh_token=token_response.get('refresh_token'),
                token_uri='https://oauth2.googleapis.com/token',
                client_id=self.client_id,
                client_secret=self.client_secret,
                scopes=self.scopes  # Use our original scopes, ignore the extra ones from Google
            )
            
            # Get user info
            user_info = self.get_user_info(credentials)
            
            return {
                'access_token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'token_uri': credentials.token_uri,
                'client_id': credentials.client_id,
                'client_secret': credentials.client_secret,
                'scopes': self.scopes,  # Use our original scopes
                'user_info': user_info
            }
            
        except Exception as e:
            logger.error(f"Error exchanging authorization code: {e}")
            raise
    
    def get_user_info(self, credentials: Credentials) -> Dict[str, Any]:
        """Get user information from Google API"""
        try:
            service = build('oauth2', 'v2', credentials=credentials)
            user_info = service.userinfo().get().execute()
            return {
                'email': user_info.get('email'),
                'name': user_info.get('name'),
                'picture': user_info.get('picture'),
                'id': user_info.get('id')
            }
        except HttpError as e:
            logger.error(f"Error getting user info: {e}")
            return {}
    
    def refresh_credentials(self, refresh_token: str) -> Optional[Credentials]:
        """Refresh access token using refresh token"""
        try:
            credentials = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret
            )
            
            credentials.refresh(Request())
            return credentials
            
        except Exception as e:
            logger.error(f"Error refreshing credentials: {e}")
            return None
    
    def revoke_token(self, token: str) -> bool:
        """Revoke an OAuth token to force re-authentication"""
        try:
            import requests
            
            # Google's token revocation endpoint
            revoke_url = 'https://oauth2.googleapis.com/revoke'
            
            response = requests.post(
                revoke_url,
                params={'token': token},
                headers={'content-type': 'application/x-www-form-urlencoded'}
            )
            
            if response.status_code == 200:
                logger.info("OAuth token successfully revoked")
                return True
            else:
                logger.warning(f"Token revocation returned status {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error revoking token: {e}")
            return False
    
    def create_credentials_from_session(self, session_data: Dict[str, Any]) -> Optional[Credentials]:
        """Create credentials object from session data"""
        try:
            return Credentials(
                token=session_data.get('access_token'),
                refresh_token=session_data.get('refresh_token'),
                token_uri=session_data.get('token_uri'),
                client_id=session_data.get('client_id'),
                client_secret=session_data.get('client_secret'),
                scopes=session_data.get('scopes')
            )
        except Exception as e:
            logger.error(f"Error creating credentials: {e}")
            return None


class GmailEmailService:
    """Email service using Gmail API for authenticated users"""
    
    def __init__(self, credentials: Credentials, sender_name: str = None):
        self.credentials = credentials
        self.sender_name = sender_name  # Display name for From header
        self.logger = logging.getLogger(__name__)
        
    def _create_message(self, sender: str, to: str, subject: str, html_content: str, attachment_path: str = None) -> Dict[str, str]:
        """Create a message for Gmail API with optional PDF attachment"""
        message = MIMEMultipart('mixed')
        message['to'] = to
        
        # Format From header with display name if available
        # Format: "Display Name" <email@example.com>
        if self.sender_name and self.sender_name.strip():
            try:
                message['from'] = formataddr((self.sender_name, sender))
            except Exception as e:
                self.logger.warning(f"Failed to format sender name, using plain email: {e}")
                message['from'] = sender
        else:
            message['from'] = sender
            
        message['subject'] = subject
        
        # Create alternative part for HTML
        msg_alternative = MIMEMultipart('alternative')
        html_part = MIMEText(html_content, 'html')
        msg_alternative.attach(html_part)
        message.attach(msg_alternative)
        
        # Add PDF attachment if provided
        if attachment_path and os.path.exists(attachment_path):
            try:
                from email.mime.application import MIMEApplication
                with open(attachment_path, 'rb') as f:
                    pdf_attachment = MIMEApplication(f.read(), _subtype='pdf')
                    pdf_attachment.add_header('Content-Disposition', 'attachment', 
                                             filename=os.path.basename(attachment_path))
                    message.attach(pdf_attachment)
                    self.logger.info(f"Attached PDF: {attachment_path}")
            except Exception as e:
                self.logger.error(f"Failed to attach PDF {attachment_path}: {str(e)}")
        
        # Encode message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return {'raw': raw_message}
    
    def send_email(self, sender_email: str, recipient: str, subject: str, html_content: str, attachment_path: str = None) -> EmailResult:
        """Send a single email using Gmail API with optional PDF attachment"""
        try:
            # Refresh credentials if needed
            if self.credentials.expired:
                self.credentials.refresh(Request())
            
            # Build Gmail service
            service = build('gmail', 'v1', credentials=self.credentials)
            
            # Create message with optional attachment (sender_name is used from self.sender_name)
            message = self._create_message(sender_email, recipient, subject, html_content, attachment_path)
            
            # Send message
            result = service.users().messages().send(userId='me', body=message).execute()
            
            self.logger.info(f"Email sent successfully to {recipient} via Gmail API")
            return EmailResult(
                success=True,
                recipient=recipient,
                timestamp=time.strftime('%Y-%m-%d %H:%M:%S')
            )
            
        except HttpError as e:
            error_msg = f"Gmail API error: {e}"
            self.logger.error(f"Failed to send email to {recipient}: {error_msg}")
            return EmailResult(
                success=False,
                recipient=recipient,
                error_message=error_msg,
                timestamp=time.strftime('%Y-%m-%d %H:%M:%S')
            )
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            self.logger.error(f"Failed to send email to {recipient}: {error_msg}")
            return EmailResult(
                success=False,
                recipient=recipient,
                error_message=error_msg,
                timestamp=time.strftime('%Y-%m-%d %H:%M:%S')
            )
    
    def send_batch_emails(self, sender_email: str, recipients: list, template_renderer, progress_callback=None) -> Dict:
        """Send emails to multiple recipients using Gmail API"""
        results = {
            'total': len(recipients),
            'sent': 0,
            'failed': 0,
            'results': [],
            'start_time': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        self.logger.info(f"Starting Gmail batch email send to {len(recipients)} recipients")
        
        for i, recipient_data in enumerate(recipients):
            recipient_email = recipient_data.get('email')
            if not recipient_email:
                self.logger.warning(f"Skipping recipient {i}: no email address")
                continue
            
            # Render email content
            try:
                html_content = template_renderer('invitation.html', recipient_data)
                subject = recipient_data.get('subject', 'Your Digital Coupon')
                
                # Send individual email
                result = self.send_email(sender_email, recipient_email, subject, html_content)
                
                results['results'].append(result)
                
                if result.success:
                    results['sent'] += 1
                else:
                    results['failed'] += 1
                
                # Call progress callback if provided
                if progress_callback:
                    progress_callback({
                        'current': i + 1,
                        'total': len(recipients),
                        'sent': results['sent'],
                        'failed': results['failed'],
                        'last_result': result
                    })
                
                # Small delay between emails to avoid rate limiting
                time.sleep(0.1)
                
            except Exception as e:
                error_result = EmailResult(
                    success=False,
                    recipient=recipient_email,
                    error_message=str(e),
                    timestamp=time.strftime('%Y-%m-%d %H:%M:%S')
                )
                results['results'].append(error_result)
                results['failed'] += 1
                self.logger.error(f"Error processing email for {recipient_email}: {e}")
        
        results['end_time'] = time.strftime('%Y-%m-%d %H:%M:%S')
        self.logger.info(f"Gmail batch email send completed: {results['sent']} sent, {results['failed']} failed")
        
        return results
    
    def test_connection(self) -> bool:
        """Test Gmail API connection by building the service"""
        try:
            if self.credentials.expired:
                self.credentials.refresh(Request())
            
            # Just build the service - don't try to read profile as we don't have permission
            service = build('gmail', 'v1', credentials=self.credentials)
            
            self.logger.info("Gmail API connection test successful - service built successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Gmail API connection test failed: {e}")
            return False