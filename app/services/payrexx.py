"""
Payrexx payment integration service.
Handles webhook processing, subscription updates, and gateway creation.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.subscription import (
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
    SubscriptionTier,
)
from app.models.webhook import WebhookEvent

logger = logging.getLogger(__name__)
settings = get_settings()

# Payrexx API configuration
PAYREXX_API_BASE = "https://api.payrexx.com/v1.0"


@dataclass
class GatewayResponse:
    """Response from Payrexx gateway creation."""

    success: bool
    gateway_url: str | None = None
    gateway_id: str | None = None
    error: str | None = None


async def create_gateway(
    amount: int,
    currency: str,
    billing_period: str,
    user_email: str,
    success_url: str,
    failed_url: str,
    cancel_url: str,
) -> GatewayResponse:
    """
    Create a Payrexx payment gateway for subscription purchase.

    Args:
        amount: Amount in cents (e.g., 799 for CHF 7.99)
        currency: Currency code (e.g., "CHF")
        billing_period: "monthly" or "yearly"
        user_email: User's email for prefilling and reference
        success_url: URL to redirect after successful payment
        failed_url: URL to redirect after failed payment
        cancel_url: URL to redirect after cancelled payment

    Returns:
        GatewayResponse with gateway URL or error
    """
    if not settings.payrexx_instance or not settings.payrexx_api_secret:
        logger.error("Payrexx credentials not configured")
        return GatewayResponse(success=False, error="Payment system not configured")

    # Build request payload
    payload = {
        "amount": amount,
        "currency": currency,
        "purpose": f"Helvetra+ {billing_period.capitalize()} Subscription",
        "successRedirectUrl": success_url,
        "failedRedirectUrl": failed_url,
        "cancelRedirectUrl": cancel_url,
        "referenceId": user_email,
        "skipResultPage": True,
        # Prefill email field
        "fields[email][value]": user_email,
        # Enable all payment methods
        "psp": [],
        # Subscription configuration
        "subscriptionState": True,
        "subscriptionInterval": "P1Y" if billing_period == "yearly" else "P1M",
        "subscriptionPeriod": "P1Y" if billing_period == "yearly" else "P1M",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{PAYREXX_API_BASE}/Gateway/",
                params={"instance": settings.payrexx_instance},
                data=payload,
                headers={
                    "X-API-KEY": settings.payrexx_api_secret,
                },
                timeout=30.0,
            )

            if response.status_code != 200:
                logger.error(f"Payrexx API error: {response.status_code} - {response.text}")
                return GatewayResponse(
                    success=False,
                    error=f"Payment gateway error: {response.status_code}",
                )

            data = response.json()

            # Check for success
            if data.get("status") == "success" and data.get("data"):
                gateway_data = data["data"][0] if isinstance(data["data"], list) else data["data"]
                gateway_url = gateway_data.get("link")
                gateway_id = str(gateway_data.get("id", ""))

                logger.info(f"Created Payrexx gateway {gateway_id} for {user_email}")
                return GatewayResponse(
                    success=True,
                    gateway_url=gateway_url,
                    gateway_id=gateway_id,
                )

            # Handle error response
            error_msg = data.get("message", "Unknown error")
            logger.error(f"Payrexx gateway creation failed: {error_msg}")
            return GatewayResponse(success=False, error=error_msg)

    except httpx.TimeoutException:
        logger.error("Payrexx API timeout")
        return GatewayResponse(success=False, error="Payment service timeout")
    except Exception as e:
        logger.exception(f"Payrexx gateway creation error: {e}")
        return GatewayResponse(success=False, error="Payment service error")


@dataclass
class PayrexxTransaction:
    """Parsed Payrexx transaction data."""

    id: str
    status: str
    amount: int
    subscription_id: str | None
    product_id: str | None
    user_email: str | None
    time: datetime | None


@dataclass
class PayrexxSubscriptionEvent:
    """Parsed Payrexx subscription event data."""

    id: str
    status: str
    user_email: str | None
    valid_until: datetime | None
    start: datetime | None


def map_product_to_tier(product_id: str | None) -> SubscriptionTier | None:
    """Map Payrexx product ID to subscription tier."""
    if not product_id:
        return None

    if product_id == settings.payrexx_product_pro_id:
        return SubscriptionTier.PRO
    elif product_id == settings.payrexx_product_business_id:
        return SubscriptionTier.BUSINESS

    return None


def parse_transaction(payload: dict[str, Any]) -> PayrexxTransaction:
    """Parse Payrexx transaction webhook payload."""
    transaction = payload.get("transaction", {})
    invoice = transaction.get("invoice", {})
    contact = transaction.get("contact", {})

    # Parse time if present
    time_str = transaction.get("time")
    parsed_time = None
    if time_str:
        try:
            parsed_time = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass

    return PayrexxTransaction(
        id=str(transaction.get("id", "")),
        status=transaction.get("status", ""),
        amount=transaction.get("amount", 0),
        subscription_id=transaction.get("subscriptionId") or invoice.get("subscriptionId"),
        product_id=invoice.get("productId") or invoice.get("referenceId"),
        user_email=contact.get("email"),
        time=parsed_time,
    )


def parse_subscription_event(payload: dict[str, Any]) -> PayrexxSubscriptionEvent:
    """Parse Payrexx subscription webhook payload."""
    subscription = payload.get("subscription", {})
    contact = subscription.get("contact", {})

    # Parse dates
    valid_until = None
    start = None
    if subscription.get("valid_until"):
        try:
            valid_until = datetime.fromisoformat(subscription["valid_until"])
        except (ValueError, AttributeError):
            pass
    if subscription.get("start"):
        try:
            start = datetime.fromisoformat(subscription["start"])
        except (ValueError, AttributeError):
            pass

    return PayrexxSubscriptionEvent(
        id=str(subscription.get("id", "")),
        status=subscription.get("status", ""),
        user_email=contact.get("email"),
        valid_until=valid_until,
        start=start,
    )


async def check_idempotency(
    db: AsyncSession, source: str, event_id: str
) -> WebhookEvent | None:
    """Check if webhook event was already processed."""
    result = await db.execute(
        select(WebhookEvent).where(
            WebhookEvent.source == source,
            WebhookEvent.event_id == event_id,
        )
    )
    return result.scalar_one_or_none()


async def record_webhook_event(
    db: AsyncSession,
    source: str,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
    processed: bool = False,
    error: str | None = None,
) -> WebhookEvent:
    """Record webhook event for idempotency and audit."""
    event = WebhookEvent(
        source=source,
        event_id=event_id,
        event_type=event_type,
        payload=json.dumps(payload),
        processed=processed,
        error=error,
    )
    db.add(event)
    await db.flush()
    return event


async def get_subscription_by_external_id(
    db: AsyncSession, external_id: str
) -> Subscription | None:
    """Find subscription by payment provider external ID."""
    result = await db.execute(
        select(Subscription).where(Subscription.external_id == external_id)
    )
    return result.scalar_one_or_none()


async def get_subscription_by_user_email(
    db: AsyncSession, email: str
) -> Subscription | None:
    """Find subscription by user email."""
    from app.models.user import User

    result = await db.execute(
        select(Subscription)
        .join(User, Subscription.user_id == User.id)
        .where(User.email == email)
    )
    return result.scalar_one_or_none()


async def handle_payment_confirmed(
    db: AsyncSession, transaction: PayrexxTransaction
) -> bool:
    """Handle successful payment - activate or renew subscription."""
    # Find subscription by external_id or user email
    subscription = None
    if transaction.subscription_id:
        subscription = await get_subscription_by_external_id(db, transaction.subscription_id)

    if not subscription and transaction.user_email:
        subscription = await get_subscription_by_user_email(db, transaction.user_email)

    if not subscription:
        logger.warning(f"No subscription found for transaction {transaction.id}")
        return False

    # Map product to tier
    tier = map_product_to_tier(transaction.product_id)
    if not tier:
        logger.warning(f"Unknown product ID: {transaction.product_id}")
        tier = SubscriptionTier.PRO  # Default to PRO if product unknown

    # Calculate period dates (1 month subscription)
    period_start = transaction.time or datetime.now(timezone.utc)
    period_end = period_start + timedelta(days=30)

    # Update subscription
    subscription.tier = tier
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.source = SubscriptionSource.PAYREXX
    subscription.external_id = transaction.subscription_id or transaction.id
    subscription.current_period_start = period_start
    subscription.current_period_end = period_end

    logger.info(f"Activated {tier.value} subscription for user {subscription.user_id}")
    return True


async def handle_payment_failed(
    db: AsyncSession, transaction: PayrexxTransaction
) -> bool:
    """Handle failed payment - mark subscription as past due."""
    subscription = None
    if transaction.subscription_id:
        subscription = await get_subscription_by_external_id(db, transaction.subscription_id)

    if not subscription:
        logger.warning(f"No subscription found for failed payment {transaction.id}")
        return False

    subscription.status = SubscriptionStatus.PAST_DUE
    logger.info(f"Marked subscription {subscription.id} as past_due")
    return True


async def handle_subscription_cancelled(
    db: AsyncSession, transaction: PayrexxTransaction
) -> bool:
    """Handle subscription cancellation."""
    subscription = None
    if transaction.subscription_id:
        subscription = await get_subscription_by_external_id(db, transaction.subscription_id)

    if not subscription:
        logger.warning(f"No subscription found for cancellation {transaction.id}")
        return False

    subscription.status = SubscriptionStatus.CANCELLED
    logger.info(f"Cancelled subscription {subscription.id}")
    return True


async def handle_refund(
    db: AsyncSession, transaction: PayrexxTransaction
) -> bool:
    """Handle refund - downgrade to free tier."""
    subscription = None
    if transaction.subscription_id:
        subscription = await get_subscription_by_external_id(db, transaction.subscription_id)

    if not subscription:
        logger.warning(f"No subscription found for refund {transaction.id}")
        return False

    subscription.tier = SubscriptionTier.FREE
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.source = None
    subscription.external_id = None
    subscription.current_period_start = None
    subscription.current_period_end = None
    logger.info(f"Refunded subscription {subscription.id}, downgraded to free")
    return True


async def handle_subscription_event(
    db: AsyncSession, sub_event: PayrexxSubscriptionEvent
) -> bool:
    """Handle subscription status update from Payrexx."""
    if not sub_event.user_email:
        logger.warning(f"No email in subscription event {sub_event.id}")
        return False

    subscription = await get_subscription_by_user_email(db, sub_event.user_email)
    if not subscription:
        logger.warning(f"No subscription found for email {sub_event.user_email}")
        return False

    if sub_event.status == "active":
        # Activate subscription
        subscription.tier = SubscriptionTier.PRO
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.source = SubscriptionSource.PAYREXX
        subscription.external_id = str(sub_event.id)

        # Set period dates from Payrexx data
        if sub_event.start:
            subscription.current_period_start = datetime.combine(
                sub_event.start.date(), datetime.min.time(), tzinfo=timezone.utc
            )
        else:
            subscription.current_period_start = datetime.now(timezone.utc)

        if sub_event.valid_until:
            subscription.current_period_end = datetime.combine(
                sub_event.valid_until.date(), datetime.min.time(), tzinfo=timezone.utc
            )
        else:
            subscription.current_period_end = subscription.current_period_start + timedelta(days=30)

        logger.info(f"Activated PRO subscription for user {subscription.user_id} via subscription event")
        return True

    elif sub_event.status == "cancelled":
        subscription.status = SubscriptionStatus.CANCELLED
        logger.info(f"Cancelled subscription for user {subscription.user_id}")
        return True

    else:
        logger.info(f"Unhandled subscription status: {sub_event.status}")
        return True


async def process_webhook(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Process Payrexx webhook event.
    Handles both transaction and subscription event types.
    """
    # Determine event type - subscription or transaction
    is_subscription_event = "subscription" in payload and "transaction" not in payload

    if is_subscription_event:
        sub_event = parse_subscription_event(payload)
        event_id = f"sub_{sub_event.id}"
        event_type = f"subscription_{sub_event.status}"
    else:
        transaction = parse_transaction(payload)
        event_id = transaction.id
        event_type = transaction.status

    if not event_id:
        return {"success": False, "error": "Missing event ID"}

    # Check idempotency
    existing = await check_idempotency(db, "payrexx", event_id)
    if existing and existing.processed:
        logger.info(f"Duplicate webhook event: {event_id}")
        return {"success": True, "message": "Already processed"}

    # Record event for audit
    webhook_event = existing or await record_webhook_event(
        db, "payrexx", event_id, event_type, payload
    )

    try:
        success = False

        if is_subscription_event:
            # Handle subscription event
            success = await handle_subscription_event(db, sub_event)
        else:
            # Handle transaction event
            if transaction.status == "confirmed":
                success = await handle_payment_confirmed(db, transaction)
            elif transaction.status in ("declined", "error"):
                success = await handle_payment_failed(db, transaction)
            elif transaction.status == "cancelled":
                success = await handle_subscription_cancelled(db, transaction)
            elif transaction.status in ("refunded", "partially-refunded"):
                success = await handle_refund(db, transaction)
            else:
                logger.info(f"Unhandled transaction status: {transaction.status}")
                success = True

        webhook_event.processed = success
        await db.flush()

        return {"success": success, "message": f"Processed {event_type} event"}

    except Exception as e:
        logger.exception(f"Error processing webhook: {e}")
        webhook_event.error = str(e)
        await db.flush()
        return {"success": False, "error": str(e)}
