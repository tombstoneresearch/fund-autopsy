"""Pipeline diagnostics.

Answers one question in plain English: when a ticker cannot be analyzed,
which stage failed, what was tried, and what to do next. The same
stage-by-stage report is embedded in every batch snapshot, so no number
ever reaches an artifact without a legible provenance trail.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

STAGE_HINTS: dict[str, str] = {
    "resolve": (
        "The ticker did not resolve to a CIK, series, and class. Check the "
        "spelling first. Then check the SEC's authoritative series/class "
        "census (investment-company-series-class CSV at sec.gov): if the "
        "ticker is absent there, it is dead or renamed and no amount of "
        "retrying will resolve it (this was the case with LIPSX, 2026-07). "
        "If it IS in the census, record it as a resolution gap."
    ),
    "structure": (
        "Filings could not be retrieved or parsed into a holdings "
        "structure. Common causes: EDGAR throttling or outage, an "
        "umbrella-trust filing layout the walker does not recognize, or a "
        "dormant fund that has stopped filing per-class prospectuses."
    ),
    "costs": (
        "Fee extraction or cost computation failed on retrieved filings. "
        "Usually a fee-table layout none of the parsers recognize (497K, "
        "family-specific, then 485BPOS XBRL all missed). The filing itself "
        "is worth a manual look."
    ),
    "rollup": (
        "Fund-of-funds rollup failed. Usually an unresolved underlying "
        "fund, or a very large wrapper hitting memory limits. Re-run with "
        "the batch runner, which processes children with a persistent "
        "cache."
    ),
    "fees": (
        "Prospectus fee extraction failed: none of the 497K, family-"
        "specific, or 485BPOS XBRL parsers produced a fee table. The "
        "fund renders without a stated expense ratio (shown as a gap, "
        "not a zero). Worth a manual look at the filing."
    ),
}


@dataclass
class StageResult:
    """Outcome of a single pipeline stage."""

    name: str
    label: str
    status: str  # "ok" | "degraded" | "failed" | "skipped"
    seconds: float = 0.0
    detail: str = ""
    hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.name,
            "label": self.label,
            "status": self.status,
            "seconds": round(self.seconds, 2),
            "detail": self.detail,
            "hint": self.hint,
        }


@dataclass
class PipelineReport:
    """Full stage-by-stage account of one ticker's analysis run."""

    ticker: str
    stages: list[StageResult] = field(default_factory=list)
    quality_notes: list[str] = field(default_factory=list)
    result: Any | None = None  # FundNode when the pipeline completes

    @property
    def completed(self) -> bool:
        return self.result is not None and not any(
            s.status == "failed" for s in self.stages
        )

    @property
    def verdict(self) -> str:
        if not self.completed:
            failed = next((s for s in self.stages if s.status == "failed"), None)
            where = f" at stage '{failed.name}'" if failed else ""
            return f"EXCLUDED — analysis failed{where}."
        if self.quality_notes:
            return "COMPLETE WITH CAVEATS — see data notes."
        return "COMPLETE — all stages clean."

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "verdict": self.verdict,
            "completed": self.completed,
            "stages": [s.to_dict() for s in self.stages],
            "quality_notes": self.quality_notes,
        }


def _collect_quality_notes(node: Any) -> list[str]:
    """Walk a FundNode tree and gather every data note as a caveat."""
    notes: list[str] = []
    try:
        for n in node.walk():
            for note in getattr(n, "data_notes", []) or []:
                label = getattr(getattr(n, "metadata", None), "ticker", "") or "?"
                notes.append(f"{label}: {note}")
    except Exception:  # noqa: BLE001 — diagnostics must never crash the pipeline
        pass
    return notes


