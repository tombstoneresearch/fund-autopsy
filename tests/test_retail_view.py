"""Tests for the retail view — Tier 1 investor output."""

from __future__ import annotations

from unittest.mock import MagicMock

from fundautopsy.models.cost_breakdown import CostBreakdown, CostRange
from fundautopsy.models.filing_data import DataSourceTag, TaggedValue
from fundautopsy.models.fund_metadata import FundMetadata
from fundautopsy.models.holdings_tree import FundNode
from fundautopsy.views import retail


def _make_cost_breakdown(
    brokerage_bps=None,
    spread_low=None,
    spread_high=None,
    impact_low=None,
    impact_high=None,
):
    """Helper to create a CostBreakdown with specified values."""
    cb = CostBreakdown(ticker="TEST", fund_name="Test Fund")

    if brokerage_bps is not None:
        cb.brokerage_commissions_bps = TaggedValue(
            value=brokerage_bps,
            tag=DataSourceTag.REPORTED,
            note="Test brokerage",
        )

    if spread_low is not None:
        cb.bid_ask_spread_cost = CostRange(
            low_bps=spread_low,
            high_bps=spread_high or spread_low,
            tag=DataSourceTag.ESTIMATED,
        )

    if impact_low is not None:
        cb.market_impact_cost = CostRange(
            low_bps=impact_low,
            high_bps=impact_high or impact_low,
            tag=DataSourceTag.ESTIMATED,
        )

    return cb


def _make_fund_node(
    ticker="VTSAX",
    name="Vanguard Total Stock Market",
    family="Vanguard",
    cost_breakdown=None,
    with_nport=True,
):
    """Helper to create a FundNode for testing."""
    node = MagicMock(spec=FundNode)
    node.metadata = FundMetadata(
        ticker=ticker,
        name=name,
        cik="0000110296",
        series_id="S000009228",
        class_id="C0000023699",
        fund_family=family,
        is_fund_of_funds=False,
    )
    node.cost_breakdown = cost_breakdown
    node.data_notes = []

    if with_nport:
        nport = MagicMock()
        nport.total_net_assets = 500_000_000_000  # $500B
        nport.holdings = [MagicMock() for _ in range(3000)]
        nport.fund_holdings = []
        nport.reporting_period_end = "2024-12-31"

        def mock_asset_weights():
            return {
                "EC": 70.0,  # 70% equities
                "DBT": 25.0,  # 25% debt
                "STIV": 5.0,  # 5% cash
            }

        nport.asset_class_weights = mock_asset_weights
        node.nport_data = nport
    else:
        node.nport_data = None

    return node


def test_render_with_no_cost_data(capsys):
    """Render should handle funds with no cost data."""
    from rich.console import Console

    node = _make_fund_node(cost_breakdown=None)
    console = Console()

    retail.render(node, console)

    captured = capsys.readouterr()
    assert "No cost data available" in captured.out


def test_render_with_complete_cost_data(capsys):
    """Render should display all cost components when available."""
    from rich.console import Console

    cost_breakdown = _make_cost_breakdown(
        brokerage_bps=2.5,
        spread_low=1.0,
        spread_high=1.5,
        impact_low=0.5,
        impact_high=1.0,
    )
    node = _make_fund_node(cost_breakdown=cost_breakdown)
    console = Console()

    retail.render(node, console)

    captured = capsys.readouterr()
    assert "Vanguard Total Stock Market" in captured.out
    assert "VTSAX" in captured.out
    assert "Hidden Cost Breakdown" in captured.out
    assert "Brokerage Commissions" in captured.out
    assert "Bid-Ask Spread Cost" in captured.out
    assert "Market Impact Cost" in captured.out


def test_render_with_soft_dollars_active(capsys):
    """Render should flag active soft dollar arrangements."""
    from rich.console import Console

    cost_breakdown = _make_cost_breakdown(brokerage_bps=2.5)
    cost_breakdown.soft_dollar_commissions_bps = TaggedValue(
        value=None,
        tag=DataSourceTag.NOT_DISCLOSED,
        note="Soft dollars active",
    )

    node = _make_fund_node(cost_breakdown=cost_breakdown)
    console = Console()

    retail.render(node, console)

    captured = capsys.readouterr()
    assert "Soft Dollar Arrangements" in captured.out
    assert "ACTIVE" in captured.out


