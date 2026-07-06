"""Tests for portfolio-level TCO rollup.

The portfolio pipeline composes `identify_fund` + `detect_structure` +
`compute_costs` + `rollup_costs` across a list of holdings. These tests
mock the single-fund pipeline so we can exercise the aggregation logic,
edge cases, and compound-drag math without hitting EDGAR.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from fundautopsy.core.portfolio import (
    CompoundDragProjection,
    HoldingResult,
    PortfolioHolding,
    PortfolioTCO,
    _project_compound_drag,
    parse_portfolio_input,
    rollup_portfolio,
)
from fundautopsy.models.cost_breakdown import CostBreakdown
from fundautopsy.models.filing_data import DataSourceTag, TaggedValue
from fundautopsy.models.fund_metadata import FundMetadata
from fundautopsy.models.holdings_tree import FundNode


def _build_priced_tree(
    ticker: str,
    er_bps: float | None,
    bc_bps: float | None = None,
    uf_bps: float | None = None,
    is_fof: bool = False,
) -> FundNode:
    """Build a fully-priced FundNode as if it had just come back from the pipeline."""
    meta = FundMetadata(
        ticker=ticker,
        name=f"{ticker} Test Fund",
        cik=f"00000{abs(hash(ticker)) % 10000:04d}",
        series_id="S000000001",
        class_id="C000000001",
        fund_family="Test Family",
    )
    node = FundNode(metadata=meta, allocation_weight=1.0, depth=0)
    cb = CostBreakdown(ticker=ticker, fund_name=meta.name)
    if er_bps is not None:
        cb.expense_ratio_bps = TaggedValue(value=er_bps, tag=DataSourceTag.REPORTED)
    if bc_bps is not None:
        cb.brokerage_commissions_bps = TaggedValue(value=bc_bps, tag=DataSourceTag.REPORTED)
    if uf_bps is not None:
        cb.underlying_funds_weighted_bps = TaggedValue(
            value=uf_bps, tag=DataSourceTag.CALCULATED,
        )
    node.cost_breakdown = cb
    if is_fof:
        # A stub child to flip is_fund_of_funds to True.
        child = FundNode(metadata=meta, allocation_weight=1.0, depth=1)
        node.children.append(child)
    return node


def _stub_pipeline_factory(fund_data: dict[str, FundNode]):
    """Build the three-function stub that the pipeline uses.

    Returns (identify_fund_stub, detect_structure_stub, compute_costs_stub,
    rollup_costs_stub). compute_costs is a no-op; the pre-built tree already
    has cost_breakdown populated. rollup_costs passes through since the tree
    is already fully populated.
    """

    def identify_stub(ticker: str):
        ticker_up = ticker.upper()
        if ticker_up not in fund_data:
            raise ValueError(f"Could not resolve '{ticker}' to a registered mutual fund.")
        return fund_data[ticker_up].metadata

    def detect_stub(fund_meta, depth: int = 0):
        return fund_data[fund_meta.ticker]

    def noop_costs(tree):
        return tree

    def noop_rollup(tree):
        return tree

    return identify_stub, detect_stub, noop_costs, noop_rollup


def _with_pipeline(fund_data: dict[str, FundNode]):
    """Context-ish decorator: apply the pipeline patches in one place.

    Includes a no-op patch for the prospectus-hydration helper so tests
    do not hit live EDGAR when _price_holding runs its ER refresh.
    """
    identify, detect, costs, rollup = _stub_pipeline_factory(fund_data)
    return (
        patch("fundautopsy.core.portfolio.identify_fund", side_effect=identify),
        patch("fundautopsy.core.portfolio.detect_structure", side_effect=detect),
        patch("fundautopsy.core.portfolio.compute_costs", side_effect=costs),
        patch("fundautopsy.core.portfolio.rollup_costs", side_effect=rollup),
        patch("fundautopsy.core.portfolio._hydrate_prospectus_er", lambda *a, **k: None),
    )


class TestRollupPortfolio:
    def test_three_standalone_funds_weighted_tco_correct(self):
        """Three index funds at 60/30/10 weights produce the weighted TCO by hand-calc."""
        fund_data = {
            "VTSAX": _build_priced_tree("VTSAX", er_bps=4.0),  # Total US stock
            "VTIAX": _build_priced_tree("VTIAX", er_bps=11.0),  # Total intl
            "VBTLX": _build_priced_tree("VBTLX", er_bps=5.0),   # Total bond
        }
        holdings = [
            PortfolioHolding(ticker="VTSAX", weight=60.0),
            PortfolioHolding(ticker="VTIAX", weight=30.0),
            PortfolioHolding(ticker="VBTLX", weight=10.0),
        ]

        p1, p2, p3, p4, p5 = _with_pipeline(fund_data)
        with p1, p2, p3, p4, p5:
            result = rollup_portfolio(holdings)

        # Hand calc: 0.6 * 4 + 0.3 * 11 + 0.1 * 5 = 2.4 + 3.3 + 0.5 = 6.2 bps
        assert result.weighted_true_tco_bps == pytest.approx(6.2, abs=0.05)
        assert result.weighted_expense_ratio_bps == pytest.approx(6.2, abs=0.05)
        # Stated ER matches true TCO here because no brokerage, no FoF rollup.
        assert result.hidden_gap_bps == pytest.approx(0.0, abs=0.05)
        assert result.priced_weight_fraction == pytest.approx(1.0)
        assert len(result.holdings) == 3

    def test_fund_of_funds_identity(self):
        """A target-date FoF in isolation and as 100% holding produce the same TCO."""
        # The wrapper has direct costs of 25 bps and rolled-up underlying of 48 bps
        fof_tree = _build_priced_tree(
            "TGTDX", er_bps=25.0, uf_bps=48.0, is_fof=True,
        )
        fund_data = {"TGTDX": fof_tree}

        p1, p2, p3, p4, p5 = _with_pipeline(fund_data)
        with p1, p2, p3, p4, p5:
            single = rollup_portfolio([PortfolioHolding(ticker="TGTDX", weight=100.0)])

        # Portfolio of only TGTDX should equal TGTDX's own total_reported_bps: 25 + 48 = 73
        assert single.weighted_true_tco_bps == pytest.approx(73.0, abs=0.05)
        assert single.weighted_expense_ratio_bps == pytest.approx(25.0, abs=0.05)
        assert single.hidden_gap_bps == pytest.approx(48.0, abs=0.05)

    def test_missing_data_tolerance(self):
        """A ticker with no N-CEN data tags UNAVAILABLE and doesn't sink the request."""
        fund_data = {
            "VTSAX": _build_priced_tree("VTSAX", er_bps=4.0),
            # BADDIE has no er_bps and no other costs — unpriceable
            "BADDIE": _build_priced_tree("BADDIE", er_bps=None),
        }
        holdings = [
            PortfolioHolding(ticker="VTSAX", weight=70.0),
            PortfolioHolding(ticker="BADDIE", weight=30.0),
        ]

        p1, p2, p3, p4, p5 = _with_pipeline(fund_data)
        with p1, p2, p3, p4, p5:
            result = rollup_portfolio(holdings)

        # Result computes — does not raise.
        assert len(result.holdings) == 2
        baddie_row = [h for h in result.holdings if h.ticker == "BADDIE"][0]
        assert baddie_row.data_quality == "UNAVAILABLE"
        # Weighted mean rebased to priced portion: TCO = (70/70) * 4 = 4 bps
        assert result.weighted_true_tco_bps == pytest.approx(4.0, abs=0.05)
        # Priced coverage should reflect the 70% that priced.
        assert result.priced_weight_fraction == pytest.approx(0.7)
        assert result.unpriced_weight_fraction == pytest.approx(0.3)
        # A data note should surface the unpriced weight.
        assert any("BADDIE" in note for note in result.data_notes)

    def test_unresolved_ticker_via_value_error(self):
        """Ticker that fails identify_fund is tagged UNAVAILABLE gracefully."""
        fund_data = {
            "VTSAX": _build_priced_tree("VTSAX", er_bps=4.0),
            # CRYPTO not in fund_data — identify_stub will raise ValueError
        }
        holdings = [
            PortfolioHolding(ticker="VTSAX", weight=90.0),
            PortfolioHolding(ticker="CRYPTO", weight=10.0),
        ]

        p1, p2, p3, p4, p5 = _with_pipeline(fund_data)
        with p1, p2, p3, p4, p5:
            result = rollup_portfolio(holdings)

        crypto_row = [h for h in result.holdings if h.ticker == "CRYPTO"][0]
        assert crypto_row.data_quality == "UNAVAILABLE"
        assert crypto_row.true_tco_bps is None
        # Portfolio still priced the VTSAX portion.
        assert result.priced_weight_fraction == pytest.approx(0.9)
        assert result.weighted_true_tco_bps == pytest.approx(4.0, abs=0.05)

    def test_weights_tolerance_within_2pct_normalizes(self):
        """Weights summing to 99% (within tolerance) normalize silently."""
        fund_data = {
            "VTSAX": _build_priced_tree("VTSAX", er_bps=4.0),
            "VBTLX": _build_priced_tree("VBTLX", er_bps=5.0),
        }
        # Total = 99% — within tolerance
        holdings = [
            PortfolioHolding(ticker="VTSAX", weight=60.0),
            PortfolioHolding(ticker="VBTLX", weight=39.0),
        ]

        p1, p2, p3, p4, p5 = _with_pipeline(fund_data)
        with p1, p2, p3, p4, p5:
            result = rollup_portfolio(holdings)

        # After normalization, weights should sum to 100.
        total = sum(h.weight_pct for h in result.holdings)
        assert total == pytest.approx(100.0, abs=0.01)
        # Note should mention the normalization.
        assert any("normalized" in n.lower() for n in result.data_notes)

    def test_weights_off_by_more_than_2pct_raises(self):
        """Weights summing to 90% or 110% raise an error."""
        holdings = [PortfolioHolding(ticker="VTSAX", weight=90.0)]
        with pytest.raises(ValueError, match="weights sum to"):
            rollup_portfolio(holdings)

    def test_negative_weight_rejected(self):
        holdings = [
            PortfolioHolding(ticker="VTSAX", weight=110.0),
            PortfolioHolding(ticker="SHORT", weight=-10.0),
        ]
        with pytest.raises(ValueError, match="non-positive"):
            rollup_portfolio(holdings)

    def test_zero_weight_rejected(self):
        holdings = [
            PortfolioHolding(ticker="VTSAX", weight=100.0),
            PortfolioHolding(ticker="ZERO", weight=0.0),
        ]
        with pytest.raises(ValueError, match="non-positive"):
            rollup_portfolio(holdings)

    def test_duplicate_ticker_weights_summed(self):
        """VTSAX entered twice with 30% and 30% should be treated as one 60% holding."""
        fund_data = {"VTSAX": _build_priced_tree("VTSAX", er_bps=4.0)}
        holdings = [
            PortfolioHolding(ticker="VTSAX", weight=30.0),
            PortfolioHolding(ticker="VTSAX", weight=30.0),
            PortfolioHolding(ticker="VTSAX", weight=40.0),
        ]

        p1, p2, p3, p4, p5 = _with_pipeline(fund_data)
        with p1, p2, p3, p4, p5:
            result = rollup_portfolio(holdings)

        assert len(result.holdings) == 1
        assert result.holdings[0].weight_pct == pytest.approx(100.0)

    def test_empty_portfolio_raises(self):
        with pytest.raises(ValueError, match="at least one"):
            rollup_portfolio([])


