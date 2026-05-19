"""
Feedback endpoint.
Handles user feedback (like/dislike) on translations.
"""

from datetime import datetime, timezone

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_client_ip
from app.config import get_settings
from app.core.database import get_db
from app.models.feedback import Feedback
from app.schemas.feedback import FeedbackRequest, FeedbackResponse

router = APIRouter()
settings = get_settings()

# Per-IP hourly cap on feedback submissions. The existing global IP rate
# limit (60/min) doesn't protect the feedback table from a slow-fill
# attack — at 60/min/IP with ~16 KB rows that's ~85 MB/day/IP of attacker-
# controlled text. 20/hour cuts that 180×. See helvetra/backend#100.
_FEEDBACK_PER_HOUR_LIMIT = 20

_redis_client: redis.Redis | None = None


async def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url)
    return _redis_client


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    """
    Store user feedback on a translation.
    Only stores data if user has given consent. Per-IP-per-hour capped
    to prevent slow-fill attacks against the feedback table.
    """
    if not request.consent:
        return FeedbackResponse(
            success=False,
            error={"code": "CONSENT_REQUIRED", "message": "User consent is required"},
        )

    client_ip = get_client_ip(http_request)
    hour_bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    rate_key = f"feedback:{client_ip}:{hour_bucket}"

    client = await _get_redis()
    count = await client.incr(rate_key)
    if count == 1:
        await client.expire(rate_key, 3600)
    if count > _FEEDBACK_PER_HOUR_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many feedback submissions from this IP this hour.",
        )

    feedback = Feedback(
        vote=request.vote,
        source_text=request.source_text,
        source_lang=request.source_lang,
        translated_text=request.translated_text,
        target_lang=request.target_lang,
        region=request.region,
        comment=request.comment,
    )
    db.add(feedback)

    return FeedbackResponse(success=True)
