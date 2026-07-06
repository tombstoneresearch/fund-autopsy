"""Market-impact cost estimation.

Based on Edelen, Evans, and Kadlec (2007) framework.
This is the least precise estimate in Fund Autopsy — always report with
explicit confidence caveats and wide ranges.
"""

from __future__ import annotations

from fundautopsy.estimates.assumptions import (
    BOND_IMPACT_ASSUMPTIONS,
    BOND_TURNOVER_LOW_HIGH_THRESHOLD,
    IMPACT_ASSUMPTIONS,
    TURNOVER_LOW_HIGH_THRESHOLD,
)
from fundautopsy.models.cost_breakdown import CostRange
from fundautopsy.models.filing_data import DataSourceTag


def estimate_market_impact(
    turnover_rate: float,
    total_net_assets: float,
    is_small_cap: bool = False,
    is_bond_fund: bool = False,
) -> CostRange:
    """Estimate market-impact cost from fund characteristics.

    Market impact is the adverse price movement caused by a fund's
    own trading activity. Larger orders in less liquid securities
    cause greater impact.

    Args:
        turnover_rate: Portfolio turnover rate (decimal).
        total_net_assets: Fund total net assets in dollars.
        is_small_cap: Whether the fund primarily holds small-cap securities.
        is_bond_fund: Whether the fund is primarily fixed income.

    Returns:
        CostRange with low/high estimates in basis points.
    """
    if is_bond_fund:
        # Bond funds: higher turnover threshold, lower impact per unit
        threshold = BOND_TURNOVER_LOW_HIGH_THRESHOLD
        is_high_turnover = turnover_rate > threshold
        key = "bond_high_turnover" if is_high_turnover else "bond_low_turnover"
        assumption = BOND_IMPACT_ASSUMPTIONS[key]
        label = "bond fund"
    else:
        # Equity funds: original logic
        threshold = TURNOVER_LOW_HIGH_THRESHOLD
        is_high_turnover = turnover_rate > threshold

        if is_small_cap and is_high_turnover:
            assumption = IMPACT_ASSUMPTIONS["small_high_turnover"]
        elif is_small_cap:
            assumption = IMPACT_ASSUMPTIONS["small_low_turnover"]
        elif is_high_turnover:
            assumption = IMPACT_ASSUMPTIONS["large_high_turnover"]
        else:
            assumption = IMPACT_ASSUMPTIONS["large_low_turnover"]
        label = f"{'small-cap' if is_small_cap else 'large-cap'}"

    # Apply turnover to impact factor
    cost_low = turnover_rate * assumption.low_pct_of_turnover * 10_000  # bps
    cost_high = turnover_rate * assumption.high_pct_of_turnover * 10_000

    return CostRange(
        low_bps=round(cost_low, 2),
        high_bps=round(cost_high, 2),
        tag=DataSourceTag.ESTIMATED,
        methodology=(
            "Market impact estimated using simplified Edelen, Evans, "
            f"and Kadlec (2007) framework. Fund category: {label}, "
            f"turnover level: {'high' if is_high_turnover else 'low'} "
            f"(threshold: {threshold:.0%}). "
            "This is the least precise estimate — treat as directional."
        ),
    )


def estimate_market_impact_regression(
    turnover_rate: float,
    total_net_assets: float,
    pct_small_cap: float = 0.0,
    pct_bond: float = 0.0,
) -> CostRange:
    """Regression-based market impact estimate using continuous asset mix.

    Instead of a binary equity/bond classification, this uses the
    portfolio's actual asset mix to weight impact assumptions. Better
    for multi-asset or balanced funds.

    Args:
        turnover_rate: Portfolio turnover rate (decimal).
        total_net_assets: Fund total net assets in dollars.
        pct_small_cap: Percentage of equity that is small-cap (0-100).
        pct_bond: Percentage of portfolio in fixed income (0-100).

    Returns:
        CostRange with low/high estimates in basis points.
    """
    # Normalize to fractions
    bond_weight: float = min(pct_bond, 100.0) / 100.0
    equity_weight: float = 1.0 - bond_weight
    small_cap_weight: float = min(pct_small_cap, 100.0) / 100.0

    # Equity component: blend small/large cap assumptions
    eq_threshold: float = TURNOVER_LOW_HIGH_THRESHOLD
    eq_high: bool = turnover_rate > eq_threshold

    if eq_high:
        large_a = IMPACT_ASSUMPTIONS["large_high_turnover"]
        small_a = IMPACT_ASSUMPTIONS["small_high_turnover"]
    else:
        large_a = IMPACT_ASSUMPTIONS["large_low_turnover"]
        small_a = IMPACT_ASSUMPTIONS["small_low_turnover"]

    eq_low_pct: float = (
        small_cap_weight * small_a.low_pct_of_turnover
        + (1.0 - small_cap_weight) * large_a.low_pct_of_turnover
    )
    eq_high_pct: float = (
        small_cap_weight * small_a.high_pct_of_turnover
        + (1.0 - small_cap_weight) * large_a.high_pct_of_turnover
    )

    # Bond component
    bond_threshold: float = BOND_TURNOVER_LOW_HIGH_THRESHOLD
    bond_key: str = "bond_high_turnover" if turnover_rate > bond_threshold else "bond_low_turnover"
    bond_a = BOND_IMPACT_ASSUMPTIONS[bond_key]

    # Weighted blend
    blended_low: float = equity_weight * eq_low_pct + bond_weight * bond_a.low_pct_of_turnover
    blended_high: float = equity_weight * eq_high_pct + bond_weight * bond_a.high_pct_of_turnover

    cost_low: float = turnover_rate * blended_low * 10_000
    cost_high: float = turnover_rate * blended_high * 10_000

    return CostRange(
        low_bps=round(cost_low, 2),
        high_bps=round(cost_high, 2),
        tag=DataSourceTag.ESTIMATED,
        methodology=(
            "Market impact estimated using regression-weighted blend of "
            "equity and fixed income impact assumptions. "
            f"Bond weight: {bond_weight:.0%}, small-cap weight: {small_cap_weight:.0%}. "
            "Based on Edelen, Evans, and Kadlec (2007). Directional estimate."
        ),
    )
