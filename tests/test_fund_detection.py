"""Tests for fund-of-funds detection logic."""

from datetime import date
from unittest.mock import patch

from fundautopsy.data.edgar import (
    MutualFundIdentifier,
    _normalize_fund_name,
    resolve_holding_name_to_fund,
)
from fundautopsy.data.nport import detect_fund_holdings
from fundautopsy.models.filing_data import NPortData, NPortHolding


class TestFundDetection:
    """Test identification of underlying funds in N-PORT holdings."""

    def test_registered_investment_company_flagged(self):
        """Holdings with issuerCat = RIC are identified as fund holdings."""
        # Create an N-PORT with a holding that has issuerCat = RIC
        nport = NPortData(
            filing_date=date(2024, 3, 31),
            reporting_period_end=date(2024, 3, 31),
            series_id="S000009228",
        )

        # Add a registered investment company holding
        fund_holding = NPortHolding(
            name="Vanguard Total Bond Market Fund",
            issuer_category="RIC",  # Explicitly marked as registered investment company
            pct_of_net_assets=15.0,
            value_usd=1500000.0,
        )
        nport.holdings.append(fund_holding)

        # Detect fund holdings
        detected = detect_fund_holdings(nport)

        # Should detect this as a fund
        assert len(detected) == 1
        assert detected[0].name == "Vanguard Total Bond Market Fund"
        assert detected[0].is_registered_investment_company is True

    def test_cusip_to_cik_resolution(self):
        """Holdings with issuerCat explicitly says RF are identified as funds."""
        # Test that holdings with issuerCat = RF are detected
        nport = NPortData(
            filing_date=date(2024, 3, 31),
            reporting_period_end=date(2024, 3, 31),
            series_id="S000009228",
        )

        # Add a holding with issuerCat = RF (rare but supported)
        fund_holding = NPortHolding(
            name="BlackRock iShares MSCI USA Small-Cap ETF Trust",
            issuer_category="RF",
            cusip="656560759",
            pct_of_net_assets=5.0,
            value_usd=500000.0,
        )
        nport.holdings.append(fund_holding)

        detected = detect_fund_holdings(nport)

        assert len(detected) == 1
        assert detected[0].is_registered_investment_company is True

    def test_non_fund_holdings_excluded(self):
        """Individual securities are not flagged as underlying funds."""
        nport = NPortData(
            filing_date=date(2024, 3, 31),
            reporting_period_end=date(2024, 3, 31),
            series_id="S000009228",
        )

        # Add various non-fund holdings
        stock_holding = NPortHolding(
            name="Apple Inc. Common Stock",
            issuer_category="CS",  # Common stock
            cusip="037833100",
            pct_of_net_assets=3.5,
            value_usd=350000.0,
        )

        bond_holding = NPortHolding(
            name="US Treasury Bond 2.5% due 2030",
            issuer_category="GV",  # Government debt
            cusip="912828K60",
            pct_of_net_assets=2.0,
            value_usd=200000.0,
        )

        nport.holdings.append(stock_holding)
        nport.holdings.append(bond_holding)

        detected = detect_fund_holdings(nport)

        # Neither should be flagged as funds
        assert len(detected) == 0
        assert stock_holding.is_registered_investment_company is False
        assert bond_holding.is_registered_investment_company is False


class TestHoldingResolver:
    """Verify that N-PORT holding names resolve to SEC fund identifiers.

    Name-based resolution is the cheap, pragmatic fallback that covers
    the most common fund-of-funds case: target-date funds and balanced
    funds holding sibling share classes whose ticker is embedded in the
    holding name.
    """

    def test_normalize_strips_share_class_suffix(self):
        assert _normalize_fund_name(
            "Vanguard Total Stock Market Index Fund - Investor Shares"
        ) == "vanguard total stock market index fund"
        # Parenthetical qualifiers dropped
        assert _normalize_fund_name(
            "American Funds Growth Fund (Class R-6)"
        ) == "american funds growth fund"

    def test_ticker_extracted_from_holding_name(self):
        """When a holding name embeds a ticker, the resolver matches it."""
        fake_universe = [
            {"cik": 12345, "series_id": "S000000001", "class_id": "C000000001", "ticker": "VFIAX"},
            {"cik": 67890, "series_id": "S000000002", "class_id": "C000000002", "ticker": "AGTHX"},
        ]
        with patch("fundautopsy.data.edgar._load_mf_universe", return_value=fake_universe):
            result = resolve_holding_name_to_fund("Vanguard 500 Index Fund (VFIAX)")
        assert result is not None
        assert result.ticker == "VFIAX"
        assert result.cik == 12345
        assert result.series_id == "S000000001"

    def test_returns_none_when_no_ticker_match(self):
        fake_universe = [
            {"cik": 12345, "series_id": "S000000001", "class_id": "C000000001", "ticker": "VFIAX"},
        ]
        with patch("fundautopsy.data.edgar._load_mf_universe", return_value=fake_universe):
            # No embedded ticker, and name-based match is not yet wired
            result = resolve_holding_name_to_fund("Some obscure partnership interest")
        assert result is None

    def test_returns_none_for_short_or_empty_names(self):
        assert resolve_holding_name_to_fund("") is None
        assert resolve_holding_name_to_fund("XYZ") is None
