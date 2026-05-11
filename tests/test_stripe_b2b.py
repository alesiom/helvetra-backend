"""
Unit tests for the B2B Stripe integration.
Focuses on logic that does not touch the network (resolver caching, tier
mapping, idempotency keys, meter event safety guards).
"""

import time
import uuid
from unittest.mock import patch

import pytest

from app.core.tiers import Tier
from app.services import stripe_b2b


@pytest.fixture(autouse=True)
def _clear_cache():
    """Make sure each test sees a clean lookup-key cache."""
    stripe_b2b._clear_price_cache_for_tests()
    yield
    stripe_b2b._clear_price_cache_for_tests()


class TestTierFromPriceLookup:
    """Mapping a Stripe price lookup key back to a B2B tier."""

    def test_starter_base_lookup_maps_to_starter(self):
        with patch.object(
            stripe_b2b.settings, "stripe_b2b_starter_base_lookup", "b2b_starter_base"
        ):
            assert stripe_b2b.tier_from_price_lookup("b2b_starter_base") == Tier.STARTER

    def test_business_base_lookup_maps_to_business(self):
        with patch.object(
            stripe_b2b.settings, "stripe_b2b_business_base_lookup", "b2b_business_base"
        ):
            assert (
                stripe_b2b.tier_from_price_lookup("b2b_business_base") == Tier.BUSINESS
            )

    def test_unknown_lookup_returns_none(self):
        assert stripe_b2b.tier_from_price_lookup("totally_unrelated") is None

    def test_empty_lookup_returns_none(self):
        assert stripe_b2b.tier_from_price_lookup("") is None


class TestResolvePriceByLookup:
    """Lookup-key resolution honours config + caches results."""

    def test_empty_lookup_key_raises(self):
        with pytest.raises(RuntimeError, match="not configured"):
            stripe_b2b.resolve_price_by_lookup("")

    def test_missing_secret_key_raises(self):
        with patch.object(stripe_b2b.settings, "stripe_secret_key", ""):
            with pytest.raises(RuntimeError, match="Stripe secret key not configured"):
                stripe_b2b.resolve_price_by_lookup("b2b_starter_base")

    def test_no_matching_price_raises(self):
        fake_list = type("FakeList", (), {"data": []})()
        with patch.object(stripe_b2b.settings, "stripe_secret_key", "sk_test_x"):
            with patch.object(stripe_b2b.stripe.Price, "list", return_value=fake_list):
                with pytest.raises(RuntimeError, match="No active Stripe price"):
                    stripe_b2b.resolve_price_by_lookup("b2b_starter_base")

    def test_first_call_hits_api_subsequent_calls_use_cache(self):
        fake_price = type("FakePrice", (), {"id": "price_test_123"})()
        fake_list = type("FakeList", (), {"data": [fake_price]})()
        with patch.object(stripe_b2b.settings, "stripe_secret_key", "sk_test_x"):
            with patch.object(
                stripe_b2b.stripe.Price, "list", return_value=fake_list
            ) as mock_list:
                first = stripe_b2b.resolve_price_by_lookup("b2b_starter_base")
                second = stripe_b2b.resolve_price_by_lookup("b2b_starter_base")
                assert first == second == "price_test_123"
                assert mock_list.call_count == 1  # second was served from cache


class TestMeterEventSafety:
    """Meter reporting must never block or crash the translation flow."""

    @pytest.mark.asyncio
    async def test_no_customer_id_is_a_noop(self):
        # Should not even reach the network — assert no Stripe call is made.
        with patch.object(stripe_b2b.stripe.billing.MeterEvent, "create") as mock_create:
            await stripe_b2b.report_translation_meter_event(
                stripe_customer_id=None, characters=100
            )
            assert mock_create.call_count == 0

    @pytest.mark.asyncio
    async def test_zero_characters_is_a_noop(self):
        with patch.object(stripe_b2b.stripe.billing.MeterEvent, "create") as mock_create:
            await stripe_b2b.report_translation_meter_event(
                stripe_customer_id="cus_abc", characters=0
            )
            assert mock_create.call_count == 0

    @pytest.mark.asyncio
    async def test_meter_event_name_unset_is_a_noop(self):
        with patch.object(stripe_b2b.settings, "stripe_b2b_meter_event_name", ""):
            with patch.object(
                stripe_b2b.stripe.billing.MeterEvent, "create"
            ) as mock_create:
                await stripe_b2b.report_translation_meter_event(
                    stripe_customer_id="cus_abc", characters=100
                )
                assert mock_create.call_count == 0

    @pytest.mark.asyncio
    async def test_stripe_error_does_not_propagate(self):
        """A Stripe API failure must be swallowed so translation responses succeed."""
        import stripe as stripe_module

        with patch.object(stripe_b2b.settings, "stripe_secret_key", "sk_test_x"):
            with patch.object(
                stripe_b2b.settings, "stripe_b2b_meter_event_name", "helvetra_chars"
            ):
                with patch.object(
                    stripe_b2b.stripe.billing.MeterEvent,
                    "create",
                    side_effect=stripe_module.StripeError("boom"),
                ):
                    # Should not raise
                    await stripe_b2b.report_translation_meter_event(
                        stripe_customer_id="cus_abc", characters=100
                    )

    @pytest.mark.asyncio
    async def test_happy_path_sends_event_with_correct_payload(self):
        with patch.object(stripe_b2b.settings, "stripe_secret_key", "sk_test_x"):
            with patch.object(
                stripe_b2b.settings, "stripe_b2b_meter_event_name", "helvetra_chars"
            ):
                with patch.object(
                    stripe_b2b.stripe.billing.MeterEvent, "create"
                ) as mock_create:
                    await stripe_b2b.report_translation_meter_event(
                        stripe_customer_id="cus_abc",
                        characters=247,
                        idempotency_key="abc-123",
                    )
                    assert mock_create.call_count == 1
                    call_kwargs = mock_create.call_args.kwargs
                    assert call_kwargs["event_name"] == "helvetra_chars"
                    assert call_kwargs["payload"]["stripe_customer_id"] == "cus_abc"
                    assert call_kwargs["payload"]["value"] == "247"
                    assert call_kwargs["identifier"] == "abc-123"


class TestMeterIdempotencyKey:
    """Idempotency keys are unique across rapid calls from the same user."""

    def test_two_calls_in_a_row_produce_different_keys(self):
        user_id = uuid.uuid4()
        k1 = stripe_b2b.generate_meter_idempotency_key(user_id, 100)
        time.sleep(0.001)
        k2 = stripe_b2b.generate_meter_idempotency_key(user_id, 100)
        assert k1 != k2

    def test_key_includes_user_id_and_character_count(self):
        user_id = uuid.uuid4()
        key = stripe_b2b.generate_meter_idempotency_key(user_id, 250)
        assert str(user_id) in key
        assert ":250" in key
