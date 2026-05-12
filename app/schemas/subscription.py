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


class UsageHistoryPoint(BaseModel):
    """One historical usage period, used for the dashboard chart."""

    period_start: datetime
    period_end: datetime
    characters_used: int
    characters_limit: int


class UsageHistoryResponse(BaseModel):
    """Ordered list of recent usage periods (oldest → newest)."""

    periods: list[UsageHistoryPoint]


class B2BSubscriptionResponse(BaseModel):
    """B2B subscription details for the customer dashboard."""

    has_subscription: bool
    tier: str | None = None
    status: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    is_trialing: bool = False
    characters_used: int = 0
    characters_limit: int = 0
    characters_remaining: int = 0
    max_chars_per_request: int = 0
    max_api_keys: int = 0


class AppleVerifyRequest(BaseModel):
    """Apple StoreKit transaction verification request."""

    signed_transaction: str


class AppleVerifyResponse(BaseModel):
    """Apple StoreKit verification result."""

    success: bool
    tier: str | None = None
    expires_at: datetime | None = None
    message: str | None = None
