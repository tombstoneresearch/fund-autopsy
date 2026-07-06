"""Batch snapshot runner.

Publish-time analysis: run the full pipeline over a list of tickers and
write one JSON snapshot per fund, each carrying its own stage-by-stage
provenance report. The static site renders exclusively from these
snapshots, so nothing unreviewed and nothing computed at request time is
ever published.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

SNAPSHOT_VERSION = "2.0"


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

        report = pipeline(ticker)
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
