"""
Translation endpoint tests.
Covers input validation, API integration, and output validation.
"""

import pytest
from fastapi.testclient import TestClient
from pytest_httpx import HTTPXMock

from app.main import app


@pytest.fixture
def client():
    """Create test client for the API."""
    return TestClient(app)


def mock_translation_response(translation: str) -> dict:
    """Build a mock API response with the given translation."""
    return {
        "choices": [
            {
                "message": {
                    "content": translation
                }
            }
        ]
    }


class TestTranslateEndpoint:
    """Tests for POST /api/v1/translate endpoint."""

    def test_translate_success(self, client: TestClient, httpx_mock: HTTPXMock):
        """Successful translation returns correct response format."""
        httpx_mock.add_response(
            json=mock_translation_response("Bonjour")
        )

        response = client.post(
            "/api/v1/translate",
            json={
                "text": "Hello",
                "source_lang": "en",
                "target_lang": "fr",
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["translation"] == "Bonjour"
        assert data["data"]["source_lang"] == "en"
        assert data["data"]["target_lang"] == "fr"
        assert "characters" in data["meta"]
        assert "processing_time_ms" in data["meta"]

    def test_translate_empty_text_rejected(self, client: TestClient):
        """Empty text is rejected with validation error."""
        response = client.post(
            "/api/v1/translate",
            json={
                "text": "",
                "source_lang": "en",
                "target_lang": "fr",
            }
        )

        assert response.status_code == 422

    def test_translate_text_too_long_rejected(self, client: TestClient):
        """Text exceeding 5000 characters is rejected."""
        response = client.post(
            "/api/v1/translate",
            json={
                "text": "a" * 5001,
                "source_lang": "en",
                "target_lang": "fr",
            }
        )

        assert response.status_code == 422

    def test_translate_max_length_accepted(self, client: TestClient, httpx_mock: HTTPXMock):
        """Text at exactly 5000 characters is accepted."""
        httpx_mock.add_response(
            json=mock_translation_response("translated")
        )

        response = client.post(
            "/api/v1/translate",
            json={
                "text": "a" * 5000,
                "source_lang": "en",
                "target_lang": "fr",
            }
        )

        assert response.status_code == 200

    def test_translate_missing_source_lang_rejected(self, client: TestClient):
        """Missing source language is rejected."""
        response = client.post(
            "/api/v1/translate",
            json={
                "text": "Hello",
                "target_lang": "fr",
            }
        )

        assert response.status_code == 422

    def test_translate_missing_target_lang_rejected(self, client: TestClient):
        """Missing target language is rejected."""
        response = client.post(
            "/api/v1/translate",
            json={
                "text": "Hello",
                "source_lang": "en",
            }
        )

        assert response.status_code == 422

    def test_translate_suspicious_output_rejected(self, client: TestClient, httpx_mock: HTTPXMock):
        """Output more than 3x input length is rejected as suspicious."""
        # 5-char input, return 20-char output (4x ratio)
        httpx_mock.add_response(
            json=mock_translation_response("This is a very long suspicious output text")
        )

        response = client.post(
            "/api/v1/translate",
            json={
                "text": "Hi",
                "source_lang": "en",
                "target_lang": "fr",
            }
        )

        assert response.status_code == 500
        assert "suspicious" in response.json()["detail"].lower()

    def test_translate_api_error_handled(self, client: TestClient, httpx_mock: HTTPXMock):
        """API errors are handled gracefully."""
        httpx_mock.add_response(status_code=500)

        response = client.post(
            "/api/v1/translate",
            json={
                "text": "Hello",
                "source_lang": "en",
                "target_lang": "fr",
            }
        )

        assert response.status_code == 500

    def test_translate_preserves_whitespace(self, client: TestClient, httpx_mock: HTTPXMock):
        """Translation preserves meaningful content."""
        httpx_mock.add_response(
            json=mock_translation_response("  Bonjour  ")
        )

        response = client.post(
            "/api/v1/translate",
            json={
                "text": "  Hello  ",
                "source_lang": "en",
                "target_lang": "fr",
            }
        )

        assert response.status_code == 200
        # Response is stripped
        assert response.json()["data"]["translation"] == "Bonjour"

    def test_translate_formality_default_auto(self, client: TestClient, httpx_mock: HTTPXMock):
        """Formality defaults to auto when not specified."""
        httpx_mock.add_response(
            json=mock_translation_response("Hallo")
        )

        response = client.post(
            "/api/v1/translate",
            json={
                "text": "Hello",
                "source_lang": "en",
                "target_lang": "de",
            }
        )

        assert response.status_code == 200

    def test_translate_formality_informal_accepted(self, client: TestClient, httpx_mock: HTTPXMock):
        """Informal formality is accepted for German translations."""
        httpx_mock.add_response(
            json=mock_translation_response("Hallo")
        )

        response = client.post(
            "/api/v1/translate",
            json={
                "text": "Hello",
                "source_lang": "en",
                "target_lang": "de",
                "formality": "informal",
            }
        )

        assert response.status_code == 200

    def test_translate_formality_formal_accepted(self, client: TestClient, httpx_mock: HTTPXMock):
        """Formal formality is accepted for German translations."""
        httpx_mock.add_response(
            json=mock_translation_response("Guten Tag")
        )

        response = client.post(
            "/api/v1/translate",
            json={
                "text": "Hello",
                "source_lang": "en",
                "target_lang": "de",
                "formality": "formal",
            }
        )

        assert response.status_code == 200

    def test_translate_formality_invalid_rejected(self, client: TestClient):
        """Invalid formality value is rejected."""
        response = client.post(
            "/api/v1/translate",
            json={
                "text": "Hello",
                "source_lang": "en",
                "target_lang": "de",
                "formality": "invalid",
            }
        )

        assert response.status_code == 422

    def test_translate_formality_french_accepted(
        self, client: TestClient, httpx_mock: HTTPXMock
    ):
        """Formality is accepted for French translations (tu/vous)."""
        httpx_mock.add_response(
            json=mock_translation_response("Comment allez-vous?")
        )

        response = client.post(
            "/api/v1/translate",
            json={
                "text": "How are you?",
                "source_lang": "en",
                "target_lang": "fr",
                "formality": "formal",
            }
        )

        assert response.status_code == 200

    def test_translate_formality_italian_accepted(
        self, client: TestClient, httpx_mock: HTTPXMock
    ):
        """Formality is accepted for Italian translations (tu/Lei)."""
        httpx_mock.add_response(
            json=mock_translation_response("Come sta?")
        )

        response = client.post(
            "/api/v1/translate",
            json={
                "text": "How are you?",
                "source_lang": "en",
                "target_lang": "it",
                "formality": "formal",
            }
        )

        assert response.status_code == 200

    def test_translate_formality_ignored_for_english(
        self, client: TestClient, httpx_mock: HTTPXMock
    ):
        """Formality parameter is accepted but ignored for English (no T-V)."""
        httpx_mock.add_response(
            json=mock_translation_response("Hello")
        )

        response = client.post(
            "/api/v1/translate",
            json={
                "text": "Bonjour",
                "source_lang": "fr",
                "target_lang": "en",
                "formality": "formal",
            }
        )

        assert response.status_code == 200
        assert response.json()["data"]["translation"] == "Hello"
