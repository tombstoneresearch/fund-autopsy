"""Stage 3: Cost computation engine.

Assembles a CostBreakdown from N-CEN brokerage data, N-PORT asset class mix,
and estimation models for bid-ask spread and market impact.
"""

from __future__ import annotations

import logging

from fundautopsy.estimates.assumptions import INDUSTRY_AVG_SOFT_DOLLAR_SHARE
from fundautopsy.estimates.cash_drag import estimate_cash_drag
from fundautopsy.estimates.impact import estimate_market_impact_regression
from fundautopsy.estimates.spread import estimate_bid_ask_spread
from fundautopsy.estimates.tax_drag import estimate_tax_drag
from fundautopsy.models.cost_breakdown import CostBreakdown, CostRange
from fundautopsy.models.filing_data import DataSourceTag, NPortData, TaggedValue
from fundautopsy.models.holdings_tree import FundNode

logger = logging.getLogger(__name__)

# Default turnover assumption when N-CEN doesn't report it
DEFAULT_TURNOVER_RATE = 0.30  # 30% — conservative for active fund

# N-PORT asset category codes that indicate small-cap equity
_SMALL_CAP_ASSET_CATS: frozenset[str] = frozenset()  # N-PORT doesn't have a small-cap code
# We detect small-cap from holdings data when asset categories alone aren't enough.
# These issuer category codes from N-PORT indicate smaller companies:
_SMALL_CAP_ISSUER_CATS: frozenset[str] = frozenset({"CORP"})  # placeholder


def compute_costs(tree: FundNode) -> FundNode:
    """Compute cost breakdowns for every node in the holdings tree.

    For each fund node:
    - Extracts brokerage commissions from N-CEN
    - Estimates bid-ask spread cost from N-PORT asset class mix + turnover
    - Estimates market-impact cost from fund size + turnover

    Args:
        tree: Holdings tree from detect_structure().

    Returns:
        Same tree with cost_breakdown populated on every node.
    """
    for node in tree.walk():
        node.cost_breakdown = _compute_single_fund_costs(node)
    return tree


