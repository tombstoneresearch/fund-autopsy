"""Stage 4: Fund-of-funds recursive cost roll-up.

For a wrapper (fund-of-funds) fund, the total cost seen by an investor is:

    Wrapper_Total_Cost = Wrapper_Direct_Cost + SUM(Child_Cost[i] * Weight[i])

where Weight[i] is the underlying fund's share of the FoF's aggregate
underlying-fund allocation (children sum to 1.0 within the FoF
unwindable portion).

Rollup is bottom-up: a child that is itself a fund-of-funds must be
rolled up first so that its total cost reflects its own children. The
depth of the tree is bounded by MAX_RECURSION_DEPTH enforced upstream
in core/structure.detect_structure.
"""

from __future__ import annotations

from fundautopsy.models.cost_breakdown import CostBreakdown
from fundautopsy.models.filing_data import DataSourceTag, TaggedValue
from fundautopsy.models.holdings_tree import FundNode


def rollup_costs(tree: FundNode) -> FundNode:
    """Recursively roll up underlying fund costs onto the wrapper node.

    Modifies `tree` in place and also returns it. For a leaf (standalone)
    fund, this is a no-op. For a fund-of-funds, the wrapper's
    cost_breakdown is augmented with a weighted sum of each resolved
    child's total reported cost. Unresolved children are noted in
    data_notes but do not contribute to the weighted cost — their
    absence is disclosed, not silently zeroed.

    Args:
        tree: Holdings tree with cost_breakdown populated on each node.

    Returns:
        The same tree with the root's cost_breakdown updated to include
        rolled-up underlying fund costs.
    """
    if tree.is_leaf:
        return tree

    # Process bottom-up so that a grandchild fund-of-funds is rolled up
    # into its parent before we roll the parent into this node.
    for child in tree.children:
        if child.is_fund_of_funds:
            rollup_costs(child)

    # Compute weighted underlying cost. Children's allocation_weight
    # already sums to 1.0 within the unwindable pool (see
    # core.structure._hydrate_children).
    weighted_bps: float = 0.0
    contributing_weight: float = 0.0
    contributors: list[tuple[str, float, float]] = []  # (ticker, weight, bps)
    missing_children: list[str] = []

    for child in tree.children:
        child_cost_bps = _child_total_bps(child)
        if child_cost_bps is None:
            missing_children.append(child.metadata.ticker or child.metadata.name)
            continue
        weighted_bps += child_cost_bps * child.allocation_weight
        contributing_weight += child.allocation_weight
        contributors.append((child.metadata.ticker, child.allocation_weight, child_cost_bps))

    # Ensure the wrapper has a cost_breakdown to augment.
    if tree.cost_breakdown is None:
        tree.cost_breakdown = CostBreakdown(
            ticker=tree.metadata.ticker,
            fund_name=tree.metadata.name,
        )

    # Attach the rolled-up weighted underlying cost as an explicit
    # TaggedValue on the wrapper's cost_breakdown. We use a dedicated
    # attribute so downstream reporting can distinguish the wrapper's
    # direct costs from what was absorbed through underlying funds.
    if contributors:
        # Tag as CALCULATED because this is derived from child data.
        underlying_tag = TaggedValue(
            value=weighted_bps,
            tag=DataSourceTag.CALCULATED,
            source_filing=None,
            note=_build_contributors_note(contributors, contributing_weight),
        )
        # Attach via setattr — CostBreakdown does not currently declare
        # this field, but adding it dynamically keeps the rollup
        # backwards-compatible with consumers that don't expect it.
        tree.cost_breakdown.underlying_funds_weighted_bps = underlying_tag
    else:
        tree.cost_breakdown.underlying_funds_weighted_bps = TaggedValue(
            value=None,
            tag=DataSourceTag.UNAVAILABLE,
            note="No underlying fund costs could be rolled up.",
        )

    # Surface the result in data_notes for legibility.
    if contributors:
        tree.data_notes.append(
            f"Rolled up {len(contributors)} underlying fund(s) "
            f"({contributing_weight*100:.1f}% of FoF allocation): "
            f"{weighted_bps:.1f} bps weighted underlying cost."
        )
    if missing_children:
        tree.data_notes.append(
            f"Missing cost data for {len(missing_children)} child fund(s): "
            f"{', '.join(missing_children[:5])}"
            f"{' …' if len(missing_children) > 5 else ''}."
        )

    return tree


def _child_total_bps(child: FundNode) -> float | None:
    """Best available total-reported cost for a child node, in basis points.

    Prefers total_reported_bps (expense ratio + brokerage commissions)
    when available. Falls back to expense_ratio only when that's all we
    have. Returns None when neither is available.
    """
    if child.cost_breakdown is None:
        return None
    total = child.cost_breakdown.total_reported_bps
    if total is not None:
        return total
    er = child.cost_breakdown.expense_ratio_bps
    if er is not None and er.is_available:
        return er.value
    return None


def _build_contributors_note(
    contributors: list[tuple[str, float, float]],
    total_weight: float,
) -> str:
    """Render a human-readable note enumerating the top child cost drivers."""
    # Sort by weighted contribution (weight * bps) descending
    ranked = sorted(
        contributors,
        key=lambda row: row[1] * row[2],
        reverse=True,
    )[:5]
    pieces = [
        f"{ticker or '?'} {weight*100:.1f}% × {bps:.1f}bps"
        for ticker, weight, bps in ranked
    ]
    return f"Top contributors ({total_weight*100:.1f}% weight covered): " + "; ".join(pieces)