class TestCompoundDragProjection:
    def test_zero_gap_zero_drag(self):
        """When true TCO equals stated ER, the drag is exactly zero."""
        proj = _project_compound_drag(
            horizon_years=30,
            starting_balance=100_000,
            gross_return_annual=0.07,
            true_tco_bps=50.0,
            stated_er_bps=50.0,
        )
        assert proj.drag_dollars == pytest.approx(0.0, abs=0.01)
        assert proj.drag_percent == pytest.approx(0.0, abs=0.0001)

    def test_fifty_bps_gap_thirty_years_closed_form(self):
        """50 bps gap over 30 years at 7% gross — hand-calc closed form."""
        proj = _project_compound_drag(
            horizon_years=30,
            starting_balance=100_000,
            gross_return_annual=0.07,
            true_tco_bps=50.0,
            stated_er_bps=0.0,
        )
        # (1.070)^30 ≈ 7.612; (1.065)^30 ≈ 6.614
        # Stated: 100_000 * 7.612 = 761_226
        # True:   100_000 * 6.614 = 661_437
        # Drag ≈ 99_789
        assert proj.terminal_wealth_stated_er == pytest.approx(761_225.5, rel=0.001)
        assert proj.terminal_wealth_true_tco == pytest.approx(661_436.7, rel=0.001)
        assert proj.drag_dollars == pytest.approx(99_788.8, rel=0.005)
        assert proj.drag_percent == pytest.approx(0.1311, abs=0.001)

    def test_horizon_zero_is_starting_balance(self):
        """A zero-year horizon should return starting balance for both."""
        proj = _project_compound_drag(
            horizon_years=0,
            starting_balance=50_000,
            gross_return_annual=0.07,
            true_tco_bps=100.0,
            stated_er_bps=25.0,
        )
        assert proj.terminal_wealth_stated_er == pytest.approx(50_000.0)
        assert proj.terminal_wealth_true_tco == pytest.approx(50_000.0)
        assert proj.drag_dollars == pytest.approx(0.0)


