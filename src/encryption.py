"""
Encryption service for the Email Coupon System.
Provides AES-256 encryption/decryption using Fernet with timestamp and email hash integration.
"""

import os
import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64


class EncryptionService:
    """
    Handles encryption and decryption of coupon data using AES-256 via Fernet.
    Integrates timestamp and email hash for additional security.
    """
    
    def __init__(self, secret_key: Optional[str] = None):
        """
        Initialize the encryption service.
        
        Args:
            secret_key: Base secret key. If None, loads from environment.
        """
        self.secret_key = secret_key or self._load_secret_key()
        if not self.secret_key:
            raise ValueError("Secret key must be provided or set in environment as COUPON_SECRET_KEY")
    
    def _load_secret_key(self) -> Optional[str]:
        """Load secret key from environment variables."""
        return os.getenv('COUPON_SECRET_KEY')
    
    def _derive_key(self, email: str, salt: bytes = None) -> bytes:
        """
        Derive encryption key from secret key and email hash.
        
        Args:
            email: User email for key derivation
            salt: Optional salt bytes. If None, uses email hash as salt.
            
        Returns:
            Derived key bytes suitable for Fernet
        """
        if salt is None:
            # Use email hash as salt for consistency
            salt = hashlib.sha256(email.lower().encode()).digest()[:16]
        
        # Combine secret key with email for key derivation
        password = f"{self.secret_key}:{email.lower()}".encode()
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password))
        return key
    
    def _create_email_hash(self, email: str) -> str:
        """
        Create a hash of the email for additional security.
        
        Args:
            email: Email address to hash
            
        Returns:
            Hexadecimal hash string
        """
        return hashlib.sha256(email.lower().encode()).hexdigest()[:16]
    
    def encrypt_coupon_data(self, data: Dict[str, Any], email: str) -> str:
        """
        Encrypt coupon data with timestamp and email hash integration.
        
        Args:
            data: Coupon data dictionary to encrypt
            email: Email address for key derivation and validation
            
        Returns:
            Base64 encoded encrypted string
        """
        # Add timestamp and email hash for security
        enhanced_data = {
            **data,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'email_hash': self._create_email_hash(email),
            'email': email.lower()
        }
        
        # Convert to JSON string
        json_data = json.dumps(enhanced_data, sort_keys=True)
        
        # Derive key and encrypt
        key = self._derive_key(email)
        fernet = Fernet(key)
        encrypted_bytes = fernet.encrypt(json_data.encode())
        
        # Return base64 encoded string
        return base64.urlsafe_b64encode(encrypted_bytes).decode()
    
    def decrypt_coupon_data(self, encrypted_data: str, email: str) -> Dict[str, Any]:
        """
        Decrypt coupon data and validate timestamp and email hash.
        
        Args:
            encrypted_data: Base64 encoded encrypted string
            email: Email address for key derivation and validation
            
        Returns:
            Decrypted coupon data dictionary
            
        Raises:
            ValueError: If decryption fails or validation fails
        """
        try:
            # Decode base64
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())
            
            # Derive key and decrypt
            key = self._derive_key(email)
            fernet = Fernet(key)
            decrypted_bytes = fernet.decrypt(encrypted_bytes)
            
            # Parse JSON
            json_data = decrypted_bytes.decode()
            data = json.loads(json_data)
            
            # Validate email hash
            expected_hash = self._create_email_hash(email)
            if data.get('email_hash') != expected_hash:
                raise ValueError("Email hash validation failed")
            
            # Validate email
            if data.get('email', '').lower() != email.lower():
                raise ValueError("Email validation failed")
            
            return data
            
        except Exception as e:
            raise ValueError(f"Decryption failed: {str(e)}") from e
    
    def validate_timestamp(self, data: Dict[str, Any], max_age_hours: int = 24) -> bool:
        """
        Validate that the timestamp in the data is within acceptable range.
        
        Args:
            data: Decrypted coupon data containing timestamp
            max_age_hours: Maximum age in hours for the coupon
            
        Returns:
            True if timestamp is valid, False otherwise
        """
        try:
            timestamp_str = data.get('timestamp')
            if not timestamp_str:
                return False
            
            # Parse timestamp
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            
            # Check if within acceptable age
            age_hours = (now - timestamp).total_seconds() / 3600
            return 0 <= age_hours <= max_age_hours
            
        except (ValueError, TypeError):
            return False
    
    def generate_secure_token(self, length: int = 32) -> str:
        """
        Generate a cryptographically secure random token.
        
        Args:
            length: Length of the token in bytes
            
        Returns:
            Base64 encoded random token
        """
        random_bytes = os.urandom(length)
        return base64.urlsafe_b64encode(random_bytes).decode().rstrip('=')