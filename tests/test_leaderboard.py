"""Tests for the leaderboard module."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fundautopsy.data.leaderboard import (
    _grade_from_hidden,
    _load_leaderboard,
    _save_leaderboard,
    get_leaderboard,
    get_leaderboard_stats,
    update_leaderboard,
)


class TestGradeFromHidden:
    """Tests for _grade_from_hidden."""

    def test_grade_a_low_hidden_cost(self):
        """Hidden cost < 10 bps should get grade A."""
        assert _grade_from_hidden(5, 9) == "A"

    def test_grade_b_medium_low_hidden_cost(self):
        """Hidden cost 10-25 bps should get grade B."""
        assert _grade_from_hidden(10, 25) == "B"

    def test_grade_c_medium_hidden_cost(self):
        """Hidden cost 25-50 bps should get grade C."""
        assert _grade_from_hidden(30, 40) == "C"

    def test_grade_d_high_hidden_cost(self):
        """Hidden cost 50-100 bps should get grade D."""
        assert _grade_from_hidden(60, 80) == "D"

    def test_grade_f_very_high_hidden_cost(self):
        """Hidden cost >= 100 bps should get grade F."""
        assert _grade_from_hidden(100, 150) == "F"

    def test_grade_boundary_10(self):
        """Boundary at 10 bps."""
        assert _grade_from_hidden(10, 10) == "B"

    def test_grade_boundary_25(self):
        """Boundary at 25 bps should get C."""
        # At exactly 25, mid = 25, which is >= 25, so should be C
        assert _grade_from_hidden(25, 25) == "C"

    def test_grade_boundary_50(self):
        """Boundary at 50 bps should get D."""
        # At exactly 50, mid = 50, which is >= 50, so should be D
        assert _grade_from_hidden(50, 50) == "D"

    def test_grade_boundary_100(self):
        """Boundary at 100 bps."""
        assert _grade_from_hidden(100, 100) == "F"


class TestLoadSaveLeaderboard:
    """Tests for loading and saving leaderboard."""

    def test_load_nonexistent_file(self):
        """Load should return empty dict if file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "leaderboard.json"
            result = _load_leaderboard(path)
            assert result == {}

    def test_load_valid_file(self):
        """Load should parse JSON and key by ticker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "leaderboard.json"
            data = [
                {
                    "ticker": "VTSAX",
                    "name": "Vanguard Total Stock Market",
                    "family": "Vanguard",
                    "hidden_cost_mid_bps": 10.5,
                    "hidden_cost_low_bps": 10.0,
                    "hidden_cost_high_bps": 11.0,
                    "expense_ratio_bps": 5.0,
                    "true_cost_mid_bps": 15.5,
                    "turnover_pct": 5.0,
                    "net_assets_display": "$500.0B",
                    "holdings_count": 3000,
                    "grade": "A",
                    "conflict_count": 0,
                    "lookup_count": 1,
                    "last_updated": "2024-01-01",
                    "dollar_impact_20yr": None,
                }
            ]
            path.write_text(json.dumps(data))

            result = _load_leaderboard(path)
            assert "VTSAX" in result
            assert result["VTSAX"]["hidden_cost_mid_bps"] == 10.5

    def test_load_malformed_json(self):
        """Load should return empty dict if JSON is invalid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "leaderboard.json"
            path.write_text("{ invalid json }")
            result = _load_leaderboard(path)
            assert result == {}

    def test_save_creates_directory(self):
        """Save should create parent directory if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "subdir" / "leaderboard.json"
            entries = {
                "VTSAX": {
                    "ticker": "VTSAX",
                    "name": "Vanguard Total Stock Market",
                    "family": "Vanguard",
                    "hidden_cost_mid_bps": 10.5,
                    "hidden_cost_low_bps": 10.0,
                    "hidden_cost_high_bps": 11.0,
                    "expense_ratio_bps": 5.0,
                    "true_cost_mid_bps": 15.5,
                    "turnover_pct": 5.0,
                    "net_assets_display": "$500.0B",
                    "holdings_count": 3000,
                    "grade": "A",
                    "conflict_count": 0,
                    "lookup_count": 1,
                    "last_updated": "2024-01-01",
                    "dollar_impact_20yr": None,
                }
            }
            _save_leaderboard(entries, path)
            assert path.exists()

    def test_save_sorts_by_hidden_cost_descending(self):
        """Save should sort entries by hidden cost, worst first."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "leaderboard.json"
            entries = {
                "VTSAX": {
                    "ticker": "VTSAX",
                    "hidden_cost_mid_bps": 10.5,
                    "hidden_cost_low_bps": 10.0,
                    "hidden_cost_high_bps": 11.0,
                    "expense_ratio_bps": 5.0,
                    "true_cost_mid_bps": 15.5,
                    "turnover_pct": 5.0,
                    "net_assets_display": "$500.0B",
                    "holdings_count": 3000,
                    "grade": "A",
                    "conflict_count": 0,
                    "lookup_count": 1,
                    "last_updated": "2024-01-01",
                    "dollar_impact_20yr": None,
                },
                "PGIM": {
                    "ticker": "PGIM",
                    "hidden_cost_mid_bps": 50.5,  # Worse
                    "hidden_cost_low_bps": 50.0,
                    "hidden_cost_high_bps": 51.0,
                    "expense_ratio_bps": 8.0,
                    "true_cost_mid_bps": 58.5,
                    "turnover_pct": 150.0,
                    "net_assets_display": "$100.0B",
                    "holdings_count": 1000,
                    "grade": "C",
                    "conflict_count": 2,
                    "lookup_count": 1,
                    "last_updated": "2024-01-01",
                    "dollar_impact_20yr": None,
                },
            }
            _save_leaderboard(entries, path)
            data = json.loads(path.read_text())
            assert data[0]["ticker"] == "PGIM"  # Worst first


