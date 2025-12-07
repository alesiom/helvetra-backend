"""
Subscription API schemas.
Defines request/response models for subscription endpoints.
"""

from datetime import datetime

from pydantic import BaseModel

from app.models.subscription import SubscriptionStatus, SubscriptionTier


class SubscriptionResponse(BaseModel):
    """Current subscription and usage status."""

    tier: SubscriptionTier
    status: SubscriptionStatus
    characters_used: int
    characters_limit: int
    credits_remaining: int
    can_translate: bool
    period_start: datetime | None
    period_end: datetime | None

    model_config = {"from_attributes": True}
