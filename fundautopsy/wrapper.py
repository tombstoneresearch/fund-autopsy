"""Target-date / fund-of-funds wrapper-fee decomposition.

Computes the number no fee table prints: what the wrapper itself
charges, defined as the fund's stated expense ratio minus the
allocation-weighted expense ratios of its underlying funds.

Integrity guards, because this computation has a known failure mode:
share-class misresolution. TDF wrappers hold institutional classes
(R-6, Z, K); name-based fallback resolution picks retail classes with
much higher ERs, inflating the underlying cost and understating the
wrapper (v1 postmortem, AADTX/Task 35). Therefore:

  1. If the OpenFIGI CUSIP path is disabled or unavailable, the result
     is stamped LOW CONFIDENCE and says why.
  2. Resolved-weight coverage below the threshold refuses a verdict
     rather than extrapolating.
  3. Every underlying fund is listed with its resolved ticker and ER so
     a human can eyeball class sanity before anything publishes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

COVERAGE_THRESHOLD = 0.90


@dataclass
class UnderlyingRow:
    ticker: str
    name: str
    weight: float  # fraction of resolved fund allocation (0-1)
    er_bps: float | None
    note: str = ""


@dataclass
class WrapperResult:
    ticker: str
    name: str
    stated_er_bps: float | None
    weighted_underlying_bps: float | None
    wrapper_bps: float | None
    resolved_weight: float  # fraction of fund-holdings NAV resolved to children
    coverage_ok: bool
    confidence: str  # "high" | "LOW — CUSIP resolution unavailable" | reason
    rows: list[UnderlyingRow] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def publishable(self) -> bool:
        return (
            self.coverage_ok
            and self.confidence == "high"
            and self.wrapper_bps is not None
        )


def _openfigi_available() -> bool:
    from fundautopsy.data import edgar

    return not edgar._openfigi_disabled  # noqa: SLF001 — deliberate introspection


def compute_wrapper(ticker: str) -> WrapperResult:
    """Run the full decomposition for one fund-of-funds ticker."""
    from fundautopsy.doctor import run_pipeline

    report = run_pipeline(ticker.upper())
    result = WrapperResult(
        ticker=ticker.upper(), name="", stated_er_bps=None,
        weighted_underlying_bps=None, wrapper_bps=None,
        resolved_weight=0.0, coverage_ok=False,
        confidence="high" if _openfigi_available() else
        "LOW — CUSIP resolution unavailable; children may be misresolved retail classes",
    )
    if not report.completed or report.result is None:
        result.problems.append(f"Pipeline did not complete: {report.verdict}")
        return result

    root = report.result
    result.name = getattr(root.metadata, "name", "") or ""
    cb = root.cost_breakdown
    if cb is not None and cb.expense_ratio_bps is not None and cb.expense_ratio_bps.is_available:
        result.stated_er_bps = cb.expense_ratio_bps.value

    children = list(getattr(root, "children", []) or [])
    if not children:
        result.problems.append(
            "No underlying funds resolved. For internal-series wrappers "
            "(Fidelity Freedom, T. Rowe Retirement) this usually means the "
            "CUSIP resolver was unavailable."
        )
        return result

    total_w = 0.0
    weighted = 0.0
    covered_w = 0.0
    for child in children:
        w = getattr(child, "allocation_weight", None) or 0.0
        c_cb = child.cost_breakdown
        er = (
            c_cb.expense_ratio_bps.value
            if c_cb is not None
            and c_cb.expense_ratio_bps is not None
            and c_cb.expense_ratio_bps.is_available
            else None
        )
        row = UnderlyingRow(
            ticker=getattr(child.metadata, "ticker", "?"),
            name=getattr(child.metadata, "name", "") or "",
            weight=w,
            er_bps=er,
            note="" if er is not None else "no fee table resolved",
        )
        result.rows.append(row)
        total_w += w
        if er is not None:
            weighted += w * er
            covered_w += w

    result.resolved_weight = covered_w
    result.coverage_ok = covered_w >= COVERAGE_THRESHOLD
    if covered_w > 0:
        result.weighted_underlying_bps = round(weighted / covered_w, 2)
    if result.stated_er_bps is not None and result.weighted_underlying_bps is not None:
        result.wrapper_bps = round(
            result.stated_er_bps - result.weighted_underlying_bps, 2
        )
    if not result.coverage_ok:
        result.problems.append(
            f"Fee coverage {covered_w:.0%} of resolved allocation is below the "
            f"{COVERAGE_THRESHOLD:.0%} threshold; refusing a publishable verdict."
        )
    return result


def render_wrapper(result: WrapperResult, console: Any) -> None:
    console.print(f"\n[bold]Wrapper decomposition[/bold] — {result.ticker}  {result.name}")
    console.print(f"  Confidence: {result.confidence}")
    for p in result.problems:
        console.print(f"  [yellow]! {p}[/yellow]")
    console.print(
        f"  Stated ER: {result.stated_er_bps} bps | weighted underlying: "
        f"{result.weighted_underlying_bps} bps | [bold]wrapper: {result.wrapper_bps} bps[/bold] "
        f"| fee coverage {result.resolved_weight:.0%}"
    )
    for r in sorted(result.rows, key=lambda x: -x.weight):
        er = f"{r.er_bps:>7.1f}" if r.er_bps is not None else "      —"
        console.print(f"    {r.weight:6.1%}  {er} bps  {r.ticker:<7} {r.name[:52]} {r.note}")
    verdict = "PUBLISHABLE" if result.publishable else "NOT PUBLISHABLE (see flags above)"
    console.print(f"  Verdict: [bold]{verdict}[/bold]\n")
