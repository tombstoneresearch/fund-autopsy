"""Fund Autopsy web API — real-time fund cost analysis.

Run with: python -m fundautopsy.web
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fundautopsy.config import CORS_ALLOWED_ORIGINS
from fundautopsy.models.filing_data import DataSourceTag
from fundautopsy.data.edgar import reset_edgar_health, get_edgar_health
from fundautopsy.data.leaderboard import (
    update_leaderboard, get_leaderboard, get_leaderboard_stats,
)
from fundautopsy.data.fee_tracker import track_fee_changes, FeeHistory
from fundautopsy.data.ncsr_parser import parse_ncsr_for_cik

app = FastAPI(title="Fund Autopsy", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Mount static files (CSS, JS, and related assets)
import os
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")


class CostComponent(BaseModel):
    """A single cost component in the fund's cost breakdown.

    applies_to distinguishes costs that drag ANY account ("all") from
    costs that only apply in a taxable brokerage account ("taxable_only").
    Tax drag is taxable-only; everything else is all-accounts.
    """

    label: str
    value: Optional[str]
    low: Optional[float] = None
    high: Optional[float] = None
    tag: str
    note: Optional[str] = None
    applies_to: str = "all"  # "all" or "taxable_only"


class FeeComponent(BaseModel):
    """Fee component expressed as percentage and basis points."""

    label: str
    pct: Optional[float]
    bps: Optional[float]


class AssetMix(BaseModel):
    """Asset class allocation data."""

    category: str
    label: str
    color: str
    pct: float


class UnderlyingFund(BaseModel):
    """A single underlying fund holding inside a fund-of-funds.

    Populated for target-date, balanced-allocation, and ETF-of-ETFs
    wrappers. The frontend renders these as a composition pie so
    investors can see the funds hidden behind their one ticker.
    The `resolved_*` fields indicate whether we were able to walk
    into that holding's own filings for recursive cost unwinding;
    they remain null when the holding name or CUSIP hasn't been
    resolved to a SEC identifier (which is the common case for
    iShares and BlackRock ETFs today).
    """

    name: str
    pct_of_net_assets: float
    cusip: Optional[str] = None
    isin: Optional[str] = None
    color: str
    resolved_ticker: Optional[str] = None
    resolved_cik: Optional[str] = None


class BrokerInfo(BaseModel):
    """Broker commission data."""

    name: str
    commission: float
    is_affiliated: bool


class SecuritiesLendingInfo(BaseModel):
    """Securities lending arrangement details."""

    is_lending: bool
    agent_name: Optional[str] = None
    is_agent_affiliated: bool = False
    net_income: Optional[float] = None
    avg_value_on_loan: Optional[float] = None


class ServiceProviders(BaseModel):
    """Key service providers for the fund."""

    adviser: Optional[str] = None
    administrator: Optional[str] = None
    custodian: Optional[str] = None
    transfer_agent: Optional[str] = None
    auditor: Optional[str] = None
    is_admin_affiliated: bool = False
    is_transfer_agent_affiliated: bool = False


class DollarImpact(BaseModel):
    """Dollar impact of costs over an investment horizon."""

    investment: float
    horizon_years: int
    assumed_return_pct: float
    expense_ratio_only_cost: Optional[float]
    true_cost_low: Optional[float]
    true_cost_high: Optional[float]
    hidden_cost_low: Optional[float]
    hidden_cost_high: Optional[float]
    final_value_er_only: Optional[float]
    final_value_true_low: Optional[float]
    final_value_true_high: Optional[float]


class FundAnalysis(BaseModel):
    """Complete fund analysis response with all cost data."""
    ticker: str
    name: str
    family: str
    share_class: Optional[str] = None
    net_assets: Optional[float]
    net_assets_display: str
    holdings_count: int
    period_end: Optional[str]
    is_fund_of_funds: bool

    # Expense ratio from prospectus
    expense_ratio_pct: Optional[float] = None
    expense_ratio_bps: Optional[float] = None
    fee_breakdown: List[FeeComponent] = []
    portfolio_turnover: Optional[float] = None
    max_sales_load: Optional[float] = None

    # Hidden costs
    costs: List[CostComponent]
    # total_hidden is the "applies to ANY account" rollup — bid-ask, impact,
    # commissions, soft dollars, cash drag. This is the headline hidden-cost
    # number and is what true_cost_low/high_bps uses.
    total_hidden_low: Optional[float]
    total_hidden_high: Optional[float]

    # Separate tax drag bucket. Only applies to taxable brokerage accounts;
    # in IRAs, 401(k)s, and other tax-deferred accounts this is zero.
    total_tax_low: Optional[float] = None
    total_tax_high: Optional[float] = None

    # True total cost = ER + hidden (tax-deferred view, default headline)
    true_cost_low_bps: Optional[float] = None
    true_cost_high_bps: Optional[float] = None
    true_cost_low_pct: Optional[float] = None
    true_cost_high_pct: Optional[float] = None

    # True total cost in a TAXABLE account = ER + hidden + tax drag
    true_cost_taxable_low_bps: Optional[float] = None
    true_cost_taxable_high_bps: Optional[float] = None

    # Dollar impact
    dollar_impact: Optional[DollarImpact] = None

    # N-CEN supplementary data
    top_brokers: List[BrokerInfo] = []
    affiliated_brokers: List[BrokerInfo] = []
    securities_lending: Optional[SecuritiesLendingInfo] = None
    service_providers: Optional[ServiceProviders] = None
    aggregate_commission_dollars: Optional[float] = None

    asset_mix: List[AssetMix]
    # Underlying fund composition — populated for fund-of-funds
    # (target-date, allocation, ETF-of-ETFs). Empty for direct-holding
    # funds. The frontend renders these as a pie chart so investors
    # see the 4-9 funds hidden behind one ticker.
    underlying_funds: List[UnderlyingFund] = []
    conflict_flags: List[str] = []
    # Affiliated-broker commission concentration — the share of total
    # brokerage commissions that went to broker-dealers affiliated with
    # the fund adviser. A structural signal of conflict intensity that
    # investors currently have no way to see without reading the SAI.
    # Zero for single-firm advisers with no affiliated broker; can run
    # above 50% for large integrated asset managers (Fidelity, Charles
    # Schwab) that execute through their own brokerage arms.
    affiliated_commission_pct: Optional[float] = None
    affiliated_commission_dollars: Optional[float] = None
    # Soft-dollar subsidy estimate, computed from N-CEN + SAI when
    # both are available. Dollars of commission paying for research
    # the adviser would otherwise pay out of pocket. Tagged as
    # estimate to distinguish from directly-reported figures.
    soft_dollar_subsidy_estimate_dollars: Optional[float] = None
    soft_dollar_subsidy_estimate_bps: Optional[float] = None
    data_notes: List[str]
    edgar_status: Optional[str] = None  # "ok" | "degraded" — subtle flakiness indicator
    generated: str


ASSET_CAT_META = {
    "EC": ("Equity", "#4ade80"),
    "EP": ("Preferred", "#a78bfa"),
    "DBT": ("Debt", "#60a5fa"),
    "STIV": ("Cash/STIV", "#fbbf24"),
    "OTHER": ("Other", "#94a3b8"),
}

# Well-known ETF and common-confusion tickers. A user who types any of
# these instead of a mutual fund ticker gets a specific error message
# rather than a generic 404. Keeping this list centralized so every
# ticker-accepting endpoint can use the same detection.
_KNOWN_ETF_TICKERS: frozenset[str] = frozenset({
    "SPY", "QQQ", "VTI", "VOO", "IVV", "VEA", "VWO", "BND",
    "AGG", "IEFA", "IEMG", "IJH", "IJR", "VUG", "VTV", "VGT",
    "VNQ", "ARKK", "SOXX", "XLK", "XLF", "XLE", "XLV", "XLI",
    "TQQQ", "SQQQ", "GLD", "SLV", "TLT", "IEF", "SHY",
    "DIA", "IWM", "EFA", "EEM", "VIG", "VYM", "SCHD", "JEPI",
    "JEPQ", "BIL", "SHV", "USFR", "MUB", "VTEB", "BSV", "VCIT",
    "VCSH", "LQD", "HYG", "EMB", "FXI", "EWJ", "EWZ", "INDA",
    "MCHI", "VXUS", "VT", "AOR", "AOM", "AOA", "BIV", "BLV",
})

_KNOWN_STOCKS: frozenset[str] = frozenset({
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META",
    "TSLA", "BRK", "BRKB", "UNH", "JNJ", "XOM", "JPM", "V",
    "MA", "WMT", "PG", "HD", "BAC", "DIS", "NFLX", "CRM",
})


def _resolve_or_explain(ticker: str):
    """Resolve a ticker to a fund, or raise an explicit HTTPException.

    Provides graceful error paths for common user mistakes with
    structured error codes so the frontend can render targeted help
    rather than a generic "internal error." Error codes surfaced in
    the HTTPException detail for client consumption:

      ERR_ETF_NOT_SUPPORTED   — 422; suggest mutual fund alternatives
      ERR_STOCK_NOT_FUND      — 422; recipient is a stock not a fund
      ERR_FUND_NAME_NOT_TICKER — 404; input looks like a name; suggest tickers
      ERR_FUND_NOT_FOUND      — 404; cannot resolve; may suggest similar names
    """
    from fundautopsy.core.fund import identify_fund as _identify
    from fundautopsy.data.fund_aliases import suggest_for_failed_ticker

    t = ticker.upper().strip()
    if t in _KNOWN_ETF_TICKERS:
        raise HTTPException(
            422,
            {
                "code": "ERR_ETF_NOT_SUPPORTED",
                "message": (
                    f"{t} is an exchange-traded fund (ETF). Fund Autopsy "
                    f"currently covers open-end mutual funds only — ETFs "
                    f"file under a different SEC disclosure regime and "
                    f"are on the roadmap."
                ),
                "suggestions": [
                    {"ticker": "VFIAX", "name": "Vanguard 500 Index Fund Admiral"},
                    {"ticker": "FXAIX", "name": "Fidelity 500 Index Fund"},
                    {"ticker": "AGTHX", "name": "American Funds Growth Fund of America"},
                ],
            },
        )
    if t in _KNOWN_STOCKS:
        raise HTTPException(
            422,
            {
                "code": "ERR_STOCK_NOT_FUND",
                "message": (
                    f"{t} is a publicly-traded stock, not a mutual fund. "
                    f"Fund Autopsy analyzes mutual funds only."
                ),
                "suggestions": [
                    {"ticker": "VFIAX", "name": "Vanguard 500 Index Fund Admiral"},
                    {"ticker": "FXAIX", "name": "Fidelity 500 Index Fund"},
                ],
            },
        )
    try:
        return _identify(ticker)
    except ValueError as exc:
        # Graceful name-vs-ticker distinction: if the input matches a
        # known fund-name alias, tell the user which ticker to try.
        suggestions = suggest_for_failed_ticker(ticker, limit=5)
        if suggestions:
            primary = suggestions[0]
            raise HTTPException(
                404,
                {
                    "code": "ERR_FUND_NAME_NOT_TICKER",
                    "message": (
                        f"'{ticker}' looks like a fund name, not a ticker. "
                        f"Try '{primary['ticker']}' ({primary['name']}) "
                        f"instead."
                    ),
                    "suggestions": suggestions,
                },
            )
        raise HTTPException(
            404,
            {
                "code": "ERR_FUND_NOT_FOUND",
                "message": str(exc),
                "suggestions": [],
            },
        )


def _fmt_dollars(amount: float) -> str:
    if abs(amount) >= 1e12:
        return f"${amount / 1e12:.1f}T"
    if abs(amount) >= 1e9:
        return f"${amount / 1e9:.1f}B"
    if abs(amount) >= 1e6:
        return f"${amount / 1e6:.1f}M"
    return f"${amount:,.0f}"


def compute_affiliated_concentration(
    affiliated_brokers: list,
    aggregate_commission: Optional[float],
) -> tuple[Optional[float], Optional[float]]:
    """Return (affiliated_dollars, affiliated_percent) from N-CEN data.

    Pulled out of the /api/analyze handler so it can be unit-tested
    without spinning up FastAPI or the full pipeline. Both outputs
    are None when either (a) there are no affiliated brokers in the
    N-CEN or (b) aggregate commission data is missing or zero.

    Args:
        affiliated_brokers: list of BrokerRecord-like objects with a
            gross_commission attribute.
        aggregate_commission: total broker commissions paid by the
            fund during the N-CEN reporting period.

    Returns:
        (affiliated_commission_dollars, affiliated_commission_pct)
    """
    if not affiliated_brokers:
        return (0.0, 0.0)
    aff_total = sum(b.gross_commission for b in affiliated_brokers)
    if aggregate_commission and aggregate_commission > 0:
        aff_pct = aff_total / aggregate_commission * 100
        return (aff_total, aff_pct)
    return (aff_total, None)


def compute_soft_dollar_subsidy(
    commissions: list,
    net_assets: Optional[float],
    years_to_average: int = 3,
) -> tuple[Optional[float], Optional[float], Optional[int], int]:
    """Compute soft-dollar subsidy estimate from SAI commission data.

    Extracted from /api/sai handler so it can be exercised without
    network. Takes the three most recent years (by default) of SAI
    disclosed research commissions, averages them, and converts to
    basis points against the fund's net assets.

    Args:
        commissions: list of BrokerageCommissions-like objects each
            carrying a `soft_dollar_commissions: dict[int, float]`
            mapping year to dollar amount.
        net_assets: fund net assets from N-PORT.
        years_to_average: max years to include in the average.

    Returns:
        (dollars, bps, most_recent_year, years_averaged)
        — dollars is None when no SAI soft-dollar data is present
        — bps is None when net_assets is not available
        — most_recent_year is None when no data
        — years_averaged is 0 when no data
    """
    recent_total = 0.0
    recent_year: Optional[int] = None
    years_averaged = 0
    for bc in commissions:
        if not getattr(bc, "soft_dollar_commissions", None):
            continue
        years_sorted = sorted(bc.soft_dollar_commissions.keys(), reverse=True)
        take = years_sorted[:years_to_average]
        if take:
            avg = sum(bc.soft_dollar_commissions[y] for y in take) / len(take)
            recent_total += avg
            years_averaged = max(years_averaged, len(take))
        if recent_year is None or years_sorted[0] > recent_year:
            recent_year = years_sorted[0]
    if recent_total == 0 and years_averaged == 0:
        return (None, None, None, 0)
    bps: Optional[float] = None
    if net_assets and net_assets > 0:
        bps = round(recent_total / net_assets * 10_000, 2)
    return (recent_total, bps, recent_year, years_averaged)


def _compute_dollar_impact(
    expense_ratio_pct: Optional[float],
    hidden_low_bps: Optional[float],
    hidden_high_bps: Optional[float],
    investment: Optional[float] = None,
    horizon: Optional[int] = None,
    annual_return: Optional[float] = None,
) -> DollarImpact:
    """Compute dollar cost of fees over time using compound drag."""
    from fundautopsy.config import DEFAULT_INVESTMENT, DEFAULT_HORIZON_YEARS, DEFAULT_ANNUAL_RETURN_PCT

    investment = investment if investment is not None else DEFAULT_INVESTMENT
    horizon = horizon if horizon is not None else DEFAULT_HORIZON_YEARS
    annual_return = annual_return if annual_return is not None else DEFAULT_ANNUAL_RETURN_PCT
    gross_return = annual_return / 100

    # ER-only scenario
    er_only_cost = None
    final_er_only = None
    if expense_ratio_pct is not None:
        er_drag = expense_ratio_pct / 100
        final_er_only = investment * ((1 + gross_return - er_drag) ** horizon)
        no_cost_final = investment * ((1 + gross_return) ** horizon)
        er_only_cost = no_cost_final - final_er_only

    # True cost scenarios (ER + hidden costs combined)
    # "best case" = lowest drag estimate; "worst case" = highest drag estimate
    cost_best_case = None
    cost_worst_case = None
    hidden_cost_best = None
    hidden_cost_worst = None
    final_value_best_case = None
    final_value_worst_case = None

    no_cost_final = investment * ((1 + gross_return) ** horizon)

    if expense_ratio_pct is not None and hidden_low_bps is not None:
        # Convert to decimal drag: pct / 100, bps / 10_000
        drag_best = expense_ratio_pct / 100 + hidden_low_bps / 10_000
        drag_worst = expense_ratio_pct / 100 + hidden_high_bps / 10_000

        # Higher drag produces lower final value
        final_value_worst_case = investment * ((1 + gross_return - drag_worst) ** horizon)
        final_value_best_case = investment * ((1 + gross_return - drag_best) ** horizon)

        # Dollar cost = what you lose vs. zero-cost scenario
        cost_best_case = no_cost_final - final_value_best_case
        cost_worst_case = no_cost_final - final_value_worst_case
        if er_only_cost is not None:
            hidden_cost_best = cost_best_case - er_only_cost
            hidden_cost_worst = cost_worst_case - er_only_cost

    return DollarImpact(
        investment=investment,
        horizon_years=horizon,
        assumed_return_pct=annual_return,
        expense_ratio_only_cost=round(er_only_cost) if er_only_cost else None,
        true_cost_low=round(cost_best_case) if cost_best_case else None,
        true_cost_high=round(cost_worst_case) if cost_worst_case else None,
        hidden_cost_low=round(hidden_cost_best) if hidden_cost_best else None,
        hidden_cost_high=round(hidden_cost_worst) if hidden_cost_worst else None,
        final_value_er_only=round(final_er_only) if final_er_only else None,
        final_value_true_low=round(final_value_best_case) if final_value_best_case else None,
        final_value_true_high=round(final_value_worst_case) if final_value_worst_case else None,
    )


@app.get("/api/analyze/{ticker}", response_model=FundAnalysis)
def analyze_fund(ticker: str):
    """Run the full Fund Autopsy pipeline on a ticker and return structured results."""
    ticker = ticker.strip().upper()
    if not ticker or not ticker.isalpha() or len(ticker) > 6:
        raise HTTPException(400, "Invalid ticker format")

    reset_edgar_health()

    try:
        from fundautopsy.core.fund import identify_fund
        from fundautopsy.core.structure import detect_structure
        from fundautopsy.core.costs import compute_costs
        from fundautopsy.core.rollup import rollup_costs
        from fundautopsy.data.prospectus import retrieve_prospectus_fees as _get_fees

        try:
            fund = identify_fund(ticker)
        except ValueError as e:
            # Graceful ETF + common non-mutual-fund handling. A user
            # typing SPY, QQQ, VTI, or a stock ticker should see a
            # specific message rather than a generic "not found" 404.
            etfs_known = {
                "SPY", "QQQ", "VTI", "VOO", "IVV", "VEA", "VWO", "BND",
                "AGG", "IEFA", "IEMG", "IJH", "IJR", "VUG", "VTV", "VGT",
                "VNQ", "ARKK", "SOXX", "XLK", "XLF", "XLE", "XLV", "XLI",
                "TQQQ", "SQQQ", "GLD", "SLV", "TLT", "IEF", "SHY",
            }
            t = ticker.upper()
            if t in etfs_known:
                raise HTTPException(
                    422,
                    f"{t} is an exchange-traded fund (ETF). Fund Autopsy "
                    f"currently covers open-end mutual funds only — ETFs "
                    f"use a different SEC disclosure regime (N-CSR(S), "
                    f"SCHEDULE 13G, etc.) and are on the roadmap. Try a "
                    f"mutual fund ticker instead (examples: VFIAX, FXAIX, "
                    f"AGTHX, DODGX).",
                )
            raise HTTPException(404, str(e))
        tree = detect_structure(fund)

        # Fetch prospectus data early so turnover feeds into cost estimates
        _prospectus_fees = None
        try:
            _prospectus_fees = _get_fees(
                ticker, series_id=fund.series_id, class_id=fund.class_id
            )
            if _prospectus_fees and _prospectus_fees.portfolio_turnover is not None:
                tree.prospectus_turnover = _prospectus_fees.portfolio_turnover
        except Exception as exc:
            logger.warning("Prospectus fetch failed for %s: %s", ticker, exc)

        tree = compute_costs(tree)
        tree = rollup_costs(tree)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.exception("Analysis failed for %s", ticker)
        raise HTTPException(500, "Analysis failed due to an internal error")

    cb = tree.cost_breakdown
    nport = tree.nport_data
    meta = tree.metadata

    # --- Prospectus fee data (already fetched above for turnover) ---
    prospectus_fees = _prospectus_fees

    expense_ratio_pct = None
    expense_ratio_bps = None
    fee_breakdown = []
    portfolio_turnover = None
    max_sales_load = None
    share_class = None

    if prospectus_fees:
        expense_ratio_pct = prospectus_fees.expense_ratio_pct
        expense_ratio_bps = prospectus_fees.expense_ratio_bps
        share_class = prospectus_fees.class_name
        portfolio_turnover = prospectus_fees.portfolio_turnover
        max_sales_load = prospectus_fees.max_sales_load

        if prospectus_fees.management_fee is not None:
            fee_breakdown.append(FeeComponent(
                label="Management Fee",
                pct=prospectus_fees.management_fee,
                bps=prospectus_fees.management_fee * 100,
            ))
        if prospectus_fees.twelve_b1_fee is not None:
            fee_breakdown.append(FeeComponent(
                label="12b-1 Fee",
                pct=prospectus_fees.twelve_b1_fee,
                bps=prospectus_fees.twelve_b1_fee * 100,
            ))
        if prospectus_fees.other_expenses is not None:
            fee_breakdown.append(FeeComponent(
                label="Other Expenses",
                pct=prospectus_fees.other_expenses,
                bps=prospectus_fees.other_expenses * 100,
            ))
        if prospectus_fees.acquired_fund_fees is not None:
            fee_breakdown.append(FeeComponent(
                label="Acquired Fund Fees",
                pct=prospectus_fees.acquired_fund_fees,
                bps=prospectus_fees.acquired_fund_fees * 100,
            ))

    # --- Build hidden cost components ---
    costs = []

    if cb:
        # Brokerage
        if cb.brokerage_commissions_bps and cb.brokerage_commissions_bps.is_available:
            costs.append(CostComponent(
                label="Brokerage Commissions",
                value=f"{cb.brokerage_commissions_bps.value:.2f}",
                low=cb.brokerage_commissions_bps.value,
                high=cb.brokerage_commissions_bps.value,
                tag="reported",
                note=cb.brokerage_commissions_bps.note,
            ))
        else:
            costs.append(CostComponent(
                label="Brokerage Commissions", value=None, tag="unavailable"
            ))

        # Soft dollars
        if cb.soft_dollar_commissions_bps:
            sd = cb.soft_dollar_commissions_bps
            if sd.tag == DataSourceTag.ESTIMATED and sd.value is not None:
                sd_low = cb.soft_dollar_commissions_low_bps or 0
                sd_high = sd.value
                costs.append(CostComponent(
                    label="Soft Dollar Cost",
                    value=f"{sd_low:.1f} – {sd_high:.1f}",
                    low=sd_low,
                    high=sd_high,
                    tag="estimated",
                    note=sd.note,
                ))
            elif sd.tag == DataSourceTag.CALCULATED and sd.value is not None:
                costs.append(CostComponent(
                    label="Soft Dollar Commissions",
                    value=f"{sd.value:.1f}",
                    low=sd.value,
                    high=sd.value,
                    tag="reported",
                    note=sd.note,
                ))
            elif sd.tag == DataSourceTag.NOT_DISCLOSED:
                costs.append(CostComponent(
                    label="Soft Dollar Arrangements",
                    value="ACTIVE",
                    tag="warning",
                    note="Fund uses client commissions to pay for research. Dollar amount not disclosed.",
                ))

        # Spread
        if cb.bid_ask_spread_cost and cb.bid_ask_spread_cost.tag != DataSourceTag.UNAVAILABLE:
            costs.append(CostComponent(
                label="Bid-Ask Spread Cost",
                value=f"{cb.bid_ask_spread_cost.low_bps:.1f} – {cb.bid_ask_spread_cost.high_bps:.1f}",
                low=cb.bid_ask_spread_cost.low_bps,
                high=cb.bid_ask_spread_cost.high_bps,
                tag="estimated",
            ))

        # Impact
        if cb.market_impact_cost and cb.market_impact_cost.tag != DataSourceTag.UNAVAILABLE:
            costs.append(CostComponent(
                label="Market Impact Cost",
                value=f"{cb.market_impact_cost.low_bps:.1f} – {cb.market_impact_cost.high_bps:.1f}",
                low=cb.market_impact_cost.low_bps,
                high=cb.market_impact_cost.high_bps,
                tag="estimated",
            ))

        # Cash drag
        if cb.cash_drag_cost and cb.cash_drag_cost.tag != DataSourceTag.UNAVAILABLE and cb.cash_drag_cost.high_bps > 0:
            costs.append(CostComponent(
                label="Cash Drag",
                value=f"{cb.cash_drag_cost.low_bps:.1f} – {cb.cash_drag_cost.high_bps:.1f}",
                low=cb.cash_drag_cost.low_bps,
                high=cb.cash_drag_cost.high_bps,
                tag="estimated",
                note=cb.cash_drag_cost.methodology,
            ))

        # Tax drag (taxable accounts only). Tagged applies_to="taxable_only"
        # so the frontend and the rollup can separate it from hidden costs
        # that affect every account regardless of wrapper.
        if cb.tax_drag_cost and cb.tax_drag_cost.tag != DataSourceTag.UNAVAILABLE and cb.tax_drag_cost.high_bps > 0:
            costs.append(CostComponent(
                label="Tax Drag (Taxable Accounts)",
                value=f"{cb.tax_drag_cost.low_bps:.1f} – {cb.tax_drag_cost.high_bps:.1f}",
                low=cb.tax_drag_cost.low_bps,
                high=cb.tax_drag_cost.high_bps,
                tag="estimated",
                note=cb.tax_drag_cost.methodology,
                applies_to="taxable_only",
            ))

    # Totals — split into two buckets:
    #   total_hidden_* = costs that apply in ANY account (bid-ask, impact,
    #       commissions, soft dollars, cash drag)
    #   total_tax_*    = tax drag, which only applies in taxable brokerage
    #       accounts and is zero in IRAs / 401(k)s
    # Everything rolled up under true_cost_* is the tax-deferred-account view
    # (the default headline). true_cost_taxable_* adds tax drag on top.
    total_hidden_low = max(0, sum(
        c.low for c in costs
        if c.low is not None and c.tag != "warning" and c.applies_to == "all"
    ))
    total_hidden_high = max(0, sum(
        c.high for c in costs
        if c.high is not None and c.tag != "warning" and c.applies_to == "all"
    ))
    total_tax_low = max(0, sum(
        c.low for c in costs
        if c.low is not None and c.tag != "warning" and c.applies_to == "taxable_only"
    ))
    total_tax_high = max(0, sum(
        c.high for c in costs
        if c.high is not None and c.tag != "warning" and c.applies_to == "taxable_only"
    ))

    # True total cost (tax-deferred account — IRA / 401(k) / HSA)
    true_cost_low_bps = None
    true_cost_high_bps = None
    true_cost_low_pct = None
    true_cost_high_pct = None
    # True total cost (taxable brokerage account — adds tax drag)
    true_cost_taxable_low_bps = None
    true_cost_taxable_high_bps = None
    if expense_ratio_bps is not None:
        true_cost_low_bps = round(expense_ratio_bps + total_hidden_low, 2)
        true_cost_high_bps = round(expense_ratio_bps + total_hidden_high, 2)
        true_cost_low_pct = round(true_cost_low_bps / 100, 3)
        true_cost_high_pct = round(true_cost_high_bps / 100, 3)
        true_cost_taxable_low_bps = round(
            expense_ratio_bps + total_hidden_low + total_tax_low, 2
        )
        true_cost_taxable_high_bps = round(
            expense_ratio_bps + total_hidden_high + total_tax_high, 2
        )

    # Dollar impact
    dollar_impact = _compute_dollar_impact(
        expense_ratio_pct=expense_ratio_pct,
        hidden_low_bps=total_hidden_low,
        hidden_high_bps=total_hidden_high,
    )

    # Asset mix
    mix_list = []
    if nport:
        weights = nport.asset_class_weights()
        for cat, pct in sorted(weights.items(), key=lambda x: -x[1]):
            label, color = ASSET_CAT_META.get(cat, (cat, "#94a3b8"))
            mix_list.append(AssetMix(
                category=cat, label=label, color=color, pct=round(pct, 2)
            ))

    # Underlying fund composition (fund-of-funds only). Pulls from the
    # parent's N-PORT holdings, filtered to the holdings flagged as
    # registered investment companies during structure detection. We
    # surface these even when CIK resolution failed so the user can
    # still see the composition pie — cost rollup recursion needs the
    # CIK, but the pie chart needs only the name and pct of NAV.
    underlying_funds_list: list[UnderlyingFund] = []
    if meta.is_fund_of_funds and nport:
        # Assign a palette so slices are visually distinct. Order by
        # pct descending so the largest slice gets the first color.
        palette = [
            "#4ade80", "#60a5fa", "#a78bfa", "#fbbf24", "#f472b6",
            "#34d399", "#f87171", "#c084fc", "#fb923c", "#22d3ee",
            "#facc15", "#818cf8",
        ]
        ric_holdings = [
            h for h in nport.holdings
            if h.is_registered_investment_company
            and h.pct_of_net_assets is not None
            and h.pct_of_net_assets > 0
        ]
        ric_holdings.sort(key=lambda h: h.pct_of_net_assets or 0, reverse=True)
        # Also attempt to pull resolved identifiers from the child node
        # when structure detection already walked into the holding.
        resolved_by_name: dict[str, tuple[Optional[str], Optional[str]]] = {}
        for child in tree.children:
            if child.metadata and child.metadata.name:
                resolved_by_name[child.metadata.name] = (
                    child.metadata.ticker or None,
                    str(child.metadata.cik) if child.metadata.cik else None,
                )
        for i, h in enumerate(ric_holdings):
            resolved_ticker, resolved_cik = resolved_by_name.get(h.name, (None, None))
            # Fall back to values the N-PORT parser recorded directly
            resolved_ticker = resolved_ticker or getattr(h, "underlying_ticker", None)
            resolved_cik = resolved_cik or getattr(h, "underlying_cik", None)
            underlying_funds_list.append(UnderlyingFund(
                name=h.name,
                pct_of_net_assets=round(h.pct_of_net_assets, 2),
                cusip=h.cusip,
                isin=h.isin,
                color=palette[i % len(palette)],
                resolved_ticker=resolved_ticker,
                resolved_cik=resolved_cik,
            ))

    # --- N-CEN supplementary data ---
    top_brokers = []
    affiliated_brokers_list = []
    securities_lending_info = None
    service_providers = None
    aggregate_commission_dollars = None

    ncen_full = tree.ncen_full
    if ncen_full is not None:
        aggregate_commission_dollars = ncen_full.aggregate_commission

        for b in ncen_full.top_brokers[:10]:
            top_brokers.append(BrokerInfo(
                name=b.name, commission=b.gross_commission, is_affiliated=False
            ))
        for b in ncen_full.affiliated_brokers:
            affiliated_brokers_list.append(BrokerInfo(
                name=b.name, commission=b.gross_commission, is_affiliated=True
            ))

        if ncen_full.securities_lending:
            sl = ncen_full.securities_lending
            securities_lending_info = SecuritiesLendingInfo(
                is_lending=sl.is_lending,
                agent_name=sl.agent_name or None,
                is_agent_affiliated=sl.is_agent_affiliated,
                net_income=sl.net_income,
                avg_value_on_loan=sl.avg_portfolio_value_on_loan,
            )

        service_providers = ServiceProviders(
            adviser=ncen_full.investment_adviser or None,
            administrator=ncen_full.administrator or None,
            custodian=ncen_full.custodian_primary or None,
            transfer_agent=ncen_full.transfer_agent or None,
            auditor=ncen_full.auditor or None,
            is_admin_affiliated=ncen_full.is_admin_affiliated,
            is_transfer_agent_affiliated=ncen_full.is_transfer_agent_affiliated,
        )

    na = nport.total_net_assets if nport else None

    # --- Build conflict flags from N-CEN data ---
    conflict_flags = []
    affiliated_commission_pct: Optional[float] = None
    affiliated_commission_dollars: Optional[float] = None
    if ncen_full is not None:
        if ncen_full.is_brokerage_research_payment:
            conflict_flags.append("Soft dollar arrangements: fund pays inflated commissions for manager's research")
        if ncen_full.affiliated_brokers:
            aff_total = sum(b.gross_commission for b in ncen_full.affiliated_brokers)
            affiliated_commission_dollars = aff_total
            agg = ncen_full.aggregate_commission
            if agg and agg > 0:
                aff_pct = aff_total / agg * 100
                affiliated_commission_pct = aff_pct
                conflict_flags.append(
                    f"Affiliated broker usage: {len(ncen_full.affiliated_brokers)} affiliated broker(s), "
                    f"${aff_total:,.0f} in commissions ({aff_pct:.1f}% of total)"
                )
            else:
                conflict_flags.append(
                    f"Affiliated broker usage: {len(ncen_full.affiliated_brokers)} affiliated broker(s), "
                    f"${aff_total:,.0f} in commissions"
                )
        if ncen_full.is_admin_affiliated:
            conflict_flags.append("Fund administrator is affiliated with the investment adviser")
        if ncen_full.is_transfer_agent_affiliated:
            conflict_flags.append("Transfer agent is affiliated with the investment adviser")
        if ncen_full.securities_lending and ncen_full.securities_lending.is_lending:
            sl = ncen_full.securities_lending
            if sl.is_agent_affiliated:
                conflict_flags.append("Securities lending agent is affiliated with the fund")
            if sl.net_income and sl.net_income > 0:
                conflict_flags.append(
                    f"Securities lending active: ${sl.net_income:,.0f} net income "
                    f"(offsets costs but rarely disclosed to investors)"
                )

    # --- Update leaderboard with this analysis ---
    try:
        update_leaderboard(
            ticker=meta.ticker,
            name=meta.name,
            family=meta.fund_family or "",
            hidden_low_bps=total_hidden_low,
            hidden_high_bps=total_hidden_high,
            expense_ratio_bps=expense_ratio_bps,
            turnover_pct=portfolio_turnover,
            net_assets_display=_fmt_dollars(na) if na else "N/A",
            holdings_count=len(nport.holdings) if nport else 0,
            conflict_count=len(conflict_flags),
            dollar_impact_hidden_low=dollar_impact.hidden_cost_low,
            dollar_impact_hidden_high=dollar_impact.hidden_cost_high,
        )
    except Exception as exc:
        logger.debug("Leaderboard update failed for %s: %s", meta.ticker, exc)

    # Determine EDGAR health status for subtle frontend indicator
    health = get_edgar_health()
    edgar_status = "degraded" if health["retries"] > 0 or health["errors"] > 0 else "ok"

    return FundAnalysis(
        ticker=meta.ticker,
        name=meta.name,
        family=meta.fund_family or "",
        share_class=share_class,
        net_assets=na,
        net_assets_display=_fmt_dollars(na) if na else "N/A",
        holdings_count=len(nport.holdings) if nport else 0,
        period_end=str(nport.reporting_period_end) if nport else None,
        is_fund_of_funds=meta.is_fund_of_funds,
        expense_ratio_pct=expense_ratio_pct,
        expense_ratio_bps=expense_ratio_bps,
        fee_breakdown=fee_breakdown,
        portfolio_turnover=portfolio_turnover,
        max_sales_load=max_sales_load,
        costs=costs,
        total_hidden_low=round(total_hidden_low, 2) if total_hidden_low is not None else None,
        total_hidden_high=round(total_hidden_high, 2) if total_hidden_high is not None else None,
        total_tax_low=round(total_tax_low, 2) if total_tax_low is not None else None,
        total_tax_high=round(total_tax_high, 2) if total_tax_high is not None else None,
        true_cost_low_bps=true_cost_low_bps,
        true_cost_high_bps=true_cost_high_bps,
        true_cost_low_pct=true_cost_low_pct,
        true_cost_high_pct=true_cost_high_pct,
        true_cost_taxable_low_bps=true_cost_taxable_low_bps,
        true_cost_taxable_high_bps=true_cost_taxable_high_bps,
        dollar_impact=dollar_impact,
        top_brokers=top_brokers,
        affiliated_brokers=affiliated_brokers_list,
        securities_lending=securities_lending_info,
        service_providers=service_providers,
        aggregate_commission_dollars=aggregate_commission_dollars,
        asset_mix=mix_list,
        underlying_funds=underlying_funds_list,
        conflict_flags=conflict_flags,
        affiliated_commission_pct=(
            round(affiliated_commission_pct, 2)
            if affiliated_commission_pct is not None else None
        ),
        affiliated_commission_dollars=affiliated_commission_dollars,
        # Soft-dollar subsidy is computed in the SAI endpoint because
        # it requires the SAI fetch; leaving it unset here keeps the
        # main /api/analyze call fast. Callers that want the estimate
        # should read /api/sai/{ticker}.
        soft_dollar_subsidy_estimate_dollars=None,
        soft_dollar_subsidy_estimate_bps=None,
        data_notes=tree.data_notes,
        edgar_status=edgar_status,
        generated=str(date.today()),
    )


class SAICommission(BaseModel):
    """Historical brokerage commission data from SAI."""

    fund_name: str
    annual_commissions: Dict[int, float]


class SAIPMCompensation(BaseModel):
    """Portfolio manager compensation structure from SAI."""

    has_base_salary: bool
    has_bonus: bool
    has_equity_ownership: bool
    has_deferred_comp: bool
    bonus_linked_to_performance: bool
    bonus_linked_to_aum: bool
    bonus_linked_to_firm_profit: bool
    compensation_not_linked_to_fund_performance: bool
    description: str


class SAISoftDollar(BaseModel):
    """Soft dollar arrangement details from SAI."""

    has_soft_dollar_arrangements: bool
    uses_commission_sharing: bool
    description: str


class SoftDollarSubsidy(BaseModel):
    """Computed estimate of the soft-dollar subsidy the fund's
    shareholders pay toward the adviser's research bill.

    Method:
      - If the SAI breaks out research commissions per year, we sum
        the most recent year's figure and treat that as the subsidy.
        This is the directly-disclosed number.
      - If only the boolean soft-dollar flag is present (no dollar
        breakdown), we return None for both dollar and bps estimates.
        No fabrication.

    The bps figure converts dollars to basis points against the
    fund's most recent net assets from N-PORT when available.
    """
    estimated_dollars: Optional[float] = None
    estimated_bps: Optional[float] = None
    methodology: str = ""
    has_disclosure: bool = False


class SAIAnalysis(BaseModel):
    """Complete SAI (Statement of Additional Information) analysis."""
    cik: int
    filing_date: str
    accession_no: str
    commissions: List[SAICommission]
    pm_compensation: Optional[SAIPMCompensation]
    soft_dollar_info: Optional[SAISoftDollar]
    soft_dollar_subsidy: Optional[SoftDollarSubsidy] = None
    conflict_flags: List[str]


@app.get("/api/sai/{ticker}", response_model=SAIAnalysis)
def analyze_sai(ticker: str):
    """Pull SAI (Statement of Additional Information) data for a fund.

    Returns brokerage commission history, PM compensation structure,
    and soft dollar arrangement details from the fund's 485BPOS filing.
    """
    ticker = ticker.strip().upper()
    if not ticker or not ticker.isalpha() or len(ticker) > 6:
        raise HTTPException(400, "Invalid ticker format")

    try:
        from fundautopsy.data.sai_parser import parse_sai_for_cik

        fund = _resolve_or_explain(ticker)
        result = parse_sai_for_cik(fund.cik)

        if result is None or not result.has_data:
            raise HTTPException(404, f"No SAI data found for {ticker} (CIK {fund.cik})")

        # Build conflict flags
        flags = []
        if result.pm_compensation:
            pm = result.pm_compensation
            if pm.compensation_not_linked_to_fund_performance:
                flags.append("PM compensation is NOT linked to fund performance")
            if pm.bonus_linked_to_aum and not pm.bonus_linked_to_performance:
                flags.append("PM bonus tied to assets under management, not returns")
            if not pm.has_equity_ownership:
                flags.append("PM has no equity ownership in the fund or advisory firm")

        if result.soft_dollar_info:
            sd = result.soft_dollar_info
            if sd.has_soft_dollar_arrangements:
                flags.append("Fund uses soft dollar arrangements (inflated commissions for 'free' research)")
            if sd.uses_commission_sharing:
                flags.append("Fund uses commission sharing / unbundling program")

        # Build response
        commissions = [
            SAICommission(
                fund_name=bc.fund_name,
                annual_commissions=bc.annual_commissions,
            )
            for bc in result.commissions
        ]

        pm_comp = None
        if result.pm_compensation:
            pm = result.pm_compensation
            pm_comp = SAIPMCompensation(
                has_base_salary=pm.has_base_salary,
                has_bonus=pm.has_bonus,
                has_equity_ownership=pm.has_equity_ownership,
                has_deferred_comp=pm.has_deferred_comp,
                bonus_linked_to_performance=pm.bonus_linked_to_performance,
                bonus_linked_to_aum=pm.bonus_linked_to_aum,
                bonus_linked_to_firm_profit=pm.bonus_linked_to_firm_profit,
                compensation_not_linked_to_fund_performance=pm.compensation_not_linked_to_fund_performance,
                description=pm.description,
            )

        sd_info = None
        if result.soft_dollar_info:
            sd = result.soft_dollar_info
            sd_info = SAISoftDollar(
                has_soft_dollar_arrangements=sd.has_soft_dollar_arrangements,
                uses_commission_sharing=sd.uses_commission_sharing,
                description=sd.description,
            )

        # Compute soft-dollar subsidy estimate when SAI breaks out
        # research commissions directly. Use a three-year average
        # (or all available years if fewer than three) to smooth
        # out lumpy research-payment years that individual filings
        # sometimes contain. Convert to basis points using the
        # analyzed fund's N-PORT net assets when we can fetch them
        # cheaply.
        subsidy = None
        recent_research_total = 0.0
        recent_year = None
        years_averaged = 0
        for bc in result.commissions:
            if bc.soft_dollar_commissions:
                # dict[int -> float], year -> dollars
                years_sorted = sorted(bc.soft_dollar_commissions.keys(), reverse=True)
                take_years = years_sorted[:3]  # up to three most recent
                if take_years:
                    avg = sum(
                        bc.soft_dollar_commissions[y] for y in take_years
                    ) / len(take_years)
                    recent_research_total += avg
                    years_averaged = max(years_averaged, len(take_years))
                if recent_year is None or years_sorted[0] > recent_year:
                    recent_year = years_sorted[0]

        has_soft_dollar = (
            result.soft_dollar_info is not None
            and result.soft_dollar_info.has_soft_dollar_arrangements
        )
        if recent_research_total > 0:
            # Fetch NAV cheaply for the bps conversion — reuses
            # the cached resolve_ticker path. NAV fetch failure
            # is non-fatal; we still return the dollar figure.
            bps = None
            try:
                from fundautopsy.data.edgar import MutualFundIdentifier
                from fundautopsy.data.nport import retrieve_nport
                mfid = MutualFundIdentifier(
                    ticker=ticker, cik=int(fund.cik),
                    series_id=fund.series_id, class_id=fund.class_id,
                )
                n = retrieve_nport(mfid)
                if n and n.total_net_assets and n.total_net_assets > 0:
                    bps = recent_research_total / n.total_net_assets * 10_000
            except Exception:
                bps = None
            method_note = (
                f"{years_averaged}-year average of SAI-disclosed research "
                f"commissions (most recent year: {recent_year}), converted "
                f"to basis points against the fund's most recent N-PORT "
                f"net assets."
            )
            subsidy = SoftDollarSubsidy(
                estimated_dollars=recent_research_total,
                estimated_bps=round(bps, 2) if bps is not None else None,
                methodology=method_note,
                has_disclosure=True,
            )
            if bps and bps > 1.0:
                flags.append(
                    f"Soft-dollar subsidy ≈ ${recent_research_total:,.0f} "
                    f"({bps:.1f} bps) — research the adviser would otherwise pay for"
                )
        elif has_soft_dollar:
            subsidy = SoftDollarSubsidy(
                estimated_dollars=None,
                estimated_bps=None,
                methodology=(
                    "Fund acknowledges soft-dollar arrangements in SAI but "
                    "does not disclose dollar amounts. Subsidy cannot be "
                    "quantified without additional data."
                ),
                has_disclosure=True,
            )

        return SAIAnalysis(
            cik=result.cik,
            filing_date=result.filing_date,
            accession_no=result.accession_no,
            commissions=commissions,
            pm_compensation=pm_comp,
            soft_dollar_info=sd_info,
            soft_dollar_subsidy=subsidy,
            conflict_flags=flags,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("SAI analysis failed for %s", ticker)
        raise HTTPException(500, "SAI analysis failed due to an internal error")


@app.get("/api/compare")
def compare_funds(tickers: str):
    """Compare up to 5 funds side by side."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if len(ticker_list) < 2:
        raise HTTPException(400, "Provide at least 2 tickers separated by commas")
    if len(ticker_list) > 5:
        raise HTTPException(400, "Maximum 5 funds for comparison")

    results = []
    errors = []
    for t in ticker_list:
        try:
            result = analyze_fund(t)
            results.append(result)
        except HTTPException as e:
            errors.append({"ticker": t, "error": e.detail})

    return {"results": results, "errors": errors}


