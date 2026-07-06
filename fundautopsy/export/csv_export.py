"""CSV export for fund cost analysis.

Exports the complete cost breakdown to CSV format for spreadsheet
applications, bulk processing, or integration with other tools.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

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


def export_csv(result: FundNode, output_path: Path) -> None:
    """Export cost breakdown to CSV.

    Creates a CSV with one row per cost component including low/high/mid
    estimates in basis points, data source tags, and fund metadata.

    Args:
        result: Root FundNode from the analysis.
        output_path: Path where CSV file will be written.
    """
    content = export_csv_string(result)
    output_path.write_text(content, encoding="utf-8")


def export_csv_string(result: FundNode) -> str:
    """Export cost breakdown to a CSV string.

    Returns:
        CSV content as a string.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    meta = result.metadata
    cb = result.cost_breakdown
    nport = result.nport_data

    # Header
    writer.writerow([
        "ticker", "fund_name", "fund_family", "component", "category",
        "low_bps", "high_bps", "mid_bps", "value_pct",
        "source_tag", "note",
    ])

    # Expense ratio
    if cb and cb.expense_ratio_bps and cb.expense_ratio_bps.is_available:
        er = cb.expense_ratio_bps.value
        writer.writerow([
            meta.ticker, meta.name, meta.fund_family or "", "Expense Ratio",
            "stated", er, er, er, er / 100,
            _tag_label(cb.expense_ratio_bps.tag), cb.expense_ratio_bps.note or "",
        ])

    # Management fee
    if cb and cb.management_fee_bps and cb.management_fee_bps.is_available:
        v = cb.management_fee_bps.value
        writer.writerow([
            meta.ticker, meta.name, meta.fund_family or "", "Management Fee",
            "stated", v, v, v, v / 100,
            _tag_label(cb.management_fee_bps.tag), "",
        ])

    # 12b-1
    if cb and cb.twelve_b1_fee_bps and cb.twelve_b1_fee_bps.is_available:
        v = cb.twelve_b1_fee_bps.value
        writer.writerow([
            meta.ticker, meta.name, meta.fund_family or "", "12b-1 Fee",
            "stated", v, v, v, v / 100,
            _tag_label(cb.twelve_b1_fee_bps.tag), "",
        ])

    # Brokerage commissions
    if cb and cb.brokerage_commissions_bps and cb.brokerage_commissions_bps.is_available:
        v = cb.brokerage_commissions_bps.value
        writer.writerow([
            meta.ticker, meta.name, meta.fund_family or "", "Brokerage Commissions",
            "hidden", v, v, v, v / 100,
            _tag_label(cb.brokerage_commissions_bps.tag),
            cb.brokerage_commissions_bps.note or "",
        ])

    # Soft dollars
    if cb and cb.soft_dollar_commissions_bps:
        tag = cb.soft_dollar_commissions_bps.tag
        if tag == DataSourceTag.NOT_DISCLOSED:
            writer.writerow([
                meta.ticker, meta.name, meta.fund_family or "",
                "Soft Dollar Arrangements", "hidden",
                "", "", "", "", "not_disclosed",
                "Active but dollar amount not disclosed",
            ])
        elif cb.soft_dollar_commissions_bps.is_available:
            v = cb.soft_dollar_commissions_bps.value
            writer.writerow([
                meta.ticker, meta.name, meta.fund_family or "",
                "Soft Dollar Commissions", "hidden",
                v, v, v, v / 100, _tag_label(tag), "",
            ])

    # Bid-ask spread
    if cb and cb.bid_ask_spread_cost and cb.bid_ask_spread_cost.tag != DataSourceTag.UNAVAILABLE:
        s = cb.bid_ask_spread_cost
        writer.writerow([
            meta.ticker, meta.name, meta.fund_family or "", "Bid-Ask Spread Cost",
            "hidden", s.low_bps, s.high_bps, s.midpoint_bps,
            s.midpoint_bps / 100, _tag_label(s.tag),
            s.methodology or "",
        ])

    # Market impact
    if cb and cb.market_impact_cost and cb.market_impact_cost.tag != DataSourceTag.UNAVAILABLE:
        m = cb.market_impact_cost
        writer.writerow([
            meta.ticker, meta.name, meta.fund_family or "", "Market Impact Cost",
            "hidden", m.low_bps, m.high_bps, m.midpoint_bps,
            m.midpoint_bps / 100, _tag_label(m.tag),
            m.methodology or "",
        ])

    # Summary row: total hidden
    brok_bps = (
        cb.brokerage_commissions_bps.value
        if cb and cb.brokerage_commissions_bps and cb.brokerage_commissions_bps.is_available
        else 0
    )
    hidden_low = sum(filter(None, [
        brok_bps,
        cb.bid_ask_spread_cost.low_bps if cb and cb.bid_ask_spread_cost else 0,
        cb.market_impact_cost.low_bps if cb and cb.market_impact_cost else 0,
    ]))
    hidden_high = sum(filter(None, [
        brok_bps,
        cb.bid_ask_spread_cost.high_bps if cb and cb.bid_ask_spread_cost else 0,
        cb.market_impact_cost.high_bps if cb and cb.market_impact_cost else 0,
    ]))
    writer.writerow([
        meta.ticker, meta.name, meta.fund_family or "", "TOTAL HIDDEN COSTS",
        "composite", hidden_low, hidden_high, (hidden_low + hidden_high) / 2,
        (hidden_low + hidden_high) / 200, "composite", "",
    ])

    # Asset mix
    if nport:
        weights = nport.asset_class_weights()
        for cat, pct in sorted(weights.items(), key=lambda x: -x[1]):
            writer.writerow([
                meta.ticker, meta.name, meta.fund_family or "",
                f"Asset: {cat}", "allocation",
                "", "", "", pct / 100, "nport", "",
            ])

    return output.getvalue()
