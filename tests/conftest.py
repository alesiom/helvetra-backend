"""
Shared test configuration and fixtures.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

# Set test environment before importing app modules
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("APERTUS_API_KEY", "test-key")
os.environ.setdefault("APERTUS_API_BASE", "https://api.test.local")
os.environ.setdefault("APERTUS_MODEL", "test-model")


@pytest.fixture(autouse=True)
def mock_rate_limiter():
    """Auto-mock rate limiter for all tests to avoid Redis dependency."""
    from app.services.rate_limiter import RateLimitResult

    mock_result = RateLimitResult(
        allowed=True,
        remaining=59,
        reset_at=9999999999,
    )

    with patch(
        "app.core.middleware.rate_limiter.check_rate_limit",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        yield
