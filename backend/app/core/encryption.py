"""Encryption utilities for storing API keys securely."""

import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.config import settings


def _get_fernet() -> Fernet:
    key = settings.encryption_key
    if not key:
        # Fallback: use a derived key (not ideal for production but functional)
        key = "epub-translator-default-key-change-me"
    # Derive a valid Fernet key from arbitrary string
    derived = hashlib.sha256(key.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(derived)
    return Fernet(fernet_key)


def encrypt_api_key(plain_key: str) -> str:
    """Encrypt an API key for storage."""
    f = _get_fernet()
    return f.encrypt(plain_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """Decrypt an API key from storage."""
    f = _get_fernet()
    return f.decrypt(encrypted_key.encode()).decode()