class TestUpdateLeaderboard:
    """Tests for update_leaderboard."""

    def test_update_new_entry(self):
        """Update should add new fund to leaderboard."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "leaderboard.json"

            update_leaderboard(
                ticker="VTSAX",
                name="Vanguard Total Stock Market",
                family="Vanguard",
                hidden_low_bps=10.0,
                hidden_high_bps=11.0,
                expense_ratio_bps=5.0,
                turnover_pct=5.0,
                net_assets_display="$500.0B",
                holdings_count=3000,
                conflict_count=0,
                dollar_impact_hidden_low=None,
                dollar_impact_hidden_high=None,
                path=path,
            )

            data = json.loads(path.read_text())
            assert len(data) == 1
            assert data[0]["ticker"] == "VTSAX"

    def test_update_existing_entry_increments_lookup_count(self):
        """Update should increment lookup_count for existing entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "leaderboard.json"

            # First update
            update_leaderboard(
                ticker="VTSAX",
                name="Vanguard Total Stock Market",
                family="Vanguard",
                hidden_low_bps=10.0,
                hidden_high_bps=11.0,
                expense_ratio_bps=5.0,
                turnover_pct=5.0,
                net_assets_display="$500.0B",
                holdings_count=3000,
                conflict_count=0,
                dollar_impact_hidden_low=None,
                dollar_impact_hidden_high=None,
                path=path,
            )

            # Second update
            update_leaderboard(
                ticker="VTSAX",
                name="Vanguard Total Stock Market",
                family="Vanguard",
                hidden_low_bps=10.0,
                hidden_high_bps=11.0,
                expense_ratio_bps=5.0,
                turnover_pct=5.0,
                net_assets_display="$500.0B",
                holdings_count=3000,
                conflict_count=0,
                dollar_impact_hidden_low=None,
                dollar_impact_hidden_high=None,
                path=path,
            )

            data = json.loads(path.read_text())
            assert data[0]["lookup_count"] == 2

    def test_update_skips_if_no_hidden_cost(self):
        """Update should return early if hidden cost is not available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "leaderboard.json"

            update_leaderboard(
                ticker="VTSAX",
                name="Vanguard Total Stock Market",
                family="Vanguard",
                hidden_low_bps=None,
                hidden_high_bps=None,
                expense_ratio_bps=5.0,
                turnover_pct=5.0,
                net_assets_display="$500.0B",
                holdings_count=3000,
                conflict_count=0,
                dollar_impact_hidden_low=None,
                dollar_impact_hidden_high=None,
                path=path,
            )

            # File should not be created if no hidden cost data
            assert not path.exists()

    def test_update_calculates_dollar_impact(self):
        """Update should compute dollar impact midpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "leaderboard.json"

            update_leaderboard(
                ticker="VTSAX",
                name="Vanguard Total Stock Market",
                family="Vanguard",
                hidden_low_bps=10.0,
                hidden_high_bps=12.0,
                expense_ratio_bps=5.0,
                turnover_pct=5.0,
                net_assets_display="$500.0B",
                holdings_count=3000,
                conflict_count=0,
                dollar_impact_hidden_low=1000,
                dollar_impact_hidden_high=1200,
                path=path,
            )

            data = json.loads(path.read_text())
            assert data[0]["dollar_impact_20yr"] == 1100  # (1000 + 1200) / 2


