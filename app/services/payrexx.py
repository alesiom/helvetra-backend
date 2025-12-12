"""
Payrexx payment integration service.
Handles webhook processing and subscription updates from payment events.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

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
    """Parse Payrexx webhook payload into structured data."""
    transaction = payload.get("transaction", {})
    invoice = payload.get("invoice", {})
    contact = payload.get("contact", {})

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


async def process_webhook(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Process Payrexx webhook event.
    Returns result dict with success status and message.
    """
    transaction = parse_transaction(payload)
    event_id = transaction.id

    if not event_id:
        return {"success": False, "error": "Missing transaction ID"}

    # Check idempotency
    existing = await check_idempotency(db, "payrexx", event_id)
    if existing and existing.processed:
        logger.info(f"Duplicate webhook event: {event_id}")
        return {"success": True, "message": "Already processed"}

    # Record event for audit
    event_type = transaction.status
    webhook_event = existing or await record_webhook_event(
        db, "payrexx", event_id, event_type, payload
    )

    try:
        # Route to appropriate handler based on status
        success = False
        if transaction.status == "confirmed":
            success = await handle_payment_confirmed(db, transaction)
        elif transaction.status in ("declined", "error"):
            success = await handle_payment_failed(db, transaction)
        elif transaction.status == "cancelled":
            success = await handle_subscription_cancelled(db, transaction)
        elif transaction.status in ("refunded", "partially-refunded"):
            success = await handle_refund(db, transaction)
        else:
            # Log but don't fail for unknown statuses
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
