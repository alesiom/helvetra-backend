"""
Generic webhook-event persistence helpers.

These were originally embedded in app/services/payrexx.py, but the
Payrexx-specific code has been removed (helvetra/backend#80, #89). The
utilities themselves are payment-provider agnostic — currently consumed
by the Stripe webhook handler and any future provider integration.

Two responsibilities:

- Idempotency: webhook providers retry. We dedupe by (source, event_id).
- Audit log: every received event is persisted as JSONB for later
  inspection (jsonb_path_ops etc. work), regardless of whether it was
  processed successfully.
"""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.webhook import WebhookEvent


def _normalise_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Coerce non-JSON-native types (e.g. Decimal in Stripe graduated prices)
    to strings via a json.dumps/loads round-trip so JSONB always accepts the
    input. Cheap enough for webhook traffic."""
    return json.loads(json.dumps(payload, default=str))


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
    """Persist a webhook event for idempotency and audit."""
    event = WebhookEvent(
        source=source,
        event_id=event_id,
        event_type=event_type,
        payload=_normalise_payload(payload),
        processed=processed,
        error=error,
    )
    db.add(event)
    await db.flush()
    return event


