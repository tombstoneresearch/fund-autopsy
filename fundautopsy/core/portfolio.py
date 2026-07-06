"""Stage 5: Portfolio-level total cost of ownership rollup.

For a list of (ticker, weight) holdings, compose the single-fund
pipeline (`identify_fund` + `detect_structure` + `compute_costs` +
`rollup_costs`) across every position and aggregate the results into a
portfolio-weighted true total cost of ownership, plus a compound-drag
projection over 10 / 20 / 30 year horizons.

This is the feature that turns Fund Autopsy from a single-fund lookup
into a portfolio-aware tool. The per-fund pipeline already absorbs
fund-of-funds recursion through `detect_structure` and `rollup_costs`,
so this module is a thin composition layer — no new filing logic, no
new domain assumptions.

The headline number every consumer cares about is the gap between the
portfolio-weighted stated expense ratio and the portfolio-weighted
true total cost of ownership, because that gap is what the industry's
retail-facing tools systematically under-report. The compound-drag
projection is the translation from basis points into dollars.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fundautopsy.core.costs import compute_costs
from fundautopsy.core.fund import identify_fund
from fundautopsy.core.rollup import rollup_costs
from fundautopsy.core.structure import detect_structure
from fundautopsy.models.holdings_tree import FundNode
from fundautopsy.models.filing_data import DataSourceTag, TaggedValue

logger = logging.getLogger(__name__)

# Default projection assumptions. Configurable per-call.
DEFAULT_STARTING_BALANCE: float = 100_000.0
DEFAULT_GROSS_RETURN: float = 0.07  # 7.0% annual before costs
DEFAULT_HORIZONS: tuple[int, ...] = (10, 20, 30)

# Tolerance for weights summing to 100%. If the user's input sums to
# 98-102 we normalize silently; outside that range we surface an error
# so the user fixes the input rather than getting a silently-wrong
# portfolio-level number.
WEIGHT_NORMALIZATION_TOLERANCE_PCT: float = 2.0


@dataclass
class PortfolioHolding:
    """One position in the investor's portfolio.

    `weight` is expressed as a percentage of portfolio value (0-100),
    not a fraction. The input layer is responsible for normalizing.
    """

    ticker: str
    weight: float
    name: str | None = None  # Optional display name from the input


@dataclass
class HoldingResult:
    """Per-holding result row in the portfolio output table."""

    ticker: str
    fund_name: str
    weight_pct: float  # 0-100

    # Cost components, all in basis points. None when the pipeline could
    # not compute the component.
    expense_ratio_bps: float | None
    brokerage_commissions_bps: float | None
    underlying_funds_weighted_bps: float | None
    true_tco_bps: float | None  # Sum of the three above, or best-available

    # Contribution to portfolio TCO in bps (weight_fraction * true_tco_bps).
    portfolio_contribution_bps: float | None

    # Data-quality tag for the true_tco_bps figure.
    # One of: REPORTED, CALCULATED, PARTIAL, UNAVAILABLE
    data_quality: str

    # Any notes raised by detect_structure / rollup_costs for this holding.
    notes: list[str] = field(default_factory=list)

    # Structural flag — true if detect_structure classified as FoF.
    is_fund_of_funds: bool = False

    @property
    def weight_fraction(self) -> float:
        return self.weight_pct / 100.0


@dataclass
class CompoundDragProjection:
    """Compound-drag projection at a single horizon."""

    horizon_years: int
    terminal_wealth_true_tco: float  # portfolio grown at (gross - true_tco)
    terminal_wealth_stated_er: float  # portfolio grown at (gross - stated_er)
    drag_dollars: float  # stated - true, i.e. what the gap costs
    drag_percent: float  # drag_dollars / terminal_wealth_stated_er

    @property
    def drag_percent_display(self) -> str:
        return f"{self.drag_percent * 100:.1f}%"


@dataclass
class PortfolioTCO:
    """Portfolio-level total cost of ownership summary."""

    holdings: list[HoldingResult]

    # Weighted across holdings that have each component. Treated as bps.
    weighted_true_tco_bps: float
    weighted_expense_ratio_bps: float
    hidden_gap_bps: float  # weighted_true_tco_bps - weighted_expense_ratio_bps

    # Coverage: what fraction of portfolio weight we could price.
    priced_weight_fraction: float  # 0.0 - 1.0
    unpriced_weight_fraction: float

    # Compound-drag projections at each requested horizon.
    projections: list[CompoundDragProjection]

    # Projection inputs (for display).
    starting_balance: float
    gross_return_annual: float

    # Portfolio-level notes: unresolved tickers, missing data, etc.
    data_notes: list[str] = field(default_factory=list)

    @property
    def unpriced_weight_pct(self) -> float:
        return self.unpriced_weight_fraction * 100.0

    @property
    def priced_weight_pct(self) -> float:
        return self.priced_weight_fraction * 100.0


def rollup_portfolio(
    holdings: list[PortfolioHolding],
    starting_balance: float = DEFAULT_STARTING_BALANCE,
    gross_return_annual: float = DEFAULT_GROSS_RETURN,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> PortfolioTCO:
    """Run the full cost pipeline over each holding and aggregate.

    Delegation pattern: for each holding we call `identify_fund` then
    `detect_structure` (which already handles FoF recursion internally),
    `compute_costs`, and `rollup_costs`. The root `FundNode` has a
    `CostBreakdown.total_reported_bps` property that surfaces the full
    cost of ownership including rolled-up underlying funds.

    The portfolio-level aggregation is a weighted mean across holdings
    where each holding has a defined cost. Holdings that fail to price
    are tagged UNAVAILABLE and excluded from the weighted mean, with
    their combined weight surfaced as `unpriced_weight_fraction` so the
    user understands the coverage of the summary.

    Args:
        holdings: Non-empty list of `(ticker, weight)` positions.
        starting_balance: Dollar starting portfolio value for projection.
        gross_return_annual: Gross return before costs. 0.07 = 7%.
        horizons: Projection horizons in years.

    Returns:
        Fully populated `PortfolioTCO`.

    Raises:
        ValueError: If holdings is empty, any weight is <= 0, or the
            total weight falls outside the normalization tolerance.
    """
    if not holdings:
        raise ValueError("Portfolio must contain at least one holding.")

    # Collapse duplicate tickers first (case-insensitive). If the user
    # entered VTSAX twice, sum the weights rather than pretending they
    # are two separate positions.
    holdings = _collapse_duplicates(holdings)

    # Validate weights.
    for h in holdings:
        if h.weight <= 0:
            raise ValueError(
                f"Holding {h.ticker!r} has non-positive weight {h.weight}. "
                "All weights must be > 0."
            )

    # Check and normalize total weight.
    total_weight = sum(h.weight for h in holdings)
    weight_off = abs(total_weight - 100.0)
    if weight_off > WEIGHT_NORMALIZATION_TOLERANCE_PCT:
        raise ValueError(
            f"Portfolio weights sum to {total_weight:.2f}%, which is more than "
            f"{WEIGHT_NORMALIZATION_TOLERANCE_PCT}% away from 100%. "
            "Adjust the weights and try again."
        )
    # Normalize to exactly 100% so downstream math is clean.
    scale = 100.0 / total_weight
    holdings = [
        PortfolioHolding(ticker=h.ticker, weight=h.weight * scale, name=h.name)
        for h in holdings
    ]

    portfolio_notes: list[str] = []
    if weight_off > 0.01:
        portfolio_notes.append(
            f"Weights totaled {total_weight:.2f}%; normalized to 100.00% for the rollup."
        )

    # Price each holding.
    results: list[HoldingResult] = []
    for h in holdings:
        result = _price_holding(h)
        results.append(result)

    # Aggregate weighted costs across holdings that priced successfully.
    weighted_true_tco_bps = 0.0
    weighted_er_bps = 0.0
    priced_weight = 0.0

    for r in results:
        if r.true_tco_bps is None:
            # Unpriceable holding — note and skip from the weighted mean.
            portfolio_notes.append(
                f"{r.ticker}: unable to compute cost of ownership "
                f"({r.weight_pct:.2f}% of portfolio weight excluded from summary)."
            )
            continue
        priced_weight += r.weight_fraction
        weighted_true_tco_bps += r.weight_fraction * r.true_tco_bps
        if r.expense_ratio_bps is not None:
            weighted_er_bps += r.weight_fraction * r.expense_ratio_bps

    # Rebase weighted means to the priced fraction so they represent
    # the cost of the portion of the portfolio we could actually price.
    # Rebasing is honest: reporting a 30 bps weighted TCO as the
    # "portfolio cost" when 40% of the portfolio wasn't priced would
    # badly understate the true cost.
    if priced_weight > 0:
        weighted_true_tco_bps = weighted_true_tco_bps / priced_weight
        weighted_er_bps = weighted_er_bps / priced_weight
    else:
        weighted_true_tco_bps = 0.0
        weighted_er_bps = 0.0

    hidden_gap_bps = weighted_true_tco_bps - weighted_er_bps

    # Compound-drag projections. Only meaningful if we priced enough
    # of the portfolio; we still build them and let the coverage
    # fraction speak for itself.
    projections = [
        _project_compound_drag(
            horizon_years=h,
            starting_balance=starting_balance,
            gross_return_annual=gross_return_annual,
            true_tco_bps=weighted_true_tco_bps,
            stated_er_bps=weighted_er_bps,
        )
        for h in horizons
    ]

    # Roll up per-holding notes onto the portfolio for display.
    for r in results:
        for note in r.notes:
            portfolio_notes.append(f"{r.ticker}: {note}")

    return PortfolioTCO(
        holdings=results,
        weighted_true_tco_bps=weighted_true_tco_bps,
        weighted_expense_ratio_bps=weighted_er_bps,
        hidden_gap_bps=hidden_gap_bps,
        priced_weight_fraction=priced_weight,
        unpriced_weight_fraction=max(0.0, 1.0 - priced_weight),
        projections=projections,
        starting_balance=starting_balance,
        gross_return_annual=gross_return_annual,
        data_notes=portfolio_notes,
    )


def _collapse_duplicates(holdings: list[PortfolioHolding]) -> list[PortfolioHolding]:
    """If the user entered the same ticker twice, sum the weights."""
    merged: dict[str, PortfolioHolding] = {}
    for h in holdings:
        key = h.ticker.strip().upper()
        if not key:
            continue
        if key in merged:
            merged[key] = PortfolioHolding(
                ticker=key,
                weight=merged[key].weight + h.weight,
                name=merged[key].name or h.name,
            )
        else:
            merged[key] = PortfolioHolding(ticker=key, weight=h.weight, name=h.name)
    return list(merged.values())


def _price_holding(h: PortfolioHolding) -> HoldingResult:
    """Run the single-fund pipeline against one holding and unpack the result."""
    # The pipeline can fail at identify_fund (ticker not in SEC
    # mutual-fund universe — ETF, stock, crypto), at the filing retrieval
    # (filings missing), or anywhere downstream. Catch each failure mode
    # and return a well-tagged HoldingResult rather than bubbling to the
    # caller: a single bad ticker should not sink the whole portfolio.
    try:
        fund = identify_fund(h.ticker)
    except ValueError as e:
        return HoldingResult(
            ticker=h.ticker,
            fund_name=h.name or h.ticker,
            weight_pct=h.weight,
            expense_ratio_bps=None,
            brokerage_commissions_bps=None,
            underlying_funds_weighted_bps=None,
            true_tco_bps=None,
            portfolio_contribution_bps=None,
            data_quality="UNAVAILABLE",
            notes=[str(e)],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("identify_fund failed for %s: %s", h.ticker, exc)
        return HoldingResult(
            ticker=h.ticker,
            fund_name=h.name or h.ticker,
            weight_pct=h.weight,
            expense_ratio_bps=None,
            brokerage_commissions_bps=None,
            underlying_funds_weighted_bps=None,
            true_tco_bps=None,
            portfolio_contribution_bps=None,
            data_quality="UNAVAILABLE",
            notes=[f"Ticker resolution error: {exc!s}"],
        )

    # Run the rest of the pipeline.
    try:
        tree: FundNode = detect_structure(fund)
        tree = compute_costs(tree)

        # Hydrate ER onto the (now-populated) CostBreakdown from the
        # prospectus before rollup_costs, so a fund-of-funds wrapper
        # sees the child's stated ER when weighting. This mirrors the
        # single-fund API path; without this step the portfolio rollup
        # would claim ER is zero for every fund and the hidden-gap
        # number would be wrong.
        _hydrate_prospectus_er(tree, h.ticker, fund)

        tree = rollup_costs(tree)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Pipeline failed for %s: %s", h.ticker, exc)
        return HoldingResult(
            ticker=h.ticker,
            fund_name=fund.name or h.ticker,
            weight_pct=h.weight,
            expense_ratio_bps=None,
            brokerage_commissions_bps=None,
            underlying_funds_weighted_bps=None,
            true_tco_bps=None,
            portfolio_contribution_bps=None,
            data_quality="UNAVAILABLE",
            notes=[f"Pipeline failure: {exc!s}"],
        )

    return _holding_result_from_tree(h, tree)


def _hydrate_prospectus_er(tree: FundNode, ticker: str, fund) -> None:
    """Pull the 497K prospectus expense ratio onto the tree's CostBreakdown.

    The single-fund API path does this inline. The portfolio rollup
    needs the same step, otherwise the weighted stated-ER number is
    meaningless and the headline hidden-gap claim is wrong.

    Failures here are soft: if the prospectus is unavailable, the
    downstream `cost_breakdown.expense_ratio_bps` remains None and the
    holding's data_quality drops accordingly. We do not raise.
    """
    try:
        from fundautopsy.data.prospectus import retrieve_prospectus_fees
    except Exception as exc:  # noqa: BLE001
        logger.debug("Prospectus import failed: %s", exc)
        return

    try:
        fees = retrieve_prospectus_fees(
            ticker, series_id=fund.series_id, class_id=fund.class_id
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Prospectus fetch failed for %s: %s", ticker, exc)
        return
    if fees is None:
        return

    # Feed turnover into compute_costs so the cost model has the right
    # trading intensity (matches single-fund behavior).
    if fees.portfolio_turnover is not None:
        tree.prospectus_turnover = fees.portfolio_turnover

    if fees.expense_ratio_bps is None:
        return

    # Ensure CostBreakdown exists, then drop the ER on as a TaggedValue.
    cb = tree.cost_breakdown
    if cb is None:
        # The tree should always have a CostBreakdown by this point, but
        # fall through defensively rather than crashing the portfolio on
        # a single holding.
        return
    cb.expense_ratio_bps = TaggedValue(
        value=float(fees.expense_ratio_bps),
        tag=DataSourceTag.REPORTED,
        note="From 497K prospectus fee table.",
    )


def _holding_result_from_tree(h: PortfolioHolding, tree: FundNode) -> HoldingResult:
    """Extract the pricing components from a fully rolled-up FundNode tree."""
    cb = tree.cost_breakdown
    notes = list(tree.data_notes)

    er = _val_or_none(cb.expense_ratio_bps if cb else None)
    bc = _val_or_none(cb.brokerage_commissions_bps if cb else None)
    uf = _val_or_none(cb.underlying_funds_weighted_bps if cb else None)
    total = cb.total_reported_bps if cb else None

    # Data-quality tag is a signal to the user about how much of the
    # true-cost figure came from reported filings versus nothing at all.
    if total is None:
        quality = "UNAVAILABLE"
    elif er is not None and (tree.is_fund_of_funds and uf is not None):
        quality = "REPORTED"
    elif er is not None:
        quality = "REPORTED"
    elif uf is not None or bc is not None:
        quality = "PARTIAL"
    else:
        quality = "CALCULATED"

    return HoldingResult(
        ticker=h.ticker,
        fund_name=tree.metadata.name or h.ticker,
        weight_pct=h.weight,
        expense_ratio_bps=er,
        brokerage_commissions_bps=bc,
        underlying_funds_weighted_bps=uf,
        true_tco_bps=total,
        portfolio_contribution_bps=(
            (h.weight / 100.0) * total if total is not None else None
        ),
        data_quality=quality,
        notes=notes,
        is_fund_of_funds=tree.is_fund_of_funds,
    )


def _val_or_none(tagged) -> float | None:
    """Pull the numeric value out of a TaggedValue if available, else None."""
    if tagged is None:
        return None
    if not getattr(tagged, "is_available", False):
        return None
    return tagged.value


def _project_compound_drag(
    horizon_years: int,
    starting_balance: float,
    gross_return_annual: float,
    true_tco_bps: float,
    stated_er_bps: float,
) -> CompoundDragProjection:
    """Compute the terminal-wealth gap between stated ER and true TCO.

    The math is deliberately simple: constant real return per year,
    fully reinvested, no taxes, no inflation adjustment, no Monte Carlo.
    What this captures is the compound arithmetic — a 50 bps annual cost
    delta over 30 years at 7% gross is not a rounding error. What it
    does not capture is sequence risk, which lives in v2.
    """
    true_net = gross_return_annual - (true_tco_bps / 10_000.0)
    stated_net = gross_return_annual - (stated_er_bps / 10_000.0)

    terminal_true = starting_balance * ((1 + true_net) ** horizon_years)
    terminal_stated = starting_balance * ((1 + stated_net) ** horizon_years)
    drag_dollars = terminal_stated - terminal_true
    drag_percent = drag_dollars / terminal_stated if terminal_stated > 0 else 0.0

    return CompoundDragProjection(
        horizon_years=horizon_years,
        terminal_wealth_true_tco=terminal_true,
        terminal_wealth_stated_er=terminal_stated,
        drag_dollars=drag_dollars,
        drag_percent=drag_percent,
    )


def parse_portfolio_input(raw: str) -> list[PortfolioHolding]:
    """Parse a textarea-style portfolio string into PortfolioHolding objects.

    Accepts one holding per line. Each line has a ticker and a weight,
    separated by whitespace, tab, comma, or colon. The weight may have a
    trailing percent sign. Blank lines and lines starting with '#' are
    ignored as comments.

    Examples of accepted input::

        VTSAX 60
        VTIAX, 30
        VBTLX: 10%

    Raises:
        ValueError: On unparseable lines or zero holdings after parse.
    """
    holdings: list[PortfolioHolding] = []
    for line_no, raw_line in enumerate(raw.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Accept common separators by normalizing to whitespace.
        normalized = line.replace(",", " ").replace(":", " ").replace("\t", " ")
        normalized = normalized.replace("%", "")
        parts = normalized.split()
        if len(parts) < 2:
            raise ValueError(
                f"Line {line_no}: expected ticker and weight, got {raw_line!r}."
            )
        ticker = parts[0].strip().upper()
        try:
            weight = float(parts[1])
        except ValueError:
            raise ValueError(
                f"Line {line_no}: could not parse weight {parts[1]!r} as a number."
            )
        if not ticker.isalpha() or not 1 <= len(ticker) <= 6:
            raise ValueError(
                f"Line {line_no}: {ticker!r} does not look like a mutual fund ticker."
            )
        holdings.append(PortfolioHolding(ticker=ticker, weight=weight))

    if not holdings:
        raise ValueError("No holdings found in portfolio input.")
    return holdings
