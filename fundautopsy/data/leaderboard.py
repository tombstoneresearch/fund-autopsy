"""Worst Offender Leaderboard — community-driven fund cost rankings.

The leaderboard populates exclusively from user lookups. Every time someone
runs a fund analysis, the result gets recorded here. This gamifies usage:
people will hunt for the worst funds to put on the board.

Storage: simple JSON file. No database dependency for pre-launch.
Thread-safe via file locking on write.
"""

from __future__ import annotations

import json
import fcntl
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Default location — can be overridden for testing
_LEADERBOARD_DIR = Path(__file__).parent.parent.parent / "data"
_LEADERBOARD_FILE = _LEADERBOARD_DIR / "leaderboard.json"


@dataclass
class LeaderboardEntry:
    """A single fund's leaderboard record."""

    ticker: str
    name: str
    family: str
    hidden_cost_mid_bps: float  # midpoint of hidden cost range
    hidden_cost_low_bps: float
    hidden_cost_high_bps: float
    expense_ratio_bps: Optional[float]
    true_cost_mid_bps: Optional[float]  # ER + hidden midpoint
    turnover_pct: Optional[float]
    net_assets_display: str
    holdings_count: int
    grade: str  # A-F letter grade
    conflict_count: int
    lookup_count: int  # how many times users have looked this up
    last_updated: str  # ISO date
    dollar_impact_20yr: Optional[float]  # hidden cost dollars per $100K


def _grade_from_hidden(low: float, high: float) -> str:
    """Assign letter grade based on hidden cost midpoint."""
    mid = (low + high) / 2
    if mid < 10:
        return "A"
    if mid < 25:
        return "B"
    if mid < 50:
        return "C"
    if mid < 100:
        return "D"
    return "F"


_REQUIRED_KEYS = frozenset({"ticker", "hidden_cost_mid_bps"})


def _load_leaderboard(path: Path = _LEADERBOARD_FILE) -> dict[str, dict]:
    """Load leaderboard from disk. Returns dict keyed by ticker.

    Entries missing required keys are silently dropped to prevent
    corrupted data from propagating through the leaderboard.
    """
    if not path.exists():
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return {}
        result = {}
        for entry in data:
            if isinstance(entry, dict) and _REQUIRED_KEYS.issubset(entry.keys()):
                result[entry["ticker"]] = entry
        return result
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}


MAX_LEADERBOARD_ENTRIES: int = 1000


def _save_leaderboard(entries: dict[str, dict], path: Path = _LEADERBOARD_FILE) -> None:
    """Save leaderboard to disk with file locking.

    Entries are sorted by hidden cost (worst first) and capped at
    MAX_LEADERBOARD_ENTRIES to prevent unbounded growth.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    sorted_entries = sorted(
        entries.values(),
        key=lambda e: e.get("hidden_cost_mid_bps", 0),
        reverse=True,
    )
    # Cap entries to prevent unbounded growth
    sorted_entries = sorted_entries[:MAX_LEADERBOARD_ENTRIES]
    with open(path, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        json.dump(sorted_entries, f, indent=2)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def update_leaderboard(
    ticker: str,
    name: str,
    family: str,
    hidden_low_bps: float | None,
    hidden_high_bps: float | None,
    expense_ratio_bps: float | None,
    turnover_pct: float | None,
    net_assets_display: str,
    holdings_count: int,
    conflict_count: int,
    dollar_impact_hidden_low: float | None,
    dollar_impact_hidden_high: float | None,
    path: Path = _LEADERBOARD_FILE,
) -> None:
    """Add or update a fund on the leaderboard after analysis."""
    if hidden_low_bps is None or hidden_high_bps is None:
        return  # Can't rank without hidden cost data

    entries = _load_leaderboard(path)
    mid = (hidden_low_bps + hidden_high_bps) / 2
    grade = _grade_from_hidden(hidden_low_bps, hidden_high_bps)

    true_cost_mid = None
    if expense_ratio_bps is not None:
        true_cost_mid = expense_ratio_bps + mid

    dollar_impact = None
    if dollar_impact_hidden_low is not None and dollar_impact_hidden_high is not None:
        dollar_impact = (dollar_impact_hidden_low + dollar_impact_hidden_high) / 2

    existing = entries.get(ticker, {})
    lookup_count = existing.get("lookup_count", 0) + 1

    from datetime import date

    entries[ticker] = {
        "ticker": ticker,
        "name": name,
        "family": family,
        "hidden_cost_mid_bps": round(mid, 2),
        "hidden_cost_low_bps": round(hidden_low_bps, 2),
        "hidden_cost_high_bps": round(hidden_high_bps, 2),
        "expense_ratio_bps": round(expense_ratio_bps, 2) if expense_ratio_bps else None,
        "true_cost_mid_bps": round(true_cost_mid, 2) if true_cost_mid else None,
        "turnover_pct": round(turnover_pct, 1) if turnover_pct else None,
        "net_assets_display": net_assets_display,
        "holdings_count": holdings_count,
        "grade": grade,
        "conflict_count": conflict_count,
        "lookup_count": lookup_count,
        "last_updated": str(date.today()),
        "dollar_impact_20yr": round(dollar_impact, 2) if dollar_impact else None,
    }

    _save_leaderboard(entries, path)


def get_leaderboard(
    sort_by: str = "hidden_cost_mid_bps",
    limit: int = 25,
    path: Path = _LEADERBOARD_FILE,
) -> list[dict]:
    """Return the leaderboard sorted by the specified field.

    sort_by options: hidden_cost_mid_bps, true_cost_mid_bps,
                     lookup_count, conflict_count, turnover_pct
    """
    entries = _load_leaderboard(path)
    items = list(entries.values())

    reverse = True  # worst first for all metrics
    if sort_by == "grade":
        grade_order = {"F": 0, "D": 1, "C": 2, "B": 3, "A": 4}
        items.sort(key=lambda e: grade_order.get(e.get("grade", "C"), 2))
    else:
        # None/missing values sort last (below all real data) by using
        # -inf as the key when sorting descending (worst-first).
        items.sort(
            key=lambda e: e.get(sort_by) if e.get(sort_by) is not None else float("-inf"),
            reverse=reverse,
        )

    return items[:limit]


def get_leaderboard_stats(path: Path = _LEADERBOARD_FILE) -> dict:
    """Summary stats for the leaderboard."""
    entries = _load_leaderboard(path)
    if not entries:
        return {
            "total_funds": 0,
            "total_lookups": 0,
            "worst_ticker": None,
            "worst_hidden_bps": None,
            "avg_hidden_bps": None,
        }

    items = list(entries.values())
    total_lookups = sum(e.get("lookup_count", 0) for e in items)
    hidden_costs = [e["hidden_cost_mid_bps"] for e in items if e.get("hidden_cost_mid_bps")]
    worst = max(items, key=lambda e: e.get("hidden_cost_mid_bps", 0))

    return {
        "total_funds": len(items),
        "total_lookups": total_lookups,
        "worst_ticker": worst["ticker"],
        "worst_hidden_bps": worst["hidden_cost_mid_bps"],
        "avg_hidden_bps": round(sum(hidden_costs) / len(hidden_costs), 1) if hidden_costs else None,
    }
