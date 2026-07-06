"""Holdings tree structure for fund-of-funds recursive analysis."""

from __future__ import annotations

from dataclasses import dataclass, field

from fundautopsy.models.cost_breakdown import CostBreakdown
from fundautopsy.models.filing_data import NCENData, NPortData
from fundautopsy.models.fund_metadata import FundMetadata


@dataclass
class FundNode:
    """A node in the fund-of-funds holdings tree."""

    metadata: FundMetadata
    allocation_weight: float = 1.0  # 1.0 for root, proportion for children
    depth: int = 0

    # Filing data (populated in Stage 2)
    ncen_data: NCENData | None = None
    nport_data: NPortData | None = None

    # Full N-CEN data (for supplementary display: lending, brokers, etc.)
    # Typed as Any to avoid circular import with ncen.py; at runtime this is NCENFullData.
    ncen_full: object | None = None

    # Portfolio turnover from 497K prospectus (may be more reliable than N-CEN)
    prospectus_turnover: float | None = None  # As percentage, e.g. 32.0 = 32%

    # Cost data (populated in Stage 3)
    cost_breakdown: CostBreakdown | None = None

    # Children (populated if fund-of-funds)
    children: list[FundNode] = field(default_factory=list)

    # Data availability flags
    ncen_available: bool = False
    nport_available: bool = False
    data_notes: list[str] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        """True if this is a standalone fund (no underlying funds)."""
        return len(self.children) == 0

    @property
    def is_fund_of_funds(self) -> bool:
        """True if this node has underlying fund holdings."""
        return len(self.children) > 0

    def walk(self) -> list[FundNode]:
        """Iterate all nodes in the tree, depth-first."""
        nodes = [self]
        for child in self.children:
            nodes.extend(child.walk())
        return nodes

    def leaf_nodes(self) -> list[FundNode]:
        """Return only leaf (standalone fund) nodes."""
        return [n for n in self.walk() if n.is_leaf]


MAX_RECURSION_DEPTH = 3
