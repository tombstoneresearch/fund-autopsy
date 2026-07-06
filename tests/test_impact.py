"""Tests for market impact estimation."""


from fundautopsy.estimates.impact import (
    estimate_market_impact,
    estimate_market_impact_regression,
)
from fundautopsy.models.filing_data import DataSourceTag


class TestMarketImpactEstimation:
    """Test market impact cost estimation."""

    def test_zero_turnover_produces_zero_impact(self):
        """No trading means no market impact."""
        result = estimate_market_impact(
            turnover_rate=0.0,
            total_net_assets=50_000_000_000,
        )
        assert result.low_bps == 0.0
        assert result.high_bps == 0.0
        assert result.tag == DataSourceTag.ESTIMATED

    def test_large_cap_low_turnover_minimal_impact(self):
        """Large-cap fund with low turnover should have minimal impact."""
        result = estimate_market_impact(
            turnover_rate=0.25,
            total_net_assets=50_000_000_000,
            is_small_cap=False,
        )
        assert result.tag == DataSourceTag.ESTIMATED
        assert result.low_bps > 0
        assert result.low_bps < result.high_bps
        # For large-cap low turnover, impact should be quite small
        assert result.high_bps <= 5.0

    def test_large_cap_high_turnover_more_impact(self):
        """Large-cap fund with high turnover (>50%) should have more impact."""
        low_turnover = estimate_market_impact(
            turnover_rate=0.25,
            total_net_assets=50_000_000_000,
            is_small_cap=False,
        )
        high_turnover = estimate_market_impact(
            turnover_rate=0.75,
            total_net_assets=50_000_000_000,
            is_small_cap=False,
        )
        # Higher turnover should produce proportionally more impact
        assert high_turnover.low_bps > low_turnover.high_bps

    def test_small_cap_higher_impact_than_large_cap(self):
        """Small-cap funds should have higher market impact at same turnover."""
        large = estimate_market_impact(
            turnover_rate=0.30,
            total_net_assets=50_000_000_000,
            is_small_cap=False,
        )
        small = estimate_market_impact(
            turnover_rate=0.30,
            total_net_assets=50_000_000_000,
            is_small_cap=True,
        )
        assert small.low_bps > large.high_bps, \
            "Small-cap should have significantly higher impact"

    def test_small_cap_high_turnover_substantial_impact(self):
        """Small-cap with high turnover should have substantial impact."""
        result = estimate_market_impact(
            turnover_rate=0.80,
            total_net_assets=1_000_000_000,
            is_small_cap=True,
        )
        # Should be meaningful but not absurd
        assert result.low_bps > 10.0
        assert result.high_bps <= 150.0

    def test_impact_scales_with_turnover(self):
        """Impact should scale linearly (or near-linearly) with turnover."""
        base = estimate_market_impact(
            turnover_rate=0.50,
            total_net_assets=50_000_000_000,
            is_small_cap=False,
        )
        double = estimate_market_impact(
            turnover_rate=1.00,
            total_net_assets=50_000_000_000,
            is_small_cap=False,
        )
        # Double turnover should roughly double impact
        assert double.low_bps > base.low_bps * 1.8

    def test_bond_fund_flag_parameter(self):
        """Bond fund flag should use different assumptions."""
        equity = estimate_market_impact(
            turnover_rate=1.50,
            total_net_assets=10_000_000_000,
            is_bond_fund=False,
        )
        bond = estimate_market_impact(
            turnover_rate=1.50,
            total_net_assets=10_000_000_000,
            is_bond_fund=True,
        )
        # Bond impact should be lower than equity at same turnover
        assert bond.high_bps < equity.high_bps

    def test_bond_fund_uses_100pct_threshold(self):
        """Bond funds should have different turnover threshold (100% vs 50%)."""
        low_bond = estimate_market_impact(
            turnover_rate=0.80,
            total_net_assets=10_000_000_000,
            is_bond_fund=True,
        )
        high_bond = estimate_market_impact(
            turnover_rate=1.20,
            total_net_assets=10_000_000_000,
            is_bond_fund=True,
        )
        # At 80% and 120%, bond funds should cross threshold at 100%
        # So high_bond should use different (higher) impact rate
        assert high_bond.high_bps > low_bond.high_bps * 1.5

    def test_very_high_turnover_capped_reasonably(self):
        """Extreme turnover shouldn't produce absurd impact estimates."""
        result = estimate_market_impact(
            turnover_rate=5.0,  # 500% turnover
            total_net_assets=50_000_000_000,
            is_small_cap=False,
        )
        # Should still be bounded
        assert result.high_bps <= 400.0, "500% turnover impact too high"

    def test_pimco_like_bond_fund_reasonable(self):
        """PIMCO-like high-turnover bond fund should produce reasonable impact."""
        result = estimate_market_impact(
            turnover_rate=3.50,
            total_net_assets=50_000_000_000,
            is_bond_fund=True,
        )
        # Should be reasonable, not insane
        assert result.low_bps > 0
        assert result.high_bps < 100.0

    def test_methodology_includes_classification(self):
        """Methodology should describe fund classification."""
        result = estimate_market_impact(
            turnover_rate=0.50,
            total_net_assets=50_000_000_000,
            is_small_cap=True,
        )
        assert "small-cap" in result.methodology.lower()

    def test_methodology_includes_turnover_level(self):
        """Methodology should indicate turnover level."""
        low = estimate_market_impact(
            turnover_rate=0.25,
            total_net_assets=50_000_000_000,
        )
        high = estimate_market_impact(
            turnover_rate=0.75,
            total_net_assets=50_000_000_000,
        )
        assert "low" in low.methodology.lower()
        assert "high" in high.methodology.lower()


