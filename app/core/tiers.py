"""
Centralized tier configuration.
Single source of truth for feature access and limits across all subscription tiers.
"""

from dataclasses import dataclass
from enum import Enum


class Tier(str, Enum):
    """All user tiers including anonymous."""

    ANONYMOUS = "anonymous"
    FREE = "free"
    PRO = "pro"
    BUSINESS = "business"


@dataclass(frozen=True)
class TierConfig:
    """Configuration for a subscription tier."""

    # Character limits
    max_chars_per_request: int
    period_limit: int  # Monthly for registered users, weekly for anonymous
    period_type: str  # "weekly" or "monthly"

    # Feature flags
    formality: bool  # Can use formal/informal toggle


TIER_CONFIGS: dict[Tier, TierConfig] = {
    Tier.ANONYMOUS: TierConfig(
        max_chars_per_request=400,
        period_limit=5_000,
        period_type="weekly",
        formality=True,
    ),
    Tier.FREE: TierConfig(
        max_chars_per_request=1_000,
        period_limit=20_000,
        period_type="monthly",
        formality=True,
    ),
    Tier.PRO: TierConfig(
        max_chars_per_request=5_000,
        period_limit=500_000,
        period_type="monthly",
        formality=True,
    ),
    Tier.BUSINESS: TierConfig(
        max_chars_per_request=10_000,
        period_limit=2_000_000,
        period_type="monthly",
        formality=True,
    ),
}


def get_tier_config(tier: Tier | str) -> TierConfig:
    """Get configuration for a tier by enum or string value."""
    if isinstance(tier, str):
        tier = Tier(tier)
    return TIER_CONFIGS[tier]


def can_use_formality(tier: Tier | str) -> bool:
    """Check if a tier can use the formality feature."""
    return get_tier_config(tier).formality


def get_max_chars(tier: Tier | str) -> int:
    """Get max characters per request for a tier."""
    return get_tier_config(tier).max_chars_per_request


def get_period_limit(tier: Tier | str) -> int:
    """Get period character limit for a tier."""
    return get_tier_config(tier).period_limit
