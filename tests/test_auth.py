"""
Authentication endpoint tests.
Covers registration, login, token refresh, logout, and protected routes.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.main import app
from app.models.user import RefreshToken, User
from app.services.auth import (
    create_access_token,
    create_refresh_token,
    hash_password,
)
from app.services.auth_rate_limiter import AuthRateLimitResult


@pytest.fixture
def mock_db():
    """Create mock database session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture(autouse=True)
def mock_rate_limiters():
    """Mock both rate limiters (middleware and auth-specific)."""
    # Mock middleware rate limiter
    with patch("app.core.middleware.rate_limiter") as mock_global:
        mock_result = MagicMock()
        mock_result.allowed = True
        mock_result.remaining = 100
        mock_result.reset_at = 0
        mock_global.check_rate_limit = AsyncMock(return_value=mock_result)

        # Mock auth rate limiter
        with patch("app.api.routes.auth.auth_rate_limiter") as mock_auth:
            mock_auth.check_register_limit = AsyncMock(
                return_value=AuthRateLimitResult(allowed=True, remaining=10)
            )
            mock_auth.check_login_limit = AsyncMock(
                return_value=AuthRateLimitResult(allowed=True, remaining=10)
            )
            mock_auth.check_account_lockout = AsyncMock(
                return_value=AuthRateLimitResult(allowed=True, remaining=10)
            )
            mock_auth.record_failed_attempt = AsyncMock(
                return_value=AuthRateLimitResult(allowed=True, remaining=9)
            )
            mock_auth.clear_failed_attempts = AsyncMock()
            yield mock_auth


@pytest.fixture
def client(mock_db):
    """Create test client with mocked database."""
    app.dependency_overrides[get_db] = lambda: mock_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def valid_register():
    """Valid registration payload."""
    return {
        "email": "test@example.com",
        "password": "SecurePass123",
    }


@pytest.fixture
def valid_login():
    """Valid login payload."""
    return {
        "email": "test@example.com",
        "password": "SecurePass123",
    }


