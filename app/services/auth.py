"""
Authentication services.
Handles password hashing, JWT token creation, and token verification.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

settings = get_settings()


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode(), salt).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: UUID) -> str:
    """Create a short-lived JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token() -> tuple[str, str]:
    """
    Create a long-lived refresh token.
    Returns (raw_token, hashed_token) - store the hash, return raw to client.
    """
    raw_token = secrets.token_urlsafe(32)
    hashed_token = hashlib.sha256(raw_token.encode()).hexdigest()
    return raw_token, hashed_token


def hash_refresh_token(raw_token: str) -> str:
    """Hash a refresh token for storage."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def decode_access_token(token: str) -> UUID | None:
    """
    Decode and validate an access token.
    Returns user_id if valid, None if invalid or expired.
    """
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        if payload.get("type") != "access":
            return None
        user_id = payload.get("sub")
        if user_id is None:
            return None
        return UUID(user_id)
    except JWTError:
        return None


def get_refresh_token_expiry() -> datetime:
    """Calculate expiry datetime for a new refresh token."""
    return datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