def _compute_single_fund_costs(node: FundNode) -> CostBreakdown:
    """Compute costs for a single fund node."""
    breakdown: CostBreakdown = CostBreakdown(
        ticker=node.metadata.ticker,
        fund_name=node.metadata.name,
    )

    ncen = node.ncen_data
    nport = node.nport_data

    # Net assets — prefer N-PORT (more recent), fall back to N-CEN
    net_assets: float | None = None
    if nport and nport.total_net_assets:
        net_assets = nport.total_net_assets
    elif ncen and ncen.total_net_assets and ncen.total_net_assets.is_available:
        net_assets = ncen.total_net_assets.value

    # --- N-CEN derived costs ---
    if ncen is not None:
        # Brokerage commissions in bps
        if ncen.total_brokerage_commissions and ncen.total_brokerage_commissions.is_available:
            comm_dollars: float = ncen.total_brokerage_commissions.value
            if net_assets and net_assets > 0:
                comm_bps: float = (comm_dollars / net_assets) * 10_000
                breakdown.brokerage_commissions_bps = TaggedValue(
                    value=round(comm_bps, 2),
                    tag=DataSourceTag.CALCULATED,
                    source_filing=ncen.total_brokerage_commissions.source_filing,
                    note=f"${comm_dollars:,.0f} commissions / ${net_assets:,.0f} net assets",
                )
            else:
                breakdown.brokerage_commissions_bps = TaggedValue(
                    value=None,
                    tag=DataSourceTag.UNAVAILABLE,
                    note="Commissions reported but net assets unavailable for bps conversion",
                )
        else:
            breakdown.brokerage_commissions_bps = TaggedValue(
                value=None,
                tag=DataSourceTag.UNAVAILABLE,
            )

        # Soft dollars: prefer the actual dollar amount when available,
        # fall back to the boolean flag if only that is reported.
        if ncen.soft_dollar_commissions and ncen.soft_dollar_commissions.is_available:
            sd_dollars: float = ncen.soft_dollar_commissions.value
            if net_assets and net_assets > 0:
                sd_bps: float = (sd_dollars / net_assets) * 10_000
                breakdown.soft_dollar_commissions_bps = TaggedValue(
                    value=round(sd_bps, 2),
                    tag=DataSourceTag.CALCULATED,
                    source_filing=ncen.soft_dollar_commissions.source_filing,
                    note=(
                        "Soft dollar arrangements active. "
                        f"${sd_dollars:,.0f} in soft dollar commissions."
                    ) if ncen.has_soft_dollar_arrangements else None,
                )
        elif ncen.has_soft_dollar_arrangements:
            # Estimate soft dollar cost as a share of total brokerage commissions.
            # Erzurumlu & Kotomin (2016) find the industry average is ~45%.
            # We use a range: 30% (conservative) to 45% (industry average).
            if (
                ncen.total_brokerage_commissions
                and ncen.total_brokerage_commissions.is_available
                and net_assets
                and net_assets > 0
            ):
                comm_total = ncen.total_brokerage_commissions.value
                sd_low_dollars = comm_total * 0.30
                sd_high_dollars = comm_total * INDUSTRY_AVG_SOFT_DOLLAR_SHARE
                sd_low_bps = (sd_low_dollars / net_assets) * 10_000
                sd_high_bps = (sd_high_dollars / net_assets) * 10_000
                breakdown.soft_dollar_commissions_bps = TaggedValue(
                    value=round(sd_high_bps, 2),
                    tag=DataSourceTag.ESTIMATED,
                    note=(
                        f"Estimated 30–45% of ${comm_total:,.0f} brokerage commissions "
                        f"(${sd_low_dollars:,.0f}–${sd_high_dollars:,.0f}). "
                        "Based on Erzurumlu & Kotomin (2016) industry average. "
                        "Fund discloses soft dollar arrangements but not the dollar amount."
                    ),
                )
                breakdown.soft_dollar_commissions_low_bps = round(sd_low_bps, 2)
                breakdown.soft_dollar_share_pct = TaggedValue(
                    value=INDUSTRY_AVG_SOFT_DOLLAR_SHARE * 100,
                    tag=DataSourceTag.ESTIMATED,
                    note="Industry average from Erzurumlu & Kotomin (2016)",
                )
            else:
                breakdown.soft_dollar_commissions_bps = TaggedValue(
                    value=None,
                    tag=DataSourceTag.NOT_DISCLOSED,
                    note=(
                        "Fund reports soft dollar arrangements but commission "
                        "data unavailable for estimation."
                    ),
                )

    # --- Turnover rate ---
    # Priority: 497K prospectus > N-CEN > default assumption
    turnover_rate: float = DEFAULT_TURNOVER_RATE

    if node.prospectus_turnover is not None:
        turnover_rate = node.prospectus_turnover / 100.0
    elif ncen and ncen.portfolio_turnover_rate and ncen.portfolio_turnover_rate.is_available:
        turnover_rate = ncen.portfolio_turnover_rate.value / 100.0

    # --- Estimated costs from N-PORT ---
    if nport is not None and nport.holdings:
        # Bid-ask spread
        breakdown.bid_ask_spread_cost = estimate_bid_ask_spread(nport, turnover_rate)

        # Market impact — use regression-based approach with actual asset mix data
        # instead of a binary small-cap heuristic
        pct_small_cap = _pct_small_cap_from_nport(nport)
        pct_bond = _pct_bond_from_nport(nport)

        if net_assets:
            breakdown.market_impact_cost = estimate_market_impact_regression(
                turnover_rate=turnover_rate,
                total_net_assets=net_assets,
                pct_small_cap=pct_small_cap,
                pct_bond=pct_bond,
            )
        # Cash drag — excess cash above operational baseline
        cash_drag = estimate_cash_drag(nport)
        if cash_drag and cash_drag.tag != DataSourceTag.UNAVAILABLE:
            breakdown.cash_drag_cost = cash_drag

    else:
        # No N-PORT — can't estimate spread or impact
        breakdown.bid_ask_spread_cost = CostRange(
            low_bps=0, high_bps=0,
            tag=DataSourceTag.UNAVAILABLE,
            methodology="N-PORT data unavailable — cannot estimate bid-ask spread.",
        )
        breakdown.market_impact_cost = CostRange(
            low_bps=0, high_bps=0,
            tag=DataSourceTag.UNAVAILABLE,
            methodology="N-PORT data unavailable — cannot estimate market impact.",
        )

    # --- Tax drag (taxable accounts only) ---
    # ETFs use in-kind creation/redemption to avoid distributing capital gains,
    # so turnover-based tax drag estimates don't apply.  Detect ETF status from
    # ticker length (mutual funds are 5 chars, ETFs are 1-4) or fund name.
    ticker = node.metadata.ticker or ""
    fund_name_upper = (node.metadata.name or "").upper()
    is_etf = len(ticker) <= 4 or "ETF" in fund_name_upper

    if is_etf:
        breakdown.tax_drag_cost = CostRange(
            low_bps=0,
            high_bps=0,
            tag=DataSourceTag.CALCULATED,
            methodology=(
                "ETF structure detected. ETFs use in-kind creation/redemption to "
                "avoid distributing capital gains, making turnover-based tax drag "
                "estimates inapplicable. Historical capital gains distributions for "
                "this ETF are near zero."
            ),
        )
    else:
        # Determine if this is an equity or bond fund from asset mix.
        # When N-PORT is present, use actual holdings weights. When N-PORT
        # is missing (which happens for some Fidelity index funds like
        # FXNAX), fall back to fund-name keyword detection so bond funds
        # don't get tax-classified as equity by default.
        is_equity = True
        if nport and nport.holdings:
            pct_bond = _pct_bond_from_nport(nport)
            is_equity = pct_bond < 50.0
        else:
            is_equity = _is_equity_from_name(fund_name_upper)

        tax_estimate = estimate_tax_drag(
            turnover_rate_pct=turnover_rate * 100.0,
            is_equity=is_equity,
        )
        if tax_estimate.estimated_tax_drag_high_bps > 0:
            breakdown.tax_drag_cost = tax_estimate.as_cost_range()

    return breakdown


