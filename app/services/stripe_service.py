"""
Stripe payment integration service.
Handles checkout session creation, webhook processing, and customer management.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.subscription import (
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
    SubscriptionTier,
)
from app.models.user import User
from app.services.payrexx import check_idempotency, record_webhook_event
from app.services.subscription import get_or_create_subscription, sync_usage_period_limit

logger = logging.getLogger(__name__)
settings = get_settings()

# Redirect URLs
BASE_URL = "https://helvetra.ch"
SUCCESS_URL = f"{BASE_URL}/pricing/success"
CANCEL_URL = f"{BASE_URL}/pricing/cancel"


@dataclass
class CheckoutResponse:
    """Response from Stripe checkout session creation."""

    success: bool
    gateway_url: str | None = None
    error: str | None = None


async def get_or_create_stripe_customer(
    db: AsyncSession, user: User
) -> str:
    """Get existing Stripe customer ID or create a new one."""
    if user.stripe_customer_id:
        return user.stripe_customer_id

    stripe.api_key = settings.stripe_secret_key

    customer = stripe.Customer.create(
        email=user.email,
        metadata={"user_id": str(user.id)},
    )

    user.stripe_customer_id = customer.id
    await db.flush()

    logger.info(f"Created Stripe customer {customer.id} for user {user.id}")
    return customer.id


async def create_checkout_session(
    db: AsyncSession,
    user: User,
    billing_period: str,
) -> CheckoutResponse:
    """Create a Stripe Checkout Session and return the URL."""
    if not settings.stripe_secret_key:
        logger.error("Stripe secret key not configured")
        return CheckoutResponse(success=False, error="Payment system not configured")

    stripe.api_key = settings.stripe_secret_key

    # Map billing period to Stripe Price ID
    price_id = (
        settings.stripe_price_monthly_id
        if billing_period == "monthly"
        else settings.stripe_price_yearly_id
    )

    if not price_id:
        logger.error(f"No Stripe price configured for {billing_period}")
        return CheckoutResponse(success=False, error="Price not configured")

    try:
        customer_id = await get_or_create_stripe_customer(db, user)

        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=SUCCESS_URL,
            cancel_url=CANCEL_URL,
            customer_update={"address": "auto"},
            payment_method_types=["card"],
        )

        logger.info(f"Created Stripe checkout session {session.id} for user {user.id}")
        return CheckoutResponse(success=True, gateway_url=session.url)

    except stripe.StripeError as e:
        logger.error(f"Stripe API error: {e}")
        return CheckoutResponse(success=False, error="Payment service error")


def verify_webhook_signature(payload: bytes, sig_header: str) -> stripe.Event | None:
    """Verify Stripe webhook signature and return the event object."""
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
        return event
    except stripe.SignatureVerificationError:
        logger.warning("Invalid Stripe webhook signature")
        return None
    except ValueError:
        logger.warning("Invalid Stripe webhook payload")
        return None


async def _handle_checkout_completed(
    db: AsyncSession, event_data: Any
) -> bool:
    """Activate PRO subscription after successful checkout."""
    session = event_data.object
    customer_id = session.customer
    stripe_sub_id = session.subscription

    if not customer_id:
        logger.warning("No customer ID in checkout session")
        return False

    # Find user by Stripe customer ID
    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        logger.warning(f"No user found for Stripe customer {customer_id}")
        return False

    subscription = await get_or_create_subscription(db, user.id)

    # Retrieve subscription details from Stripe for period dates
    stripe.api_key = settings.stripe_secret_key
    stripe_sub = stripe.Subscription.retrieve(stripe_sub_id)
    sub_item = stripe_sub.items.data[0]

    old_tier = subscription.tier
    subscription.tier = SubscriptionTier.PRO
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.source = SubscriptionSource.STRIPE
    subscription.external_id = stripe_sub_id
    subscription.current_period_start = datetime.fromtimestamp(
        sub_item.current_period_start, tz=timezone.utc
    )
    subscription.current_period_end = datetime.fromtimestamp(
        sub_item.current_period_end, tz=timezone.utc
    )

    if old_tier != SubscriptionTier.PRO:
        await sync_usage_period_limit(db, user.id, SubscriptionTier.PRO)

    logger.info(f"Activated PRO subscription for user {user.id} via Stripe checkout")
    return True


async def _handle_invoice_payment_succeeded(
    db: AsyncSession, event_data: Any
) -> bool:
    """Renew subscription on successful invoice payment."""
    invoice = event_data.object
    stripe_sub_id = invoice.subscription

    if not stripe_sub_id:
        return True  # One-off invoice, not subscription-related

    # Find subscription by external_id
    result = await db.execute(
        select(Subscription).where(
            Subscription.external_id == stripe_sub_id,
            Subscription.source == SubscriptionSource.STRIPE,
        )
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        logger.warning(f"No subscription found for Stripe sub {stripe_sub_id}")
        return False

    # Update period dates from the Stripe subscription
    stripe.api_key = settings.stripe_secret_key
    stripe_sub = stripe.Subscription.retrieve(stripe_sub_id)
    sub_item = stripe_sub.items.data[0]

    subscription.status = SubscriptionStatus.ACTIVE
    subscription.current_period_start = datetime.fromtimestamp(
        sub_item.current_period_start, tz=timezone.utc
    )
    subscription.current_period_end = datetime.fromtimestamp(
        sub_item.current_period_end, tz=timezone.utc
    )

    logger.info(f"Renewed subscription {subscription.id} via Stripe invoice")
    return True


async def _handle_invoice_payment_failed(
    db: AsyncSession, event_data: Any
) -> bool:
    """Mark subscription as past due on failed payment."""
    invoice = event_data.object
    stripe_sub_id = invoice.subscription

    if not stripe_sub_id:
        return True

    result = await db.execute(
        select(Subscription).where(
            Subscription.external_id == stripe_sub_id,
            Subscription.source == SubscriptionSource.STRIPE,
        )
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        logger.warning(f"No subscription found for failed invoice, sub {stripe_sub_id}")
        return False

    subscription.status = SubscriptionStatus.PAST_DUE
    logger.info(f"Marked subscription {subscription.id} as past_due")
    return True


async def _handle_subscription_deleted(
    db: AsyncSession, event_data: Any
) -> bool:
    """Downgrade to FREE tier when Stripe subscription is cancelled/deleted."""
    stripe_sub = event_data.object
    stripe_sub_id = stripe_sub.id

    result = await db.execute(
        select(Subscription).where(
            Subscription.external_id == stripe_sub_id,
            Subscription.source == SubscriptionSource.STRIPE,
        )
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        logger.warning(f"No subscription found for deleted Stripe sub {stripe_sub_id}")
        return False

    old_tier = subscription.tier
    subscription.tier = SubscriptionTier.FREE
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.source = None
    subscription.external_id = None
    subscription.current_period_start = None
    subscription.current_period_end = None

    if old_tier != SubscriptionTier.FREE:
        await sync_usage_period_limit(db, subscription.user_id, SubscriptionTier.FREE)

    logger.info(f"Downgraded subscription {subscription.id} to FREE (Stripe sub deleted)")
    return True


async def process_webhook(db: AsyncSession, event: Any) -> dict[str, Any]:
    """Route Stripe webhook events to the appropriate handler."""
    event_id = event.id
    event_type = event.type
    event_data = event.data

    if not event_id:
        return {"success": False, "error": "Missing event ID"}

    # Check idempotency
    existing = await check_idempotency(db, "stripe", event_id)
    if existing and existing.processed:
        logger.info(f"Duplicate Stripe webhook event: {event_id}")
        return {"success": True, "message": "Already processed"}

    # Record event for audit (convert Stripe object to dict for JSON storage)
    payload_dict = event_data.object.to_dict() if event_data else {}
    webhook_event = existing or await record_webhook_event(
        db, "stripe", event_id, event_type, payload_dict
    )

    try:
        if event_type == "checkout.session.completed":
            success = await _handle_checkout_completed(db, event_data)
        elif event_type == "invoice.payment_succeeded":
            success = await _handle_invoice_payment_succeeded(db, event_data)
        elif event_type == "invoice.payment_failed":
            success = await _handle_invoice_payment_failed(db, event_data)
        elif event_type == "customer.subscription.deleted":
            success = await _handle_subscription_deleted(db, event_data)
        else:
            logger.info(f"Unhandled Stripe event type: {event_type}")
            success = True

        webhook_event.processed = success
        await db.flush()

        return {"success": success, "message": f"Processed {event_type} event"}

    except Exception as e:
        logger.exception(f"Error processing Stripe webhook: {e}")
        webhook_event.error = str(e)
        await db.flush()
        return {"success": False, "error": str(e)}


async def cancel_stripe_subscription(external_id: str) -> bool:
    """Cancel a Stripe subscription. Returns True if cancelled successfully."""
    if not settings.stripe_secret_key:
        logger.error("Stripe secret key not configured")
        return False

    stripe.api_key = settings.stripe_secret_key

    try:
        stripe.Subscription.cancel(external_id)
        logger.info(f"Cancelled Stripe subscription {external_id}")
        return True
    except stripe.StripeError as e:
        logger.error(f"Error cancelling Stripe subscription {external_id}: {e}")
        return False