class TestParsePortfolioInput:
    def test_simple_space_separated(self):
        raw = "VTSAX 60\nVTIAX 30\nVBTLX 10"
        parsed = parse_portfolio_input(raw)
        assert [h.ticker for h in parsed] == ["VTSAX", "VTIAX", "VBTLX"]
        assert [h.weight for h in parsed] == [60.0, 30.0, 10.0]

    def test_comma_separated(self):
        raw = "VTSAX, 60\nVTIAX, 30\nVBTLX, 10"
        parsed = parse_portfolio_input(raw)
        assert [h.weight for h in parsed] == [60.0, 30.0, 10.0]

    def test_colon_and_percent(self):
        raw = "VTSAX: 60%\nVTIAX: 30%\nVBTLX: 10%"
        parsed = parse_portfolio_input(raw)
        assert [h.weight for h in parsed] == [60.0, 30.0, 10.0]

    def test_comments_and_blanks_ignored(self):
        raw = "# my retirement portfolio\n\nVTSAX 60\n# bonds section\nVBTLX 40"
        parsed = parse_portfolio_input(raw)
        assert len(parsed) == 2
        assert parsed[0].ticker == "VTSAX"
        assert parsed[1].ticker == "VBTLX"

    def test_empty_input_raises(self):
        with pytest.raises(ValueError, match="No holdings"):
            parse_portfolio_input("")

    def test_malformed_line_raises(self):
        with pytest.raises(ValueError, match="expected ticker and weight"):
            parse_portfolio_input("VTSAX")

    def test_non_numeric_weight_raises(self):
        with pytest.raises(ValueError, match="could not parse weight"):
            parse_portfolio_input("VTSAX abcd")

    def test_bogus_ticker_raises(self):
        with pytest.raises(ValueError, match="does not look like"):
            parse_portfolio_input("123ABC 60")

    def test_lowercase_ticker_normalized_to_upper(self):
        parsed = parse_portfolio_input("vtsax 100")
        assert parsed[0].ticker == "VTSAX"
