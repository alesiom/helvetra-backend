"""
Authentication-specific rate limiting.
Provides stricter limits for login, registration, and brute force protection.
"""

from dataclasses import dataclass
from datetime import datetime

import redis.asyncio as redis

from app.config import get_settings

settings = get_settings()


@dataclass
class AuthRateLimitResult:
    """Result of auth rate limit check."""

    allowed: bool
    remaining: int
    retry_after: int | None = None
    locked_out: bool = False
    lockout_remaining: int | None = None


class AuthRateLimiter:
    """Redis-based rate limiter for authentication endpoints."""

    # Rate limits per endpoint type
    LOGIN_LIMIT_PER_MINUTE = 10
    REGISTER_LIMIT_PER_HOUR = 10

    # Brute force protection
    MAX_FAILED_ATTEMPTS = 10
    LOCKOUT_DURATION = 900  # 15 minutes in seconds

    def __init__(self):
        """Initialize auth rate limiter."""
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

    async def check_login_limit(self, ip_address: str) -> AuthRateLimitResult:
        """Check if login attempt is within rate limits (5/min per IP)."""
        await self.connect()

        now = datetime.now()
        current_minute = now.strftime("%Y%m%d%H%M")
        key = f"auth:login:{ip_address}:{current_minute}"

        count = int(await self.client.get(key) or 0)

        if count >= self.LOGIN_LIMIT_PER_MINUTE:
            seconds_until_next_minute = 60 - now.second
            return AuthRateLimitResult(
                allowed=False,
                remaining=0,
                retry_after=seconds_until_next_minute,
            )

        await self.client.incr(key)
        await self.client.expire(key, 60)

        return AuthRateLimitResult(
            allowed=True,
            remaining=self.LOGIN_LIMIT_PER_MINUTE - count - 1,
        )

    async def check_register_limit(self, ip_address: str) -> AuthRateLimitResult:
        """Check if registration attempt is within rate limits (3/hour per IP)."""
        await self.connect()

        now = datetime.now()
        current_hour = now.strftime("%Y%m%d%H")
        key = f"auth:register:{ip_address}:{current_hour}"

        count = int(await self.client.get(key) or 0)

        if count >= self.REGISTER_LIMIT_PER_HOUR:
            seconds_until_next_hour = 3600 - (now.minute * 60 + now.second)
            return AuthRateLimitResult(
                allowed=False,
                remaining=0,
                retry_after=seconds_until_next_hour,
            )

        await self.client.incr(key)
        await self.client.expire(key, 3600)

        return AuthRateLimitResult(
            allowed=True,
            remaining=self.REGISTER_LIMIT_PER_HOUR - count - 1,
        )

    # Lockout is per-(email, IP) rather than per-email so a single attacker
    # can't keep a victim's account permanently locked by rotating proxies —
    # the lockout only affects the attacker's own IPs. See helvetra/backend#95.

    async def check_account_lockout(
        self, email: str, ip_address: str
    ) -> AuthRateLimitResult:
        """Check if (email, IP) pair is locked out due to failed attempts."""
        await self.connect()

        lockout_key = f"auth:lockout:{email}:{ip_address}"
        lockout_ttl = await self.client.ttl(lockout_key)

        if lockout_ttl > 0:
            return AuthRateLimitResult(
                allowed=False,
                remaining=0,
                locked_out=True,
                lockout_remaining=lockout_ttl,
            )

        return AuthRateLimitResult(allowed=True, remaining=self.MAX_FAILED_ATTEMPTS)

    async def record_failed_attempt(
        self, email: str, ip_address: str
    ) -> AuthRateLimitResult:
        """Record a failed login attempt; lock out (email, IP) when over threshold."""
        await self.connect()

        attempts_key = f"auth:failed:{email}:{ip_address}"
        lockout_key = f"auth:lockout:{email}:{ip_address}"

        attempts = await self.client.incr(attempts_key)
        await self.client.expire(attempts_key, self.LOCKOUT_DURATION)

        if attempts >= self.MAX_FAILED_ATTEMPTS:
            await self.client.set(lockout_key, "1", ex=self.LOCKOUT_DURATION)
            await self.client.delete(attempts_key)
            return AuthRateLimitResult(
                allowed=False,
                remaining=0,
                locked_out=True,
                lockout_remaining=self.LOCKOUT_DURATION,
            )

        return AuthRateLimitResult(
            allowed=True,
            remaining=self.MAX_FAILED_ATTEMPTS - attempts,
        )

    async def clear_failed_attempts(self, email: str, ip_address: str) -> None:
        """Clear failed attempts on successful login from this IP."""
        await self.connect()
        await self.client.delete(f"auth:failed:{email}:{ip_address}")


# Global auth rate limiter instance
auth_rate_limiter = AuthRateLimiter()
