"""
Subscription endpoints.
Provides subscription status and usage information.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.subscription import SubscriptionResponse
from app.services.subscription import get_usage_status

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