class TestMarketImpactRegression:
    """Test regression-based market impact estimation."""

    def test_zero_turnover_produces_zero_impact_regression(self):
        """No trading means no impact in regression model."""
        result = estimate_market_impact_regression(
            turnover_rate=0.0,
            total_net_assets=50_000_000_000,
        )
        assert result.low_bps == 0.0
        assert result.high_bps == 0.0

    def test_pure_large_cap_equity_low_impact(self):
        """Pure large-cap equity with regression model."""
        result = estimate_market_impact_regression(
            turnover_rate=0.30,
            total_net_assets=50_000_000_000,
            pct_small_cap=0.0,
            pct_bond=0.0,
        )
        assert result.low_bps > 0
        assert result.high_bps < 10.0

    def test_pure_small_cap_equity_more_impact(self):
        """Pure small-cap equity should have higher impact."""
        large = estimate_market_impact_regression(
            turnover_rate=0.30,
            total_net_assets=50_000_000_000,
            pct_small_cap=0.0,
            pct_bond=0.0,
        )
        small = estimate_market_impact_regression(
            turnover_rate=0.30,
            total_net_assets=50_000_000_000,
            pct_small_cap=100.0,
            pct_bond=0.0,
        )
        assert small.low_bps > large.high_bps

    def test_pure_bond_fund_low_impact(self):
        """Pure bond portfolio should have low impact."""
        result = estimate_market_impact_regression(
            turnover_rate=2.0,  # High for bonds
            total_net_assets=50_000_000_000,
            pct_small_cap=0.0,
            pct_bond=100.0,
        )
        # Bond impact even with high turnover should be reasonable
        assert result.high_bps <= 50.0

    def test_balanced_fund_blended_impact(self):
        """Balanced fund should have impact between pure equity and pure bond."""
        equity = estimate_market_impact_regression(
            turnover_rate=0.50,
            total_net_assets=50_000_000_000,
            pct_small_cap=0.0,
            pct_bond=0.0,
        )
        balanced = estimate_market_impact_regression(
            turnover_rate=0.50,
            total_net_assets=50_000_000_000,
            pct_small_cap=0.0,
            pct_bond=50.0,
        )
        bond = estimate_market_impact_regression(
            turnover_rate=0.50,
            total_net_assets=50_000_000_000,
            pct_small_cap=0.0,
            pct_bond=100.0,
        )
        assert bond.high_bps < balanced.high_bps < equity.high_bps

    def test_mixed_cap_portfolio(self):
        """Mixed cap portfolio should blend small and large cap assumptions."""
        large_only = estimate_market_impact_regression(
            turnover_rate=0.40,
            total_net_assets=50_000_000_000,
            pct_small_cap=0.0,
            pct_bond=0.0,
        )
        fifty_fifty = estimate_market_impact_regression(
            turnover_rate=0.40,
            total_net_assets=50_000_000_000,
            pct_small_cap=50.0,
            pct_bond=0.0,
        )
        small_only = estimate_market_impact_regression(
            turnover_rate=0.40,
            total_net_assets=50_000_000_000,
            pct_small_cap=100.0,
            pct_bond=0.0,
        )

        # 50/50 should be between pure large and pure small
        assert large_only.high_bps < fifty_fifty.high_bps < small_only.high_bps

    def test_complex_multi_asset_allocation(self):
        """Complex allocation should compute without error."""
        result = estimate_market_impact_regression(
            turnover_rate=0.60,
            total_net_assets=100_000_000_000,
            pct_small_cap=30.0,  # 30% of equity is small cap
            pct_bond=40.0,  # 40% of portfolio is bonds
        )
        assert result.low_bps > 0
        assert result.high_bps > result.low_bps

    def test_pct_parameters_clipped_to_100(self):
        """Percentages >100 should be clipped."""
        over = estimate_market_impact_regression(
            turnover_rate=0.30,
            total_net_assets=50_000_000_000,
            pct_small_cap=150.0,  # Over 100
            pct_bond=150.0,  # Over 100
        )
        at_100 = estimate_market_impact_regression(
            turnover_rate=0.30,
            total_net_assets=50_000_000_000,
            pct_small_cap=100.0,
            pct_bond=100.0,
        )
        # Should produce same result (clipped)
        assert over.low_bps == at_100.low_bps
        assert over.high_bps == at_100.high_bps

    def test_bond_threshold_applied_in_regression(self):
        """Regression model should apply 100% turnover threshold for bonds."""
        low_turnover_bond = estimate_market_impact_regression(
            turnover_rate=0.80,
            total_net_assets=50_000_000_000,
            pct_small_cap=0.0,
            pct_bond=100.0,
        )
        high_turnover_bond = estimate_market_impact_regression(
            turnover_rate=1.20,
            total_net_assets=50_000_000_000,
            pct_small_cap=0.0,
            pct_bond=100.0,
        )
        # Should cross 100% threshold
        assert high_turnover_bond.high_bps > low_turnover_bond.high_bps * 1.2

    def test_methodology_includes_blending_info(self):
        """Methodology should describe blending of assumptions."""
        result = estimate_market_impact_regression(
            turnover_rate=0.50,
            total_net_assets=50_000_000_000,
            pct_small_cap=25.0,
            pct_bond=30.0,
        )
        assert "regression" in result.methodology.lower() or "blend" in result.methodology.lower()
        assert "30" in result.methodology or "30.0" in result.methodology  # Bond weight (30%)

    def test_regression_vs_simple_model_consistency(self):
        """Regression model should produce similar results to simple model for pure cases."""
        simple = estimate_market_impact(
            turnover_rate=0.30,
            total_net_assets=50_000_000_000,
            is_small_cap=False,
            is_bond_fund=False,
        )
        regression = estimate_market_impact_regression(
            turnover_rate=0.30,
            total_net_assets=50_000_000_000,
            pct_small_cap=0.0,
            pct_bond=0.0,
        )
        # Should be within reasonable tolerance (both use same assumptions)
        assert abs(simple.low_bps - regression.low_bps) < 0.5
        assert abs(simple.high_bps - regression.high_bps) < 0.5

    def test_high_turnover_equity_fund_reasonable(self):
        """High-turnover equity fund should produce reasonable impact."""
        result = estimate_market_impact_regression(
            turnover_rate=1.50,
            total_net_assets=50_000_000_000,
            pct_small_cap=0.0,
            pct_bond=0.0,
        )
        # Should be substantial but not absurd
        assert result.low_bps > 5.0
        assert result.high_bps <= 150.0
