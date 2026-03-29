"""
Webhook endpoints for payment providers.
Handles incoming webhooks from Stripe, Payrexx, and Apple.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.payrexx import process_webhook as process_payrexx_webhook
from app.services.stripe_service import process_webhook as process_stripe_webhook
from app.services.stripe_service import verify_webhook_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks")


@router.post("/payrexx")
async def payrexx_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """
    Handle Payrexx payment webhooks.

    Payrexx sends transaction updates for:
    - confirmed: Payment successful
    - declined/error: Payment failed
    - cancelled: Subscription cancelled
    - refunded: Payment refunded
    """
    try:
        payload = await request.json()
    except Exception:
        logger.warning("Invalid JSON in Payrexx webhook")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    status = payload.get("transaction", {}).get("status", "unknown")
    logger.info(f"Received Payrexx webhook: {status}")

    result = await process_payrexx_webhook(db, payload)

    if not result["success"]:
        logger.error(f"Webhook processing failed: {result.get('error')}")
        # Return 200 to prevent Payrexx from retrying (we've logged the error)
        # The webhook event is stored for manual review

    await db.commit()

    return {"status": "ok"}


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """
    Handle Stripe payment webhooks.

    Stripe sends event notifications for:
    - checkout.session.completed: Successful checkout
    - invoice.payment_succeeded: Subscription renewed
    - invoice.payment_failed: Payment failed
    - customer.subscription.deleted: Subscription cancelled
    """
    body = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    event = verify_webhook_signature(body, sig_header)
    if event is None:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event.type
    logger.info(f"Received Stripe webhook: {event_type}")

    result = await process_stripe_webhook(db, event)

    if not result["success"]:
        logger.error(f"Stripe webhook processing failed: {result.get('error')}")

    await db.commit()

    return {"status": "ok"}


@router.post("/apple")
async def apple_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """
    Handle App Store Server Notifications v2.

    Apple sends notifications for:
    - SUBSCRIBED: New subscription
    - DID_RENEW: Subscription renewed
    - EXPIRED: Subscription expired
    - DID_CHANGE_RENEWAL_STATUS: Auto-renew toggled
    - REVOKE: Subscription revoked (refund)
    """
    from sqlalchemy import select

    from app.models.subscription import (
        Subscription,
        SubscriptionSource,
        SubscriptionStatus,
        SubscriptionTier,
    )
    from app.services.apple_storekit import parse_server_notification
    from app.services.subscription import sync_usage_period_limit

    try:
        payload = await request.json()
    except Exception:
        logger.warning("Invalid JSON in Apple webhook")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    signed_payload = payload.get("signedPayload", "")
    if not signed_payload:
        logger.warning("Missing signedPayload in Apple webhook")
        raise HTTPException(status_code=400, detail="Missing signedPayload")

    # Parse and validate the notification
    status_update = await parse_server_notification(signed_payload)
    if not status_update:
        logger.error("Failed to parse Apple server notification")
        return {"status": "ok"}  # Return 200 to prevent retries

    # Find subscription by Apple original transaction ID
    result = await db.execute(
        select(Subscription).where(
            Subscription.external_id == status_update.original_transaction_id,
            Subscription.source == SubscriptionSource.APPLE,
        )
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        logger.warning(
            f"No subscription found for Apple transaction: "
            f"{status_update.original_transaction_id}"
        )
        return {"status": "ok"}

    # Update subscription based on status
    if status_update.status == "active":
        old_tier = subscription.tier
        if status_update.tier:
            subscription.tier = SubscriptionTier(status_update.tier)
        subscription.status = SubscriptionStatus.ACTIVE
        if status_update.expires_date:
            subscription.current_period_end = status_update.expires_date

        if old_tier != subscription.tier:
            await sync_usage_period_limit(db, subscription.user_id, subscription.tier)

    elif status_update.status == "expired":
        old_tier = subscription.tier
        subscription.tier = SubscriptionTier.FREE
        subscription.status = SubscriptionStatus.EXPIRED
        subscription.source = None
        subscription.external_id = None

        if old_tier != SubscriptionTier.FREE:
            await sync_usage_period_limit(db, subscription.user_id, SubscriptionTier.FREE)

    elif status_update.status == "in_billing_retry":
        subscription.status = SubscriptionStatus.PAST_DUE

    logger.info(
        f"Updated Apple subscription {subscription.id}: "
        f"{status_update.status}"
    )

    await db.commit()

    return {"status": "ok"}
