"""
Generic webhook-event persistence helpers.

These were originally embedded in app/services/payrexx.py, but the
Payrexx-specific code has been removed (helvetra/backend#80, #89). The
utilities themselves are payment-provider agnostic — currently consumed
by the Stripe webhook handler and any future provider integration.

Two responsibilities:

- Idempotency: webhook providers retry. We dedupe by (source, event_id).
- Audit log: every received event is persisted as JSON for later
  inspection, regardless of whether it was processed successfully.
"""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription
from app.models.webhook import WebhookEvent


async def check_idempotency(
    db: AsyncSession, source: str, event_id: str
) -> WebhookEvent | None:
    """Return the existing WebhookEvent row for (source, event_id), or None."""
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
    """
    Persist a webhook event for idempotency and audit.

    `default=str` on json.dumps coerces non-JSON-native types — notably
    Decimal, which Stripe uses for fractional-unit graduated prices — to
    strings so the payload can always be stored. Without it the B2B
    metered-price webhooks raise TypeError.
    """
    event = WebhookEvent(
        source=source,
        event_id=event_id,
        event_type=event_type,
        payload=json.dumps(payload, default=str),
        processed=processed,
        error=error,
    )
    db.add(event)
    await db.flush()
    return event


async def get_subscription_by_external_id(
    db: AsyncSession, external_id: str
) -> Subscription | None:
    """Find a subscription by its payment-provider external ID."""
    result = await db.execute(
        select(Subscription).where(Subscription.external_id == external_id)
    )
    return result.scalar_one_or_none()
