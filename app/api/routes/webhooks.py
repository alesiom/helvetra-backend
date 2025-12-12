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
