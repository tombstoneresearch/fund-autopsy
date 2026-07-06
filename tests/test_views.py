"""Tests for view modules (advisor, comparison, researcher).

These are stub implementations that print "not yet implemented" messages.
Tests verify that the stubs execute without error.
"""

from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock

from fundautopsy.views import advisor, comparison, researcher


def test_advisor_view_renders_not_implemented():
    """Advisor view should print not-yet-implemented message."""
    console_mock = MagicMock()
    result_mock = MagicMock()

    # Should not raise
    advisor.render(result_mock, console_mock)

    # Should print exactly once
    assert console_mock.print.call_count == 1
    call_args = console_mock.print.call_args[0]
    assert "not yet implemented" in call_args[0].lower()


def test_comparison_view_renders_empty_list():
    """Comparison view should handle empty results list."""
    console_mock = MagicMock()

    # Should not raise with empty list
    comparison.render_comparison(
        [],
        investment=100000,
        horizon=20,
        assumed_return=7.0,
        console=console_mock,
    )

    assert console_mock.print.call_count == 1


def test_comparison_view_renders_real_funds():
    """Comparison view should render a Rich table for real FundNode data."""
    from fundautopsy.models.cost_breakdown import CostBreakdown, CostRange
    from fundautopsy.models.filing_data import DataSourceTag, TaggedValue
    from fundautopsy.models.fund_metadata import FundMetadata
    from fundautopsy.models.holdings_tree import FundNode

    # Build minimal but real FundNode objects
    def make_node(ticker: str, name: str, er_bps: float, brokerage_bps: float) -> FundNode:
        meta = FundMetadata(
            ticker=ticker, name=name, cik=12345,
            series_id="S000001", class_id="C000001",
            fund_family="Test Family",
        )
        cb = CostBreakdown(
            ticker=ticker, fund_name=name,
            expense_ratio_bps=TaggedValue(value=er_bps, tag=DataSourceTag.REPORTED),
            brokerage_commissions_bps=TaggedValue(value=brokerage_bps, tag=DataSourceTag.REPORTED),
            bid_ask_spread_cost=CostRange(low_bps=2.0, high_bps=5.0, tag=DataSourceTag.ESTIMATED),
            market_impact_cost=CostRange(low_bps=1.0, high_bps=3.0, tag=DataSourceTag.ESTIMATED),
        )
        return FundNode(metadata=meta, cost_breakdown=cb)

    fund_a = make_node("AAAA", "Fund A", 45.0, 3.0)
    fund_b = make_node("BBBB", "Fund B", 80.0, 8.0)

    from rich.console import Console
    buf = StringIO()
    console = Console(file=buf, width=120)

    comparison.render_comparison(
        [fund_a, fund_b],
        investment=100000,
        horizon=20,
        assumed_return=7.0,
        console=console,
    )

    output = buf.getvalue()
    assert "AAAA" in output
    assert "BBBB" in output
    assert "Fund Autopsy" in output


def test_researcher_view_renders_not_implemented():
    """Researcher view should print not-yet-implemented message."""
    console_mock = MagicMock()
    result_mock = MagicMock()

    # Should not raise
    researcher.render(result_mock, console_mock)

    # Should print exactly once
    assert console_mock.print.call_count == 1
    call_args = console_mock.print.call_args[0]
    assert "not yet implemented" in call_args[0].lower()
