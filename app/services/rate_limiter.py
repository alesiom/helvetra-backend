"""
Rate limiting service using Redis.
Tracks request counts per IP address with configurable limits.
"""

from dataclasses import dataclass
from datetime import datetime

import redis.asyncio as redis

from app.config import get_settings

settings = get_settings()


@dataclass
class RateLimitResult:
    """Result of rate limit check."""

    allowed: bool
    remaining: int
    reset_at: int  # Unix timestamp
    retry_after: int | None = None  # Seconds until retry


class RateLimiter:
    """Redis-based rate limiter with sliding window."""

    def __init__(self):
        """Initialize rate limiter with Redis connection."""
        self.client: redis.Redis | None = None
        self.minute_limit = settings.rate_limit_per_minute
        self.day_limit = settings.rate_limit_per_day

    async def connect(self):
        """Establish Redis connection."""
        if self.client is None:
            self.client = redis.from_url(settings.redis_url)

    async def close(self):
        """Close Redis connection."""
        if self.client:
            await self.client.aclose()
            self.client = None

    async def check_rate_limit(self, ip_address: str) -> RateLimitResult:
        """
        Check if request is within rate limits.
        Returns result with remaining quota and reset time.
        """
        await self.connect()

        now = datetime.now()
        current_minute = now.strftime("%Y%m%d%H%M")
        current_day = now.strftime("%Y%m%d")

        minute_key = f"rate:minute:{ip_address}:{current_minute}"
        day_key = f"rate:day:{ip_address}:{current_day}"

        # Get current counts
        pipe = self.client.pipeline()
        pipe.get(minute_key)
        pipe.get(day_key)
        results = await pipe.execute()

        minute_count = int(results[0] or 0)
        day_count = int(results[1] or 0)

        # Check minute limit
        if minute_count >= self.minute_limit:
            seconds_until_next_minute = 60 - now.second
            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_at=int(now.timestamp()) + seconds_until_next_minute,
                retry_after=seconds_until_next_minute,
            )

        # Check day limit
        if day_count >= self.day_limit:
            # Calculate seconds until midnight
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            next_midnight = midnight.replace(day=midnight.day + 1)
            seconds_until_midnight = int((next_midnight - now).total_seconds())
            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_at=int(next_midnight.timestamp()),
                retry_after=seconds_until_midnight,
            )

        # Increment counters
        pipe = self.client.pipeline()
        pipe.incr(minute_key)
        pipe.expire(minute_key, 60)
        pipe.incr(day_key)
        pipe.expire(day_key, 86400)
        await pipe.execute()

        # Return remaining (use the more restrictive limit)
        remaining_minute = self.minute_limit - minute_count - 1
        remaining_day = self.day_limit - day_count - 1
        remaining = min(remaining_minute, remaining_day)

        return RateLimitResult(
            allowed=True,
            remaining=remaining,
            reset_at=int(now.timestamp()) + (60 - now.second),
        )


# Global rate limiter instance
rate_limiter = RateLimiter()
