"""Bid-ask spread cost estimation."""

from __future__ import annotations

import logging

from fundautopsy.estimates.assumptions import (
    DEFAULT_SPREAD,
    NPORT_ASSET_CAT_MAP,
    SPREAD_ASSUMPTIONS,
)
from fundautopsy.models.cost_breakdown import CostRange
from fundautopsy.models.filing_data import DataSourceTag, NPortData

logger = logging.getLogger(__name__)


def estimate_bid_ask_spread(
    nport: NPortData,
    turnover_rate: float,
) -> CostRange | None:
    """Estimate bid-ask spread cost from asset class mix and turnover.

    Formula: Spread_Cost = Turnover_Rate x 2 x Weighted_Avg_One_Way_Spread

    The factor of 2 accounts for both sides of each trade
    (sell old position + buy replacement).

    Args:
        nport: N-PORT data with holdings and asset class breakdown.
        turnover_rate: Portfolio turnover rate from N-CEN (decimal, e.g., 0.45 for 45%).

    Returns:
        CostRange with low and high estimates in basis points.
    """
    weights: dict[str, float] = nport.asset_class_weights()

    weighted_low: float = 0.0
    weighted_high: float = 0.0
    total_weight: float = 0.0

    for asset_cat, weight_pct in weights.items():
        # Map N-PORT category to our assumption key
        assumption_key = NPORT_ASSET_CAT_MAP.get(asset_cat, None)
        assumption = SPREAD_ASSUMPTIONS.get(assumption_key, DEFAULT_SPREAD) if assumption_key else DEFAULT_SPREAD

        weight_decimal = weight_pct / 100.0
        weighted_low += assumption.low_one_way_pct * weight_decimal
        weighted_high += assumption.high_one_way_pct * weight_decimal
        total_weight += weight_decimal

    # If less than half the portfolio could be mapped to known asset categories,
    # the estimate is unreliable — return None instead of a misleading number.
    if total_weight < 0.01:
        logger.warning(
            "Cannot estimate bid-ask spread: no asset category weights available "
            "(all holdings unmapped or portfolio empty)"
        )
        return None

    if total_weight < 0.50:
        logger.warning(
            "Bid-ask spread estimate covers only %.0f%% of portfolio — "
            "too low for a reliable estimate",
            total_weight * 100,
        )
        return None

    # Normalize if weights don't sum to 1
    if abs(total_weight - 1.0) > 0.01:
        weighted_low /= total_weight
        weighted_high /= total_weight

    # Apply turnover (x2 for round-trip)
    cost_low = turnover_rate * 2 * weighted_low * 10_000  # Convert to bps
    cost_high = turnover_rate * 2 * weighted_high * 10_000

    return CostRange(
        low_bps=round(cost_low, 2),
        high_bps=round(cost_high, 2),
        tag=DataSourceTag.ESTIMATED,
        methodology=(
            "Bid-ask spread estimated from N-PORT asset class weights "
            "and portfolio turnover. Spread assumptions based on "
            "asset-class-specific averages. Formula: turnover x 2 x "
            "weighted avg one-way spread."
        ),
    )
