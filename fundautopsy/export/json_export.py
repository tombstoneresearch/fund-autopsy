"""JSON export for fund cost analysis.

Exports the full fund analysis tree as a structured JSON file for
downstream processing, integration with other tools, or archival.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from fundautopsy.models.filing_data import DataSourceTag
from fundautopsy.models.holdings_tree import FundNode


def _tag_label(tag: DataSourceTag) -> str:
    """Human-readable label for a data source tag."""
    labels = {
        DataSourceTag.REPORTED: "reported",
        DataSourceTag.ESTIMATED: "estimated",
        DataSourceTag.NOT_DISCLOSED: "not_disclosed",
        DataSourceTag.UNAVAILABLE: "unavailable",
    }
    return labels.get(tag, str(tag))


def _serialize_node(node: FundNode) -> dict[str, Any]:
    """Convert a FundNode to a JSON-serializable dict."""
    meta = node.metadata
    cb = node.cost_breakdown
    nport = node.nport_data

    result: dict[str, Any] = {
        "ticker": meta.ticker,
        "name": meta.name,
        "fund_family": meta.fund_family or "",
        "cik": meta.cik,
        "series_id": meta.series_id,
        "class_id": meta.class_id,
        "is_fund_of_funds": meta.is_fund_of_funds,
        "allocation_weight": node.allocation_weight,
        "depth": node.depth,
    }

    # Net assets and holdings
    if nport:
        result["net_assets"] = nport.total_net_assets
        result["holdings_count"] = len(nport.holdings)
        result["reporting_period_end"] = str(nport.reporting_period_end) if nport.reporting_period_end else None
        result["asset_class_weights"] = nport.asset_class_weights()
    else:
        result["net_assets"] = None
        result["holdings_count"] = 0
        result["reporting_period_end"] = None
        result["asset_class_weights"] = {}

    # Cost breakdown
    costs: dict[str, Any] = {}

    if cb:
        # Stated costs
        if cb.expense_ratio_bps and cb.expense_ratio_bps.is_available:
            costs["expense_ratio_bps"] = {
                "value": cb.expense_ratio_bps.value,
                "tag": _tag_label(cb.expense_ratio_bps.tag),
            }

        if cb.management_fee_bps and cb.management_fee_bps.is_available:
            costs["management_fee_bps"] = {
                "value": cb.management_fee_bps.value,
                "tag": _tag_label(cb.management_fee_bps.tag),
            }

        if cb.twelve_b1_fee_bps and cb.twelve_b1_fee_bps.is_available:
            costs["twelve_b1_fee_bps"] = {
                "value": cb.twelve_b1_fee_bps.value,
                "tag": _tag_label(cb.twelve_b1_fee_bps.tag),
            }

        # Hidden costs
        if cb.brokerage_commissions_bps and cb.brokerage_commissions_bps.is_available:
            costs["brokerage_commissions_bps"] = {
                "value": cb.brokerage_commissions_bps.value,
                "tag": _tag_label(cb.brokerage_commissions_bps.tag),
                "note": cb.brokerage_commissions_bps.note,
            }

        if cb.soft_dollar_commissions_bps:
            tag = cb.soft_dollar_commissions_bps.tag
            costs["soft_dollar_arrangements"] = {
                "active": tag == DataSourceTag.NOT_DISCLOSED or (
                    cb.soft_dollar_commissions_bps.is_available
                    and cb.soft_dollar_commissions_bps.value > 0
                ),
                "value_bps": (
                    cb.soft_dollar_commissions_bps.value if cb.soft_dollar_commissions_bps.is_available else None
                ),
                "tag": _tag_label(tag),
            }

        if cb.bid_ask_spread_cost and cb.bid_ask_spread_cost.tag != DataSourceTag.UNAVAILABLE:
            costs["bid_ask_spread_cost"] = {
                "low_bps": cb.bid_ask_spread_cost.low_bps,
                "high_bps": cb.bid_ask_spread_cost.high_bps,
                "mid_bps": cb.bid_ask_spread_cost.midpoint_bps,
                "tag": _tag_label(cb.bid_ask_spread_cost.tag),
                "methodology": cb.bid_ask_spread_cost.methodology,
            }

        if cb.market_impact_cost and cb.market_impact_cost.tag != DataSourceTag.UNAVAILABLE:
            costs["market_impact_cost"] = {
                "low_bps": cb.market_impact_cost.low_bps,
                "high_bps": cb.market_impact_cost.high_bps,
                "mid_bps": cb.market_impact_cost.midpoint_bps,
                "tag": _tag_label(cb.market_impact_cost.tag),
                "methodology": cb.market_impact_cost.methodology,
            }

        # Composite
        costs["total_reported_bps"] = cb.total_reported_bps
        costs["total_estimated_low_bps"] = cb.total_estimated_low_bps
        costs["total_estimated_high_bps"] = cb.total_estimated_high_bps
        costs["hidden_cost_gap_bps"] = cb.hidden_cost_gap_bps

    result["costs"] = costs
    result["data_notes"] = node.data_notes

    # Children (fund-of-funds)
    if node.children:
        result["underlying_funds"] = [
            _serialize_node(child) for child in node.children
        ]

    return result


def export_json(result: FundNode, output_path: Path) -> None:
    """Export full analysis results to JSON.

    Serializes the complete FundNode analysis tree to a JSON file,
    preserving the hierarchical structure and all cost estimates.

    Args:
        result: Root FundNode from the analysis.
        output_path: Path where JSON file will be written.
    """
    content = export_json_string(result)
    output_path.write_text(content, encoding="utf-8")


def export_json_string(result: FundNode) -> str:
    """Export full analysis results to a JSON string.

    Returns:
        JSON content as a string.
    """
    data = {
        "fund_autopsy_version": "0.1.0",
        "generated": str(date.today()),
        "analysis": _serialize_node(result),
    }
    return json.dumps(data, indent=2, default=str)
