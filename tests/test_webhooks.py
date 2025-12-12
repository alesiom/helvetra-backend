"""
Webhook endpoint tests.
Covers Payrexx payment webhook processing.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.main import app
from app.models.subscription import Subscription, SubscriptionSource, SubscriptionStatus, SubscriptionTier


@pytest.fixture
def mock_db():
    """Create mock database session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def client(mock_db):
    """Create test client with mocked database."""
    app.dependency_overrides[get_db] = lambda: mock_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def mock_subscription():
    """Create a mock subscription object."""
    sub = MagicMock(spec=Subscription)
    sub.id = uuid.uuid4()
    sub.user_id = uuid.uuid4()
    sub.tier = SubscriptionTier.FREE
    sub.status = SubscriptionStatus.ACTIVE
    sub.source = None
    sub.external_id = None
    sub.current_period_start = None
    sub.current_period_end = None
    return sub


@pytest.fixture
def payrexx_confirmed_payload():
    """Valid Payrexx confirmed payment webhook payload."""
    return {
        "transaction": {
            "id": "txn_12345",
            "status": "confirmed",
            "amount": 990,
            "subscriptionId": "sub_abc123",
            "time": "2025-01-15T10:30:00Z",
        },
        "invoice": {
            "subscriptionId": "sub_abc123",
            "productId": "prod_pro",
        },
        "contact": {
            "email": "test@example.com",
        },
    }


@pytest.fixture
def payrexx_failed_payload():
    """Payrexx failed payment webhook payload."""
    return {
        "transaction": {
            "id": "txn_67890",
            "status": "declined",
            "amount": 990,
            "subscriptionId": "sub_abc123",
        },
        "invoice": {},
        "contact": {},
    }


@pytest.fixture
def payrexx_cancelled_payload():
    """Payrexx cancelled subscription webhook payload."""
    return {
        "transaction": {
            "id": "txn_cancel",
            "status": "cancelled",
            "subscriptionId": "sub_abc123",
        },
        "invoice": {},
        "contact": {},
    }


@pytest.fixture
def payrexx_refunded_payload():
    """Payrexx refunded payment webhook payload."""
    return {
        "transaction": {
            "id": "txn_refund",
            "status": "refunded",
            "subscriptionId": "sub_abc123",
        },
        "invoice": {},
        "contact": {},
    }