@app.get("/api/leaderboard")
def leaderboard(sort_by: str = "lookup_count", limit: int = 25):
    """Return the Most-Searched Funds board.

    Sort modes are restricted to REPORTED fields and lookup counts to
    avoid ranking named funds on modeled estimates. Deprecated modes
    (hidden_cost_mid_bps, true_cost_mid_bps) are silently remapped to
    lookup_count so legacy clients do not break.
    """
    _ALLOWED_SORTS = {
        "lookup_count",
        "conflict_count",
        "aggregate_commissions_usd",
    }
    if sort_by not in _ALLOWED_SORTS:
        sort_by = "lookup_count"
    entries = get_leaderboard(sort_by=sort_by, limit=limit)
    stats = get_leaderboard_stats()
    return {"entries": entries, "stats": stats, "sort_by": sort_by}


@app.get("/api/fee-history/{ticker}")
def fee_history(ticker: str):
    """Return fee change history from historical 485BPOS filings."""
    ticker = ticker.strip().upper()
    if not ticker or not ticker.isalpha() or len(ticker) > 6:
        raise HTTPException(400, "Invalid ticker format")

    try:
        fund = _resolve_or_explain(ticker)
        history = track_fee_changes(
            cik=int(fund.cik),
            ticker=ticker,
            series_id=fund.series_id,
            class_id=fund.class_id,
            max_filings=5,
        )

        snapshots = [
            {
                "filing_date": s.filing_date,
                "form_type": s.form_type,
                "management_fee": s.management_fee,
                "twelve_b1_fee": s.twelve_b1_fee,
                "other_expenses": s.other_expenses,
                "total_annual_expenses": s.total_annual_expenses,
                "net_expenses": s.net_expenses,
                "effective_expense_ratio": s.effective_expense_ratio,
                "max_sales_load": s.max_sales_load,
                "portfolio_turnover": s.portfolio_turnover,
            }
            for s in history.snapshots
        ]

        changes = [
            {
                "field_label": c.field_label,
                "old_value": c.old_value,
                "new_value": c.new_value,
                "change_bps": c.change_bps,
                "direction": c.direction,
                "old_filing_date": c.old_filing_date,
                "new_filing_date": c.new_filing_date,
            }
            for c in history.changes
        ]

        return {
            "ticker": ticker,
            "cik": fund.cik,
            "has_changes": history.has_changes,
            "net_change_bps": history.net_change_bps,
            "snapshots": snapshots,
            "changes": changes,
        }

    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.exception("Fee history failed for %s", ticker)
        raise HTTPException(500, "Fee history failed due to an internal error")


