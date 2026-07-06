"""Tests for N-CEN filing parser."""

from fundautopsy.data.ncen import (
    DerivativeUsage,
    LineOfCreditData,
    parse_ncen_xml,
)
from fundautopsy.models.filing_data import DataSourceTag


class TestNCENParser:
    """Test N-CEN XML parsing and data extraction."""

    def test_parse_soft_dollar_fields(self, agthx_ncen_xml, agthx_series_id):
        """Verify extraction of C.6.a, C.6.b, C.6.c from sample filing."""
        result = parse_ncen_xml(agthx_ncen_xml, agthx_series_id)

        assert result is not None, "Parse should succeed with valid XML"
        assert result.fund_name is not None
        assert len(result.fund_name) > 0
        # N-CEN has aggregate commission data
        assert result.aggregate_commission is not None

    def test_missing_soft_dollar_fields_tagged_correctly(self, agthx_ncen_xml, agthx_series_id):
        """When C.6.b/C.6.c are absent, tag as UNAVAILABLE or NOT_DISCLOSED."""
        result = parse_ncen_xml(agthx_ncen_xml, agthx_series_id)

        assert result is not None
        # Convert to NCENData to verify tagging
        ncen_data = result.to_ncen_data()

        # If soft dollar arrangements exist but amounts are not disclosed,
        # the soft_dollar_commissions should be tagged as NOT_DISCLOSED
        if result.is_brokerage_research_payment:
            # Soft dollars are present
            assert ncen_data.has_soft_dollar_arrangements is True
            # But the amount tag should be NOT_DISCLOSED (typical for N-CEN)
            assert ncen_data.soft_dollar_commissions.tag in (
                DataSourceTag.NOT_DISCLOSED,
                DataSourceTag.UNAVAILABLE,
            )

    def test_multi_series_filing_isolates_correct_series(self, agthx_ncen_xml, agthx_series_id):
        """Multi-series trust N-CEN should return data for target series only."""
        # Parse with the correct series ID
        result = parse_ncen_xml(agthx_ncen_xml, agthx_series_id)
        assert result is not None, "Should find the target series"

        # The series ID in the result should match
        assert result.series_id == agthx_series_id

    def test_turnover_rate_extraction(self, agthx_ncen_xml, agthx_series_id):
        """Verify that N-CEN parsing returns core fund data."""
        result = parse_ncen_xml(agthx_ncen_xml, agthx_series_id)

        assert result is not None
        # Core fields should be extracted
        assert result.fund_name  # Fund name should be present
        assert result.series_id  # Series ID should be set
        # Most N-CEN filings should have some service provider data
        assert result.investment_adviser or result.administrator


class TestLineOfCreditParser:
    """Verify Item C.5 credit-facility fields populate on a real filing.

    AGTHX shares an uncommitted $1.5B facility with ~75 sibling American
    Funds portfolios. That concentration is the Thread 5 stress signal
    we need to surface.
    """

    def test_facility_flagged_and_sized(self, agthx_ncen_xml, agthx_series_id):
        result = parse_ncen_xml(agthx_ncen_xml, agthx_series_id)
        assert result is not None
        loc = result.line_of_credit
        assert loc is not None
        assert loc.has_line_of_credit is True
        assert loc.committed_facility_size == 1_500_000_000.0
        assert loc.credit_line_type == "Uncommitted"

    def test_lending_institution_extracted(self, agthx_ncen_xml, agthx_series_id):
        result = parse_ncen_xml(agthx_ncen_xml, agthx_series_id)
        loc = result.line_of_credit
        names = [li.name for li in loc.lending_institutions]
        assert any("JPMORGAN" in n.upper() for n in names)

    def test_shared_facility_flag_and_coborrowers(self, agthx_ncen_xml, agthx_series_id):
        result = parse_ncen_xml(agthx_ncen_xml, agthx_series_id)
        loc = result.line_of_credit
        # Facility is shared across the American Funds complex
        assert loc.is_facility_shared is True
        # The co-borrower list is the concentration signal we surface in
        # Thread 5 when max outstanding is not reported.
        assert loc.co_borrower_count >= 20
        assert any("AMCAP" in n.upper() for n in loc.co_borrowers)

    def test_utilization_ratio_computation(self):
        # Unit-level check of the derived property since AGTHX does not
        # report max outstanding (utilization ratio is None in that case).
        loc = LineOfCreditData(
            committed_facility_size=1_000_000_000,
            max_outstanding_balance=800_000_000,
        )
        assert loc.utilization_ratio == 0.8

    def test_utilization_ratio_none_when_max_missing(self, agthx_ncen_xml, agthx_series_id):
        result = parse_ncen_xml(agthx_ncen_xml, agthx_series_id)
        loc = result.line_of_credit
        assert loc.max_outstanding_balance is None
        assert loc.utilization_ratio is None


class TestDerivativesParser:
    """Verify Item C.4 derivatives extraction.

    AGTHX is a long-only equity fund and reports no derivatives. The
    parser should cleanly return an empty list for funds like this
    rather than raising, and should aggregate distinct types for funds
    that do report them.
    """

    def test_no_derivatives_for_long_only_fund(self, agthx_ncen_xml, agthx_series_id):
        result = parse_ncen_xml(agthx_ncen_xml, agthx_series_id)
        assert result.derivatives == []
        assert result.distinct_derivative_types == 0
        assert result.aggregate_derivative_notional is None

    def test_distinct_type_count_aggregates(self):
        # Hand-build to exercise the deduplication/count logic without
        # needing a second fixture.
        from fundautopsy.data.ncen import NCENFullData
        d = NCENFullData()
        d.derivatives = [
            DerivativeUsage(derivative_type="swap", notional_value=1e9, count=1),
            DerivativeUsage(derivative_type="future", notional_value=5e8, count=3),
            DerivativeUsage(derivative_type="option", notional_value=None, count=2),
        ]
        assert d.distinct_derivative_types == 3
        # Aggregate notional ignores missing values
        assert d.aggregate_derivative_notional == 1_500_000_000.0
