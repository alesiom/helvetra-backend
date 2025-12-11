"""
Anonymous usage tracking service.
Tracks character usage by IP address with weekly limits for anonymous users.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

import redis.asyncio as redis

from app.config import get_settings
from app.core.tiers import Tier, get_tier_config

settings = get_settings()


@dataclass
class UsageResult:
    """Result of usage check."""

    allowed: bool
    characters_used: int
    characters_limit: int
    characters_remaining: int
    reset_at: int  # Unix timestamp


def get_week_key() -> str:
    """Get the current ISO week identifier (YYYY-WW)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%G-W%V")


class AnonymousUsageTracker:
    """Redis-based tracker for anonymous user character usage."""

    def __init__(self):
        """Initialize tracker with Redis connection."""
        self.client: redis.Redis | None = None

    async def connect(self):
        """Establish Redis connection."""
        if self.client is None:
            self.client = redis.from_url(settings.redis_url)

    async def close(self):
        """Close Redis connection."""
        if self.client:
            await self.client.aclose()
            self.client = None

    async def check_and_record_usage(
        self, ip_address: str, characters: int
    ) -> UsageResult:
        """
        Check if usage is within limit and record the characters if allowed.
        Uses atomic operations to prevent race conditions.
        """
        await self.connect()

        config = get_tier_config(Tier.ANONYMOUS)
        limit = config.period_limit
        week_key = get_week_key()
        redis_key = f"usage:anon:{ip_address}:{week_key}"

        # Get current usage
        current = await self.client.get(redis_key)
        current_usage = int(current or 0)

        # Calculate reset time (end of current ISO week)
        now = datetime.now(timezone.utc)
        days_until_monday = (7 - now.weekday()) % 7 or 7
        next_monday = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        next_monday = next_monday.replace(day=now.day + days_until_monday)
        reset_at = int(next_monday.timestamp())

        # Check if adding these characters would exceed limit
        if current_usage + characters > limit:
            return UsageResult(
                allowed=False,
                characters_used=current_usage,
                characters_limit=limit,
                characters_remaining=max(0, limit - current_usage),
                reset_at=reset_at,
            )

        # Record usage atomically
        new_usage = await self.client.incrby(redis_key, characters)

        # Set expiry to 8 days (covers week + buffer)
        await self.client.expire(redis_key, 8 * 24 * 60 * 60)

        return UsageResult(
            allowed=True,
            characters_used=new_usage,
            characters_limit=limit,
            characters_remaining=max(0, limit - new_usage),
            reset_at=reset_at,
        )

    async def get_usage(self, ip_address: str) -> UsageResult:
        """Get current usage without recording anything."""
        await self.connect()

        config = get_tier_config(Tier.ANONYMOUS)
        limit = config.period_limit
        week_key = get_week_key()
        redis_key = f"usage:anon:{ip_address}:{week_key}"

        current = await self.client.get(redis_key)
        current_usage = int(current or 0)

        # Calculate reset time
        now = datetime.now(timezone.utc)
        days_until_monday = (7 - now.weekday()) % 7 or 7
        next_monday = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        next_monday = next_monday.replace(day=now.day + days_until_monday)
        reset_at = int(next_monday.timestamp())

        return UsageResult(
            allowed=current_usage < limit,
            characters_used=current_usage,
            characters_limit=limit,
            characters_remaining=max(0, limit - current_usage),
            reset_at=reset_at,
        )


# Global tracker instance
anonymous_usage_tracker = AnonymousUsageTracker()