@pytest.fixture
def mock_user():
    """Create a mock user object."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "test@example.com"
    user.password_hash = hash_password("SecurePass123")
    user.email_verified = False
    user.apple_id = None
    return user


@pytest.fixture
def mock_refresh_token(mock_user):
    """Create a mock refresh token."""
    raw_token, hashed = create_refresh_token()
    token = MagicMock(spec=RefreshToken)
    token.id = uuid.uuid4()
    token.user_id = mock_user.id
    token.token_hash = hashed
    token.expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    token.revoked = False
    return token, raw_token


class TestRegisterEndpoint:
    """Tests for POST /api/v1/auth/register endpoint."""

    def test_register_success(self, client: TestClient, mock_db, valid_register):
        """Successful registration returns user and tokens."""
        # Mock: no existing user
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        # Mock: user object gets populated after add
        created_user = MagicMock()
        created_user.id = uuid.uuid4()
        created_user.email = valid_register["email"]
        created_user.email_verified = False

        def capture_user(obj):
            if hasattr(obj, "email"):
                obj.id = created_user.id
                obj.email_verified = False

        mock_db.add.side_effect = capture_user

        response = client.post("/api/v1/auth/register", json=valid_register)

        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert "user" in data["data"]
        assert "tokens" in data["data"]
        assert data["data"]["user"]["email"] == valid_register["email"]
        assert "access_token" in data["data"]["tokens"]
        assert "refresh_token" in data["data"]["tokens"]

    def test_register_duplicate_email_rejected(
        self, client: TestClient, mock_db, valid_register, mock_user
    ):
        """Registration with existing email returns 409."""
        # Mock: existing user found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        response = client.post("/api/v1/auth/register", json=valid_register)

        assert response.status_code == 409
        assert "already registered" in response.json()["detail"]

    def test_register_weak_password_rejected(self, client: TestClient, valid_register):
        """Password without numbers is rejected."""
        valid_register["password"] = "NoNumbers"
        response = client.post("/api/v1/auth/register", json=valid_register)

        assert response.status_code == 422

    def test_register_short_password_rejected(self, client: TestClient, valid_register):
        """Password shorter than 8 characters is rejected."""
        valid_register["password"] = "Short1"
        response = client.post("/api/v1/auth/register", json=valid_register)

        assert response.status_code == 422

    def test_register_invalid_email_rejected(self, client: TestClient, valid_register):
        """Invalid email format is rejected."""
        valid_register["email"] = "not-an-email"
        response = client.post("/api/v1/auth/register", json=valid_register)

        assert response.status_code == 422

    def test_register_missing_email_rejected(self, client: TestClient, valid_register):
        """Missing email is rejected."""
        del valid_register["email"]
        response = client.post("/api/v1/auth/register", json=valid_register)

        assert response.status_code == 422

    def test_register_missing_password_rejected(self, client: TestClient, valid_register):
        """Missing password is rejected."""
        del valid_register["password"]
        response = client.post("/api/v1/auth/register", json=valid_register)

        assert response.status_code == 422


class TestLoginEndpoint:
    """Tests for POST /api/v1/auth/login endpoint."""

    def test_login_success(self, client: TestClient, mock_db, valid_login, mock_user):
        """Successful login returns user and tokens."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        response = client.post("/api/v1/auth/login", json=valid_login)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "user" in data["data"]
        assert "tokens" in data["data"]

    def test_login_wrong_password_rejected(
        self, client: TestClient, mock_db, valid_login, mock_user
    ):
        """Wrong password returns 401."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        valid_login["password"] = "WrongPassword123"
        response = client.post("/api/v1/auth/login", json=valid_login)

        assert response.status_code == 401
        assert "Invalid email or password" in response.json()["detail"]

    def test_login_unknown_email_rejected(self, client: TestClient, mock_db, valid_login):
        """Unknown email returns 401."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        response = client.post("/api/v1/auth/login", json=valid_login)

        assert response.status_code == 401

    def test_login_user_without_password_rejected(
        self, client: TestClient, mock_db, valid_login, mock_user
    ):
        """User without password (Apple-only) cannot login with password."""
        mock_user.password_hash = None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        response = client.post("/api/v1/auth/login", json=valid_login)

        assert response.status_code == 401


class TestRefreshEndpoint:
    """Tests for POST /api/v1/auth/refresh endpoint."""

    def test_refresh_success(self, client: TestClient, mock_db, mock_user, mock_refresh_token):
        """Valid refresh token returns new tokens."""
        stored_token, raw_token = mock_refresh_token

        # First call returns refresh token, second returns user
        mock_result_token = MagicMock()
        mock_result_token.scalar_one_or_none.return_value = stored_token
        mock_result_user = MagicMock()
        mock_result_user.scalar_one_or_none.return_value = mock_user
        mock_db.execute.side_effect = [mock_result_token, mock_result_user]

        response = client.post("/api/v1/auth/refresh", json={"refresh_token": raw_token})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "tokens" in data["data"]
        # Old token should be revoked
        assert stored_token.revoked is True

    def test_refresh_invalid_token_rejected(self, client: TestClient, mock_db):
        """Invalid refresh token returns 401."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        response = client.post("/api/v1/auth/refresh", json={"refresh_token": "invalid_token"})

        assert response.status_code == 401

    def test_refresh_expired_token_rejected(
        self, client: TestClient, mock_db, mock_user, mock_refresh_token
    ):
        """Expired refresh token returns 401."""
        stored_token, raw_token = mock_refresh_token
        stored_token.expires_at = datetime.now(timezone.utc) - timedelta(days=1)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = stored_token
        mock_db.execute.return_value = mock_result

        response = client.post("/api/v1/auth/refresh", json={"refresh_token": raw_token})

        assert response.status_code == 401
        assert "expired" in response.json()["detail"]

    def test_refresh_revoked_token_rejected(self, client: TestClient, mock_db, mock_refresh_token):
        """Revoked refresh token returns 401."""
        stored_token, raw_token = mock_refresh_token
        stored_token.revoked = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # Query filters out revoked
        mock_db.execute.return_value = mock_result

        response = client.post("/api/v1/auth/refresh", json={"refresh_token": raw_token})

        assert response.status_code == 401


class TestLogoutEndpoint:
    """Tests for POST /api/v1/auth/logout endpoint."""

    def test_logout_success(self, client: TestClient, mock_db, mock_refresh_token):
        """Logout revokes the refresh token."""
        stored_token, raw_token = mock_refresh_token

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = stored_token
        mock_db.execute.return_value = mock_result

        response = client.post("/api/v1/auth/logout", json={"refresh_token": raw_token})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert stored_token.revoked is True

    def test_logout_invalid_token_succeeds(self, client: TestClient, mock_db):
        """Logout with invalid token still succeeds (idempotent)."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        response = client.post("/api/v1/auth/logout", json={"refresh_token": "invalid"})

        assert response.status_code == 200
        assert response.json()["success"] is True


