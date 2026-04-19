"""
Subscription API schemas.
Defines request/response models for subscription endpoints.
"""

from datetime import datetime

from pydantic import BaseModel

from app.models.subscription import SubscriptionProduct, SubscriptionStatus, SubscriptionTier


class SubscriptionResponse(BaseModel):
    """Current subscription and usage status."""

    product: SubscriptionProduct = SubscriptionProduct.CONSUMER
    tier: SubscriptionTier
    status: SubscriptionStatus
    characters_used: int
    characters_limit: int
    credits_remaining: int
    can_translate: bool
    period_start: datetime | None
    period_end: datetime | None

    model_config = {"from_attributes": True}


class TierLimitsResponse(BaseModel):
    """Tier configuration and limits for the current user."""

    tier: str
    max_chars_per_request: int
    period_limit: int
    period_type: str
    formality: bool


class AnonymousUsageResponse(BaseModel):
    """Usage status for anonymous users."""

    characters_used: int
    characters_limit: int
    characters_remaining: int
    reset_at: int


class AppleVerifyRequest(BaseModel):
    """Apple StoreKit transaction verification request."""

    signed_transaction: str


class AppleVerifyResponse(BaseModel):
    """Apple StoreKit verification result."""

    success: bool
    tier: str | None = None
    expires_at: datetime | None = None
    message: str | None = None
