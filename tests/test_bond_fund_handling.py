"""Tests for bond fund cost estimation — the PIMIX fix."""

from datetime import date

from fundautopsy.estimates.assumptions import NPORT_ASSET_CAT_MAP, SPREAD_ASSUMPTIONS
from fundautopsy.estimates.impact import estimate_market_impact, estimate_market_impact_regression
from fundautopsy.estimates.spread import estimate_bid_ask_spread
from fundautopsy.models.filing_data import DataSourceTag, NPortData, NPortHolding


class TestBondFundHandling:
    """Tests for bond fund cost estimation — the PIMIX fix."""

    def test_bond_fund_impact_reasonable(self):
        """Bond fund with high turnover should NOT produce insane impact numbers."""
        # PIMCO-like: 350% turnover, $50B AUM
        result = estimate_market_impact(
            turnover_rate=3.50,
            total_net_assets=50_000_000_000,
            is_small_cap=False,
            is_bond_fund=True,
        )
        assert result.low_bps < 100, f"Bond impact too high: {result.low_bps} bps"
        assert result.high_bps < 150, f"Bond impact too high: {result.high_bps} bps"

    def test_bond_impact_lower_than_equity_at_same_turnover(self):
        """At the same turnover, bond funds should have lower market impact than equity."""
        bond = estimate_market_impact(
            turnover_rate=0.80,
            total_net_assets=10e9,
            is_bond_fund=True,
        )
        equity = estimate_market_impact(
            turnover_rate=0.80,
            total_net_assets=10e9,
            is_small_cap=False,
            is_bond_fund=False,
        )
        assert bond.high_bps < equity.high_bps

    def test_bond_turnover_threshold_is_100pct(self):
        """Bond funds use 100% as the high turnover threshold, not 50%."""
        low_turnover = estimate_market_impact(
            turnover_rate=0.90,
            total_net_assets=10e9,
            is_bond_fund=True,
        )
        high_turnover = estimate_market_impact(
            turnover_rate=1.10,
            total_net_assets=10e9,
            is_bond_fund=True,
        )
        # The per-unit impact rate should change at the 100% boundary
        low_rate = low_turnover.high_bps / 0.90
        high_rate = high_turnover.high_bps / 1.10
        assert high_rate > low_rate, "Bond high-turnover should use a higher impact rate"

    def test_regression_bond_fund_reasonable(self):
        """Regression model: bond fund with high turnover should be reasonable."""
        # PIMCO-like: 350% turnover, $50B AUM
        result = estimate_market_impact_regression(
            turnover_rate=3.50,
            total_net_assets=50_000_000_000,
            pct_small_cap=0.0,
            pct_bond=100.0,
        )
        # Regression should produce reasonable values for bonds
        assert result.low_bps > 0
        assert result.high_bps < 200, f"Regression bond impact too high: {result.high_bps} bps"

    def test_regression_bond_vs_equity(self):
        """Regression model: bonds should have lower impact than equities at same turnover."""
        bond = estimate_market_impact_regression(
            turnover_rate=0.80,
            total_net_assets=10e9,
            pct_small_cap=0.0,
            pct_bond=100.0,
        )
        equity = estimate_market_impact_regression(
            turnover_rate=0.80,
            total_net_assets=10e9,
            pct_small_cap=0.0,
            pct_bond=0.0,
        )
        assert bond.high_bps < equity.high_bps

    def test_abs_mbs_spread_assumptions_exist(self):
        """ABS/MBS categories should map to dedicated spread assumptions."""
        for cat in ["ABS-MBS", "ABS-O", "ABS-CBDO", "ABS-A"]:
            assert cat in NPORT_ASSET_CAT_MAP
            key = NPORT_ASSET_CAT_MAP[cat]
            assert key in SPREAD_ASSUMPTIONS

    def test_bond_heavy_portfolio_spread(self):
        """A bond-heavy portfolio should produce reasonable spread estimates."""
        nport = NPortData(
            filing_date=date(2025, 6, 30),
            reporting_period_end=date(2025, 3, 31),
            series_id="S000000001",
            total_net_assets=50_000_000_000,
            holdings=[
                NPortHolding(
                    name="US Treasury 5Y",
                    asset_category="DBT",
                    pct_of_net_assets=30.0,
                    value_usd=15e9,
                ),
                NPortHolding(
                    name="Agency MBS Pool",
                    asset_category="ABS-MBS",
                    pct_of_net_assets=25.0,
                    value_usd=12.5e9,
                ),
                NPortHolding(
                    name="IG Corporate Bond",
                    asset_category="DBT",
                    pct_of_net_assets=20.0,
                    value_usd=10e9,
                ),
                NPortHolding(
                    name="CLO Tranche A",
                    asset_category="ABS-CBDO",
                    pct_of_net_assets=10.0,
                    value_usd=5e9,
                ),
                NPortHolding(
                    name="Interest Rate Swap",
                    asset_category="DIR",
                    pct_of_net_assets=5.0,
                    value_usd=2.5e9,
                ),
                NPortHolding(
                    name="Cash Sweep",
                    asset_category="STIV",
                    pct_of_net_assets=10.0,
                    value_usd=5e9,
                ),
            ],
        )
        result = estimate_bid_ask_spread(nport, turnover_rate=3.50)
        assert result.tag == DataSourceTag.ESTIMATED
        # Bond portfolio spreads should be reasonable, not the 100+ bps we saw with PIMIX
        assert result.high_bps < 200, f"Bond spread too high: {result.high_bps} bps"
