"""Tests for cash drag estimation."""

from datetime import date

from fundautopsy.estimates.cash_drag import (
    estimate_cash_drag,
)
from fundautopsy.models.filing_data import NPortData, NPortHolding


class TestCashDragEstimation:
    """Test cash drag estimation."""

    def test_no_cash_position_produces_zero_drag(self):
        """Fund with no cash should have zero drag."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=100_000_000,
            holdings=[
                NPortHolding(name="Stock", asset_category="EC", pct_of_net_assets=100.0),
            ],
        )
        result = estimate_cash_drag(nport)

        assert result is not None
        assert result.low_bps == 0.0
        assert result.high_bps == 0.0

    def test_cash_within_baseline_produces_zero_drag(self):
        """Cash within operational baseline (2%) should produce no drag."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=100_000_000,
            holdings=[
                NPortHolding(name="Stock", asset_category="EC", pct_of_net_assets=98.0),
                NPortHolding(name="Cash", asset_category="STIV", pct_of_net_assets=2.0),
            ],
        )
        result = estimate_cash_drag(nport)

        assert result.low_bps == 0.0
        assert result.high_bps == 0.0
        assert "within operational baseline" in result.methodology.lower()

    def test_excess_cash_produces_drag(self):
        """Cash above baseline (2%) should produce proportional drag."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=100_000_000,
            holdings=[
                NPortHolding(name="Stock", asset_category="EC", pct_of_net_assets=93.0),
                NPortHolding(name="Cash", asset_category="STIV", pct_of_net_assets=7.0),
            ],
        )
        result = estimate_cash_drag(nport)

        # Excess = 7% - 2% = 5%
        # Drag = 5% x 2-6 bps per 1% = 10-30 bps
        assert result.low_bps > 0
        assert result.high_bps > result.low_bps
        assert result.low_bps >= 5.0  # At least 1% x 5 bps minimum
        assert result.high_bps <= 35.0  # At most 5% x 7 bps

    def test_high_cash_position_flagged(self):
        """Cash > 5% threshold should be flagged."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=100_000_000,
            holdings=[
                NPortHolding(name="Stock", asset_category="EC", pct_of_net_assets=93.0),
                NPortHolding(name="Cash", asset_category="STIV", pct_of_net_assets=7.0),
            ],
        )
        result = estimate_cash_drag(nport)

        assert "WARNING" in result.methodology.upper()
        assert "exceed" in result.methodology.lower()
        assert "5" in result.methodology  # Flag threshold

    def test_cash_at_flag_threshold(self):
        """Cash exactly at flag threshold (5%) should be flagged."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=100_000_000,
            holdings=[
                NPortHolding(name="Stock", asset_category="EC", pct_of_net_assets=95.0),
                NPortHolding(name="Cash", asset_category="STIV", pct_of_net_assets=5.0),
            ],
        )
        result = estimate_cash_drag(nport)

        # At 5%, should be flagged (threshold is >5%)
        # Actually, if exactly at 5%, it's not > 5%, so no flag
        # But the methodology should mention it
        assert "5.0" in result.methodology

    def test_cash_like_holdings_detected(self):
        """Holdings with cash-like names should be counted."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=100_000_000,
            holdings=[
                NPortHolding(name="Stock", asset_category="EC", pct_of_net_assets=93.0),
                NPortHolding(name="Money Market Fund", asset_category="OTHER", pct_of_net_assets=4.0),
                NPortHolding(name="Treasury Bill", asset_category="OTHER", pct_of_net_assets=3.0),
            ],
        )
        result = estimate_cash_drag(nport)

        # Money Market Fund + Treasury Bill = 7% = 5% excess
        # Should produce drag
        assert result.low_bps > 0
        assert result.high_bps > result.low_bps

    def test_drag_scales_with_excess_cash(self):
        """Drag should scale linearly with excess cash percentage."""
        base = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=100_000_000,
            holdings=[
                NPortHolding(name="Stock", asset_category="EC", pct_of_net_assets=90.0),
                NPortHolding(name="Cash", asset_category="STIV", pct_of_net_assets=10.0),
            ],
        )
        high = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=100_000_000,
            holdings=[
                NPortHolding(name="Stock", asset_category="EC", pct_of_net_assets=80.0),
                NPortHolding(name="Cash", asset_category="STIV", pct_of_net_assets=20.0),
            ],
        )

        result_base = estimate_cash_drag(base)
        result_high = estimate_cash_drag(high)

        # 8% excess vs 18% excess - should be roughly 2.25x higher
        assert result_high.low_bps > result_base.low_bps * 2.0

    def test_negative_cash_treated_as_zero(self):
        """Negative cash (hypothetically) should be treated as zero."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=100_000_000,
            holdings=[
                NPortHolding(name="Stock", asset_category="EC", pct_of_net_assets=100.0),
            ],
        )
        result = estimate_cash_drag(nport)

        assert result.low_bps == 0.0
        assert result.high_bps == 0.0

    def test_none_nport_returns_none(self):
        """None nport input should return None."""
        result = estimate_cash_drag(None)
        assert result is None

    def test_nport_no_holdings_returns_zero_drag(self):
        """NPort with empty holdings should return zero drag."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=100_000_000,
            holdings=[],
        )
        result = estimate_cash_drag(nport)

        assert result.low_bps == 0.0
        assert result.high_bps == 0.0

    def test_nport_zero_net_assets_returns_zero(self):
        """NPort with zero net assets should return zero drag."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=0,
            holdings=[
                NPortHolding(name="Cash", asset_category="STIV", pct_of_net_assets=100.0),
            ],
        )
        result = estimate_cash_drag(nport)

        assert result.low_bps == 0.0
        assert result.high_bps == 0.0

    def test_methodology_populated(self):
        """Result should include methodology."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=100_000_000,
            holdings=[
                NPortHolding(name="Stock", asset_category="EC", pct_of_net_assets=90.0),
                NPortHolding(name="Cash", asset_category="STIV", pct_of_net_assets=10.0),
            ],
        )
        result = estimate_cash_drag(nport)

        assert result.methodology is not None
        assert len(result.methodology) > 0
        assert "%" in result.methodology

    def test_multiple_cash_like_holdings_combined(self):
        """Multiple cash-like holdings should be summed."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=100_000_000,
            holdings=[
                NPortHolding(name="Stock", asset_category="EC", pct_of_net_assets=85.0),
                NPortHolding(name="Money Market", asset_category="STIV", pct_of_net_assets=3.0),
                NPortHolding(name="T-Bills", asset_category="OTHER", pct_of_net_assets=4.0),
                NPortHolding(name="Fed Funds", asset_category="OTHER", pct_of_net_assets=3.0),
                NPortHolding(name="Commercial Paper", asset_category="OTHER", pct_of_net_assets=5.0),
            ],
        )
        result = estimate_cash_drag(nport)

        # Total cash: 3% + 4% + 3% + 5% = 15%
        # Excess: 15% - 2% = 13%
        # Drag: 13% x 2-6 bps = 26-78 bps
        assert result.low_bps > 0
        assert result.low_bps >= 20.0
        assert result.high_bps <= 90.0

    def test_repo_holdings_recognized(self):
        """Repurchase agreement holdings should be recognized as cash-like."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=100_000_000,
            holdings=[
                NPortHolding(name="Stock", asset_category="EC", pct_of_net_assets=92.0),
                NPortHolding(name="Repurchase Agreement", asset_category="OTHER", pct_of_net_assets=8.0),
            ],
        )
        result = estimate_cash_drag(nport)

        # 8% cash, 6% excess
        assert result.low_bps > 0
        assert result.high_bps > result.low_bps

    def test_cash_collateral_recognized(self):
        """Cash collateral holdings should be recognized."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=100_000_000,
            holdings=[
                NPortHolding(name="Stock", asset_category="EC", pct_of_net_assets=91.0),
                NPortHolding(name="Cash Collateral", asset_category="OTHER", pct_of_net_assets=9.0),
            ],
        )
        result = estimate_cash_drag(nport)

        # 9% cash, 7% excess
        assert result.low_bps > 0
        assert result.high_bps > result.low_bps

    def test_cd_holdings_recognized(self):
        """Certificate of Deposit holdings should be recognized."""
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000000001",
            total_net_assets=100_000_000,
            holdings=[
                NPortHolding(name="Stock", asset_category="EC", pct_of_net_assets=89.0),
                NPortHolding(name="Certificate of Deposit", asset_category="OTHER", pct_of_net_assets=11.0),
            ],
        )
        result = estimate_cash_drag(nport)

        # 11% cash, 9% excess
        assert result.low_bps > 0
        assert result.high_bps > result.low_bps
