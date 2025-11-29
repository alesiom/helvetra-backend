"""
Feedback endpoint tests.
Covers consent validation and feedback submission.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.main import app


@pytest.fixture
def mock_db():
    """Create mock database session."""
    session = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def client(mock_db):
    """Create test client with mocked database."""
    app.dependency_overrides[get_db] = lambda: mock_db
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestFeedbackEndpoint:
    """Tests for POST /api/v1/feedback endpoint."""

    def test_feedback_with_consent_accepted(self, client: TestClient, mock_db):
        """Feedback is stored when consent is given."""
        response = client.post(
            "/api/v1/feedback",
            json={
                "translation_id": "abc123",
                "vote": "like",
                "consent": True,
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert mock_db.add.called

    def test_feedback_without_consent_rejected(self, client: TestClient, mock_db):
        """Feedback is rejected when consent is not given."""
        response = client.post(
            "/api/v1/feedback",
            json={
                "translation_id": "abc123",
                "vote": "like",
                "consent": False,
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "CONSENT_REQUIRED"
        assert not mock_db.add.called

    def test_feedback_like_vote(self, client: TestClient, mock_db):
        """Like vote is accepted."""
        response = client.post(
            "/api/v1/feedback",
            json={
                "translation_id": "abc123",
                "vote": "like",
                "consent": True,
            }
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_feedback_dislike_vote(self, client: TestClient, mock_db):
        """Dislike vote is accepted."""
        response = client.post(
            "/api/v1/feedback",
            json={
                "translation_id": "abc123",
                "vote": "dislike",
                "consent": True,
            }
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_feedback_invalid_vote_rejected(self, client: TestClient):
        """Invalid vote value is rejected."""
        response = client.post(
            "/api/v1/feedback",
            json={
                "translation_id": "abc123",
                "vote": "invalid",
                "consent": True,
            }
        )

        assert response.status_code == 422

    def test_feedback_missing_translation_id_rejected(self, client: TestClient):
        """Missing translation_id is rejected."""
        response = client.post(
            "/api/v1/feedback",
            json={
                "vote": "like",
                "consent": True,
            }
        )

        assert response.status_code == 422

    def test_feedback_empty_translation_id_rejected(self, client: TestClient):
        """Empty translation_id is rejected."""
        response = client.post(
            "/api/v1/feedback",
            json={
                "translation_id": "",
                "vote": "like",
                "consent": True,
            }
        )

        assert response.status_code == 422
