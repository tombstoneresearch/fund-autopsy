"""The Fund Graveyard: harvesting fund deaths from EDGAR form indexes.

Form N-8F is the application a registered investment company files to
deregister: the death certificate. Form N-14 is the merger/
reorganization filing: often the cause of death. EDGAR publishes
quarterly form indexes (form.idx) listing every filing; this module
harvests N-8F and N-14 events from 2018 forward into a dataset nobody
else maintains, the raw material for survivorship-bias work.

Resumable by quarter: each quarter's filtered rows cache to disk, so
interrupted scans resume where they stopped.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any, Callable

import httpx

FORM_INDEX_URL = "https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{q}/form.idx"
TARGET_PREFIXES = ("N-8F", "N-14")


def _quarters(start_year: int = 2018) -> list[tuple[int, int]]:
    today = date.today()
    out = []
    for y in range(start_year, today.year + 1):
        for q in range(1, 5):
            if y == today.year and q > (today.month - 1) // 3 + 1:
                break
            out.append((y, q))
    return out


def _parse_form_idx(text: str) -> list[dict[str, str]]:
    """Parse the fixed-width form.idx into filtered rows."""
    rows: list[dict[str, str]] = []
    lines = text.splitlines()
    # Locate the header separator; data follows the dashed line.
    start = 0
    for i, line in enumerate(lines[:20]):
        if set(line.strip()) == {"-"}:
            start = i + 1
            break
    for line in lines[start:]:
        if not line.strip():
            continue
        form = line[:12].strip()
        if not form.startswith(TARGET_PREFIXES):
            continue
        company = line[12:74].strip()
        cik = line[74:86].strip()
        filed = line[86:98].strip()
        filename = line[98:].strip()
        rows.append(
            {
                "form": form,
                "company": company,
                "cik": cik,
                "date_filed": filed,
                "filing_path": filename,
                "event": "deregistration" if form.startswith("N-8F") else "merger/reorg",
            }
        )
    return rows


def scan(
    out_root: Path,
    start_year: int = 2018,
    client: httpx.Client | None = None,
    on_progress: Callable[[str], None] | None = None,
    time_budget_s: float | None = None,
) -> dict[str, Any]:
    """Harvest all quarters, resumably. Returns summary counts."""
    import time

    from fundautopsy.data.edgar import get_edgar_client

    t0 = time.time()
    raw_dir = Path(out_root) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    own = client is None
    if own:
        client = get_edgar_client()
    fetched = skipped = 0
    try:
        for y, q in _quarters(start_year):
            cache = raw_dir / f"{y}Q{q}.csv"
            if cache.exists():
                skipped += 1
                continue
            if time_budget_s and (time.time() - t0) > time_budget_s:
                break
            resp = client.get(FORM_INDEX_URL.format(year=y, q=q))
            resp.raise_for_status()
            rows = _parse_form_idx(resp.text)
            with cache.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(
                    f, fieldnames=["form", "company", "cik", "date_filed", "filing_path", "event"]
                )
                w.writeheader()
                w.writerows(rows)
            fetched += 1
            if on_progress:
                on_progress(f"{y}Q{q}: {len(rows)} events")
    finally:
        if own:
            client.close()
    return {"quarters_fetched": fetched, "quarters_cached": skipped}


def aggregate(out_root: Path) -> dict[str, Any]:
    """Combine quarter caches into graveyard.csv plus summary counts."""
    raw_dir = Path(out_root) / "raw"
    all_rows: list[dict[str, str]] = []
    for p in sorted(raw_dir.glob("*.csv")):
        with p.open(encoding="utf-8") as f:
            all_rows.extend(csv.DictReader(f))
    all_rows.sort(key=lambda r: r["date_filed"])
    combined = Path(out_root) / "graveyard.csv"
    with combined.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["form", "company", "cik", "date_filed", "filing_path", "event"]
        )
        w.writeheader()
        w.writerows(all_rows)

    by_year: dict[str, dict[str, int]] = {}
    for r in all_rows:
        y = r["date_filed"][:4]
        d = by_year.setdefault(y, {"deregistration": 0, "merger/reorg": 0})
        d[r["event"]] += 1
    return {
        "total_events": len(all_rows),
        "deregistrations": sum(1 for r in all_rows if r["event"] == "deregistration"),
        "mergers": sum(1 for r in all_rows if r["event"] == "merger/reorg"),
        "by_year": by_year,
        "csv": str(combined),
    }
