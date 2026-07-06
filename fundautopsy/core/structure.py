"""Stage 1b: Fund-of-funds structure detection and holdings tree construction."""

from __future__ import annotations

import logging

from fundautopsy.data.edgar import MutualFundIdentifier, resolve_holding_to_fund
from fundautopsy.data.ncen import retrieve_ncen
from fundautopsy.data.nport import detect_fund_holdings, retrieve_nport
from fundautopsy.models.filing_data import NPortData, NPortHolding
from fundautopsy.models.fund_metadata import FundMetadata
from fundautopsy.models.holdings_tree import MAX_RECURSION_DEPTH, FundNode

logger = logging.getLogger(__name__)


def detect_structure(fund: FundMetadata, depth: int = 0) -> FundNode:
    """Build a holdings tree by detecting fund-of-funds structures.

    Retrieves N-CEN and N-PORT filings, then scans N-PORT holdings
    for underlying fund positions. For the MVP, we detect fund-of-funds
    but don't recursively resolve underlying fund costs (that requires
    CUSIP-to-CIK resolution which is a Release 2+ feature).

    Args:
        fund: Fund metadata from identify_fund().
        depth: Current recursion depth (internal use).

    Returns:
        Root FundNode with filing data populated.
    """
    fund_id: MutualFundIdentifier = MutualFundIdentifier(
        ticker=fund.ticker,
        cik=int(fund.cik),
        series_id=fund.series_id,
        class_id=fund.class_id,
    )

    node: FundNode = FundNode(
        metadata=fund,
        allocation_weight=1.0,
        depth=depth,
    )

    # Retrieve N-CEN
    ncen_full = retrieve_ncen(fund_id)
    if ncen_full is not None:
        node.ncen_data = ncen_full.to_ncen_data()
        node.ncen_full = ncen_full  # Preserve full N-CEN for supplementary display
        node.ncen_available = True

        # Update fund name from N-CEN (more accurate than registrant name)
        if ncen_full.fund_name:
            fund.name = ncen_full.fund_name

        # Capture service provider info
        if ncen_full.investment_adviser:
            fund.fund_family = ncen_full.investment_adviser
    else:
        node.data_notes.append("N-CEN filing not found — brokerage commission data unavailable")

    # Retrieve N-PORT
    nport: NPortData | None = retrieve_nport(fund_id)
    if nport is not None:
        node.nport_data = nport
        node.nport_available = True

        # Update net assets from N-PORT if we got it
        if nport.total_net_assets:
            fund.total_net_assets = nport.total_net_assets

        # Detect fund-of-funds structure
        fund_holdings = detect_fund_holdings(nport)
        if fund_holdings:
            total_fund_pct: float = sum(h.pct_of_net_assets or 0 for h in fund_holdings)
            # Only classify as true fund-of-funds if underlying funds are >25% of assets.
            # Rationale: many equity funds hold small (<5%) positions in money market
            # sweep vehicles for cash management. A 25% threshold catches genuine
            # fund-of-funds structures (target-date funds, balanced funds that allocate
            # to underlying portfolios) while excluding incidental cash sweeps.
            if total_fund_pct > 25.0:
                fund.is_fund_of_funds = True
                _hydrate_children(node, fund_holdings, total_fund_pct, depth)
                resolved = len(node.children)
                unresolved = len(fund_holdings) - resolved
                node.data_notes.append(
                    f"Fund-of-funds detected: {len(fund_holdings)} underlying fund holdings "
                    f"representing ~{total_fund_pct:.1f}% of net assets. "
                    f"Resolved {resolved}/{len(fund_holdings)} to SEC CIKs for recursive unwind."
                )
                if unresolved > 0:
                    node.data_notes.append(
                        f"{unresolved} underlying holding(s) could not be resolved to a SEC "
                        "fund identifier; their costs are not yet reflected in the rollup."
                    )
            elif total_fund_pct > 0.5:
                node.data_notes.append(
                    f"Cash management: {len(fund_holdings)} registered fund holdings "
                    f"(~{total_fund_pct:.1f}% of assets, likely cash sweep vehicles)."
                )
    else:
        node.data_notes.append("N-PORT filing not found — holdings-based estimates unavailable")

    return node


def _hydrate_children(
    parent_node: FundNode,
    fund_holdings: list[NPortHolding],
    total_fund_pct: float,
    parent_depth: int,
) -> None:
    """Resolve each underlying fund holding and recurse into it.

    For every holding flagged as a registered investment company, try
    to resolve it to a SEC CIK/series via the holding name (and CUSIP
    once that resolver path is wired). When resolved, build a child
    FundMetadata, call detect_structure recursively at depth+1, and
    attach the result to parent_node.children with its allocation
    weight set to pct_of_net_assets / total_fund_pct.

    Recursion halts at MAX_RECURSION_DEPTH to prevent runaway depth on
    pathological filings.
    """
    child_depth = parent_depth + 1
    if child_depth >= MAX_RECURSION_DEPTH:
        parent_node.data_notes.append(
            f"Max recursion depth ({MAX_RECURSION_DEPTH}) reached — "
            "underlying holdings at this level not further unwound."
        )
        return

    # Guard against zero-division on total_fund_pct (shouldn't happen at
    # this point because caller checks >25.0, but belt-and-suspenders).
    if total_fund_pct <= 0:
        return

    for holding in fund_holdings:
        if holding.pct_of_net_assets is None or holding.pct_of_net_assets <= 0:
            continue

        # Attempt resolution. The N-PORT holding gives us the name and
        # sometimes the CUSIP/ISIN; the resolver decides.
        resolved_id = resolve_holding_to_fund(
            holding_name=holding.name,
            cusip=holding.cusip,
            isin=holding.isin,
        )
        if resolved_id is None:
            # Note the unresolved holding on the parent so the UI can
            # show which positions are opaque.
            parent_node.data_notes.append(
                f"Unresolved underlying fund: {holding.name!r} "
                f"({holding.pct_of_net_assets:.2f}% of NAV, CUSIP {holding.cusip or 'n/a'})."
            )
            continue

        holding.underlying_cik = str(resolved_id.cik)
        holding.underlying_ticker = resolved_id.ticker

        # Build a skeletal FundMetadata for the child. Name is taken
        # from the holding; the rest will be overwritten by the child's
        # own N-CEN parse inside detect_structure.
        child_meta = FundMetadata(
            ticker=resolved_id.ticker,
            name=holding.name,
            cik=str(resolved_id.cik),
            series_id=resolved_id.series_id,
            class_id=resolved_id.class_id,
            fund_family="",
        )

        # Allocation weight: child's share of the FoF's underlying-fund
        # pool, normalized so children sum to 1.0. This is what rollup
        # uses to compute a weighted cost.
        weight = holding.pct_of_net_assets / total_fund_pct

        try:
            child_node = detect_structure(child_meta, depth=child_depth)
            child_node.allocation_weight = weight
            parent_node.children.append(child_node)
        except Exception as exc:  # noqa: BLE001 — keep parent rollup running
            logger.warning(
                "Failed to hydrate underlying fund %s (%s): %s",
                holding.name, resolved_id.ticker, exc,
            )
            parent_node.data_notes.append(
                f"Child resolution failed for {holding.name!r}: {exc!s}"
            )