@app.get("/api/ncsr/{ticker}")
def analyze_ncsr(ticker: str):
    """Pull N-CSR (shareholder report) data for a fund.

    Returns audited brokerage commission history, portfolio turnover
    from financial highlights, and board advisory contract approval text.
    """
    ticker = ticker.strip().upper()
    if not ticker or not ticker.isalpha() or len(ticker) > 6:
        raise HTTPException(400, "Invalid ticker format")

    try:
        fund = _resolve_or_explain(ticker)
        result = parse_ncsr_for_cik(fund.cik)

        if result is None or not result.has_data:
            raise HTTPException(
                404, f"No N-CSR data found for {ticker} (CIK {fund.cik})"
            )

        commissions = [
            {
                "fund_name": nc.fund_name,
                "annual_commissions": nc.annual_commissions,
                "research_commissions": nc.research_commissions,
                "recapture_amounts": nc.recapture_amounts,
            }
            for nc in result.commissions
        ]

        turnover = [
            {"fund_name": nt.fund_name, "annual_turnover": nt.annual_turnover}
            for nt in result.turnover
        ]

        return {
            "cik": result.cik,
            "filing_date": result.filing_date,
            "accession_no": result.accession_no,
            "is_annual": result.is_annual,
            "commissions": commissions,
            "turnover": turnover,
            "board_approval_text": result.board_approval_text[:2000]
            if result.board_approval_text
            else "",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("N-CSR analysis failed for %s", ticker)
        raise HTTPException(500, "N-CSR analysis failed due to an internal error")


@app.get("/api/derivatives/{ticker}")
def analyze_derivatives(ticker: str):
    """Return the fund's derivative positions aggregated from N-PORT Item C.

    Breakdown of distinct derivative categories (equity, interest rate,
    credit, FX/forward, commodity, other), instrument type counts
    (swap, future, forward, option/swaption/warrant), aggregate USD
    notional across the derivative book, and the top counterparties
    by notional weight.

    The aggregate notional is the sum of USD-denominated notional
    amounts across all derivative positions. Non-USD notionals are
    captured per-position but excluded from the aggregate because
    the cross-currency FX mark would introduce a reporting
    distortion against USD fund NAV. Notional is face value, not
    market value — a $1B notional interest-rate swap might have a
    $5M market exposure.
    """
    ticker = ticker.strip().upper()
    if not ticker or not ticker.isalpha() or len(ticker) > 6:
        raise HTTPException(400, "Invalid ticker format")

    try:
        from fundautopsy.data.edgar import MutualFundIdentifier
        from fundautopsy.data.nport import retrieve_nport

        fund = _resolve_or_explain(ticker)
        mfid = MutualFundIdentifier(
            ticker=ticker,
            cik=int(fund.cik),
            series_id=fund.series_id,
            class_id=fund.class_id,
        )
        nport = retrieve_nport(mfid)

        if nport is None:
            raise HTTPException(
                404, f"No N-PORT data available for {ticker}"
            )

        # Aggregate counterparty notional across derivatives. Top 10.
        cp_notional: Dict[str, float] = {}
        for d in nport.derivatives:
            if d.counterparty_name and d.notional_usd:
                key = d.counterparty_name
                cp_notional[key] = cp_notional.get(key, 0.0) + d.notional_usd
        top_counterparties = sorted(
            cp_notional.items(), key=lambda kv: kv[1], reverse=True
        )[:10]

        # Notional intensity: derivative notional relative to fund NAV
        nav = nport.total_net_assets or 0
        notional_pct_of_nav = None
        if nav and nav > 0:
            notional_pct_of_nav = (
                nport.aggregate_derivative_notional_usd / nav * 100
            )

        # Unrealized appreciation total — mark-to-market exposure
        unrealized_total = sum(
            (d.unrealized_appreciation_usd or 0.0)
            for d in nport.derivatives
        )

        return {
            "ticker": ticker,
            "fund_name": fund.name,
            "reporting_period_end": (
                nport.reporting_period_end.isoformat()
                if nport.reporting_period_end else None
            ),
            "filing_date": (
                nport.filing_date.isoformat()
                if nport.filing_date else None
            ),
            "total_net_assets_usd": nav,
            "derivative_positions_count": len(nport.derivatives),
            "distinct_derivative_categories": nport.distinct_derivative_categories,
            "distinct_instrument_types": nport.distinct_derivative_instrument_types,
            "aggregate_notional_usd": nport.aggregate_derivative_notional_usd,
            "notional_pct_of_nav": notional_pct_of_nav,
            "unrealized_appreciation_total_usd": unrealized_total,
            "category_counts": nport.derivative_category_counts,
            "top_counterparties_by_notional": [
                {"name": name, "aggregate_notional_usd": notional}
                for name, notional in top_counterparties
            ],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Derivatives analysis failed for %s", ticker)
        raise HTTPException(
            500, "Derivatives analysis failed due to an internal error"
        )


@app.get("/api/geography/{ticker}")
def analyze_geography(ticker: str):
    """Return the fund's country exposure from N-PORT holdings.

    Aggregates the issuer country code (`<invCountry>`) across all
    holdings, weighted by each holding's percentage of net assets.
    This is the issuer's country rather than the country of risk or
    the trading venue — a Cayman Islands shell for an emerging-markets
    bond will report KY, not the underlying country of exposure.
    Useful as a sanity check against a prospectus's diversification
    claims.
    """
    ticker = ticker.strip().upper()
    if not ticker or not ticker.isalpha() or len(ticker) > 6:
        raise HTTPException(400, "Invalid ticker format")

    try:
        from fundautopsy.data.edgar import MutualFundIdentifier
        from fundautopsy.data.nport import retrieve_nport

        fund = _resolve_or_explain(ticker)
        mfid = MutualFundIdentifier(
            ticker=ticker,
            cik=int(fund.cik),
            series_id=fund.series_id,
            class_id=fund.class_id,
        )
        nport = retrieve_nport(mfid)
        if nport is None:
            raise HTTPException(
                404, f"No N-PORT data available for {ticker}"
            )

        exposure = nport.country_exposure_pct()
        top_1 = nport.country_concentration_pct(top_n=1)
        top_5 = nport.country_concentration_pct(top_n=5)
        non_us_pct = 100.0 - exposure.get("US", 0.0) - exposure.get("UNKNOWN", 0.0)

        # Keep the response focused — top-20 countries plus aggregate buckets
        top_countries = [
            {"country": country, "weight_pct": round(weight, 4)}
            for country, weight in list(exposure.items())[:20]
        ]
        return {
            "ticker": ticker,
            "fund_name": fund.name,
            "reporting_period_end": (
                nport.reporting_period_end.isoformat()
                if nport.reporting_period_end else None
            ),
            "filing_date": (
                nport.filing_date.isoformat()
                if nport.filing_date else None
            ),
            "distinct_countries": len([c for c in exposure if c != "UNKNOWN"]),
            "top_country_pct": round(top_1, 4),
            "top_5_countries_pct": round(top_5, 4),
            "non_us_excluding_unknown_pct": round(non_us_pct, 4),
            "top_countries": top_countries,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Geography analysis failed for %s", ticker)
        raise HTTPException(
            500, "Geography analysis failed due to an internal error"
        )


@app.get("/api/mergers/{ticker}")
def analyze_mergers(ticker: str):
    """Return recent N-14 fund merger / reorganization filings for the trust.

    N-14 is the SEC registration statement filed when an investment
    company proposes to merge, reorganize, or exchange shares with
    another fund. Each filing announces one or more reorganizations
    and identifies target and acquirer funds. This endpoint surfaces
    recent N-14 activity at the trust level, classifies same-complex
    vs cross-complex reorganizations where the parser can infer them,
    and returns the filing URLs for direct review.

    Trust-level scope: an N-14 filed under an umbrella trust like
    Fidelity Concord Street Trust may announce a merger affecting a
    single series while the other hundred series inside the trust are
    unaffected. A shareholder of one fund should still see any recent
    N-14 that the trust has filed because it may touch their fund.
    """
    ticker = ticker.strip().upper()
    if not ticker or not ticker.isalpha() or len(ticker) > 6:
        raise HTTPException(400, "Invalid ticker format")

    try:
        from fundautopsy.data.n14_parser import retrieve_n14_for_cik

        fund = _resolve_or_explain(ticker)
        filings = retrieve_n14_for_cik(int(fund.cik), max_filings=5, classify=True)

        serialized = [
            {
                "accession_no": f.accession_no,
                "filing_date": f.filing_date.isoformat(),
                "form_type": f.form_type,
                "company_name": f.company_name,
                "filing_url": f.filing_url,
                "reorganization_type": f.reorganization_type,
                "target_fund_names": f.target_fund_names,
                "acquiring_fund_names": f.acquiring_fund_names,
                "summary_snippet": f.summary_snippet,
            }
            for f in filings
        ]

        return {
            "ticker": ticker,
            "fund_name": fund.name,
            "cik": fund.cik,
            "n14_filings_count": len(serialized),
            "filings": serialized,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Mergers analysis failed for %s", ticker)
        raise HTTPException(
            500, "Mergers analysis failed due to an internal error"
        )


# --- Portfolio-level total cost of ownership rollup ---


class PortfolioInputHolding(BaseModel):
    """One holding row as received from the client."""

    ticker: str
    weight: float  # percentage (0-100)


class PortfolioRequest(BaseModel):
    """Request body for /api/portfolio.

    Accepts either a list of structured holdings or a raw textarea-style
    string. One must be provided.
    """

    raw: Optional[str] = None
    holdings: Optional[List[PortfolioInputHolding]] = None
    starting_balance: Optional[float] = None
    gross_return_pct: Optional[float] = None  # e.g. 7.0 for 7%


class PortfolioHoldingRow(BaseModel):
    ticker: str
    fund_name: str
    weight_pct: float
    expense_ratio_bps: Optional[float]
    brokerage_commissions_bps: Optional[float]
    underlying_funds_weighted_bps: Optional[float]
    true_tco_bps: Optional[float]
    portfolio_contribution_bps: Optional[float]
    data_quality: str
    is_fund_of_funds: bool
    notes: List[str]


class PortfolioProjection(BaseModel):
    horizon_years: int
    terminal_wealth_true_tco: float
    terminal_wealth_stated_er: float
    drag_dollars: float
    drag_percent: float


class PortfolioResponse(BaseModel):
    holdings: List[PortfolioHoldingRow]
    weighted_true_tco_bps: float
    weighted_expense_ratio_bps: float
    hidden_gap_bps: float
    priced_weight_fraction: float
    unpriced_weight_fraction: float
    projections: List[PortfolioProjection]
    starting_balance: float
    gross_return_annual: float
    data_notes: List[str]


@app.post("/api/portfolio", response_model=PortfolioResponse)
def analyze_portfolio(req: PortfolioRequest):
    """Compute portfolio-weighted true total cost of ownership.

    Accepts either a raw textarea-style input string or a list of
    structured holdings. Runs the full single-fund pipeline against
    each ticker, aggregates weighted costs, and projects compound drag
    over 10 / 20 / 30-year horizons.
    """
    from fundautopsy.core.portfolio import (
        PortfolioHolding,
        parse_portfolio_input,
        rollup_portfolio,
        DEFAULT_STARTING_BALANCE,
        DEFAULT_GROSS_RETURN,
    )

    # Resolve holdings input.
    holdings: List[PortfolioHolding]
    try:
        if req.holdings:
            holdings = [
                PortfolioHolding(ticker=h.ticker.strip().upper(), weight=h.weight)
                for h in req.holdings
            ]
        elif req.raw:
            holdings = parse_portfolio_input(req.raw)
        else:
            raise HTTPException(
                400, "Provide either 'holdings' or 'raw' in the request body."
            )
    except ValueError as e:
        raise HTTPException(400, str(e))

    starting_balance = (
        req.starting_balance if req.starting_balance is not None
        else DEFAULT_STARTING_BALANCE
    )
    gross_return = (
        req.gross_return_pct / 100.0 if req.gross_return_pct is not None
        else DEFAULT_GROSS_RETURN
    )
    if starting_balance <= 0:
        raise HTTPException(400, "Starting balance must be positive.")
    if not -0.5 <= gross_return <= 0.5:
        raise HTTPException(
            400, "Gross return must be between -50% and 50%."
        )

    try:
        tco = rollup_portfolio(
            holdings=holdings,
            starting_balance=starting_balance,
            gross_return_annual=gross_return,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("Portfolio rollup failed")
        raise HTTPException(500, "Portfolio analysis failed due to an internal error")

    return PortfolioResponse(
        holdings=[
            PortfolioHoldingRow(
                ticker=h.ticker,
                fund_name=h.fund_name,
                weight_pct=round(h.weight_pct, 4),
                expense_ratio_bps=round(h.expense_ratio_bps, 2) if h.expense_ratio_bps is not None else None,
                brokerage_commissions_bps=round(h.brokerage_commissions_bps, 2) if h.brokerage_commissions_bps is not None else None,
                underlying_funds_weighted_bps=round(h.underlying_funds_weighted_bps, 2) if h.underlying_funds_weighted_bps is not None else None,
                true_tco_bps=round(h.true_tco_bps, 2) if h.true_tco_bps is not None else None,
                portfolio_contribution_bps=round(h.portfolio_contribution_bps, 4) if h.portfolio_contribution_bps is not None else None,
                data_quality=h.data_quality,
                is_fund_of_funds=h.is_fund_of_funds,
                notes=h.notes,
            )
            for h in tco.holdings
        ],
        weighted_true_tco_bps=round(tco.weighted_true_tco_bps, 2),
        weighted_expense_ratio_bps=round(tco.weighted_expense_ratio_bps, 2),
        hidden_gap_bps=round(tco.hidden_gap_bps, 2),
        priced_weight_fraction=round(tco.priced_weight_fraction, 4),
        unpriced_weight_fraction=round(tco.unpriced_weight_fraction, 4),
        projections=[
            PortfolioProjection(
                horizon_years=p.horizon_years,
                terminal_wealth_true_tco=round(p.terminal_wealth_true_tco, 2),
                terminal_wealth_stated_er=round(p.terminal_wealth_stated_er, 2),
                drag_dollars=round(p.drag_dollars, 2),
                drag_percent=round(p.drag_percent, 4),
            )
            for p in tco.projections
        ],
        starting_balance=tco.starting_balance,
        gross_return_annual=tco.gross_return_annual,
        data_notes=tco.data_notes,
    )


@app.get("/portfolio", response_class=HTMLResponse)
def portfolio_page():
    """Server-rendered portfolio rollup page."""
    from fundautopsy.web.frontend import PORTFOLIO_HTML

    return PORTFOLIO_HTML


@app.get("/leaderboard", response_class=HTMLResponse)
def leaderboard_page():
    """Worst-offender leaderboard page.

    Renders a server-generated ranked table of the funds currently in
    the leaderboard cache, sorted by hidden cost. This page is the
    landing target for Reddit, Hacker News, and Twitter/X share links
    because it does not require a ticker input.
    """
    entries = get_leaderboard(sort_by="hidden_cost_mid_bps", limit=50)
    rows_html = []
    for i, e in enumerate(entries, 1):
        hidden = e.get("hidden_cost_mid_bps") or 0
        er = e.get("expense_ratio_bps") or 0
        family = e.get("family", "") or ""
        rows_html.append(
            f"<tr>"
            f"<td>{i}</td>"
            f"<td><a href='/?ticker={e['ticker']}' style='color:#ef4444'>{e['ticker']}</a></td>"
            f"<td>{e.get('name', '')[:60]}</td>"
            f"<td>{family[:30]}</td>"
            f"<td style='text-align:right'>{er:.0f} bps</td>"
            f"<td style='text-align:right;color:#ef4444;font-weight:600'>{hidden:.0f} bps</td>"
            f"<td style='text-align:right'>{e.get('net_assets_display', '')}</td>"
            f"</tr>"
        )
    rows = "\n".join(rows_html) if rows_html else (
        "<tr><td colspan='7' style='text-align:center;padding:40px;color:#a1a1aa'>"
        "Leaderboard populates as funds are analyzed. "
        "Query a ticker from the home page first."
        "</td></tr>"
    )

    return f"""<!DOCTYPE html>
<html lang='en'>
<head>
<meta charset='UTF-8'>
<meta name='viewport' content='width=device-width, initial-scale=1.0'>
<title>Fund Autopsy — Worst Offenders Leaderboard</title>
<meta name='description' content='Live ranked leaderboard of mutual funds by hidden cost of ownership. Open-source tool built on SEC filings.'>
<meta property='og:type' content='website'>
<meta property='og:title' content='Fund Autopsy — Worst Offenders Leaderboard'>
<meta property='og:description' content='Live ranked list of mutual funds by hidden cost of ownership, sorted by sub-NAV drag in basis points.'>
<meta property='og:url' content='https://fund-autopsy.onrender.com/leaderboard'>
<meta name='twitter:card' content='summary_large_image'>
<meta name='twitter:site' content='@ejbaldwin_'>
<meta name='twitter:title' content='Fund Autopsy — Worst Offenders Leaderboard'>
<meta name='twitter:description' content='Live ranked list of mutual funds by hidden cost of ownership, sorted by sub-NAV drag in basis points.'>
<link rel='stylesheet' href='/static/styles.css'>
<style>
body {{ background: #0a0a0b; color: #e4e4e7; font-family: 'Inter', sans-serif; margin: 0; padding: 0; }}
.container {{ max-width: 1100px; margin: 0 auto; padding: 32px 24px; }}
h1 {{ font-weight: 800; font-size: 28px; margin: 0 0 8px 0; }}
.subtitle {{ color: #a1a1aa; font-size: 14px; margin-bottom: 24px; }}
table {{ width: 100%; border-collapse: collapse; background: #18181b; border-radius: 12px; overflow: hidden; }}
th {{ text-align: left; padding: 12px; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #a1a1aa; background: #27272a; }}
td {{ padding: 12px; font-size: 13px; border-bottom: 1px solid #27272a; }}
tr:last-child td {{ border-bottom: none; }}
a {{ text-decoration: none; }}
.back {{ color: #60a5fa; font-size: 14px; margin-bottom: 16px; display: inline-block; }}
.footer {{ margin-top: 32px; font-size: 12px; color: #a1a1aa; line-height: 1.6; }}
@media (max-width: 700px) {{
  .container {{ padding: 16px 12px; }}
  th, td {{ padding: 8px 6px; font-size: 12px; }}
}}
</style>
</head>
<body>
<div class='container'>
<a href='/' class='back'>&larr; Back to analyzer</a>
<h1>Worst Offenders</h1>
<p class='subtitle'>Mutual funds ranked by hidden cost of ownership (sub-NAV drag in basis points). Click any ticker to see the full cost breakdown. Powered by live SEC filings, updated as funds are analyzed.</p>
<table>
<thead><tr>
<th>#</th><th>Ticker</th><th>Fund</th><th>Family</th>
<th style='text-align:right'>Expense Ratio</th>
<th style='text-align:right'>Hidden Cost</th>
<th style='text-align:right'>Net Assets</th>
</tr></thead>
<tbody>
{rows}
</tbody>
</table>
<div class='footer'>
Fund Autopsy &middot; <a href='https://github.com/Tombstone-Research/fund-autopsy' style='color:#60a5fa'>GitHub</a> &middot; <a href='https://github.com/Tombstone-Research/fund-autopsy/blob/main/research/working_paper_01_beneath_the_expense_ratio.md' style='color:#60a5fa'>Working paper</a>
<br><br>
All cost estimates derived from public SEC filings (N-CEN, N-PORT, 497K, 485BPOS, SAI, N-CSR). Methodology is documented in the working paper. Tombstone Research is not a registered investment adviser.
</div>
</div>
</body>
</html>"""


@app.get("/api/search")
def search_funds(q: str = "", limit: int = 5):
    """Fund-name → ticker autocomplete.

    Matches the query substring against a curated alias map of the
    largest retail mutual funds. Users who know the fund name but
    not the ticker get a ranked list of suggestions to click through.
    Returns empty list for queries under 2 characters.
    """
    from fundautopsy.data.fund_aliases import search_aliases
    q = (q or "").strip()
    if len(q) < 2:
        return {"query": q, "suggestions": []}
    suggestions = search_aliases(q, limit=max(1, min(limit, 20)))
    return {"query": q, "suggestions": suggestions}


@app.get("/methodology", response_class=HTMLResponse)
def methodology_page():
    """Plain-English methodology summary for journalists and academics.

    A dedicated page so reviewers who click through from outreach
    emails land on the methodology without needing to download the
    working-paper PDF first. Summary in markdown-rendered HTML with
    links to the deeper artifacts (working paper, stress test data,
    test suite coverage report).
    """
    return """<!DOCTYPE html>
<html lang='en'>
<head>
<meta charset='UTF-8'>
<meta name='viewport' content='width=device-width, initial-scale=1.0'>
<title>Fund Autopsy — Methodology</title>
<meta name='description' content='Methodology behind Fund Autopsy. Six SEC filing types, named data-source tags, reproducible stress tests, open-source code.'>
<meta property='og:title' content='Fund Autopsy — Methodology'>
<meta property='og:description' content='How the cost numbers are derived. Every metric traces to a specific SEC filing.'>
<meta property='og:type' content='article'>
<meta name='twitter:card' content='summary_large_image'>
<meta name='twitter:site' content='@ejbaldwin_'>
<link rel='stylesheet' href='/static/styles.css'>
<style>
body { background: #0a0a0b; color: #e4e4e7; font-family: 'Inter', sans-serif; margin: 0; padding: 0; line-height: 1.6; }
.container { max-width: 760px; margin: 0 auto; padding: 40px 24px; }
h1 { font-weight: 800; font-size: 32px; margin: 0 0 16px 0; }
h2 { font-weight: 600; font-size: 22px; margin: 32px 0 12px 0; color: #fafafa; border-bottom: 1px solid #27272a; padding-bottom: 8px; }
h3 { font-weight: 600; font-size: 16px; margin: 20px 0 8px 0; color: #fafafa; }
p { color: #d4d4d8; font-size: 15px; margin: 12px 0; }
code { background: #18181b; padding: 2px 6px; border-radius: 4px; font-family: 'JetBrains Mono', monospace; font-size: 13px; color: #fbbf24; }
a { color: #60a5fa; text-decoration: none; }
a:hover { text-decoration: underline; }
.back { font-size: 14px; margin-bottom: 16px; display: inline-block; }
.badge { display: inline-block; background: #18181b; border: 1px solid #27272a; padding: 4px 10px; border-radius: 6px; font-size: 11px; color: #a1a1aa; margin-right: 6px; margin-bottom: 6px; }
ul { padding-left: 20px; }
li { margin: 6px 0; }
</style>
</head>
<body>
<div class='container'>
<a href='/' class='back'>&larr; Back to analyzer</a>
<h1>Methodology</h1>
<p>Fund Autopsy parses six SEC filing types at the share-class level and surfaces cost, conflict, and governance detail that the expense ratio does not capture. This page documents how each surfaced number is derived and where the underlying data lives on EDGAR.</p>

<div>
<span class='badge'>Open Source (MIT)</span>
<span class='badge'>Reproducible Stress Tests</span>
<span class='badge'>75+ Unit Tests</span>
<span class='badge'>CI Gated</span>
<span class='badge'>Data-Source Tagged</span>
</div>

<h2>Data sources</h2>
<p>Every metric on the dashboard traces to one of these six filings. Each filing is publicly available on SEC EDGAR.</p>
<ul>
<li><strong>Form N-CEN</strong> — Annual census report. Brokerage commissions, soft-dollar arrangements, affiliated-broker routing, securities-lending revenue, service providers.</li>
<li><strong>Form N-PORT</strong> — Quarterly portfolio holdings (made public after a 60-day lag). Complete holdings list, asset class classifications, issuer country, derivative positions with counterparty and notional data.</li>
<li><strong>Form 497K</strong> — Summary prospectus. Expense ratio, management fee, 12b-1 fee, other expenses, portfolio turnover.</li>
<li><strong>Form 485BPOS</strong> — Statutory prospectus. Structured XBRL fee facts used as fallback when the 497K HTML is incomplete or unavailable. Covers the <code>oef:</code> (Open-ended Fund) and <code>rr:</code> (Risk/Return) XBRL taxonomies.</li>
<li><strong>Statement of Additional Information (SAI)</strong> — Filed with 485BPOS. Broker-specific commission breakdowns, portfolio manager compensation structure, soft-dollar research arrangements.</li>
<li><strong>Form N-CSR</strong> — Semiannual shareholder report. Audited commission history, turnover from financial highlights, board advisory contract approval narrative.</li>
</ul>

<h2>Data-source transparency</h2>
<p>Every numeric field carries a source tag so a reader can see whether a number was reported directly, calculated from reported data, or estimated from a model:</p>
<ul>
<li><strong>REPORTED</strong> — Directly from the filing.</li>
<li><strong>CALCULATED</strong> — Computed from other reported fields.</li>
<li><strong>ESTIMATED</strong> — Derived using documented model assumptions.</li>
<li><strong>UNAVAILABLE</strong> — Expected but missing from the filing.</li>
<li><strong>NOT_DISCLOSED</strong> — Fund acknowledged but did not report amounts.</li>
</ul>

<h2>Novel metrics</h2>

<h3>Sub-NAV drag</h3>
<p>The sum of brokerage commissions, bid-ask spreads, and market impact that hits returns before the expense ratio is deducted. Commissions come from N-CEN directly. Spreads and impact are estimated from N-PORT asset mix and turnover.</p>

<h3>Affiliated commission concentration</h3>
<p>The share of aggregate commissions routed through broker-dealers affiliated with the fund adviser. Computed from N-CEN Item C.6. Displayed as a percentage with green/yellow/red color coding: below 20% is routine, 20-50% is elevated, above 50% is structural.</p>

<h3>Soft-dollar subsidy estimate</h3>
<p>Three-year average of SAI-disclosed research commissions, converted to basis points against the fund's most recent N-PORT net assets. Surfaces the dollar amount of research the fund's shareholders effectively subsidize on behalf of the adviser.</p>

<h3>Derivative notional footprint</h3>
<p>Aggregate USD notional of derivative positions from N-PORT Item C, across forwards, swaps, futures, and options/swaptions/warrants. Expressed both in raw dollars and as a percentage of fund net assets.</p>

<h3>Geographic issuer concentration</h3>
<p>Issuer country (N-PORT <code>invCountry</code>) weighted by percentage of net assets. Three named modes: <code>net</code> (signed, economically correct), <code>gross_long</code> (filters to positive positions), <code>gross_absolute</code> (sums absolute values). Dashboard displays net by default with a footnote when the top country exceeds 100% (which happens for leveraged bond funds with synthetic short positions).</p>

<h2>Coverage</h2>
<p>Validated against a 68-ticker stratified stress set covering indexed equity (18), active equity (22), active bond (6), target-date across five sponsors (19), sector, international, boutique active, and a fund-of-funds wrapper: <strong>68/68 pass</strong> with zero exceptions. A 250-ticker broader stress test is in progress; results appear at <code>Intelligence/publication_stress_2026-04-23/summary.md</code> in the repository when complete.</p>

<h2>Reproducibility</h2>
<p>Everything is reproducible. Code is MIT-licensed on <a href='https://github.com/Tombstone-Research/fund-autopsy'>GitHub</a>. The stress-test runners live in <code>Intelligence/</code>. Unit tests covering the critical parsers live in <code>tests/</code>. CI runs the full suite with a coverage threshold on every push and executes a pseudonymity scan as a blocking step.</p>

<h2>Limitations</h2>
<ul>
<li>N-CEN data begins in 2018; no structured soft-dollar data before that.</li>
<li>N-CEN is filed annually; commission data can be up to 12 months old.</li>
<li>Bid-ask spread and market impact are model estimates, not observed execution costs.</li>
<li>Form CRS and Form ADV parsers are roadmap items, not yet implemented.</li>
<li>Post-target-date dormant TDFs (funds past their target year whose sponsors have stopped filing per-class summary prospectuses) are a known disclosure edge case.</li>
<li>Exchange-traded funds are out of scope; ETF filings follow a different SEC regime.</li>
</ul>

<h2>Citation</h2>
<p>Tombstone Research (2026). <em>Beneath the Expense Ratio: Ten Disclosure Dimensions in SEC Form N-CEN That Industry Cost Analysis Systematically Omits.</em> Working Paper No. 1. <a href='https://github.com/Tombstone-Research/fund-autopsy/blob/main/research/working_paper_01_beneath_the_expense_ratio.md'>Full text</a>.</p>

<div style='margin-top: 48px; padding-top: 20px; border-top: 1px solid #27272a; font-size: 12px; color: #a1a1aa;'>
Fund Autopsy &middot; <a href='https://github.com/Tombstone-Research/fund-autopsy'>GitHub</a> &middot; <a href='/leaderboard'>Leaderboard</a> &middot; <a href='/'>Analyzer</a>
<br><br>
Tombstone Research is not a registered investment adviser, broker-dealer, or financial planner. Methodology and code are public for independent verification.
</div>
</div>
</body>
</html>"""


@app.get("/robots.txt")
def robots_txt():
    """Open the site to search indexers. Small but lifts discoverability."""
    from fastapi.responses import PlainTextResponse
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Sitemap: https://fund-autopsy.onrender.com/sitemap.xml\n"
    )
    return PlainTextResponse(content=content)


@app.get("/sitemap.xml")
def sitemap_xml():
    """Static sitemap listing the indexable routes for search engines."""
    from fastapi.responses import Response
    today = date.today().isoformat()
    base = "https://fund-autopsy.onrender.com"
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{base}/</loc><lastmod>{today}</lastmod><priority>1.0</priority></url>
  <url><loc>{base}/leaderboard</loc><lastmod>{today}</lastmod><priority>0.9</priority></url>
  <url><loc>{base}/methodology</loc><lastmod>{today}</lastmod><priority>0.9</priority></url>
  <url><loc>{base}/portfolio</loc><lastmod>{today}</lastmod><priority>0.7</priority></url>
</urlset>
"""
    return Response(content=content, media_type="application/xml")


@app.get("/health")
def health_check():
    """Basic health endpoint for load balancers and monitoring."""
    health = get_edgar_health()
    return {
        "status": "ok",
        "edgar": {
            "retries": health["retries"],
            "errors": health["errors"],
            "status": "degraded" if health["errors"] > 0 else "ok",
        },
    }


@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Serve the interactive dashboard."""
    from fundautopsy.web.frontend import DASHBOARD_HTML

    return DASHBOARD_HTML


@app.get("/f/{ticker}", response_class=HTMLResponse)
@app.get("/fund/{ticker}", response_class=HTMLResponse)
def fund_deep_link(ticker: str):
    """Serve the dashboard with an auto-analyze hint for the given ticker.

    The HTML is identical to the root dashboard. The ticker is surfaced
    via a data-attribute on <body> so app.js can parse it on load and
    trigger runAnalysis() automatically. This gives every fund a
    bookmarkable, shareable, SEO-indexable URL without a server-side
    render of fund-specific data.
    """
    from fundautopsy.web.frontend import DASHBOARD_HTML

    safe = ticker.strip().upper()[:8]
    html = DASHBOARD_HTML.replace(
        "<body>",
        f'<body data-deep-link-ticker="{safe}">',
        1,
    )
    return html


@app.get("/corrections", response_class=HTMLResponse)
def corrections_page():
    """Serve the public corrections log.

    A corrections page is the single highest-leverage compliance move
    for a research publisher: it documents every error ever corrected,
    with dates and descriptions. Builds credibility with readers and
    mitigates defamation risk by demonstrating a good-faith correction
    practice.
    """
    from pathlib import Path as _Path

    corrections_md = (
        _Path(__file__).parent.parent.parent / "docs" / "corrections.md"
    )
    body_md = corrections_md.read_text(encoding="utf-8") if corrections_md.exists() else (
        "# Corrections\n\nNo corrections logged since public launch on 2026-04-06."
    )
    # Minimal inline rendering (markdown → HTML) without adding a dep.
    # Headings and paragraphs only; detailed formatting is not required.
    html_body = (
        body_md
        .replace("### ", "<h3>").replace("## ", "<h2>").replace("# ", "<h1>")
    )
    html_body_lines = []
    for line in html_body.splitlines():
        if line.startswith("<h"):
            html_body_lines.append(f"{line}</{line[1:3]}>")
        elif line.strip() == "":
            html_body_lines.append("")
        else:
            html_body_lines.append(f"<p>{line}</p>")
    html_body = "\n".join(html_body_lines)
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Corrections — Tombstone Research</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>
 body {{ font-family: Inter, sans-serif; background:#0a0a0a; color:#e4e4e7;
        max-width: 720px; margin: 48px auto; padding: 0 24px; line-height:1.65; }}
 h1,h2,h3 {{ color:#fafafa; }}
 h1 {{ border-bottom:1px solid #27272a; padding-bottom:12px; }}
 a {{ color:#60a5fa; }}
 .nav {{ margin-bottom:32px; font-size:13px; }}
 .nav a {{ color:#a1a1aa; text-decoration:none; }}
</style>
</head><body>
<div class="nav"><a href="/">← Back to Fund Autopsy</a></div>
{html_body}
</body></html>"""
