"""
Custom middleware for request processing.
Handles rate limiting and other cross-cutting concerns.
"""

import logging
from datetime import datetime, timezone

from cachetools import TTLCache
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.dependencies import get_client_ip
from app.services.apple_storekit import verify_transaction
from app.services.auth import decode_access_token
from app.services.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

# Cache verified StoreKit transactions for 5 minutes
_storekit_cache: TTLCache = TTLCache(maxsize=1000, ttl=300)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce rate limits on API requests."""

    # Paths exempt from rate limiting
    EXEMPT_PATHS = {"/api/health", "/docs", "/redoc", "/openapi.json"}

    def _is_authenticated(self, request: Request) -> bool:
        """Check if request has a valid Bearer token."""
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return False
        token = auth_header[7:]  # Remove "Bearer " prefix
        user_id = decode_access_token(token)
        return user_id is not None

    async def _has_valid_storekit_subscription(self, request: Request) -> bool:
        """Check if request has a valid StoreKit subscription via JWS header."""
        jws = request.headers.get("X-StoreKit-JWS")
        if not jws:
            return False

        # Check cache first (use first 64 chars as key to avoid huge cache keys)
        cache_key = jws[:64]
        cached = _storekit_cache.get(cache_key)
        if cached is not None:
            return cached

        # Verify with Apple
        try:
            transaction = await verify_transaction(jws)
            if transaction and transaction.tier:
                # Check if subscription is still valid
                if transaction.expires_date:
                    now = datetime.now(timezone.utc)
                    if transaction.expires_date > now:
                        _storekit_cache[cache_key] = True
                        logger.info(
                            f"Valid StoreKit subscription: {transaction.product_id}"
                        )
                        return True
                    else:
                        logger.info(
                            f"StoreKit subscription expired: {transaction.product_id}"
                        )
                        _storekit_cache[cache_key] = False
                        return False
                else:
                    # Non-expiring product or missing date - assume valid
                    _storekit_cache[cache_key] = True
                    return True

            _storekit_cache[cache_key] = False
            return False

        except Exception as e:
            logger.warning(f"StoreKit verification failed: {e}")
            return False

    async def dispatch(self, request: Request, call_next):
        """Check rate limit before processing request."""
        # Skip rate limiting for CORS preflight requests
        if request.method == "OPTIONS":
            return await call_next(request)

        # Skip rate limiting for exempt paths
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        # Skip IP-based rate limiting for authenticated users
        if self._is_authenticated(request):
            return await call_next(request)

        # Skip rate limiting for users with valid StoreKit subscription
        if await self._has_valid_storekit_subscription(request):
            return await call_next(request)

        client_ip = get_client_ip(request)

        # Check rate limit for anonymous users only
        result = await rate_limiter.check_rate_limit(client_ip)

        if not result.allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "Too many requests. Please try again later.",
                        "retry_after": result.retry_after,
                    },
                },
                headers={
                    "Retry-After": str(result.retry_after),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(result.reset_at),
                },
            )

        # Process request and add rate limit headers to response
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        response.headers["X-RateLimit-Reset"] = str(result.reset_at)

        return response
