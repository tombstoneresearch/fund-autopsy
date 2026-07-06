"""Batch snapshot runner.

Publish-time analysis: run the full pipeline over a list of tickers and
write one JSON snapshot per fund, each carrying its own stage-by-stage
provenance report. The static site renders exclusively from these
snapshots, so nothing unreviewed and nothing computed at request time is
ever published.
"""

from __future__ import annotations

import json
import signal
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

SNAPSHOT_VERSION = "2.0"

DEFAULT_PER_FUND_TIMEOUT_S = 180


class FundTimeout(Exception):
    """Raised inside a pipeline stage when the per-fund wall clock expires."""


class _fund_deadline:
    """SIGALRM-based wall-clock guard around one fund's pipeline run.

    A hung EDGAR request or a pathological registrant scan becomes a
    legible stage failure ("FundTimeout: exceeded Ns") instead of a
    silent multi-minute stall — the exact v1 failure mode that drove
    the operator away. Unix main-thread only; a zero/None timeout
    disables the guard.
    """

    def __init__(self, seconds: int | None):
        self.seconds = seconds or 0

    def __enter__(self) -> None:
        if self.seconds > 0:
            def _raise(_signum: int, _frame: Any) -> None:
                raise FundTimeout(
                    f"exceeded the {self.seconds}s per-fund wall clock"
                )

            self._old = signal.signal(signal.SIGALRM, _raise)
            signal.alarm(self.seconds)

    def __exit__(self, *exc: Any) -> None:
        if self.seconds > 0:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, self._old)


def default_quarter_label(today: date | None = None) -> str:
    """YYYY-Qn label used as the snapshot directory name."""
    d = today or date.today()
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


@dataclass
class BatchSummary:
    """Aggregate outcome of a batch run."""

    quarter: str
    out_dir: Path
    complete: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_version": SNAPSHOT_VERSION,
            "quarter": self.quarter,
            "generated": str(date.today()),
            "complete": self.complete,
            "complete_with_caveats": self.caveats,
            "excluded": self.excluded,
            "skipped_existing": self.skipped,
        }


def _default_serializer(node: Any) -> dict[str, Any]:
    from fundautopsy.export.json_export import _serialize_node

    return _serialize_node(node)


def run_batch(
    tickers: list[str],
    out_root: Path,
    force: bool = False,
    pipeline: Callable[[str], Any] | None = None,
    serializer: Callable[[Any], dict[str, Any]] | None = None,
    on_progress: Callable[[str, str], None] | None = None,
    per_fund_timeout_s: int | None = DEFAULT_PER_FUND_TIMEOUT_S,
) -> BatchSummary:
    """Analyze each ticker and write per-fund snapshots plus a manifest.

    Args:
        tickers: Ticker symbols to analyze.
        out_root: Snapshot root; files land in ``out_root/YYYY-Qn/``.
        force: Re-analyze tickers whose snapshot already exists.
        pipeline: Injection seam for tests; defaults to ``doctor.run_pipeline``.
        serializer: Injection seam for tests; defaults to the JSON exporter.
        on_progress: Optional callback ``(ticker, status)`` per fund.
    """
    if pipeline is None:
        from fundautopsy.doctor import run_pipeline as pipeline  # type: ignore[assignment]
    if serializer is None:
        serializer = _default_serializer

    quarter = default_quarter_label()
    out_dir = Path(out_root) / quarter
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = BatchSummary(quarter=quarter, out_dir=out_dir)

    for raw in tickers:
        ticker = raw.strip().upper()
        if not ticker or ticker.startswith("#"):
            continue
        snap_path = out_dir / f"{ticker}.json"
        if snap_path.exists() and not force:
            summary.skipped.append(ticker)
            if on_progress:
                on_progress(ticker, "skipped (snapshot exists)")
            continue

        report = None
        crash_reason: str | None = None
        try:
            with _fund_deadline(per_fund_timeout_s):
                report = pipeline(ticker)
        except FundTimeout as exc:
            crash_reason = f"Wall clock: {exc}"
        except Exception as exc:  # noqa: BLE001 — one fund must never kill the batch
            crash_reason = f"Pipeline crash outside stage handling: {type(exc).__name__}: {exc}"

        if report is None:
            snapshot = {
                "snapshot_version": SNAPSHOT_VERSION,
                "generated": str(date.today()),
                "quarter": quarter,
                "ticker": ticker,
                "provenance": {
                    "ticker": ticker,
                    "verdict": f"EXCLUDED — {crash_reason}",
                    "completed": False,
                    "stages": [],
                    "quality_notes": [],
                },
                "analysis": None,
                "excluded_reason": crash_reason,
            }
            snap_path.write_text(
                json.dumps(snapshot, indent=2, default=str), encoding="utf-8"
            )
            summary.excluded.append(ticker)
            if on_progress:
                on_progress(ticker, f"excluded ({crash_reason})")
            continue

        snapshot: dict[str, Any] = {
            "snapshot_version": SNAPSHOT_VERSION,
            "generated": str(date.today()),
            "quarter": quarter,
            "ticker": ticker,
            "provenance": report.to_dict(),
        }
        if report.completed:
            snapshot["analysis"] = serializer(report.result)
            if report.quality_notes:
                summary.caveats.append(ticker)
                status = "complete with caveats"
            else:
                summary.complete.append(ticker)
                status = "complete"
        else:
            snapshot["analysis"] = None
            failed = next(
                (s for s in report.stages if s.status == "failed"), None
            )
            snapshot["excluded_reason"] = (
                f"{failed.label}: {failed.detail}" if failed else "unknown failure"
            )
            summary.excluded.append(ticker)
            status = "excluded"

        snap_path.write_text(
            json.dumps(snapshot, indent=2, default=str), encoding="utf-8"
        )
        if on_progress:
            on_progress(ticker, status)

    (out_dir / "manifest.json").write_text(
        json.dumps(summary.to_dict(), indent=2), encoding="utf-8"
    )
    return summary
