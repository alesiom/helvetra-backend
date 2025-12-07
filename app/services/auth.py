"""
Authentication services.
Handles password hashing, JWT token creation, and token verification.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from uuid import UUID

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

settings = get_settings()


@lru_cache(maxsize=1)
def _load_common_passwords() -> frozenset[str]:
    """Load common passwords list from file (cached)."""
    password_file = Path(__file__).parent.parent / "data" / "common_passwords.txt"
    if password_file.exists():
        with open(password_file) as f:
            return frozenset(line.strip().lower() for line in f if line.strip())
    return frozenset()


def is_common_password(password: str) -> bool:
    """Check if password is in the common passwords list."""
    common_passwords = _load_common_passwords()
    return password.lower() in common_passwords


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode(), salt).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify a password against its hash using timing-safe comparison.
    bcrypt.checkpw is already timing-safe, but we add an extra layer.
    """
    try:
        result = bcrypt.checkpw(password.encode(), password_hash.encode())
        # Use hmac.compare_digest for the final boolean comparison
        # This prevents timing attacks on the result itself
        return hmac.compare_digest(str(result), str(True))
    except Exception:
        # On any error, return False in constant time
        hmac.compare_digest("a", "b")
        return False


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
