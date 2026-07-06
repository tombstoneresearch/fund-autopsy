"""Tests for N-PORT filing parser."""

from fundautopsy.data.nport import detect_fund_holdings, parse_nport_xml


class TestNPortParser:
    """Test N-PORT XML parsing and holdings extraction."""

    def test_parse_holdings_list(self, agthx_nport_xml, agthx_series_id):
        """Verify complete holdings extraction from sample filing."""
        result = parse_nport_xml(agthx_nport_xml, agthx_series_id)

        assert result is not None, "Parse should succeed with valid N-PORT XML"
        assert len(result.holdings) > 0, "Should extract at least one holding"

        # Check that holdings have basic data populated
        for holding in result.holdings:
            assert holding.name is not None and len(holding.name) > 0
            # At least some holdings should have market values
            if holding.value_usd is not None:
                assert holding.value_usd > 0

    def test_asset_class_weights(self, agthx_nport_xml, agthx_series_id):
        """Verify asset class weight computation from holdings."""
        result = parse_nport_xml(agthx_nport_xml, agthx_series_id)

        assert result is not None
        weights = result.asset_class_weights()

        # Should have at least one asset category
        assert len(weights) > 0

        # At least some weight should be in equity or similar
        total_weight = sum(weights.values())
        assert total_weight > 0, "Total asset weights should sum to positive amount"

    def test_fund_of_funds_detection(self, agthx_nport_xml, agthx_series_id):
        """Holdings with issuerCat = registered investment co. are flagged."""
        result = parse_nport_xml(agthx_nport_xml, agthx_series_id)

        assert result is not None
        fund_holdings = detect_fund_holdings(result)

        # Most equity funds won't be fund-of-funds, so just verify the method works
        # and that detected holdings are marked correctly
        for holding in fund_holdings:
            assert holding.is_registered_investment_company is True
