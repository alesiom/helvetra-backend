"""
Optional-auth dependency tests.
A request without credentials stays anonymous; a request with bad credentials
is rejected with 401 instead of being silently downgraded to anonymous limits.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

settings = get_settings()


@pytest.fixture
def client():
    """Create test client for the API."""
    return TestClient(app)


def make_expired_access_token() -> str:
    """Create a structurally valid access token that expired an hour ago."""
    payload = {
        "sub": str(uuid4()),
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


class TestOptionalAuthRejectsBadTokens:
    """Bad credentials on optional-auth routes return 401 TOKEN_EXPIRED."""

    def test_translate_expired_token_returns_401(self, client: TestClient):
        """An expired access token must not fall back to anonymous limits."""
        response = client.post(
            "/api/v1/translate",
            json={"text": "Hello", "source_lang": "en", "target_lang": "fr"},
            headers={"Authorization": f"Bearer {make_expired_access_token()}"},
        )

        assert response.status_code == 401
        detail = response.json()["detail"]
        assert detail["code"] == "TOKEN_EXPIRED"
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_translate_malformed_token_returns_401(self, client: TestClient):
        """A malformed bearer token is rejected, not treated as anonymous."""
        response = client.post(
            "/api/v1/translate",
            json={"text": "Hello", "source_lang": "en", "target_lang": "fr"},
            headers={"Authorization": "Bearer not-a-jwt"},
        )

        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "TOKEN_EXPIRED"

    def test_limits_expired_token_returns_401(self, client: TestClient):
        """Limits endpoint must not report anonymous limits for expired tokens."""
        response = client.get(
            "/api/v1/subscription/limits",
            headers={"Authorization": f"Bearer {make_expired_access_token()}"},
        )

        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "TOKEN_EXPIRED"


class TestOptionalAuthAnonymousUnchanged:
    """Requests without credentials keep working as anonymous."""

    def test_limits_without_token_returns_anonymous_tier(self, client: TestClient):
        response = client.get("/api/v1/subscription/limits")

        assert response.status_code == 200
        data = response.json()
        assert data["tier"] == "anonymous"
        assert data["max_chars_per_request"] == 400