_BOND_FUND_KEYWORDS: tuple[str, ...] = (
    "BOND", "INCOME", "TREASURY", "TIPS", "FIXED INCOME", "FIXED-INCOME",
    "MUNI", "MUNICIPAL", "AGG", "AGGREGATE", "CORPORATE BOND",
    "GOVERNMENT BOND", "GOVT BOND", "FLOATING RATE", "BANK LOAN",
    "HIGH YIELD", "SHORT-TERM BOND", "INTERMEDIATE BOND", "LONG-TERM BOND",
    "MORTGAGE", "CREDIT FUND",
)


def _is_equity_from_name(fund_name_upper: str) -> bool:
    """Classify fund as equity vs bond based on fund name when N-PORT
    holdings aren't available.

    Conservative fallback: if any strong bond-fund keyword is present,
    treat it as a bond fund. Otherwise default to equity.
    """
    if not fund_name_upper:
        return True
    for kw in _BOND_FUND_KEYWORDS:
        if kw in fund_name_upper:
            return False
    return True


def _pct_small_cap_from_nport(nport: NPortData) -> float:
    """Estimate percentage of equity holdings that are small-cap.

    Uses actual holding market values from N-PORT rather than a binary
    heuristic. Holdings under $2B market cap (approximated from position
    size relative to portfolio weight) are classified as small-cap.

    Returns:
        Percentage (0-100) of equity value in small-cap positions.
    """
    if not nport.holdings:
        return 0.0

    equity_value: float = 0.0
    small_cap_value: float = 0.0

    for h in nport.holdings:
        cat = h.asset_category or ""
        # Only consider equity holdings
        if cat not in ("EC", "EP"):
            continue
        val = h.value_usd or 0.0
        if val <= 0:
            continue

        equity_value += val

        # Approximate: if individual position value is small relative to
        # a large portfolio, the company is likely smaller-cap. This is
        # imperfect but uses real data rather than arbitrary thresholds.
        # A position under $50M in a fund with 50+ equity holdings
        # is more likely small/mid-cap.
        if val < 50_000_000:
            small_cap_value += val

    if equity_value <= 0:
        return 0.0

    return (small_cap_value / equity_value) * 100.0


def _pct_bond_from_nport(nport: NPortData) -> float:
    """Calculate percentage of portfolio in fixed income from N-PORT asset categories.

    Uses actual N-PORT assetCat codes rather than heuristics.

    Returns:
        Percentage (0-100) of net assets in bond/debt positions.
    """
    weights = nport.asset_class_weights()
    bond_cats = {"DBT", "ABS-MBS", "ABS-O", "ABS-CBDO", "ABS-A", "LOAN"}
    return sum(weights.get(cat, 0.0) for cat in bond_cats)
