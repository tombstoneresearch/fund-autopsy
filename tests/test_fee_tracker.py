"""Tests for the fee_tracker module."""

from __future__ import annotations

from fundautopsy.data.fee_tracker import (
    FeeChange,
    FeeHistory,
    FeeSnapshot,
    _compare_snapshots,
)


class TestFeeSnapshot:
    """Tests for FeeSnapshot dataclass."""

    def test_effective_expense_ratio_net_expenses(self):
        """effective_expense_ratio should return net_expenses if available."""
        snap = FeeSnapshot(
            filing_date="2024-01-01",
            accession_no="0000123456-24-000001",
            form_type="485BPOS",
            total_annual_expenses=0.75,
            net_expenses=0.65,  # After waivers
        )
        assert snap.effective_expense_ratio == 0.65

    def test_effective_expense_ratio_falls_back_to_total(self):
        """effective_expense_ratio should return total if no net_expenses."""
        snap = FeeSnapshot(
            filing_date="2024-01-01",
            accession_no="0000123456-24-000001",
            form_type="485BPOS",
            total_annual_expenses=0.75,
            net_expenses=None,
        )
        assert snap.effective_expense_ratio == 0.75

    def test_effective_expense_ratio_returns_none_if_both_none(self):
        """effective_expense_ratio should return None if no expense data."""
        snap = FeeSnapshot(
            filing_date="2024-01-01",
            accession_no="0000123456-24-000001",
            form_type="485BPOS",
        )
        assert snap.effective_expense_ratio is None


class TestFeeChange:
    """Tests for FeeChange dataclass."""

    def test_fee_change_increase(self):
        """FeeChange should mark increases correctly."""
        change = FeeChange(
            field_name="management_fee",
            field_label="Management Fee",
            old_value=0.50,
            new_value=0.60,
            change_bps=10.0,
            old_filing_date="2023-01-01",
            new_filing_date="2024-01-01",
            direction="increase",
        )
        assert change.direction == "increase"
        assert change.change_bps == 10.0

    def test_fee_change_decrease(self):
        """FeeChange should mark decreases correctly."""
        change = FeeChange(
            field_name="total_annual_expenses",
            field_label="Total Annual Expenses",
            old_value=0.75,
            new_value=0.70,
            change_bps=-5.0,
            old_filing_date="2023-01-01",
            new_filing_date="2024-01-01",
            direction="decrease",
        )
        assert change.direction == "decrease"


class TestFeeHistory:
    """Tests for FeeHistory dataclass."""

    def test_has_changes_empty(self):
        """has_changes should return False if no changes detected."""
        history = FeeHistory(ticker="VTSAX", cik=880869)
        assert not history.has_changes

    def test_has_changes_with_data(self):
        """has_changes should return True if changes exist."""
        change = FeeChange(
            field_name="management_fee",
            field_label="Management Fee",
            old_value=0.50,
            new_value=0.60,
            change_bps=10.0,
            old_filing_date="2023-01-01",
            new_filing_date="2024-01-01",
            direction="increase",
        )
        history = FeeHistory(ticker="VTSAX", cik=880869)
        history.changes = [change]
        assert history.has_changes

    def test_net_change_bps_empty(self):
        """net_change_bps should return 0 if no changes."""
        history = FeeHistory(ticker="VTSAX", cik=880869)
        assert history.net_change_bps == 0.0

    def test_net_change_bps_single_increase(self):
        """net_change_bps should sum increases."""
        change = FeeChange(
            field_name="management_fee",
            field_label="Management Fee",
            old_value=0.50,
            new_value=0.60,
            change_bps=10.0,
            old_filing_date="2023-01-01",
            new_filing_date="2024-01-01",
            direction="increase",
        )
        history = FeeHistory(ticker="VTSAX", cik=880869)
        history.changes = [change]
        assert history.net_change_bps == 10.0

    def test_net_change_bps_mixed_changes(self):
        """net_change_bps should net increases and decreases."""
        increase = FeeChange(
            field_name="management_fee",
            field_label="Management Fee",
            old_value=0.50,
            new_value=0.60,
            change_bps=10.0,
            old_filing_date="2023-01-01",
            new_filing_date="2023-06-01",
            direction="increase",
        )
        decrease = FeeChange(
            field_name="twelve_b1_fee",
            field_label="12b-1 Fee",
            old_value=0.25,
            new_value=0.20,
            change_bps=-5.0,
            old_filing_date="2023-06-01",
            new_filing_date="2024-01-01",
            direction="decrease",
        )
        history = FeeHistory(ticker="VTSAX", cik=880869)
        history.changes = [increase, decrease]
        assert history.net_change_bps == 5.0  # 10 - 5


