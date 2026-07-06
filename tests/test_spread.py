"""Tests for bid-ask spread estimation."""

from datetime import date

from fundautopsy.estimates.spread import estimate_bid_ask_spread
from fundautopsy.models.filing_data import DataSourceTag, NPortData, NPortHolding


class TestBidAskSpreadEstimation:
    """Test bid-ask spread cost estimation."""

    def test_zero_turnover_produces_zero_spread(self):
        """No trading means no spread cost."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=50_000_000_000,
            holdings=[
                NPortHolding(name="Large Cap Stock", asset_category="EC", pct_of_net_assets=100.0),
            ],
        )
        result = estimate_bid_ask_spread(nport, turnover_rate=0.0)
        assert result.low_bps == 0.0
        assert result.high_bps == 0.0
        assert result.tag == DataSourceTag.ESTIMATED

    def test_large_cap_equity_fund_reasonable_spread(self):
        """Large-cap equity fund with normal turnover should have modest spread."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=50_000_000_000,
            holdings=[
                NPortHolding(name="Large Cap Stock", asset_category="EC", pct_of_net_assets=100.0),
            ],
        )
        result = estimate_bid_ask_spread(nport, turnover_rate=0.30)
        assert result.tag == DataSourceTag.ESTIMATED
        assert result.low_bps > 0
        assert result.low_bps < result.high_bps
        # 30% turnover x 2 x 0.05%-0.10% spread = 3-6 bps
        assert result.low_bps <= 10.0
        assert result.high_bps <= 20.0

    def test_small_cap_equity_wider_spread(self):
        """Small-cap fund should have wider spread than large-cap at same turnover."""
        turnover = 0.30
        large_nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=50_000_000_000,
            holdings=[
                NPortHolding(name="Large Cap", asset_category="EC", pct_of_net_assets=100.0),
            ],
        )
        small_nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000002",
            total_net_assets=50_000_000_000,
            holdings=[
                NPortHolding(name="Small Cap", asset_category="EC_SMALL", pct_of_net_assets=100.0),
            ],
        )

        large_result = estimate_bid_ask_spread(large_nport, turnover)
        small_result = estimate_bid_ask_spread(small_nport, turnover)

        # Small-cap should have wider spreads
        assert small_result.low_bps >= large_result.low_bps
        assert small_result.high_bps > large_result.high_bps

    def test_high_turnover_produces_higher_spread(self):
        """Spread scales linearly with turnover."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=50_000_000_000,
            holdings=[
                NPortHolding(name="Stock", asset_category="EC", pct_of_net_assets=100.0),
            ],
        )
        low_turnover = estimate_bid_ask_spread(nport, turnover_rate=0.20)
        high_turnover = estimate_bid_ask_spread(nport, turnover_rate=0.60)

        # With 3x turnover, spread should be roughly 3x higher
        assert high_turnover.low_bps > low_turnover.low_bps * 2.5

    def test_bond_fund_tight_spread(self):
        """Government bond fund should have tight spreads."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=50_000_000_000,
            holdings=[
                NPortHolding(name="US Treasury", asset_category="DBT", pct_of_net_assets=100.0),
            ],
        )
        result = estimate_bid_ask_spread(nport, turnover_rate=0.30)
        # Treasury/DBT spreads should be tight (maps to DBT_IG by default)
        assert result.high_bps < 10.0

    def test_high_yield_bond_wider_spread(self):
        """High yield bonds should have wider spreads than IG."""
        nport_ig = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=50_000_000_000,
            holdings=[
                NPortHolding(name="IG Bond", asset_category="DBT", pct_of_net_assets=100.0),
            ],
        )
        # Simulate high yield as "other" since NPORT doesn't distinguish credit quality
        nport_hy = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000002",
            total_net_assets=50_000_000_000,
            holdings=[
                NPortHolding(name="HY Bond", asset_category="OTHER", pct_of_net_assets=100.0),
            ],
        )

        result_ig = estimate_bid_ask_spread(nport_ig, turnover_rate=0.30)
        result_hy = estimate_bid_ask_spread(nport_hy, turnover_rate=0.30)
        # Defaults to wider spread for unknown
        assert result_hy.low_bps >= result_ig.low_bps

    def test_mixed_portfolio_weighted_average(self):
        """Portfolio with mixed assets should use weighted-average spread."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=100_000_000,
            holdings=[
                NPortHolding(name="Large Cap Stock", asset_category="EC", pct_of_net_assets=50.0),
                NPortHolding(name="Treasury Bond", asset_category="DBT", pct_of_net_assets=30.0),
                NPortHolding(name="Cash", asset_category="CASH", pct_of_net_assets=20.0),
            ],
        )
        result = estimate_bid_ask_spread(nport, turnover_rate=0.25)

        # Just verify it produces a valid result
        assert result.low_bps >= 0
        assert result.high_bps > result.low_bps
        # Spread should be reasonable for mixed portfolio
        assert result.high_bps <= 10.0

    def test_cash_drag_minimal_spread(self):
        """Cash/STIV positions should have minimal spread cost."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=10_000_000,
            holdings=[
                NPortHolding(name="Money Market", asset_category="STIV", pct_of_net_assets=100.0),
            ],
        )
        result = estimate_bid_ask_spread(nport, turnover_rate=0.50)
        # Cash/STIV spreads are very tight (maps to EC which is then treated as tight)
        assert result.low_bps <= 5.0
        assert result.high_bps <= 10.0

    def test_very_high_turnover(self):
        """Extreme turnover (500%) should produce proportionally higher spread."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=50_000_000_000,
            holdings=[
                NPortHolding(name="Stock", asset_category="EC", pct_of_net_assets=100.0),
            ],
        )
        result = estimate_bid_ask_spread(nport, turnover_rate=5.0)
        # 500% turnover should produce 10x the spread of 50% turnover
        baseline = estimate_bid_ask_spread(nport, turnover_rate=0.50)
        assert result.low_bps > baseline.low_bps * 8.0

    def test_multiple_asset_categories(self):
        """Portfolio with many asset types should compute correctly."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=1_000_000_000,
            holdings=[
                NPortHolding(name="US Large Cap", asset_category="EC", pct_of_net_assets=25.0),
                NPortHolding(name="Intl Equity", asset_category="EC_INTL", pct_of_net_assets=15.0),
                NPortHolding(name="IG Corporate", asset_category="DBT", pct_of_net_assets=25.0),
                NPortHolding(name="Treasury", asset_category="DBT", pct_of_net_assets=20.0),
                NPortHolding(name="Cash Equiv", asset_category="CASH", pct_of_net_assets=15.0),
            ],
        )
        result = estimate_bid_ask_spread(nport, turnover_rate=0.40)

        assert result.tag == DataSourceTag.ESTIMATED
        assert result.low_bps > 0
        assert result.low_bps < result.high_bps
        assert result.methodology is not None

    def test_unknown_asset_category_uses_default(self):
        """Unknown asset categories should fall back to DEFAULT_SPREAD."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=50_000_000_000,
            holdings=[
                NPortHolding(name="Unknown", asset_category="UNKNOWN_CAT", pct_of_net_assets=100.0),
            ],
        )
        result = estimate_bid_ask_spread(nport, turnover_rate=0.30)

        # Should use default spread (not crash)
        assert result.low_bps > 0
        assert result.high_bps > result.low_bps

    def test_abs_mbs_reasonable_spread(self):
        """Agency MBS should have reasonable, tight spread."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=50_000_000_000,
            holdings=[
                NPortHolding(name="Agency MBS", asset_category="ABS-MBS", pct_of_net_assets=100.0),
            ],
        )
        result = estimate_bid_ask_spread(nport, turnover_rate=0.40)

        # MBS spreads should be tight (similar to IG)
        assert result.low_bps < 10.0
        assert result.high_bps < 20.0

    def test_methodology_field_populated(self):
        """Result should include methodology description."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=50_000_000_000,
            holdings=[
                NPortHolding(name="Stock", asset_category="EC", pct_of_net_assets=100.0),
            ],
        )
        result = estimate_bid_ask_spread(nport, turnover_rate=0.30)

        assert result.methodology is not None
        assert len(result.methodology) > 10
        assert "turnover" in result.methodology.lower()
        assert "spread" in result.methodology.lower()

    def test_empty_holdings_returns_none(self):
        """Portfolio with no holdings should return None (no data, not zero cost)."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=50_000_000_000,
            holdings=[],
        )
        result = estimate_bid_ask_spread(nport, turnover_rate=0.30)

        # Empty portfolio means we can't estimate — should signal missing, not zero
        assert result is None

    def test_emerging_market_equity_wider_than_us(self):
        """Emerging market equity should have wider spreads than US equity."""
        us_nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=50_000_000_000,
            holdings=[
                NPortHolding(name="US Large Cap", asset_category="EC", pct_of_net_assets=100.0),
            ],
        )
        em_nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000002",
            total_net_assets=50_000_000_000,
            holdings=[
                NPortHolding(name="EM Equity", asset_category="EC_EM", pct_of_net_assets=100.0),
            ],
        )

        turnover = 0.30
        us_result = estimate_bid_ask_spread(us_nport, turnover)
        em_result = estimate_bid_ask_spread(em_nport, turnover)

        assert em_result.low_bps >= us_result.high_bps, \
            "EM equity spreads should be significantly wider"
