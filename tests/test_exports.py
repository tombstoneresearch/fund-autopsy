"""Tests for export functionality."""

import tempfile
from datetime import date
from pathlib import Path

from fundautopsy.export.html_export import (
    _extract_report_data,
    _format_dollars,
    _format_dollars_full,
    export_html,
)
from fundautopsy.models.cost_breakdown import CostBreakdown
from fundautopsy.models.filing_data import DataSourceTag, NPortData, NPortHolding, TaggedValue
from fundautopsy.models.fund_metadata import FundMetadata
from fundautopsy.models.holdings_tree import FundNode


class TestFormatDollars:
    """Test dollar formatting utilities."""

    def test_format_small_amount(self):
        """Small amounts should format as dollars."""
        assert _format_dollars(1000) == "$1,000"
        assert _format_dollars(100000) == "$100,000"

    def test_format_millions(self):
        """Millions should format with M."""
        assert "M" in _format_dollars(1_000_000)
        assert "M" in _format_dollars(100_000_000)

    def test_format_billions(self):
        """Billions should format with B."""
        assert "B" in _format_dollars(1_000_000_000)
        assert "B" in _format_dollars(50_000_000_000)

    def test_format_trillions(self):
        """Trillions should format with T."""
        assert "T" in _format_dollars(1_000_000_000_000)

    def test_format_negative_amounts(self):
        """Negative amounts should format."""
        result = _format_dollars(-1_000_000)
        assert "-" in result or result.startswith("$-")

    def test_format_zero(self):
        """Zero should format as $0."""
        assert _format_dollars(0) == "$0"

    def test_format_dollars_full(self):
        """Full format should include all digits."""
        result = _format_dollars_full(1_234_567)
        assert "," in result
        assert "1,234,567" in result

    def test_format_dollars_full_negative(self):
        """Full format should handle negatives."""
        result = _format_dollars_full(-1000)
        assert "-" in result or result.startswith("$-")


class TestReportDataExtraction:
    """Test extraction of report data from FundNode."""

    def test_basic_fund_node_extraction(self):
        """Basic fund node should extract key data."""
        metadata = FundMetadata(
            ticker="VTSAX",
            name="Vanguard Total Stock Market Index Fund",
            cik="1000",
            series_id="S000001",
            class_id="C001",
            fund_family="Vanguard",
        )
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000001",
            total_net_assets=100_000_000_000,
            holdings=[
                NPortHolding(name="Stock 1", asset_category="EC", pct_of_net_assets=100.0),
            ],
        )
        node = FundNode(metadata=metadata, allocation_weight=1.0, depth=0)
        node.nport_data = nport

        data = _extract_report_data(node)

        assert data["ticker"] == "VTSAX"
        assert data["name"] == "Vanguard Total Stock Market Index Fund"
        assert data["net_assets"] == 100_000_000_000
        assert data["holdings_count"] == 1

    def test_data_with_cost_breakdown(self):
        """Extraction should include cost breakdown."""
        metadata = FundMetadata(
            ticker="AGTHX",
            name="Growth Fund",
            cik="1000",
            series_id="S000001",
            class_id="C001",
            fund_family="Capital Group",
        )
        node = FundNode(metadata=metadata, allocation_weight=1.0, depth=0)

        cb = CostBreakdown(ticker="AGTHX", fund_name="Growth Fund")
        cb.brokerage_commissions_bps = TaggedValue(value=5.0, tag=DataSourceTag.REPORTED)
        node.cost_breakdown = cb

        data = _extract_report_data(node)

        assert "brokerage_bps" in data

    def test_data_with_asset_mix(self):
        """Extraction should include asset allocation."""
        metadata = FundMetadata(
            ticker="VTSAX",
            name="Test Fund",
            cik="1000",
            series_id="S000001",
            class_id="C001",
            fund_family="Vanguard",
        )
        nport = NPortData(
            filing_date=date(2025, 3, 15),
            reporting_period_end=date(2024, 12, 31),
            series_id="S000001",
            total_net_assets=1_000_000,
            holdings=[
                NPortHolding(name="Large Cap", asset_category="EC", pct_of_net_assets=60.0),
                NPortHolding(name="Bond", asset_category="DBT", pct_of_net_assets=40.0),
            ],
        )
        node = FundNode(metadata=metadata, allocation_weight=1.0, depth=0)
        node.nport_data = nport

        data = _extract_report_data(node)

        assert "asset_mix" in data
        assert len(data["asset_mix"]) > 0

    def test_data_without_nport(self):
        """Extraction should handle missing N-PORT data."""
        metadata = FundMetadata(
            ticker="UNKNOWN",
            name="Unknown Fund",
            cik="1000",
            series_id="S000001",
            class_id="C001",
            fund_family="Unknown",
        )
        node = FundNode(metadata=metadata, allocation_weight=1.0, depth=0)
        # No nport_data

        data = _extract_report_data(node)

        assert data["ticker"] == "UNKNOWN"
        assert data["net_assets"] is None