class TestGetLeaderboard:
    """Tests for get_leaderboard."""

    def test_get_empty_leaderboard(self):
        """Get should return empty list for empty leaderboard."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "leaderboard.json"
            result = get_leaderboard(path=path)
            assert result == []

    def test_get_sorted_by_hidden_cost_default(self):
        """Get should sort by hidden_cost_mid_bps descending by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "leaderboard.json"

            update_leaderboard(
                ticker="VTSAX",
                name="Vanguard Total Stock Market",
                family="Vanguard",
                hidden_low_bps=10.0,
                hidden_high_bps=11.0,
                expense_ratio_bps=5.0,
                turnover_pct=5.0,
                net_assets_display="$500.0B",
                holdings_count=3000,
                conflict_count=0,
                dollar_impact_hidden_low=None,
                dollar_impact_hidden_high=None,
                path=path,
            )

            update_leaderboard(
                ticker="PGIM",
                name="PGIM Equity Dividend",
                family="PGIM",
                hidden_low_bps=50.0,
                hidden_high_bps=51.0,
                expense_ratio_bps=8.0,
                turnover_pct=150.0,
                net_assets_display="$100.0B",
                holdings_count=1000,
                conflict_count=2,
                dollar_impact_hidden_low=None,
                dollar_impact_hidden_high=None,
                path=path,
            )

            result = get_leaderboard(path=path)
            assert result[0]["ticker"] == "PGIM"  # Worst first
            assert result[1]["ticker"] == "VTSAX"

    def test_get_respects_limit(self):
        """Get should return only up to limit entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "leaderboard.json"

            for i in range(5):
                update_leaderboard(
                    ticker=f"FUND{i}",
                    name=f"Fund {i}",
                    family="TestFamily",
                    hidden_low_bps=float(i * 10),
                    hidden_high_bps=float(i * 10 + 1),
                    expense_ratio_bps=2.0,
                    turnover_pct=10.0,
                    net_assets_display="$100.0B",
                    holdings_count=1000,
                    conflict_count=0,
                    dollar_impact_hidden_low=None,
                    dollar_impact_hidden_high=None,
                    path=path,
                )

            result = get_leaderboard(limit=3, path=path)
            assert len(result) == 3

    def test_get_sorted_by_grade(self):
        """Get should sort by grade (F worst to A best)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "leaderboard.json"

            # Create entries with different grades
            update_leaderboard(
                ticker="FUND_A",
                name="Grade A Fund",
                family="TestFamily",
                hidden_low_bps=5.0,
                hidden_high_bps=6.0,
                expense_ratio_bps=2.0,
                turnover_pct=10.0,
                net_assets_display="$100.0B",
                holdings_count=1000,
                conflict_count=0,
                dollar_impact_hidden_low=None,
                dollar_impact_hidden_high=None,
                path=path,
            )

            update_leaderboard(
                ticker="FUND_F",
                name="Grade F Fund",
                family="TestFamily",
                hidden_low_bps=100.0,
                hidden_high_bps=110.0,
                expense_ratio_bps=8.0,
                turnover_pct=200.0,
                net_assets_display="$100.0B",
                holdings_count=1000,
                conflict_count=2,
                dollar_impact_hidden_low=None,
                dollar_impact_hidden_high=None,
                path=path,
            )

            result = get_leaderboard(sort_by="grade", path=path)
            assert result[0]["grade"] == "F"  # Worst first
            assert result[1]["grade"] == "A"


class TestGetLeaderboardStats:
    """Tests for get_leaderboard_stats."""

    def test_stats_empty_leaderboard(self):
        """Stats should return zeros for empty leaderboard."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "leaderboard.json"
            result = get_leaderboard_stats(path=path)

            assert result["total_funds"] == 0
            assert result["total_lookups"] == 0
            assert result["worst_ticker"] is None
            assert result["worst_hidden_bps"] is None
            assert result["avg_hidden_bps"] is None

    def test_stats_with_data(self):
        """Stats should aggregate correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "leaderboard.json"

            update_leaderboard(
                ticker="VTSAX",
                name="Vanguard Total Stock Market",
                family="Vanguard",
                hidden_low_bps=10.0,
                hidden_high_bps=11.0,
                expense_ratio_bps=5.0,
                turnover_pct=5.0,
                net_assets_display="$500.0B",
                holdings_count=3000,
                conflict_count=0,
                dollar_impact_hidden_low=None,
                dollar_impact_hidden_high=None,
                path=path,
            )

            update_leaderboard(
                ticker="PGIM",
                name="PGIM Equity Dividend",
                family="PGIM",
                hidden_low_bps=50.0,
                hidden_high_bps=51.0,
                expense_ratio_bps=8.0,
                turnover_pct=150.0,
                net_assets_display="$100.0B",
                holdings_count=1000,
                conflict_count=2,
                dollar_impact_hidden_low=None,
                dollar_impact_hidden_high=None,
                path=path,
            )

            # Do second lookup on first fund
            update_leaderboard(
                ticker="VTSAX",
                name="Vanguard Total Stock Market",
                family="Vanguard",
                hidden_low_bps=10.0,
                hidden_high_bps=11.0,
                expense_ratio_bps=5.0,
                turnover_pct=5.0,
                net_assets_display="$500.0B",
                holdings_count=3000,
                conflict_count=0,
                dollar_impact_hidden_low=None,
                dollar_impact_hidden_high=None,
                path=path,
            )

            result = get_leaderboard_stats(path=path)

            assert result["total_funds"] == 2
            assert result["total_lookups"] == 3  # 2 + 1
            assert result["worst_ticker"] == "PGIM"
            assert result["worst_hidden_bps"] == 50.5
            assert result["avg_hidden_bps"] == 30.5  # (10.5 + 50.5) / 2
