"""Cost breakdown data model."""

from __future__ import annotations

from dataclasses import dataclass

from fundautopsy.models.filing_data import DataSourceTag, TaggedValue


@dataclass
class CostRange:
    """A cost estimate expressed as a range (low to high) in basis points."""

    low_bps: float
    high_bps: float
    tag: DataSourceTag
    methodology: str | None = None

    @property
    def midpoint_bps(self) -> float:
        """Midpoint of the cost range in basis points."""
        return (self.low_bps + self.high_bps) / 2

    @property
    def low_pct(self) -> float:
        """Low end of cost range as a percentage."""
        return self.low_bps / 100

    @property
    def high_pct(self) -> float:
        """High end of cost range as a percentage."""
        return self.high_bps / 100


@dataclass
class CostBreakdown:
    """Complete cost breakdown for a single fund."""

    ticker: str
    fund_name: str

    # Reported costs
    expense_ratio_bps: TaggedValue | None = None  # Net expense ratio
    management_fee_bps: TaggedValue | None = None
    twelve_b1_fee_bps: TaggedValue | None = None
    other_expenses_bps: TaggedValue | None = None

    # N-CEN derived
    brokerage_commissions_bps: TaggedValue | None = None  # C.6.a / net assets
    soft_dollar_commissions_bps: TaggedValue | None = None  # C.6.b / net assets (high estimate)
    soft_dollar_commissions_low_bps: float | None = None  # Low estimate when range-based
    soft_dollar_share_pct: TaggedValue | None = None  # C.6.b / C.6.a

    # Estimated costs
    bid_ask_spread_cost: CostRange | None = None
    market_impact_cost: CostRange | None = None
    cash_drag_cost: CostRange | None = None
    tax_drag_cost: CostRange | None = None  # Taxable accounts only

    # Fund-of-funds roll-up — weighted underlying fund total cost in bps.
    # Populated by core.rollup.rollup_costs when this node has children.
    underlying_funds_weighted_bps: TaggedValue | None = None

    # Composite
    @property
    def total_reported_bps(self) -> float | None:
        """Expense ratio + brokerage commissions + rolled-up underlying costs.

        Returns whatever reported cost data is available. If only brokerage
        commissions exist (no prospectus ER), those are still real costs
        that should be surfaced rather than returning None. For a
        fund-of-funds wrapper, the weighted underlying fund cost is
        included so callers see the total cost of ownership, not just
        the wrapper's direct costs.
        """
        er = (
            self.expense_ratio_bps.value
            if self.expense_ratio_bps and self.expense_ratio_bps.is_available else None
        )
        bc = (
            self.brokerage_commissions_bps.value
            if self.brokerage_commissions_bps and self.brokerage_commissions_bps.is_available else None
        )
        uf = (
            self.underlying_funds_weighted_bps.value
            if self.underlying_funds_weighted_bps and self.underlying_funds_weighted_bps.is_available else None
        )
        if er is None and bc is None and uf is None:
            return None
        return (er or 0) + (bc or 0) + (uf or 0)

    @property
    def total_estimated_low_bps(self) -> float | None:
        """Total reported + low end of estimated costs."""
        reported = self.total_reported_bps
        if reported is None:
            return None
        spread_low = self.bid_ask_spread_cost.low_bps if self.bid_ask_spread_cost else 0
        impact_low = self.market_impact_cost.low_bps if self.market_impact_cost else 0
        return reported + spread_low + impact_low

    @property
    def total_estimated_high_bps(self) -> float | None:
        """Total reported + high end of estimated costs."""
        reported = self.total_reported_bps
        if reported is None:
            return None
        spread_high = self.bid_ask_spread_cost.high_bps if self.bid_ask_spread_cost else 0
        impact_high = self.market_impact_cost.high_bps if self.market_impact_cost else 0
        return reported + spread_high + impact_high

    @property
    def hidden_cost_gap_bps(self) -> tuple[float, float] | None:
        """The gap between stated expense ratio and estimated total cost."""
        er = self.expense_ratio_bps.value if self.expense_ratio_bps and self.expense_ratio_bps.is_available else None
        low = self.total_estimated_low_bps
        high = self.total_estimated_high_bps
        if er is not None and low is not None and high is not None:
            return (low - er, high - er)
        return None