class TestCompareSnapshots:
    """Tests for _compare_snapshots."""

    def test_detect_management_fee_increase(self):
        """Compare should detect management fee increases."""
        old = FeeSnapshot(
            filing_date="2023-01-01",
            accession_no="0000123456-23-000001",
            form_type="485BPOS",
            management_fee=0.50,
        )
        new = FeeSnapshot(
            filing_date="2024-01-01",
            accession_no="0000123456-24-000001",
            form_type="485BPOS",
            management_fee=0.60,
        )
        changes = _compare_snapshots(old, new)

        assert len(changes) == 1
        assert changes[0].field_name == "management_fee"
        assert changes[0].old_value == 0.50
        assert changes[0].new_value == 0.60
        assert changes[0].change_bps == 10.0
        assert changes[0].direction == "increase"

    def test_detect_management_fee_decrease(self):
        """Compare should detect management fee decreases."""
        old = FeeSnapshot(
            filing_date="2023-01-01",
            accession_no="0000123456-23-000001",
            form_type="485BPOS",
            management_fee=0.60,
        )
        new = FeeSnapshot(
            filing_date="2024-01-01",
            accession_no="0000123456-24-000001",
            form_type="485BPOS",
            management_fee=0.50,
        )
        changes = _compare_snapshots(old, new)

        assert len(changes) == 1
        assert changes[0].direction == "decrease"
        assert changes[0].change_bps == -10.0

    def test_ignore_trivial_changes(self):
        """Compare should ignore changes < 0.1 bps."""
        old = FeeSnapshot(
            filing_date="2023-01-01",
            accession_no="0000123456-23-000001",
            form_type="485BPOS",
            management_fee=0.50,
        )
        new = FeeSnapshot(
            filing_date="2024-01-01",
            accession_no="0000123456-24-000001",
            form_type="485BPOS",
            management_fee=0.5000099,  # 0.00099% change = 0.099 bps
        )
        changes = _compare_snapshots(old, new)
        assert len(changes) == 0  # Below tolerance

    def test_detect_multiple_changes(self):
        """Compare should detect changes in multiple fields."""
        old = FeeSnapshot(
            filing_date="2023-01-01",
            accession_no="0000123456-23-000001",
            form_type="485BPOS",
            management_fee=0.50,
            twelve_b1_fee=0.25,
            total_annual_expenses=0.75,
        )
        new = FeeSnapshot(
            filing_date="2024-01-01",
            accession_no="0000123456-24-000001",
            form_type="485BPOS",
            management_fee=0.60,
            twelve_b1_fee=0.20,
            total_annual_expenses=0.80,
        )
        changes = _compare_snapshots(old, new)

        assert len(changes) == 3
        field_names = [c.field_name for c in changes]
        assert "management_fee" in field_names
        assert "twelve_b1_fee" in field_names
        assert "total_annual_expenses" in field_names

    def test_ignore_none_values(self):
        """Compare should skip fields where either value is None."""
        old = FeeSnapshot(
            filing_date="2023-01-01",
            accession_no="0000123456-23-000001",
            form_type="485BPOS",
            management_fee=0.50,
            twelve_b1_fee=None,  # Not available
        )
        new = FeeSnapshot(
            filing_date="2024-01-01",
            accession_no="0000123456-24-000001",
            form_type="485BPOS",
            management_fee=0.60,
            twelve_b1_fee=0.30,  # Now available but was None
        )
        changes = _compare_snapshots(old, new)

        # Should only detect management_fee change, not 12b-1 (old was None)
        assert len(changes) == 1
        assert changes[0].field_name == "management_fee"

    def test_net_expenses_change(self):
        """Compare should detect net expense ratio changes."""
        old = FeeSnapshot(
            filing_date="2023-01-01",
            accession_no="0000123456-23-000001",
            form_type="485BPOS",
            total_annual_expenses=0.75,
            net_expenses=0.65,
        )
        new = FeeSnapshot(
            filing_date="2024-01-01",
            accession_no="0000123456-24-000001",
            form_type="485BPOS",
            total_annual_expenses=0.75,
            net_expenses=0.62,  # Waiver increased
        )
        changes = _compare_snapshots(old, new)

        # Should detect net_expenses change but not total_annual_expenses
        field_names = [c.field_name for c in changes]
        assert "net_expenses" in field_names
        assert "total_annual_expenses" not in field_names

    def test_max_sales_load_change(self):
        """Compare should detect sales load changes."""
        old = FeeSnapshot(
            filing_date="2023-01-01",
            accession_no="0000123456-23-000001",
            form_type="485BPOS",
            max_sales_load=5.50,
        )
        new = FeeSnapshot(
            filing_date="2024-01-01",
            accession_no="0000123456-24-000001",
            form_type="485BPOS",
            max_sales_load=4.75,
        )
        changes = _compare_snapshots(old, new)

        assert len(changes) == 1
        assert changes[0].field_name == "max_sales_load"
        assert changes[0].old_value == 5.50
        assert changes[0].new_value == 4.75