def _enrich_root_fees(root: Any) -> StageResult:
    """Populate the root node's stated fee facts from the prospectus.

    v1's CLI pipeline never carried the stated expense ratio — only the
    web app fetched it, separately. Snapshots therefore lacked the one
    number every reader anchors on. This stage closes that gap for the
    root fund. Non-fatal by design: a fund whose fee table resists all
    three parser families still renders, with the stated column shown
    as an honest gap.
    """
    label = "Retrieve stated fees from prospectus (497K/485BPOS)"
    t0 = time.perf_counter()
    try:
        from fundautopsy.data.prospectus import retrieve_prospectus_fees
        from fundautopsy.models.filing_data import DataSourceTag, TaggedValue

        ticker = getattr(getattr(root, "metadata", None), "ticker", None)
        cb = getattr(root, "cost_breakdown", None)
        if not ticker or cb is None:
            return StageResult(
                "fees", label, "degraded", time.perf_counter() - t0,
                detail="No root ticker or cost breakdown to enrich.",
            )
        fees = retrieve_prospectus_fees(ticker)
        if fees is None:
            return StageResult(
                "fees", label, "degraded", time.perf_counter() - t0,
                detail="No parseable fee table found.",
                hint=STAGE_HINTS.get("fees", ""),
            )

        def _bps(pct: float | None) -> float | None:
            return round(pct * 100.0, 2) if pct is not None else None

        er_pct = fees.net_expenses if fees.net_expenses is not None else fees.total_annual_expenses
        if cb.expense_ratio_bps is None and er_pct is not None:
            cb.expense_ratio_bps = TaggedValue(
                value=_bps(er_pct), tag=DataSourceTag.REPORTED,
                note="Prospectus fee table",
            )
        if cb.management_fee_bps is None and fees.management_fee is not None:
            cb.management_fee_bps = TaggedValue(
                value=_bps(fees.management_fee), tag=DataSourceTag.REPORTED,
            )
        if cb.twelve_b1_fee_bps is None and fees.twelve_b1_fee is not None:
            cb.twelve_b1_fee_bps = TaggedValue(
                value=_bps(fees.twelve_b1_fee), tag=DataSourceTag.REPORTED,
            )
        if fees.portfolio_turnover is not None and getattr(root, "prospectus_turnover", None) is None:
            try:
                root.prospectus_turnover = fees.portfolio_turnover
            except Exception:  # noqa: BLE001 — attribute optional on some nodes
                pass
        return StageResult("fees", label, "ok", time.perf_counter() - t0)
    except Exception as exc:  # noqa: BLE001 — never fail the run over fees
        return StageResult(
            "fees", label, "degraded", time.perf_counter() - t0,
            detail=f"{type(exc).__name__}: {exc}",
            hint=STAGE_HINTS.get("fees", ""),
        )


def run_pipeline(ticker: str) -> PipelineReport:
    """Run the four analysis stages one at a time, timing and trapping each."""
    from fundautopsy.core.costs import compute_costs
    from fundautopsy.core.fund import identify_fund
    from fundautopsy.core.rollup import rollup_costs
    from fundautopsy.core.structure import detect_structure

    report = PipelineReport(ticker=ticker.upper())
    steps: list[tuple[str, str, Any]] = [
        ("resolve", "Resolve ticker to CIK / series / class", lambda _: identify_fund(ticker)),
        ("structure", "Retrieve filings, detect fund structure", detect_structure),
        ("costs", "Extract fees, compute cost estimates", compute_costs),
        ("rollup", "Roll up fund-of-funds cost tree", rollup_costs),
    ]

    value: Any = None
    failed = False
    for name, label, fn in steps:
        if failed:
            report.stages.append(
                StageResult(name, label, "skipped", hint="Skipped: an earlier stage failed.")
            )
            continue
        t0 = time.perf_counter()
        try:
            value = fn(value)
            elapsed = time.perf_counter() - t0
            if value is None:
                failed = True
                report.stages.append(
                    StageResult(
                        name, label, "failed", elapsed,
                        detail="Stage returned no result (None).",
                        hint=STAGE_HINTS.get(name, ""),
                    )
                )
            else:
                report.stages.append(StageResult(name, label, "ok", elapsed))
        except MemoryError as exc:
            failed = True
            report.stages.append(
                StageResult(
                    name, label, "failed", time.perf_counter() - t0,
                    detail=f"MemoryError: {exc}",
                    hint=STAGE_HINTS.get("rollup", ""),
                )
            )
        except Exception as exc:  # noqa: BLE001 — the whole point is a legible failure
            failed = True
            report.stages.append(
                StageResult(
                    name, label, "failed", time.perf_counter() - t0,
                    detail=f"{type(exc).__name__}: {exc}",
                    hint=STAGE_HINTS.get(name, ""),
                )
            )

    if not failed and value is not None:
        report.stages.append(_enrich_root_fees(value))
        report.result = value
        report.quality_notes = _collect_quality_notes(value)
        if report.quality_notes:
            # Mark the costs stage degraded so the caveat is visible at stage level.
            for s in report.stages:
                if s.name == "costs" and s.status == "ok":
                    s.status = "degraded"
                    s.detail = f"{len(report.quality_notes)} data note(s); see quality_notes."
    return report


def render_report(report: PipelineReport, console: Any) -> None:
    """Print a plain-English diagnosis to a rich console."""
    icons = {"ok": "[green]OK[/green]", "degraded": "[yellow]DEGRADED[/yellow]",
             "failed": "[red]FAILED[/red]", "skipped": "[dim]SKIPPED[/dim]"}
    console.print(f"\n[bold]Fund Autopsy doctor[/bold] — {report.ticker}\n")
    for s in report.stages:
        line = f"  {icons.get(s.status, s.status):<10}  {s.label}  [dim]({s.seconds:.1f}s)[/dim]"
        console.print(line)
        if s.detail:
            console.print(f"             [dim]{s.detail}[/dim]")
        if s.hint and s.status == "failed":
            console.print(f"             [italic]{s.hint}[/italic]")
    if report.quality_notes:
        console.print("\n  [bold]Data notes:[/bold]")
        for note in report.quality_notes[:20]:
            console.print(f"   - {note}")
        if len(report.quality_notes) > 20:
            console.print(f"   … and {len(report.quality_notes) - 20} more")
    console.print(f"\n  [bold]Verdict:[/bold] {report.verdict}\n")
