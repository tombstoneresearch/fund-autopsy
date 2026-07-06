"""Tests for cost computation engine."""


from datetime import date

from fundautopsy.estimates.impact import estimate_market_impact
from fundautopsy.estimates.spread import estimate_bid_ask_spread
from fundautopsy.models.filing_data import DataSourceTag, NPortData, NPortHolding


class TestBidAskSpreadEstimation:
    """Test bid-ask spread cost estimation."""

    def test_large_cap_equity_fund(self):
        """Large-cap equity fund should have low spread estimate."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=50_000_000_000,
            holdings=[
                NPortHolding(
                    name="Test Stock",
                    asset_category="EC",
                    pct_of_net_assets=100.0,
                ),
            ],
        )
        result = estimate_bid_ask_spread(nport, turnover_rate=0.30)
        assert result.tag == DataSourceTag.ESTIMATED
        assert result.low_bps < result.high_bps
        assert result.low_bps > 0
        # 30% turnover x 2 x 0.05%-0.10% = 0.03%-0.06% = 3-6 bps
        assert 2.0 <= result.low_bps <= 10.0
        assert 2.0 <= result.high_bps <= 10.0

    def test_zero_turnover_gives_zero_spread(self):
        """No trading means no spread cost."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            holdings=[
                NPortHolding(name="Test", asset_category="EC", pct_of_net_assets=100.0),
            ],
        )
        result = estimate_bid_ask_spread(nport, turnover_rate=0.0)
        assert result.low_bps == 0.0
        assert result.high_bps == 0.0


class TestMarketImpactEstimation:
    """Test market impact cost estimation."""

    def test_large_cap_low_turnover(self):
        """Large-cap fund with low turnover should have minimal impact."""
        result = estimate_market_impact(
            turnover_rate=0.25,
            total_net_assets=50_000_000_000,
            is_small_cap=False,
        )
        assert result.tag == DataSourceTag.ESTIMATED
        assert result.low_bps < result.high_bps
        assert result.low_bps < 10  # Should be small

    def test_small_cap_high_turnover_has_higher_impact(self):
        """Small-cap + high turnover should produce larger estimates."""
        small = estimate_market_impact(0.80, 1_000_000_000, is_small_cap=True)
        large = estimate_market_impact(0.80, 50_000_000_000, is_small_cap=False)
        assert small.midpoint_bps > large.midpoint_bps
