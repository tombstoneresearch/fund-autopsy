"""Tests for the HTML export module."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from fundautopsy.export.html_export import (
    _extract_report_data,
    _format_dollars,
    _format_dollars_full,
    _render_html,
    export_html,
)
from fundautopsy.models.cost_breakdown import CostBreakdown, CostRange
from fundautopsy.models.filing_data import DataSourceTag, TaggedValue
from fundautopsy.models.fund_metadata import FundMetadata


def _make_fund_node(
    ticker="VTSAX",
    name="Vanguard Total Stock Market",
    family="Vanguard",
    net_assets=500_000_000_000,
    holdings_count=3000,
    cost_breakdown=None,
):
    """Helper to create a mock FundNode."""
    node = MagicMock()
    node.metadata = FundMetadata(
        ticker=ticker,
        name=name,
        cik="0000110296",
        series_id="S000009228",
        class_id="C0000023699",
        fund_family=family,
        is_fund_of_funds=False,
    )

    # Mock N-PORT data
    nport = MagicMock()
    nport.total_net_assets = net_assets
    nport.holdings = [MagicMock() for _ in range(holdings_count)]
    nport.fund_holdings = []
    nport.reporting_period_end = "2024-12-31"

    def mock_asset_weights():
        return {"EC": 70.0, "DBT": 25.0, "STIV": 5.0}

    nport.asset_class_weights = mock_asset_weights
    node.nport_data = nport

    # Cost breakdown
    node.cost_breakdown = cost_breakdown
    node.data_notes = []

    return node


class TestFormatDollars:
    """Tests for _format_dollars."""

    def test_format_billions(self):
        """Should format billions correctly."""
        assert _format_dollars(500_000_000_000) == "$500.0B"

    def test_format_millions(self):
        """Should format millions correctly."""
        assert _format_dollars(25_000_000) == "$25.0M"

    def test_format_thousands(self):
        """Should format thousands with comma."""
        assert _format_dollars(10_000) == "$10,000"

    def test_format_hundreds(self):
        """Should format hundreds correctly."""
        assert _format_dollars(500) == "$500"

    def test_format_trillions(self):
        """Should format trillions correctly."""
        assert _format_dollars(1_200_000_000_000) == "$1.2T"

    def test_format_zero(self):
        """Should format zero correctly."""
        assert _format_dollars(0) == "$0"

    def test_format_negative(self):
        """Should handle negative values."""
        assert _format_dollars(-500_000_000_000) == "$-500.0B"


class TestFormatDollarsFull:
    """Tests for _format_dollars_full."""

    def test_format_with_commas(self):
        """Should format with commas."""
        assert _format_dollars_full(1_000_000) == "$1,000,000"

    def test_format_thousands(self):
        """Should format thousands correctly."""
        assert _format_dollars_full(10_000) == "$10,000"

    def test_format_hundreds(self):
        """Should format hundreds correctly."""
        assert _format_dollars_full(500) == "$500"


class TestExtractReportData:
    """Tests for _extract_report_data."""

    def test_extract_basic_fund_info(self):
        """Should extract basic fund information."""
        node = _make_fund_node()
        data = _extract_report_data(node)

        assert data["ticker"] == "VTSAX"
        assert data["name"] == "Vanguard Total Stock Market"
        assert data["family"] == "Vanguard"

    def test_extract_nport_data(self):
        """Should extract N-PORT data."""
        node = _make_fund_node(net_assets=500_000_000_000, holdings_count=3000)
        data = _extract_report_data(node)

        assert data["net_assets"] == 500_000_000_000
        assert data["holdings_count"] == 3000
        assert data["period_end"] == "2024-12-31"

    def test_extract_asset_mix(self):
        """Should extract asset class weights."""
        node = _make_fund_node()
        data = _extract_report_data(node)

        assert "asset_mix" in data
        assert data["asset_mix"]["EC"] == 70.0
        assert data["asset_mix"]["DBT"] == 25.0

    def test_extract_with_no_cost_breakdown(self):
        """Should handle missing cost breakdown."""
        node = _make_fund_node(cost_breakdown=None)
        data = _extract_report_data(node)

        assert data["brokerage_bps"] is None
        assert data["total_low"] is None
        assert data["total_high"] is None

    def test_extract_with_cost_breakdown(self):
        """Should extract cost breakdown data."""
        cb = CostBreakdown(ticker="VTSAX", fund_name="Test")
        cb.brokerage_commissions_bps = TaggedValue(
            value=2.5,
            tag=DataSourceTag.REPORTED,
            note="Test",
        )
        cb.bid_ask_spread_cost = CostRange(
            low_bps=1.0,
            high_bps=1.5,
            tag=DataSourceTag.ESTIMATED,
        )
        cb.market_impact_cost = CostRange(
            low_bps=0.5,
            high_bps=1.0,
            tag=DataSourceTag.ESTIMATED,
        )

        node = _make_fund_node(cost_breakdown=cb)
        data = _extract_report_data(node)

        assert data["brokerage_bps"] == 2.5
        assert data["spread_low"] == 1.0
        assert data["spread_high"] == 1.5
        assert data["impact_low"] == 0.5
        assert data["impact_high"] == 1.0
        assert data["total_low"] == 4.0  # 2.5 + 1.0 + 0.5
        assert data["total_high"] == 5.0  # 2.5 + 1.5 + 1.0

    def test_extract_soft_dollar_flag(self):
        """Should flag active soft dollar arrangements."""
        cb = CostBreakdown(ticker="VTSAX", fund_name="Test")
        cb.soft_dollar_commissions_bps = TaggedValue(
            value=None,
            tag=DataSourceTag.NOT_DISCLOSED,
            note="Active",
        )

        node = _make_fund_node(cost_breakdown=cb)
        data = _extract_report_data(node)

        assert data["soft_dollar_active"] is True

    def test_extract_fof_flag(self):
        """Should flag fund-of-funds structure."""
        node = _make_fund_node()
        node.metadata.is_fund_of_funds = True
        data = _extract_report_data(node)

        assert data["is_fof"] is True

    def test_extract_data_notes(self):
        """Should include data notes."""
        node = _make_fund_node()
        node.data_notes = ["Note 1", "Note 2"]
        data = _extract_report_data(node)

        assert len(data["data_notes"]) == 2
        assert "Note 1" in data["data_notes"]


class TestRenderHtml:
    """Tests for _render_html."""

    def test_render_includes_fund_name_and_ticker(self):
        """Rendered HTML should include fund name and ticker."""
        data = {
            "ticker": "VTSAX",
            "name": "Vanguard Total Stock Market",
            "family": "Vanguard",
            "net_assets": 500_000_000_000,
            "holdings_count": 3000,
            "period_end": "2024-12-31",
            "asset_mix": {"EC": 70.0, "DBT": 25.0, "STIV": 5.0},
            "is_fof": False,
            "data_notes": [],
            "generated": "2024-01-15",
            "brokerage_bps": 2.5,
            "brokerage_note": None,
            "soft_dollar_active": False,
            "spread_low": 1.0,
            "spread_high": 1.5,
            "impact_low": 0.5,
            "impact_high": 1.0,
            "total_low": 4.0,
            "total_high": 5.0,
        }

        html = _render_html(data)

        assert "Vanguard Total Stock Market" in html
        assert "VTSAX" in html

    def test_render_includes_cost_breakdown_table(self):
        """Rendered HTML should include cost breakdown table."""
        data = {
            "ticker": "VTSAX",
            "name": "Vanguard Total Stock Market",
            "family": "Vanguard",
            "net_assets": 500_000_000_000,
            "holdings_count": 3000,
            "period_end": "2024-12-31",
            "asset_mix": {"EC": 70.0, "DBT": 25.0, "STIV": 5.0},
            "is_fof": False,
            "data_notes": [],
            "generated": "2024-01-15",
            "brokerage_bps": 2.5,
            "brokerage_note": None,
            "soft_dollar_active": False,
            "spread_low": 1.0,
            "spread_high": 1.5,
            "impact_low": 0.5,
            "impact_high": 1.0,
            "total_low": 4.0,
            "total_high": 5.0,
        }

        html = _render_html(data)

        assert "Brokerage Commissions" in html
        assert "Bid-Ask Spread Cost" in html
        assert "Market Impact Cost" in html
        assert "4.0 – 5.0" in html  # Total cost range

    def test_render_includes_asset_allocation(self):
        """Rendered HTML should include asset allocation section."""
        data = {
            "ticker": "VTSAX",
            "name": "Vanguard Total Stock Market",
            "family": "Vanguard",
            "net_assets": 500_000_000_000,
            "holdings_count": 3000,
            "period_end": "2024-12-31",
            "asset_mix": {"EC": 70.0, "DBT": 25.0, "STIV": 5.0},
            "is_fof": False,
            "data_notes": [],
            "generated": "2024-01-15",
            "brokerage_bps": 2.5,
            "brokerage_note": None,
            "soft_dollar_active": False,
            "spread_low": 1.0,
            "spread_high": 1.5,
            "impact_low": 0.5,
            "impact_high": 1.0,
            "total_low": 4.0,
            "total_high": 5.0,
        }

        html = _render_html(data)

        assert "Asset Allocation" in html
        assert "Equity" in html
        assert "Debt" in html
        assert "70.0%" in html

    def test_render_handles_missing_net_assets(self):
        """Rendered HTML should handle missing net assets."""
        data = {
            "ticker": "TEST",
            "name": "Test Fund",
            "family": "TestFamily",
            "net_assets": None,
            "holdings_count": 0,
            "period_end": None,
            "asset_mix": {},
            "is_fof": False,
            "data_notes": [],
            "generated": "2024-01-15",
            "brokerage_bps": None,
            "brokerage_note": None,
            "soft_dollar_active": False,
            "spread_low": None,
            "spread_high": None,
            "impact_low": None,
            "impact_high": None,
            "total_low": None,
            "total_high": None,
        }

        html = _render_html(data)

        assert "N/A" in html
        assert "TEST" in html

    def test_render_includes_tombstone_branding(self):
        """Rendered HTML should include Tombstone Research branding."""
        data = {
            "ticker": "VTSAX",
            "name": "Vanguard Total Stock Market",
            "family": "Vanguard",
            "net_assets": 500_000_000_000,
            "holdings_count": 3000,
            "period_end": "2024-12-31",
            "asset_mix": {"EC": 70.0},
            "is_fof": False,
            "data_notes": [],
            "generated": "2024-01-15",
            "brokerage_bps": 2.5,
            "brokerage_note": None,
            "soft_dollar_active": False,
            "spread_low": 1.0,
            "spread_high": 1.5,
            "impact_low": 0.5,
            "impact_high": 1.0,
            "total_low": 4.0,
            "total_high": 5.0,
        }

        html = _render_html(data)

        assert "Tombstone Research" in html
        assert "fundautopsy" in html


class TestExportHtml:
    """Tests for export_html."""

    def test_export_creates_html_file(self):
        """Export should create an HTML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "report.html"
            node = _make_fund_node()

            export_html(node, output_path)

            assert output_path.exists()

    def test_export_file_contains_fund_data(self):
        """Exported file should contain fund data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "report.html"
            node = _make_fund_node()

            export_html(node, output_path)

            content = output_path.read_text()
            assert "VTSAX" in content
            assert "Vanguard Total Stock Market" in content

    def test_export_with_cost_breakdown(self):
        """Export should include cost breakdown when available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "report.html"

            cb = CostBreakdown(ticker="VTSAX", fund_name="Test")
            cb.brokerage_commissions_bps = TaggedValue(
                value=2.5,
                tag=DataSourceTag.REPORTED,
                note="Test",
            )

            node = _make_fund_node(cost_breakdown=cb)
            export_html(node, output_path)

            content = output_path.read_text()
            assert "Brokerage Commissions" in content

    def test_export_uses_utf8_encoding(self):
        """Export should use UTF-8 encoding."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "report.html"
            node = _make_fund_node(name="Vanguard Total Stock — Market")

            export_html(node, output_path)

            # Read back and verify UTF-8 handling
            content = output_path.read_text(encoding="utf-8")
            assert "—" in content  # Em dash should be preserved
