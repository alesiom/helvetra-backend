"""
Global error envelope tests.
Every failure path must emit {"success": false, "error": {"code", "message"}}
so web and iOS clients can rely on a single shape.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Create test client for the API."""
    return TestClient(app, raise_server_exceptions=False)


class TestErrorEnvelope:
    """All error paths return the canonical envelope."""

    def test_pydantic_validation_error_enveloped(self, client: TestClient):
        """Schema validation failures use the envelope, not FastAPI's array."""
        response = client.post(
            "/api/v1/translate",
            json={"text": "Hello", "source_lang": "en"},
        )

        assert response.status_code == 422
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert "target_lang" in body["error"]["message"]

    def test_dict_detail_enveloped_with_extras(self, client: TestClient):
        """Structured route errors keep their code and extra fields."""
        response = client.post(
            "/api/v1/translate",
            json={"text": "a" * 401, "source_lang": "en", "target_lang": "fr"},
        )

        assert response.status_code == 400
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "TEXT_TOO_LONG"
        assert body["error"]["limit"] == 400

    def test_string_detail_enveloped_with_fallback_code(self, client: TestClient):
        """Plain-string HTTPException details get a status-derived code."""
        response = client.get("/api/v1/subscription")

        assert response.status_code == 401
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "UNAUTHORIZED"
        assert body["error"]["message"]

    def test_not_found_enveloped(self, client: TestClient):
        """Router-level 404s use the envelope too."""
        response = client.get("/api/v1/does-not-exist")

        assert response.status_code == 404
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "NOT_FOUND"

    def test_unhandled_exception_enveloped_without_leak(self, client: TestClient):
        """Crashes return a generic INTERNAL_ERROR, never the exception text."""
        from unittest.mock import AsyncMock, patch

        secret = "database password is hunter2"
        with patch(
            "app.api.routes.translate.translate_text",
            new_callable=AsyncMock,
            side_effect=RuntimeError(secret),
        ):
            response = client.post(
                "/api/v1/translate",
                json={"text": "Hello", "source_lang": "en", "target_lang": "fr"},
            )

        assert response.status_code == 500
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert secret not in response.text

    def test_auth_headers_preserved(self, client: TestClient):
        """401 responses keep their WWW-Authenticate header."""
        response = client.post(
            "/api/v1/translate",
            json={"text": "Hello", "source_lang": "en", "target_lang": "fr"},
            headers={"Authorization": "Bearer not-a-jwt"},
        )

        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert response.json()["error"]["code"] == "TOKEN_EXPIRED"