class TestPayrexxWebhook:
    """Tests for POST /api/v1/webhooks/payrexx endpoint."""

    def test_webhook_invalid_json_rejected(self, client: TestClient):
        """Invalid JSON payload returns 400."""
        response = client.post(
            "/api/v1/webhooks/payrexx",
            content="not json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400
        assert "Invalid JSON" in response.json()["detail"]

    def test_webhook_missing_transaction_id(self, client: TestClient, mock_db):
        """Missing transaction ID returns success but doesn't process."""
        # No existing webhook event
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        response = client.post(
            "/api/v1/webhooks/payrexx",
            json={"transaction": {"status": "confirmed"}},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_webhook_confirmed_activates_subscription(
        self, client: TestClient, mock_db, mock_subscription, payrexx_confirmed_payload
    ):
        """Confirmed payment activates subscription to PRO tier."""
        # First call: no existing webhook event
        # Second call: find subscription by external_id
        mock_result_no_event = MagicMock()
        mock_result_no_event.scalar_one_or_none.return_value = None

        mock_result_subscription = MagicMock()
        mock_result_subscription.scalar_one_or_none.return_value = mock_subscription

        mock_db.execute.side_effect = [
            mock_result_no_event,  # check_idempotency
            mock_result_subscription,  # get_subscription_by_external_id
        ]

        with patch("app.services.payrexx.settings") as mock_settings:
            mock_settings.payrexx_product_pro_id = "prod_pro"
            mock_settings.payrexx_product_business_id = "prod_business"

            response = client.post(
                "/api/v1/webhooks/payrexx",
                json=payrexx_confirmed_payload,
            )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        # Verify subscription was updated
        assert mock_subscription.tier == SubscriptionTier.PRO
        assert mock_subscription.status == SubscriptionStatus.ACTIVE
        assert mock_subscription.source == SubscriptionSource.PAYREXX

    def test_webhook_failed_marks_past_due(
        self, client: TestClient, mock_db, mock_subscription, payrexx_failed_payload
    ):
        """Failed payment marks subscription as past due."""
        mock_subscription.external_id = "sub_abc123"

        mock_result_no_event = MagicMock()
        mock_result_no_event.scalar_one_or_none.return_value = None

        mock_result_subscription = MagicMock()
        mock_result_subscription.scalar_one_or_none.return_value = mock_subscription

        mock_db.execute.side_effect = [
            mock_result_no_event,  # check_idempotency
            mock_result_subscription,  # get_subscription_by_external_id
        ]

        response = client.post(
            "/api/v1/webhooks/payrexx",
            json=payrexx_failed_payload,
        )

        assert response.status_code == 200
        assert mock_subscription.status == SubscriptionStatus.PAST_DUE

    def test_webhook_cancelled_cancels_subscription(
        self, client: TestClient, mock_db, mock_subscription, payrexx_cancelled_payload
    ):
        """Cancelled event cancels the subscription."""
        mock_subscription.external_id = "sub_abc123"

        mock_result_no_event = MagicMock()
        mock_result_no_event.scalar_one_or_none.return_value = None

        mock_result_subscription = MagicMock()
        mock_result_subscription.scalar_one_or_none.return_value = mock_subscription

        mock_db.execute.side_effect = [
            mock_result_no_event,  # check_idempotency
            mock_result_subscription,  # get_subscription_by_external_id
        ]

        response = client.post(
            "/api/v1/webhooks/payrexx",
            json=payrexx_cancelled_payload,
        )

        assert response.status_code == 200
        assert mock_subscription.status == SubscriptionStatus.CANCELLED

    def test_webhook_refunded_downgrades_to_free(
        self, client: TestClient, mock_db, mock_subscription, payrexx_refunded_payload
    ):
        """Refund downgrades subscription to free tier."""
        mock_subscription.tier = SubscriptionTier.PRO
        mock_subscription.external_id = "sub_abc123"

        mock_result_no_event = MagicMock()
        mock_result_no_event.scalar_one_or_none.return_value = None

        mock_result_subscription = MagicMock()
        mock_result_subscription.scalar_one_or_none.return_value = mock_subscription

        mock_db.execute.side_effect = [
            mock_result_no_event,  # check_idempotency
            mock_result_subscription,  # get_subscription_by_external_id
        ]

        response = client.post(
            "/api/v1/webhooks/payrexx",
            json=payrexx_refunded_payload,
        )

        assert response.status_code == 200
        assert mock_subscription.tier == SubscriptionTier.FREE
        assert mock_subscription.status == SubscriptionStatus.ACTIVE
        assert mock_subscription.source is None
        assert mock_subscription.external_id is None

    def test_webhook_idempotency_prevents_duplicate_processing(
        self, client: TestClient, mock_db, payrexx_confirmed_payload
    ):
        """Already processed webhook is not reprocessed."""
        # Return existing processed event
        existing_event = MagicMock()
        existing_event.processed = True

        mock_result_existing = MagicMock()
        mock_result_existing.scalar_one_or_none.return_value = existing_event
        mock_db.execute.return_value = mock_result_existing

        response = client.post(
            "/api/v1/webhooks/payrexx",
            json=payrexx_confirmed_payload,
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        # Should only have one execute call (idempotency check)
        assert mock_db.execute.call_count == 1

    def test_webhook_unknown_status_succeeds(self, client: TestClient, mock_db):
        """Unknown transaction status is logged but doesn't fail."""
        mock_result_no_event = MagicMock()
        mock_result_no_event.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result_no_event

        payload = {
            "transaction": {
                "id": "txn_unknown",
                "status": "pending",
            }
        }

        response = client.post(
            "/api/v1/webhooks/payrexx",
            json=payload,
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_webhook_no_subscription_found(
        self, client: TestClient, mock_db, payrexx_confirmed_payload
    ):
        """Webhook for unknown subscription succeeds but logs warning."""
        mock_result_none = MagicMock()
        mock_result_none.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result_none

        response = client.post(
            "/api/v1/webhooks/payrexx",
            json=payrexx_confirmed_payload,
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestPayrexxTransactionParsing:
    """Tests for Payrexx transaction parsing."""

    def test_parse_transaction_extracts_fields(self):
        """Transaction parser extracts all relevant fields."""
        from app.services.payrexx import parse_transaction

        payload = {
            "transaction": {
                "id": "txn_123",
                "status": "confirmed",
                "amount": 1990,
                "subscriptionId": "sub_456",
                "time": "2025-01-15T10:30:00Z",
            },
            "invoice": {
                "productId": "prod_pro",
            },
            "contact": {
                "email": "user@example.com",
            },
        }

        tx = parse_transaction(payload)

        assert tx.id == "txn_123"
        assert tx.status == "confirmed"
        assert tx.amount == 1990
        assert tx.subscription_id == "sub_456"
        assert tx.product_id == "prod_pro"
        assert tx.user_email == "user@example.com"
        assert tx.time is not None

    def test_parse_transaction_handles_missing_fields(self):
        """Transaction parser handles missing optional fields."""
        from app.services.payrexx import parse_transaction

        payload = {
            "transaction": {
                "id": "txn_123",
                "status": "confirmed",
            }
        }

        tx = parse_transaction(payload)

        assert tx.id == "txn_123"
        assert tx.status == "confirmed"
        assert tx.amount == 0
        assert tx.subscription_id is None
        assert tx.product_id is None
        assert tx.user_email is None
        assert tx.time is None


class TestProductToTierMapping:
    """Tests for product ID to tier mapping."""

    def test_map_pro_product(self):
        """PRO product ID maps to PRO tier."""
        from app.services.payrexx import map_product_to_tier

        with patch("app.services.payrexx.settings") as mock_settings:
            mock_settings.payrexx_product_pro_id = "prod_pro"
            mock_settings.payrexx_product_business_id = "prod_business"

            tier = map_product_to_tier("prod_pro")

        assert tier == SubscriptionTier.PRO

    def test_map_business_product(self):
        """BUSINESS product ID maps to BUSINESS tier."""
        from app.services.payrexx import map_product_to_tier

        with patch("app.services.payrexx.settings") as mock_settings:
            mock_settings.payrexx_product_pro_id = "prod_pro"
            mock_settings.payrexx_product_business_id = "prod_business"

            tier = map_product_to_tier("prod_business")

        assert tier == SubscriptionTier.BUSINESS

    def test_map_unknown_product_returns_none(self):
        """Unknown product ID returns None."""
        from app.services.payrexx import map_product_to_tier

        with patch("app.services.payrexx.settings") as mock_settings:
            mock_settings.payrexx_product_pro_id = "prod_pro"
            mock_settings.payrexx_product_business_id = "prod_business"

            tier = map_product_to_tier("unknown_product")

        assert tier is None

    def test_map_none_product_returns_none(self):
        """None product ID returns None."""
        from app.services.payrexx import map_product_to_tier

        tier = map_product_to_tier(None)

        assert tier is None