def test_render_handles_fund_of_funds(capsys):
    """Render should flag fund-of-funds structure."""
    from rich.console import Console

    cost_breakdown = _make_cost_breakdown(brokerage_bps=2.5)
    node = _make_fund_node(cost_breakdown=cost_breakdown)
    node.metadata.is_fund_of_funds = True
    node.nport_data.fund_holdings = [MagicMock() for _ in range(5)]

    console = Console()

    retail.render(node, console)

    captured = capsys.readouterr()
    assert "Fund-of-Funds" in captured.out
    assert "5 underlying" in captured.out


def test_render_with_data_notes(capsys):
    """Render should display data notes."""
    from rich.console import Console

    cost_breakdown = _make_cost_breakdown(brokerage_bps=2.5)
    node = _make_fund_node(cost_breakdown=cost_breakdown)
    node.data_notes = [
        "Limited holdings data available",
        "Estimated spread based on asset class",
    ]

    console = Console()

    retail.render(node, console)

    captured = capsys.readouterr()
    assert "Data Notes:" in captured.out
    assert "Limited holdings data available" in captured.out


def test_render_without_nport(capsys):
    """Render should handle missing N-PORT data gracefully."""
    from rich.console import Console

    cost_breakdown = _make_cost_breakdown(brokerage_bps=2.5)
    node = _make_fund_node(cost_breakdown=cost_breakdown, with_nport=False)

    console = Console()

    retail.render(node, console)

    captured = capsys.readouterr()
    # Should not crash, should have header and cost table
    assert "Vanguard Total Stock Market" in captured.out
    assert "Hidden Cost Breakdown" in captured.out


def test_tag_label_reported():
    """_tag_label should format REPORTED tag."""
    result = retail._tag_label(DataSourceTag.REPORTED)
    assert "SEC filing" in result


def test_tag_label_calculated():
    """_tag_label should format CALCULATED tag."""
    result = retail._tag_label(DataSourceTag.CALCULATED)
    assert "calculated" in result


def test_tag_label_estimated():
    """_tag_label should format ESTIMATED tag."""
    result = retail._tag_label(DataSourceTag.ESTIMATED)
    assert "estimated" in result


def test_tag_label_unavailable():
    """_tag_label should format UNAVAILABLE tag."""
    result = retail._tag_label(DataSourceTag.UNAVAILABLE)
    assert "unavailable" in result


def test_tag_label_not_disclosed():
    """_tag_label should format NOT_DISCLOSED tag."""
    result = retail._tag_label(DataSourceTag.NOT_DISCLOSED)
    assert "not disclosed" in result


def test_sum_costs_low_with_all_components():
    """_sum_costs_low should sum all available components."""
    cb = _make_cost_breakdown(
        brokerage_bps=2.5,
        spread_low=1.0,
        impact_low=0.5,
    )
    result = retail._sum_costs_low(cb)
    assert result == 4.0


def test_sum_costs_low_with_none_components():
    """_sum_costs_low should return None if no components available."""
    cb = CostBreakdown(ticker="TEST", fund_name="Test")
    result = retail._sum_costs_low(cb)
    assert result is None


def test_sum_costs_low_partial():
    """_sum_costs_low should sum only available components."""
    cb = _make_cost_breakdown(brokerage_bps=2.5)
    result = retail._sum_costs_low(cb)
    assert result == 2.5


def test_sum_costs_high_with_all_components():
    """_sum_costs_high should sum the high end of all components."""
    cb = _make_cost_breakdown(
        brokerage_bps=2.5,
        spread_low=1.0,
        spread_high=1.5,
        impact_low=0.5,
        impact_high=1.0,
    )
    result = retail._sum_costs_high(cb)
    assert result == 5.0  # 2.5 + 1.5 + 1.0


def test_sum_costs_high_with_none_components():
    """_sum_costs_high should return None if no components available."""
    cb = CostBreakdown(ticker="TEST", fund_name="Test")
    result = retail._sum_costs_high(cb)
    assert result is None


def test_format_dollars_billions():
    """_format_dollars should format billions correctly."""
    result = retail._format_dollars(500_000_000_000)
    assert result == "$500.0B"


def test_format_dollars_millions():
    """_format_dollars should format millions correctly."""
    result = retail._format_dollars(25_000_000)
    assert result == "$25.0M"


def test_format_dollars_thousands():
    """_format_dollars should format thousands with comma."""
    result = retail._format_dollars(10_000)
    assert result == "$10,000"


def test_format_dollars_trillions():
    """_format_dollars should format trillions correctly."""
    result = retail._format_dollars(1_200_000_000_000)
    assert result == "$1.2T"
