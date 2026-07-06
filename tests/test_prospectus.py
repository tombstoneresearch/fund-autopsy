"""Tests for the prospectus module."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from fundautopsy.data.prospectus import (
    ProspectusFees,
    _edgartools_has_fees,
    _to_float,
)


class TestProspectusFees:
    """Tests for ProspectusFees dataclass."""

    def test_expense_ratio_pct_returns_net_when_available(self):
        """expense_ratio_pct should return net_expenses if available."""
        fees = ProspectusFees(
            ticker="VTSAX",
            class_name="Investor Shares",
            total_annual_expenses=0.75,
            net_expenses=0.65,
        )
        assert fees.expense_ratio_pct == 0.65

    def test_expense_ratio_pct_falls_back_to_total(self):
        """expense_ratio_pct should return total_annual_expenses if no net."""
        fees = ProspectusFees(
            ticker="VTSAX",
            class_name="Investor Shares",
            total_annual_expenses=0.75,
            net_expenses=None,
        )
        assert fees.expense_ratio_pct == 0.75

    def test_expense_ratio_pct_returns_none_if_both_none(self):
        """expense_ratio_pct should return None if no expense data."""
        fees = ProspectusFees(
            ticker="VTSAX",
            class_name="Investor Shares",
        )
        assert fees.expense_ratio_pct is None

    def test_expense_ratio_bps_converts_to_basis_points(self):
        """expense_ratio_bps should convert percentage to basis points."""
        fees = ProspectusFees(
            ticker="VTSAX",
            class_name="Investor Shares",
            total_annual_expenses=0.75,
        )
        assert fees.expense_ratio_bps == 75.0

    def test_expense_ratio_bps_returns_none_if_no_pct(self):
        """expense_ratio_bps should return None if no expense_ratio_pct."""
        fees = ProspectusFees(
            ticker="VTSAX",
            class_name="Investor Shares",
        )
        assert fees.expense_ratio_bps is None

    def test_expense_ratio_bps_uses_net_if_available(self):
        """expense_ratio_bps should use net_expenses when available."""
        fees = ProspectusFees(
            ticker="VTSAX",
            class_name="Investor Shares",
            total_annual_expenses=0.75,
            net_expenses=0.65,
        )
        assert fees.expense_ratio_bps == 65.0


class TestEdgartoolsHasFees:
    """Tests for _edgartools_has_fees."""

    def test_returns_true_with_management_fee(self):
        """Should return True if management_fee is not None."""
        mock_class = MagicMock()
        mock_class.management_fee = 0.50
        mock_class.total_annual_expenses = None
        mock_class.net_expenses = None
        assert _edgartools_has_fees(mock_class)

    def test_returns_true_with_total_annual_expenses(self):
        """Should return True if total_annual_expenses is not None."""
        mock_class = MagicMock()
        mock_class.management_fee = None
        mock_class.total_annual_expenses = 0.75
        mock_class.net_expenses = None
        assert _edgartools_has_fees(mock_class)

    def test_returns_true_with_net_expenses(self):
        """Should return True if net_expenses is not None."""
        mock_class = MagicMock()
        mock_class.management_fee = None
        mock_class.total_annual_expenses = None
        mock_class.net_expenses = 0.65
        assert _edgartools_has_fees(mock_class)

    def test_returns_false_if_all_none(self):
        """Should return False if all fee fields are None."""
        mock_class = MagicMock()
        mock_class.management_fee = None
        mock_class.total_annual_expenses = None
        mock_class.net_expenses = None
        assert not _edgartools_has_fees(mock_class)


class TestToFloat:
    """Tests for _to_float."""

    def test_converts_float(self):
        """Should convert float to float."""
        assert _to_float(0.75) == 0.75

    def test_converts_decimal(self):
        """Should convert Decimal to float."""
        assert _to_float(Decimal("0.75")) == 0.75

    def test_converts_int(self):
        """Should convert int to float."""
        assert _to_float(75) == 75.0

    def test_converts_string_number(self):
        """Should convert numeric string to float."""
        assert _to_float("0.75") == 0.75

    def test_returns_none_for_none(self):
        """Should return None for None input."""
        assert _to_float(None) is None

    def test_returns_none_for_invalid_string(self):
        """Should return None for non-numeric string."""
        assert _to_float("not a number") is None

    def test_returns_none_for_invalid_type(self):
        """Should return None for invalid types."""
        assert _to_float([0.75]) is None
        assert _to_float({"value": 0.75}) is None


class TestRetrieveProspectusFees:
    """Tests for retrieve_prospectus_fees.

    Note: These tests are integration-heavy due to EDGAR dependencies.
    Full tests would require mocking edgar library calls.
    """

    @patch("fundautopsy.data.prospectus.edgar.find_fund")
    def test_returns_none_if_fund_not_found(self, mock_find_fund):
        """Should return None if edgar.find_fund returns None."""
        from fundautopsy.data.prospectus import retrieve_prospectus_fees

        mock_find_fund.return_value = None

        result = retrieve_prospectus_fees("NOTAFUND")
        assert result is None

    @patch("fundautopsy.data.prospectus.edgar.find_fund")
    def test_returns_none_if_no_497k_filings(self, mock_find_fund):
        """Should return None if no 497K filings found."""
        from fundautopsy.data.prospectus import retrieve_prospectus_fees

        mock_fund_class = MagicMock()
        mock_series = MagicMock()
        mock_filings = MagicMock()
        mock_k497 = MagicMock()

        mock_fund_class.series = mock_series
        mock_series.get_filings.return_value = mock_filings
        mock_filings.filter.return_value = mock_k497
        len(mock_k497) == 0  # No 497K filings

        mock_find_fund.return_value = mock_fund_class

        # Mock len() to return 0
        mock_k497.__len__.return_value = 0

        result = retrieve_prospectus_fees("VTSAX")
        assert result is None

    @patch("fundautopsy.data.prospectus.edgar.find_fund")
    def test_handles_exception_gracefully(self, mock_find_fund):
        """Should return None if any exception occurs."""
        from fundautopsy.data.prospectus import retrieve_prospectus_fees

        mock_find_fund.side_effect = Exception("EDGAR API error")

        result = retrieve_prospectus_fees("VTSAX")
        assert result is None


class TestTryEdgartoolsParser:
    """Tests for _try_edgartools_parser.

    Note: Integration tests with edgar library mocking.
    """

    @patch("fundautopsy.data.prospectus.edgar")
    def test_handles_missing_prospectus_object(self, mock_edgar):
        """Should return None if prospectus.obj() returns None."""
        from fundautopsy.data.prospectus import _try_edgartools_parser

        mock_filings = MagicMock()
        mock_filing = MagicMock()
        mock_filings.__getitem__.return_value = mock_filing
        mock_filing.obj.return_value = None

        result = _try_edgartools_parser(mock_filings, "VTSAX", None)
        assert result is None

    @patch("fundautopsy.data.prospectus.edgar")
    def test_handles_empty_share_classes(self, mock_edgar):
        """Should return None if no share classes found."""
        from fundautopsy.data.prospectus import _try_edgartools_parser

        mock_filings = MagicMock()
        mock_filing = MagicMock()
        mock_prospectus = MagicMock()

        mock_filings.__getitem__.return_value = mock_filing
        mock_filing.obj.return_value = mock_prospectus
        mock_prospectus.share_classes = []

        result = _try_edgartools_parser(mock_filings, "VTSAX", None)
        assert result is None

    @patch("fundautopsy.data.prospectus.edgar")
    def test_returns_none_if_no_fees_extracted(self, mock_edgar):
        """Should return None if edgartools didn't extract any fees."""
        from fundautopsy.data.prospectus import _try_edgartools_parser

        mock_filings = MagicMock()
        mock_filing = MagicMock()
        mock_prospectus = MagicMock()
        mock_share_class = MagicMock()

        mock_filings.__getitem__.return_value = mock_filing
        mock_filing.obj.return_value = mock_prospectus
        mock_prospectus.share_classes = [mock_share_class]
        mock_prospectus.portfolio_turnover = None

        # All fee fields None
        mock_share_class.ticker = "VTSAX"
        mock_share_class.class_name = "Investor Shares"
        mock_share_class.management_fee = None
        mock_share_class.total_annual_expenses = None
        mock_share_class.net_expenses = None
        mock_share_class.twelve_b1_fee = None
        mock_share_class.other_expenses = None
        mock_share_class.acquired_fund_fees = None
        mock_share_class.fee_waiver = None
        mock_share_class.max_sales_load = None
        mock_share_class.max_deferred_sales_load = None
        mock_share_class.redemption_fee = None

        result = _try_edgartools_parser(mock_filings, "VTSAX", None)
        assert result is None
