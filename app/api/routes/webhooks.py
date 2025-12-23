"""
Webhook endpoints for payment providers.
Handles incoming webhooks from Payrexx and other payment services.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.payrexx import process_webhook

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

    result = await process_webhook(db, payload)

    if not result["success"]:
        logger.error(f"Webhook processing failed: {result.get('error')}")
        # Return 200 to prevent Payrexx from retrying (we've logged the error)
        # The webhook event is stored for manual review

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
        if status_update.tier:
            subscription.tier = SubscriptionTier(status_update.tier)
        subscription.status = SubscriptionStatus.ACTIVE
        if status_update.expires_date:
            subscription.current_period_end = status_update.expires_date

    elif status_update.status == "expired":
        subscription.tier = SubscriptionTier.FREE
        subscription.status = SubscriptionStatus.EXPIRED
        subscription.source = None
        subscription.external_id = None

    elif status_update.status == "in_billing_retry":
        subscription.status = SubscriptionStatus.PAST_DUE

    logger.info(
        f"Updated Apple subscription {subscription.id}: "
        f"{status_update.status}"
    )

    await db.commit()

    return {"status": "ok"}
