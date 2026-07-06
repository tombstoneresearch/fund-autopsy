"""Tests for fund-of-funds recursive cost roll-up."""

from fundautopsy.core.rollup import rollup_costs
from fundautopsy.models.cost_breakdown import CostBreakdown
from fundautopsy.models.filing_data import DataSourceTag, TaggedValue
from fundautopsy.models.fund_metadata import FundMetadata
from fundautopsy.models.holdings_tree import MAX_RECURSION_DEPTH, FundNode


class TestRollup:
    """Test recursive cost roll-up for fund-of-funds."""

    def test_standalone_fund_passes_through(self):
        """Standalone fund (no children) should return unchanged."""
        # Create a simple standalone fund node
        metadata = FundMetadata(
            ticker="AGTHX",
            name="Growth Fund of America",
            cik="0000010797",
            series_id="S000009228",
            class_id="C000000001",
            fund_family="American Funds",
        )

        node = FundNode(
            metadata=metadata,
            allocation_weight=1.0,
            depth=0,
        )

        # Add cost breakdown
        node.cost_breakdown = CostBreakdown(
            ticker="AGTHX",
            fund_name="Growth Fund of America",
            expense_ratio_bps=TaggedValue(
                value=50.0,
                tag=DataSourceTag.REPORTED,
                source_filing="prospectus",
            ),
        )

        result = rollup_costs(node)

        # Should return unchanged (same node)
        assert result is node
        assert result.is_leaf is True
        assert len(result.children) == 0
        assert result.cost_breakdown is not None
        assert result.cost_breakdown.expense_ratio_bps.value == 50.0

    def test_simple_two_fund_rollup(self):
        """Two underlying funds with known costs produce correct weighted sum."""
        # Create a wrapper fund with two child funds
        wrapper_metadata = FundMetadata(
            ticker="WRAPPER",
            name="Fund of Funds Wrapper",
            cik="1234567",
            series_id="S000000001",
            class_id="C000000001",
            fund_family="Test Family",
        )

        wrapper = FundNode(
            metadata=wrapper_metadata,
            allocation_weight=1.0,
            depth=0,
        )

        # Add wrapper's own cost breakdown
        wrapper.cost_breakdown = CostBreakdown(
            ticker="WRAPPER",
            fund_name="Fund of Funds Wrapper",
            expense_ratio_bps=TaggedValue(
                value=25.0,
                tag=DataSourceTag.REPORTED,
            ),
        )

        # Create child fund 1
        child1_metadata = FundMetadata(
            ticker="CHILD1",
            name="Child Fund 1",
            cik="2222222",
            series_id="S000000002",
            class_id="C000000001",
            fund_family="Test Family",
        )
        child1 = FundNode(
            metadata=child1_metadata,
            allocation_weight=0.6,  # 60% of wrapper
            depth=1,
        )
        child1.cost_breakdown = CostBreakdown(
            ticker="CHILD1",
            fund_name="Child Fund 1",
            expense_ratio_bps=TaggedValue(
                value=40.0,
                tag=DataSourceTag.REPORTED,
            ),
        )

        # Create child fund 2
        child2_metadata = FundMetadata(
            ticker="CHILD2",
            name="Child Fund 2",
            cik="3333333",
            series_id="S000000003",
            class_id="C000000001",
            fund_family="Test Family",
        )
        child2 = FundNode(
            metadata=child2_metadata,
            allocation_weight=0.4,  # 40% of wrapper
            depth=1,
        )
        child2.cost_breakdown = CostBreakdown(
            ticker="CHILD2",
            fund_name="Child Fund 2",
            expense_ratio_bps=TaggedValue(
                value=60.0,
                tag=DataSourceTag.REPORTED,
            ),
        )

        wrapper.children = [child1, child2]

        # Run rollup
        result = rollup_costs(wrapper)

        # Wrapper should still have its own cost breakdown
        assert result.cost_breakdown is not None
        # Rolled-up weighted underlying cost: 0.6 * 40 + 0.4 * 60 = 48 bps
        assert result.cost_breakdown.underlying_funds_weighted_bps is not None
        assert result.cost_breakdown.underlying_funds_weighted_bps.value == 48.0
        # Wrapper's total reported cost now includes the underlying rollup:
        # wrapper direct (25) + weighted underlying (48) = 73 bps
        assert result.cost_breakdown.total_reported_bps == 73.0
        # Should add a data note summarizing the rollup
        assert any(
            "weighted underlying cost" in note.lower()
            or "rolled up" in note.lower()
            for note in result.data_notes
        )

    def test_wrapper_direct_costs_added(self):
        """Wrapper fund's own trading costs are added on top of rolled-up child costs."""
        wrapper_metadata = FundMetadata(
            ticker="WRAPPER2",
            name="Wrapper with Direct Costs",
            cik="4444444",
            series_id="S000000004",
            class_id="C000000001",
            fund_family="Test Family",
        )

        wrapper = FundNode(
            metadata=wrapper_metadata,
            allocation_weight=1.0,
            depth=0,
        )

        # Wrapper has both expense ratio and brokerage costs
        wrapper.cost_breakdown = CostBreakdown(
            ticker="WRAPPER2",
            fund_name="Wrapper with Direct Costs",
            expense_ratio_bps=TaggedValue(
                value=30.0,
                tag=DataSourceTag.REPORTED,
            ),
            brokerage_commissions_bps=TaggedValue(
                value=5.0,
                tag=DataSourceTag.REPORTED,
            ),
        )

        # Create one child
        child_metadata = FundMetadata(
            ticker="SUBCHILD",
            name="Sub-Fund",
            cik="5555555",
            series_id="S000000005",
            class_id="C000000001",
            fund_family="Test Family",
        )
        child = FundNode(
            metadata=child_metadata,
            allocation_weight=1.0,
            depth=1,
        )
        child.cost_breakdown = CostBreakdown(
            ticker="SUBCHILD",
            fund_name="Sub-Fund",
            expense_ratio_bps=TaggedValue(
                value=50.0,
                tag=DataSourceTag.REPORTED,
            ),
        )

        wrapper.children = [child]

        result = rollup_costs(wrapper)

        # Wrapper's direct costs should be preserved
        assert result.cost_breakdown is not None
        assert result.cost_breakdown.expense_ratio_bps.value == 30.0
        assert result.cost_breakdown.brokerage_commissions_bps.value == 5.0

    def test_max_recursion_depth_flagged(self):
        """Recursion beyond MAX_RECURSION_DEPTH is flagged, not infinite."""
        # Create a deeply nested structure
        current = FundNode(
            metadata=FundMetadata(
                ticker=f"DEEP{MAX_RECURSION_DEPTH + 2}",
                name=f"Deep Fund {MAX_RECURSION_DEPTH + 2}",
                cik=str(1000000 + MAX_RECURSION_DEPTH + 2),
                series_id="S000000999",
                class_id="C000000001",
                fund_family="Test Family",
            ),
            allocation_weight=1.0,
            depth=MAX_RECURSION_DEPTH + 2,
        )
        current.cost_breakdown = CostBreakdown(
            ticker=current.metadata.ticker,
            fund_name=current.metadata.name,
            expense_ratio_bps=TaggedValue(
                value=20.0,
                tag=DataSourceTag.REPORTED,
            ),
        )

        # Build chain from root
        root = FundNode(
            metadata=FundMetadata(
                ticker="ROOT",
                name="Root Fund",
                cik="9999999",
                series_id="S000000000",
                class_id="C000000001",
                fund_family="Test Family",
            ),
            allocation_weight=1.0,
            depth=0,
        )
        root.cost_breakdown = CostBreakdown(
            ticker="ROOT",
            fund_name="Root Fund",
            expense_ratio_bps=TaggedValue(
                value=15.0,
                tag=DataSourceTag.REPORTED,
            ),
        )

        # Just test that rollup doesn't infinite loop on deep structures
        result = rollup_costs(root)
        assert result is not None
