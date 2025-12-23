"""
Apple Sign-In authentication service.
Validates Apple identity tokens and manages Apple ID user accounts.
"""

import logging
import time
from dataclasses import dataclass

import httpx
from jose import JWTError, jwt
from jose.exceptions import JWKError

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Apple's public key endpoint
APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"

# Cache for Apple's public keys (refreshed every hour)
_apple_keys: dict | None = None
_apple_keys_fetched: float = 0
KEYS_CACHE_SECONDS = 3600


@dataclass
class AppleUser:
    """Validated Apple user info from identity token."""

    apple_id: str  # The 'sub' claim - unique Apple user identifier
    email: str | None
    email_verified: bool
    is_private_email: bool


async def _fetch_apple_keys() -> dict | None:
    """Fetch Apple's public keys from JWKS endpoint."""
    global _apple_keys, _apple_keys_fetched

    now = time.time()
    if _apple_keys is not None and (now - _apple_keys_fetched) < KEYS_CACHE_SECONDS:
        return _apple_keys

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(APPLE_KEYS_URL, timeout=10.0)
            response.raise_for_status()
            _apple_keys = response.json()
            _apple_keys_fetched = now
            return _apple_keys
    except Exception as e:
        logger.error(f"Failed to fetch Apple public keys: {e}")
        return _apple_keys  # Return cached keys if available


def _get_key_for_token(keys: dict, token: str) -> dict | None:
    """Find the correct key from JWKS based on token header."""
    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        for key in keys.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None
    except JWTError:
        return None


async def validate_identity_token(identity_token: str) -> AppleUser | None:
    """
    Validate an Apple Sign-In identity token (JWT).
    Returns AppleUser if valid, None if invalid.
    """
    # Fetch Apple's public keys
    keys = await _fetch_apple_keys()
    if not keys:
        logger.error("Cannot validate token: no Apple keys available")
        return None

    # Find the correct key for this token
    key = _get_key_for_token(keys, identity_token)
    if not key:
        logger.warning("No matching key found for Apple identity token")
        return None

    try:
        # Decode and validate the token
        payload = jwt.decode(
            identity_token,
            key,
            algorithms=["RS256"],
            audience=settings.apple_bundle_id,
            issuer="https://appleid.apple.com",
            options={
                "verify_exp": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )

        # Extract user info from claims
        apple_id = payload.get("sub")
        if not apple_id:
            logger.warning("Apple identity token missing 'sub' claim")
            return None

        email = payload.get("email")
        email_verified = payload.get("email_verified", False)

        # Check if using Apple's private email relay
        is_private_email = payload.get("is_private_email", False)
        if is_private_email == "true":
            is_private_email = True
        elif is_private_email == "false":
            is_private_email = False

        return AppleUser(
            apple_id=apple_id,
            email=email,
            email_verified=bool(email_verified),
            is_private_email=bool(is_private_email),
        )

    except jwt.ExpiredSignatureError:
        logger.warning("Apple identity token expired")
        return None
    except jwt.JWTClaimsError as e:
        logger.warning(f"Apple identity token claims error: {e}")
        return None
    except (JWTError, JWKError) as e:
        logger.warning(f"Failed to validate Apple identity token: {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error validating Apple identity token: {e}")
        return None


async def refresh_apple_keys() -> bool:
    """Force refresh of Apple's public keys cache."""
    global _apple_keys, _apple_keys_fetched

    _apple_keys = None
    _apple_keys_fetched = 0

    keys = await _fetch_apple_keys()
    return keys is not None
