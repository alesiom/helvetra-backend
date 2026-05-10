"""
Tier configuration tests.
Locks in the published B2B pricing/features so tier values cannot drift unnoticed.
"""

from app.core.tiers import (
    B2B_TIER_CONFIGS,
    CONSUMER_TIER_CONFIGS,
    Tier,
    get_tier_config,
)


class TestB2BTierConfig:
    """The B2B Starter and Business tier values are part of the public pricing contract."""

    def test_starter_pricing_inputs(self):
        config = B2B_TIER_CONFIGS[Tier.STARTER]
        assert config.period_limit == 500_000
        assert config.period_type == "monthly"
        assert config.max_chars_per_request == 10_000
        assert config.max_api_keys == 1
        assert config.formality is True

    def test_business_pricing_inputs(self):
        config = B2B_TIER_CONFIGS[Tier.BUSINESS]
        assert config.period_limit == 2_000_000
        assert config.period_type == "monthly"
        assert config.max_chars_per_request == 50_000
        assert config.max_api_keys == 10
        assert config.formality is True

    def test_business_per_request_is_5x_starter(self):
        """Business must allow meaningfully larger requests than Starter."""
        starter = B2B_TIER_CONFIGS[Tier.STARTER]
        business = B2B_TIER_CONFIGS[Tier.BUSINESS]
        assert business.max_chars_per_request >= starter.max_chars_per_request * 5

    def test_business_more_keys_than_starter(self):
        """Business must offer more API keys than Starter to incentivize upgrade."""
        starter = B2B_TIER_CONFIGS[Tier.STARTER]
        business = B2B_TIER_CONFIGS[Tier.BUSINESS]
        assert business.max_api_keys > starter.max_api_keys


class TestConsumerHasNoApiAccess:
    """Consumer tiers must not grant API key creation."""

    def test_anonymous_no_keys(self):
        assert CONSUMER_TIER_CONFIGS[Tier.ANONYMOUS].max_api_keys == 0

    def test_free_no_keys(self):
        assert CONSUMER_TIER_CONFIGS[Tier.FREE].max_api_keys == 0

    def test_pro_no_keys(self):
        assert CONSUMER_TIER_CONFIGS[Tier.PRO].max_api_keys == 0


class TestGetTierConfig:
    """Product-scoped lookup must return the B2B config for B2B tiers."""

    def test_b2b_lookup_returns_b2b_config(self):
        config = get_tier_config(Tier.STARTER, product="b2b")
        assert config.max_api_keys == 1

    def test_string_tier_resolves(self):
        config = get_tier_config("business", product="b2b")
        assert config.max_chars_per_request == 50_000
