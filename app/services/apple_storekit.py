"""
Apple StoreKit 2 subscription verification service.
Validates App Store signed transactions and manages Apple subscriptions.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from jose import JWTError, jwt
from jose.exceptions import JWKError

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Apple's public key endpoint (same as Sign-In, used for StoreKit JWS)
APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"

# Product ID to tier mapping
APPLE_PRODUCT_TIERS = {
    "ch.helvetra.pro.monthly": "pro",
    "ch.helvetra.pro.yearly": "pro",
    "ch.helvetra.business.monthly": "business",
    "ch.helvetra.business.yearly": "business",
}

# Cache for Apple's public keys
_storekit_keys: dict | None = None
_storekit_keys_fetched: float = 0
KEYS_CACHE_SECONDS = 3600


@dataclass
class AppleTransaction:
    """Parsed Apple StoreKit transaction info."""

    transaction_id: str
    original_transaction_id: str
    product_id: str
    purchase_date: datetime
    expires_date: datetime | None
    is_upgraded: bool
    environment: str  # sandbox or production
    tier: str | None


@dataclass
class AppleSubscriptionStatus:
    """Subscription status from App Store Server Notification."""

    original_transaction_id: str
    product_id: str
    status: str  # active, expired, in_billing_retry, revoked
    expires_date: datetime | None
    auto_renew_status: bool
    tier: str | None


async def _fetch_storekit_keys() -> dict | None:
    """Fetch Apple's public keys from JWKS endpoint."""
    global _storekit_keys, _storekit_keys_fetched

    now = time.time()
    if _storekit_keys is not None and (now - _storekit_keys_fetched) < KEYS_CACHE_SECONDS:
        return _storekit_keys

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(APPLE_KEYS_URL, timeout=10.0)
            response.raise_for_status()
            _storekit_keys = response.json()
            _storekit_keys_fetched = now
            return _storekit_keys
    except Exception as e:
        logger.error(f"Failed to fetch Apple StoreKit keys: {e}")
        return _storekit_keys


def _get_key_for_jws(keys: dict, jws: str) -> dict | None:
    """Find the correct key from JWKS based on JWS header."""
    try:
        unverified_header = jwt.get_unverified_header(jws)
        kid = unverified_header.get("kid")

        for key in keys.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None
    except JWTError:
        return None


async def _decode_jws(jws_string: str) -> dict | None:
    """Decode a JWS (signed transaction) from Apple."""
    keys = await _fetch_storekit_keys()
    if not keys:
        logger.error("Cannot decode JWS: no Apple keys available")
        return None

    key = _get_key_for_jws(keys, jws_string)
    if not key:
        logger.warning("No matching key found for Apple JWS")
        return None

    try:
        # StoreKit uses ES256 for transactions
        payload = jwt.decode(
            jws_string,
            key,
            algorithms=["ES256", "RS256"],
            options={
                "verify_exp": False,  # StoreKit transactions may be historical
                "verify_aud": False,
                "verify_iss": False,
            },
        )
        return payload

    except (JWTError, JWKError) as e:
        logger.warning(f"Failed to decode Apple JWS: {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error decoding Apple JWS: {e}")
        return None


async def verify_transaction(signed_transaction: str) -> AppleTransaction | None:
    """
    Verify and parse a signed StoreKit 2 transaction.
    Returns AppleTransaction if valid, None if invalid.

    Gated by settings.apple_storekit_enabled. The verifier in this file
    points at the Sign-In-with-Apple JWKS instead of the App Store Root
    CA chain and disables expiry/audience/issuer checks — so it must
    stay off until rewritten. See helvetra/backend#94.
    """
    if not settings.apple_storekit_enabled:
        logger.warning(
            "Apple StoreKit verification is disabled (backend#94). "
            "Refusing to process signed_transaction."
        )
        return None

    payload = await _decode_jws(signed_transaction)
    if not payload:
        return None

    try:
        # Parse transaction info
        transaction_id = payload.get("transactionId", "")
        original_transaction_id = payload.get("originalTransactionId", "")
        product_id = payload.get("productId", "")
        environment = payload.get("environment", "sandbox")

        # Parse dates (milliseconds since epoch)
        purchase_date_ms = payload.get("purchaseDate", 0)
        expires_date_ms = payload.get("expiresDate")

        purchase_date = datetime.fromtimestamp(purchase_date_ms / 1000, tz=timezone.utc)
        expires_date = None
        if expires_date_ms:
            expires_date = datetime.fromtimestamp(expires_date_ms / 1000, tz=timezone.utc)

        # Check if upgraded to another subscription
        is_upgraded = payload.get("isUpgraded", False)

        # Map product to tier
        tier = APPLE_PRODUCT_TIERS.get(product_id)

        return AppleTransaction(
            transaction_id=transaction_id,
            original_transaction_id=original_transaction_id,
            product_id=product_id,
            purchase_date=purchase_date,
            expires_date=expires_date,
            is_upgraded=is_upgraded,
            environment=environment,
            tier=tier,
        )

    except Exception as e:
        logger.exception(f"Error parsing Apple transaction: {e}")
        return None


async def parse_server_notification(signed_payload: str) -> AppleSubscriptionStatus | None:
    """
    Parse an App Store Server Notification v2.
    Returns subscription status info if valid.

    Gated by settings.apple_storekit_enabled — same reason as
    verify_transaction. See helvetra/backend#94.
    """
    if not settings.apple_storekit_enabled:
        logger.warning(
            "Apple StoreKit verification is disabled (backend#94). "
            "Refusing to process server notification."
        )
        return None

    # First decode the outer notification
    notification = await _decode_jws(signed_payload)
    if not notification:
        return None

    try:
        notification_type = notification.get("notificationType", "")
        subtype = notification.get("subtype", "")

        # Get the signed transaction data
        data = notification.get("data", {})
        signed_transaction_info = data.get("signedTransactionInfo", "")

        if not signed_transaction_info:
            logger.warning("No signed transaction in notification")
            return None

        # Decode the transaction
        transaction = await _decode_jws(signed_transaction_info)
        if not transaction:
            return None

        # Parse transaction details
        original_transaction_id = transaction.get("originalTransactionId", "")
        product_id = transaction.get("productId", "")
        expires_date_ms = transaction.get("expiresDate")

        expires_date = None
        if expires_date_ms:
            expires_date = datetime.fromtimestamp(expires_date_ms / 1000, tz=timezone.utc)

        # Get renewal info if available
        signed_renewal_info = data.get("signedRenewalInfo", "")
        auto_renew_status = True
        if signed_renewal_info:
            renewal_info = await _decode_jws(signed_renewal_info)
            if renewal_info:
                auto_renew_status = renewal_info.get("autoRenewStatus", 1) == 1

        # Determine subscription status based on notification type
        status = "active"
        if notification_type in ("EXPIRED", "REVOKE"):
            status = "expired"
        elif notification_type == "GRACE_PERIOD_EXPIRED":
            status = "expired"
        elif notification_type == "DID_FAIL_TO_RENEW":
            status = "in_billing_retry"
        elif subtype == "AUTO_RENEW_DISABLED":
            status = "active"  # Still active, just won't renew

        tier = APPLE_PRODUCT_TIERS.get(product_id)

        logger.info(f"Apple notification: {notification_type}/{subtype} for {product_id}")

        return AppleSubscriptionStatus(
            original_transaction_id=original_transaction_id,
            product_id=product_id,
            status=status,
            expires_date=expires_date,
            auto_renew_status=auto_renew_status,
            tier=tier,
        )

    except Exception as e:
        logger.exception(f"Error parsing Apple server notification: {e}")
        return None