class TestMeEndpoint:
    """Tests for GET /api/v1/auth/me endpoint."""

    def test_me_with_valid_token(self, client: TestClient, mock_db, mock_user):
        """Valid access token returns user profile."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value.jwt_secret_key = "test_secret"
            mock_settings.return_value.jwt_algorithm = "HS256"
            mock_settings.return_value.access_token_expire_minutes = 15

            access_token = create_access_token(mock_user.id)
            response = client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["user"]["email"] == mock_user.email

    def test_me_without_token_rejected(self, client: TestClient):
        """Request without token returns 401."""
        response = client.get("/api/v1/auth/me")

        assert response.status_code == 401

    def test_me_with_invalid_token_rejected(self, client: TestClient):
        """Invalid token returns 401."""
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid_token"},
        )

        assert response.status_code == 401

    def test_me_with_expired_token_rejected(self, client: TestClient, mock_user):
        """Expired token returns 401."""
        with patch("app.services.auth.settings") as mock_settings:
            mock_settings.jwt_secret_key = "test_secret"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.access_token_expire_minutes = -1  # Already expired

            access_token = create_access_token(mock_user.id)

        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 401


class TestPasswordHashing:
    """Tests for password hashing utilities."""

    def test_hash_password_produces_different_hashes(self):
        """Same password produces different hashes (salt)."""
        from app.services.auth import hash_password

        hash1 = hash_password("password123")
        hash2 = hash_password("password123")

        assert hash1 != hash2

    def test_verify_password_correct(self):
        """Correct password verifies successfully."""
        from app.services.auth import hash_password, verify_password

        password = "SecurePass123"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Incorrect password fails verification."""
        from app.services.auth import hash_password, verify_password

        hashed = hash_password("SecurePass123")

        assert verify_password("WrongPass123", hashed) is False


class TestJwtTokens:
    """Tests for JWT token utilities."""

    def test_create_and_decode_access_token(self):
        """Access token can be created and decoded."""
        from app.services.auth import create_access_token, decode_access_token

        user_id = uuid.uuid4()

        with patch("app.services.auth.settings") as mock_settings:
            mock_settings.jwt_secret_key = "test_secret"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.access_token_expire_minutes = 15

            token = create_access_token(user_id)
            decoded_id = decode_access_token(token)

        assert decoded_id == user_id

    def test_decode_invalid_token_returns_none(self):
        """Invalid token returns None."""
        from app.services.auth import decode_access_token

        result = decode_access_token("invalid_token")

        assert result is None

    def test_refresh_token_is_hashed_differently(self):
        """Refresh token hash is deterministic."""
        from app.services.auth import create_refresh_token, hash_refresh_token

        raw, hashed = create_refresh_token()
        rehashed = hash_refresh_token(raw)

        assert hashed == rehashed
