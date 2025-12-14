"""
Translation endpoint.
Handles text translation requests between supported languages.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_client_ip, get_current_user_optional
from app.core.database import get_db
from app.core.tiers import Tier, get_tier_config
from app.models.user import User
from app.schemas.translate import TranslateRequest, TranslateResponse
from app.services.subscription import get_or_create_subscription
from app.services.translation import translate_text
from app.services.usage_tracker import anonymous_usage_tracker

logger = logging.getLogger(__name__)
router = APIRouter()


def get_user_tier(user: User | None, subscription_tier: str | None) -> Tier:
    """Determine the effective tier for a request."""
    if user is None:
        return Tier.ANONYMOUS
    if subscription_tier:
        return Tier(subscription_tier)
    return Tier.FREE


@router.post("/translate", response_model=TranslateResponse)
async def translate(
    request: TranslateRequest,
    http_request: Request,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> TranslateResponse:
    """
    Translate text from source language to target language.
    Enforces per-request and period character limits based on user tier.
    """
    # Determine user tier
    subscription_tier = None
    if user:
        subscription = await get_or_create_subscription(db, user.id)
        subscription_tier = subscription.tier.value

    tier = get_user_tier(user, subscription_tier)
    config = get_tier_config(tier)
    text_length = len(request.text)

    # Enforce per-request character limit
    if text_length > config.max_chars_per_request:
        if tier == Tier.ANONYMOUS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "TEXT_TOO_LONG",
                    "message": f"Text exceeds {config.max_chars_per_request} character limit. Create a free account for longer texts.",
                    "limit": config.max_chars_per_request,
                },
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "TEXT_TOO_LONG",
                    "message": f"Text exceeds {config.max_chars_per_request} character limit for your plan.",
                    "limit": config.max_chars_per_request,
                },
            )

    # Enforce weekly limit for anonymous users
    if tier == Tier.ANONYMOUS:
        client_ip = get_client_ip(http_request)
        usage_result = await anonymous_usage_tracker.check_and_record_usage(
            client_ip, text_length
        )
        if not usage_result.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "WEEKLY_LIMIT_EXCEEDED",
                    "message": f"Weekly limit of {usage_result.characters_limit} characters reached. Create a free account for more.",
                    "characters_used": usage_result.characters_used,
                    "characters_limit": usage_result.characters_limit,
                    "reset_at": usage_result.reset_at,
                },
            )

    try:
        result = await translate_text(
            text=request.text,
            source_lang=request.source_lang,
            target_lang=request.target_lang,
            formality=request.formality,
            dialect=request.dialect,
        )

        # Build response data
        response_data = {
            "translation": result.translation,
            "source_lang": result.detected_source_lang or request.source_lang,
            "target_lang": request.target_lang,
        }

        # Include detected_source_lang when auto-detection was used
        if result.detected_source_lang:
            response_data["detected_source_lang"] = result.detected_source_lang

        return TranslateResponse(
            success=True,
            data=response_data,
            meta={
                "characters": text_length,
                "processing_time_ms": result.processing_time_ms,
            },
        )
    except Exception as e:
        logger.exception(f"Translation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
