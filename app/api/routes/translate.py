"""
Translation endpoint.
Handles text translation requests between supported languages.
"""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_client_ip, get_current_user_optional
from app.core.database import get_db
from app.core.tiers import Tier, get_tier_config
from app.models.user import User
from app.schemas.translate import SUPPORTED_LANGUAGE_CODES, TranslateRequest, TranslateResponse
from app.services.apple_storekit import verify_transaction
from app.services.subscription import get_or_create_subscription, record_usage
from app.services.translation import TranslationValidationError, translate_text
from app.services.usage_tracker import anonymous_usage_tracker

logger = logging.getLogger(__name__)
router = APIRouter()


async def get_storekit_tier(request: Request) -> str | None:
    """Check if request has a valid StoreKit subscription and return tier."""
    jws = request.headers.get("X-StoreKit-JWS")
    if not jws:
        return None

    try:
        from datetime import datetime, timezone

        transaction = await verify_transaction(jws)
        if transaction and transaction.tier:
            # Check if subscription is still valid
            if transaction.expires_date:
                now = datetime.now(timezone.utc)
                if transaction.expires_date > now:
                    logger.info(f"StoreKit subscription valid: {transaction.product_id}")
                    return transaction.tier
            else:
                # Non-expiring product - assume valid
                return transaction.tier
        return None
    except Exception as e:
        logger.warning(f"StoreKit verification failed in translate: {e}")
        return None


def get_user_tier(
    user: User | None, subscription_tier: str | None, is_ios_client: bool = False
) -> Tier:
    """Determine the effective tier for a request."""
    # If we have a subscription tier (from DB or StoreKit), use it
    if subscription_tier:
        return Tier(subscription_tier)
    # Anonymous user with no subscription
    if user is None:
        # iOS app users get FREE tier limits (20k/month) instead of ANONYMOUS (5k/week)
        return Tier.FREE if is_ios_client else Tier.ANONYMOUS
    # Authenticated user with no subscription
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
    # Validate language codes against supported list
    if request.source_lang != "auto" and request.source_lang not in SUPPORTED_LANGUAGE_CODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "UNSUPPORTED_LANGUAGE",
                "message": (
                    f"'{request.source_lang}' is not yet supported. "
                    "Interested in this language? Reach out to gruezi@helvetra.ch"
                ),
            },
        )
    if request.target_lang not in SUPPORTED_LANGUAGE_CODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "UNSUPPORTED_LANGUAGE",
                "message": (
                    f"'{request.target_lang}' is not yet supported. "
                    "Interested in this language? Reach out to gruezi@helvetra.ch"
                ),
            },
        )

    # Check if request is from iOS app
    is_ios_client = http_request.headers.get("X-Client") == "helvetra-ios"

    # Determine user tier
    subscription_tier = None
    storekit_tier = None

    if user:
        subscription = await get_or_create_subscription(db, user.id)
        subscription_tier = subscription.tier.value
    else:
        # For anonymous users, check for StoreKit subscription
        storekit_tier = await get_storekit_tier(http_request)
        if storekit_tier:
            subscription_tier = storekit_tier

    tier = get_user_tier(user, subscription_tier, is_ios_client)
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

        # Record usage for authenticated users
        if user:
            await record_usage(db, user.id, text_length)
            await db.commit()

        return TranslateResponse(
            success=True,
            data=response_data,
            meta={
                "characters": text_length,
                "processing_time_ms": result.processing_time_ms,
            },
        )
    except TranslationValidationError as e:
        logger.warning(
            "Translation validation rejected (%s): %s",
            e.code,
            e.detail,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": e.code,
                "message": (
                    "We couldn't produce a clean translation. "
                    "Please try again, or rephrase the text."
                ),
            },
        )
    except ValueError as e:
        if "suspiciously long" in str(e):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "SUSPICIOUS_OUTPUT",
                    "message": (
                        "Translation rejected due to suspicious output. "
                        "Please provide text to translate, not instructions."
                    ),
                },
            )
        raise
    except httpx.HTTPError as e:
        # Upstream model API failure is not our 500: tell clients the
        # service is temporarily unavailable so they can show a real message.
        logger.error(f"Upstream translation API error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "UPSTREAM_UNAVAILABLE",
                "message": (
                    "The translation service is temporarily unavailable. "
                    "Please try again in a moment."
                ),
            },
        )
