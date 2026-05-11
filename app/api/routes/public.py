"""
Public API endpoints for B2B customers.
Authenticated via API key (X-API-Key header), separate from the consumer JWT-based API.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

import asyncio

from app.api.dependencies import get_current_user_from_api_key
from app.core.database import get_db
from app.core.tiers import Tier, get_tier_config
from app.models.api_key import ApiKey
from app.models.subscription import SubscriptionProduct
from app.models.user import User
from app.schemas.translate import SUPPORTED_LANGUAGE_CODES
from app.services.stripe_b2b import (
    generate_meter_idempotency_key,
    report_translation_meter_event,
)
from app.services.subscription import get_or_create_subscription, get_usage_status, record_usage
from app.services.translation import translate_text

logger = logging.getLogger(__name__)
router = APIRouter()

# Supported Swiss German dialects (same as consumer API)
SWISS_DIALECTS = {"bern", "zurich", "basel", "stgallen", "wallis", "luzern"}

SUPPORTED_LANGUAGES = [
    {"code": "de", "name": "German", "native_name": "Deutsch"},
    {"code": "gsw", "name": "Swiss German", "native_name": "Schwyzerdütsch"},
    {"code": "fr", "name": "French", "native_name": "Français"},
    {"code": "it", "name": "Italian", "native_name": "Italiano"},
    {"code": "en", "name": "English", "native_name": "English"},
    {"code": "rm", "name": "Romansh", "native_name": "Rumantsch"},
]


# --- Schemas ---


class PublicTranslateRequest(BaseModel):
    """Translation request for the public API."""

    text: str = Field(..., min_length=1)
    source_lang: str = Field(..., min_length=2, max_length=4)
    target_lang: str = Field(..., min_length=2, max_length=3)
    formality: str = Field(default="auto")
    dialect: str | None = Field(default=None)


class PublicTranslateResponse(BaseModel):
    """Translation result from the public API."""

    translation: str
    source_lang: str
    target_lang: str
    detected_source_lang: str | None = None
    characters: int


class PublicLanguageResponse(BaseModel):
    """Language entry in the supported languages list."""

    code: str
    name: str
    native_name: str


class PublicUsageResponse(BaseModel):
    """Current usage status for the authenticated API key owner."""

    characters_used: int
    characters_limit: int
    characters_remaining: int
    period_start: str | None
    period_end: str | None


class PublicErrorDetail(BaseModel):
    """Error response from the public API."""

    code: str
    message: str
    detail: dict[str, Any] | None = None


# --- Routes ---


@router.post("/translate", response_model=PublicTranslateResponse)
async def public_translate(
    request: PublicTranslateRequest,
    auth: tuple[User, ApiKey] = Depends(get_current_user_from_api_key),
    db: AsyncSession = Depends(get_db),
) -> PublicTranslateResponse:
    """Translate text between supported languages."""
    user, api_key = auth

    # Validate language codes
    if request.source_lang != "auto" and request.source_lang not in SUPPORTED_LANGUAGE_CODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "UNSUPPORTED_LANGUAGE",
                "message": f"'{request.source_lang}' is not supported.",
            },
        )
    if request.target_lang not in SUPPORTED_LANGUAGE_CODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "UNSUPPORTED_LANGUAGE",
                "message": f"'{request.target_lang}' is not supported.",
            },
        )

    # Validate dialect
    if request.dialect and request.dialect not in SWISS_DIALECTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "UNSUPPORTED_DIALECT",
                "message": f"'{request.dialect}' is not a supported dialect.",
            },
        )

    # Get B2B subscription and tier config
    subscription = await get_or_create_subscription(db, user.id, SubscriptionProduct.B2B)
    tier = Tier(subscription.tier.value)
    config = get_tier_config(tier, product="b2b")
    text_length = len(request.text)

    # Enforce per-request character limit
    if text_length > config.max_chars_per_request:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "TEXT_TOO_LONG",
                "message": f"Text exceeds {config.max_chars_per_request} character limit.",
                "limit": config.max_chars_per_request,
            },
        )

    # Check period usage
    usage_status = await record_usage(db, user.id, text_length)
    if not usage_status.can_translate:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "USAGE_LIMIT_EXCEEDED",
                "message": "Monthly character limit exceeded.",
                "characters_used": usage_status.characters_used,
                "characters_limit": usage_status.characters_limit,
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

        await db.commit()

        # Report usage to Stripe asynchronously so meter problems never
        # block the translation response.
        asyncio.create_task(
            report_translation_meter_event(
                stripe_customer_id=user.stripe_customer_id,
                characters=text_length,
                idempotency_key=generate_meter_idempotency_key(user.id, text_length),
            )
        )

        return PublicTranslateResponse(
            translation=result.translation,
            source_lang=result.detected_source_lang or request.source_lang,
            target_lang=request.target_lang,
            detected_source_lang=result.detected_source_lang,
            characters=text_length,
        )
    except ValueError as e:
        if "suspiciously long" in str(e):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "SUSPICIOUS_OUTPUT",
                    "message": "Translation rejected due to suspicious output.",
                },
            )
        raise HTTPException(
            status_code=500,
            detail={"code": "TRANSLATION_ERROR", "message": str(e)},
        )
    except Exception as e:
        logger.exception(f"Public API translation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail={"code": "INTERNAL_ERROR", "message": "Translation service error."},
        )


@router.get("/languages", response_model=list[PublicLanguageResponse])
async def public_languages(
    auth: tuple[User, ApiKey] = Depends(get_current_user_from_api_key),
) -> list[PublicLanguageResponse]:
    """List all supported languages for translation."""
    return [PublicLanguageResponse(**lang) for lang in SUPPORTED_LANGUAGES]


@router.get("/usage", response_model=PublicUsageResponse)
async def public_usage(
    auth: tuple[User, ApiKey] = Depends(get_current_user_from_api_key),
    db: AsyncSession = Depends(get_db),
) -> PublicUsageResponse:
    """Get current usage and remaining quota for the authenticated account."""
    user, _ = auth

    usage = await get_usage_status(db, user.id)
    remaining = max(0, usage.characters_limit - usage.characters_used)

    return PublicUsageResponse(
        characters_used=usage.characters_used,
        characters_limit=usage.characters_limit,
        characters_remaining=remaining,
        period_start=usage.period_start.isoformat() if usage.period_start else None,
        period_end=usage.period_end.isoformat() if usage.period_end else None,
    )
