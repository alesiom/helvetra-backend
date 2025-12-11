"""
Subscription endpoints.
Provides subscription status and usage information.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_client_ip, get_current_user, get_current_user_optional
from app.core.database import get_db
from app.core.tiers import Tier, get_tier_config
from app.models.user import User
from app.schemas.subscription import (
    AnonymousUsageResponse,
    SubscriptionResponse,
    TierLimitsResponse,
)
from app.services.subscription import get_or_create_subscription, get_usage_status
from app.services.usage_tracker import anonymous_usage_tracker

router = APIRouter(prefix="/subscription")


@router.get("", response_model=SubscriptionResponse)
async def get_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionResponse:
    """Get current subscription status and usage for the authenticated user."""
    status = await get_usage_status(db, user.id)

    return SubscriptionResponse(
        tier=status.tier,
        status=status.status,
        characters_used=status.characters_used,
        characters_limit=status.characters_limit,
        credits_remaining=status.credits_remaining,
        can_translate=status.can_translate,
        period_start=status.period_start,
        period_end=status.period_end,
    )


@router.get("/limits", response_model=TierLimitsResponse)
async def get_tier_limits(
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> TierLimitsResponse:
    """Get tier limits for the current user (or anonymous defaults)."""
    if user:
        subscription = await get_or_create_subscription(db, user.id)
        tier = Tier(subscription.tier.value)
    else:
        tier = Tier.ANONYMOUS

    config = get_tier_config(tier)

    return TierLimitsResponse(
        tier=tier.value,
        max_chars_per_request=config.max_chars_per_request,
        period_limit=config.period_limit,
        period_type=config.period_type,
        formality=config.formality,
    )


@router.get("/anonymous-usage", response_model=AnonymousUsageResponse)
async def get_anonymous_usage(request: Request) -> AnonymousUsageResponse:
    """Get current usage for anonymous users (tracked by IP)."""
    client_ip = get_client_ip(request)
    usage = await anonymous_usage_tracker.get_usage(client_ip)

    return AnonymousUsageResponse(
        characters_used=usage.characters_used,
        characters_limit=usage.characters_limit,
        characters_remaining=usage.characters_remaining,
        reset_at=usage.reset_at,
    )