class TestHTMLExport:
    """Test HTML export functionality."""

    def test_html_export_creates_file(self):
        """HTML export should create a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "report.html"

            metadata = FundMetadata(
                ticker="VTSAX",
                name="Vanguard Total Stock",
                cik="1000",
                series_id="S000001",
                class_id="C001",
                fund_family="Vanguard",
            )
            node = FundNode(metadata=metadata, allocation_weight=1.0, depth=0)

            export_html(node, output_path)

            assert output_path.exists()
            assert output_path.stat().st_size > 0

    def test_html_export_contains_fund_info(self):
        """Exported HTML should contain fund information."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "report.html"

            metadata = FundMetadata(
                ticker="AGTHX",
                name="Growth Fund of America",
                cik="1000",
                series_id="S000001",
                class_id="C001",
                fund_family="Capital Group",
            )
            node = FundNode(metadata=metadata, allocation_weight=1.0, depth=0)

            export_html(node, output_path)

            html = output_path.read_text()
            assert "AGTHX" in html
            assert "Growth Fund" in html

    def test_html_export_valid_html(self):
        """Exported HTML should be valid HTML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "report.html"

            metadata = FundMetadata(
                ticker="TEST",
                name="Test Fund",
                cik="1000",
                series_id="S000001",
                class_id="C001",
                fund_family="Test Family",
            )
            node = FundNode(metadata=metadata, allocation_weight=1.0, depth=0)

            export_html(node, output_path)

            html = output_path.read_text()
            assert "<!DOCTYPE html>" in html
            assert "<html" in html
            assert "</html>" in html
            assert "<head>" in html
            assert "<body>" in html

    def test_html_export_includes_styles(self):
        """Exported HTML should include styling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "report.html"

            metadata = FundMetadata(
                ticker="TEST",
                name="Test Fund",
                cik="1000",
                series_id="S000001",
                class_id="C001",
                fund_family="Test Family",
            )
            node = FundNode(metadata=metadata, allocation_weight=1.0, depth=0)

            export_html(node, output_path)

            html = output_path.read_text()
            assert "<style>" in html
            assert "color:" in html or "background:" in html

    def test_html_export_self_contained(self):
        """Exported HTML should be self-contained (no external resources)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "report.html"

            metadata = FundMetadata(
                ticker="TEST",
                name="Test Fund",
                cik="1000",
                series_id="S000001",
                class_id="C001",
                fund_family="Test Family",
            )
            node = FundNode(metadata=metadata, allocation_weight=1.0, depth=0)

            export_html(node, output_path)

            html = output_path.read_text()
            # Should have inline styles, not external links
            assert "<style>" in html
            # Should not have external stylesheet links (except fonts)
            assert "link rel=\"stylesheet\"" not in html or "fonts.googleapis.com" in html

    def test_html_includes_tombstone_branding(self):
        """Exported HTML should include Tombstone Research branding."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "report.html"

            metadata = FundMetadata(
                ticker="TEST",
                name="Test Fund",
                cik="1000",
                series_id="S000001",
                class_id="C001",
                fund_family="Test Family",
            )
            node = FundNode(metadata=metadata, allocation_weight=1.0, depth=0)

            export_html(node, output_path)

            html = output_path.read_text()
            assert "Tombstone Research" in html
            assert "fundautopsy" in html.lower() or "fund autopsy" in html.lower()

    def test_html_export_no_crash_without_cost_breakdown(self):
        """HTML export should work without cost breakdown."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "report.html"

            metadata = FundMetadata(
                ticker="TEST",
                name="Test Fund",
                cik="1000",
                series_id="S000001",
                class_id="C001",
                fund_family="Test Family",
            )
            node = FundNode(metadata=metadata, allocation_weight=1.0, depth=0)
            # No cost_breakdown set

            # Should not crash
            export_html(node, output_path)
            assert output_path.exists()

    def test_html_export_handles_large_numbers(self):
        """HTML export should format large AUM correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "report.html"

            metadata = FundMetadata(
                ticker="BIGFUND",
                name="Very Large Fund",
                cik="1000",
                series_id="S000001",
                class_id="C001",
                fund_family="Mega Fund Company",
            )
            nport = NPortData(
                filing_date=date(2025, 3, 15),
                reporting_period_end=date(2024, 12, 31),
                series_id="S000001",
                total_net_assets=500_000_000_000,  # $500B
                holdings=[
                    NPortHolding(name="Stock", asset_category="EC", pct_of_net_assets=100.0),
                ],
            )
            node = FundNode(metadata=metadata, allocation_weight=1.0, depth=0)
            node.nport_data = nport

            export_html(node, output_path)

            html = output_path.read_text()
            # Should include formatted large number
            assert "500" in html or "B" in html
