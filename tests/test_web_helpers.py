"""Unit tests for extracted web-layer helpers.

Tests the two pure helper functions extracted from /api/analyze and
/api/sai handlers for testability:

  - compute_affiliated_concentration
  - compute_soft_dollar_subsidy

These encapsulate business logic that previously lived inline inside
FastAPI route handlers. Extracting them lets us verify the math
without spinning up the web layer.

Skipped when FastAPI is not installed (since the helpers import from
fundautopsy.web.app).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")


# ── compute_affiliated_concentration ─────────────────────────────────


def _broker(gross_commission: float) -> SimpleNamespace:
    """Build a BrokerRecord-shaped object for tests."""
    return SimpleNamespace(gross_commission=gross_commission)


def test_affiliated_concentration_empty_list_returns_zeros():
    from fundautopsy.web.app import compute_affiliated_concentration
    dollars, pct = compute_affiliated_concentration([], 1000.0)
    assert dollars == 0.0
    assert pct == 0.0


def test_affiliated_concentration_with_brokers_and_total():
    from fundautopsy.web.app import compute_affiliated_concentration
    brokers = [_broker(300.0), _broker(200.0)]
    dollars, pct = compute_affiliated_concentration(brokers, 1000.0)
    assert dollars == 500.0
    assert pct == 50.0


def test_affiliated_concentration_missing_aggregate_returns_dollars_only():
    from fundautopsy.web.app import compute_affiliated_concentration
    brokers = [_broker(100.0)]
    dollars, pct = compute_affiliated_concentration(brokers, None)
    assert dollars == 100.0
    assert pct is None


def test_affiliated_concentration_zero_aggregate_returns_dollars_only():
    from fundautopsy.web.app import compute_affiliated_concentration
    brokers = [_broker(100.0)]
    dollars, pct = compute_affiliated_concentration(brokers, 0)
    assert dollars == 100.0
    assert pct is None


def test_affiliated_concentration_high_pct_not_capped():
    """When affiliated commissions exceed aggregate (data-quality
    weirdness), we surface the raw percentage rather than silently
    capping. A consumer can choose to clamp the display."""
    from fundautopsy.web.app import compute_affiliated_concentration
    brokers = [_broker(1500.0)]
    dollars, pct = compute_affiliated_concentration(brokers, 1000.0)
    assert dollars == 1500.0
    assert pct == 150.0


# ── compute_soft_dollar_subsidy ──────────────────────────────────────


def _commissions_entry(year_to_dollars: dict[int, float]) -> SimpleNamespace:
    """Build a BrokerageCommissions-shaped object for tests."""
    return SimpleNamespace(soft_dollar_commissions=year_to_dollars)


def test_subsidy_empty_commissions_returns_all_none():
    from fundautopsy.web.app import compute_soft_dollar_subsidy
    d, bps, yr, n = compute_soft_dollar_subsidy([], 1_000_000_000.0)
    assert d is None
    assert bps is None
    assert yr is None
    assert n == 0


def test_subsidy_averages_three_most_recent_years():
    from fundautopsy.web.app import compute_soft_dollar_subsidy
    entry = _commissions_entry({
        2023: 100_000.0,
        2024: 200_000.0,
        2025: 300_000.0,
        # 2020 and 2021 should not be in the average (older than top 3)
        2020: 999_999_999.0,
        2021: 999_999_999.0,
    })
    d, bps, yr, n = compute_soft_dollar_subsidy([entry], None)
    # Average of the top-3 years: (100k + 200k + 300k) / 3 = 200k
    assert d == 200_000.0
    assert yr == 2025
    assert n == 3


def test_subsidy_handles_single_year():
    from fundautopsy.web.app import compute_soft_dollar_subsidy
    entry = _commissions_entry({2025: 500_000.0})
    d, bps, yr, n = compute_soft_dollar_subsidy([entry], None)
    assert d == 500_000.0
    assert yr == 2025
    assert n == 1


def test_subsidy_bps_conversion_against_nav():
    from fundautopsy.web.app import compute_soft_dollar_subsidy
    entry = _commissions_entry({2025: 1_000_000.0})
    # $1M subsidy / $10B NAV = 1 bps
    d, bps, yr, n = compute_soft_dollar_subsidy([entry], 10_000_000_000.0)
    assert d == 1_000_000.0
    assert bps == 1.0


def test_subsidy_bps_is_none_when_nav_missing():
    from fundautopsy.web.app import compute_soft_dollar_subsidy
    entry = _commissions_entry({2025: 1_000_000.0})
    d, bps, yr, n = compute_soft_dollar_subsidy([entry], None)
    assert d == 1_000_000.0
    assert bps is None


def test_subsidy_multiple_funds_sums_averages():
    from fundautopsy.web.app import compute_soft_dollar_subsidy
    entry1 = _commissions_entry({2025: 100_000.0, 2024: 100_000.0})
    entry2 = _commissions_entry({2025: 200_000.0, 2024: 200_000.0})
    d, bps, yr, n = compute_soft_dollar_subsidy([entry1, entry2], None)
    # Entry1 avg = 100k, Entry2 avg = 200k. Summed = 300k.
    assert d == 300_000.0
    assert yr == 2025


def test_subsidy_configurable_averaging_window():
    from fundautopsy.web.app import compute_soft_dollar_subsidy
    entry = _commissions_entry({
        2023: 1.0, 2024: 2.0, 2025: 3.0, 2026: 4.0, 2027: 5.0,
    })
    # years_to_average=5 pulls all five
    d, _bps, _yr, n = compute_soft_dollar_subsidy(
        [entry], None, years_to_average=5
    )
    assert d == 3.0  # (1+2+3+4+5) / 5
    assert n == 5
