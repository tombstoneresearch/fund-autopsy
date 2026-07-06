"""Tier 1: Retail investor view — clean summary card.

The flagship output. Shows the gap between what investors think they pay
(expense ratio) and what they actually pay (total cost of ownership).
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from fundautopsy.models.filing_data import DataSourceTag
from fundautopsy.models.holdings_tree import FundNode


def render(result: FundNode, console: Console) -> None:
    """Render Tier 1 retail output: summary card with cost breakdown.

    Shows:
    - Fund name and ticker
    - Brokerage commissions (from N-CEN)
    - Soft dollar flag
    - Estimated bid-ask spread cost
    - Estimated market impact cost
    - Total hidden cost range
    - Data source transparency tags
    - Key fund facts (holdings count, net assets, asset mix)
    """
    cb = result.cost_breakdown
    if cb is None:
        console.print("[red]No cost data available for this fund.[/red]")
        return

    meta = result.metadata

    # --- Header ---
    console.print()
    header = Text()
    header.append(meta.name, style="bold white")
    header.append(f"  ({meta.ticker})", style="dim")
    if meta.fund_family:
        header.append(f"\n{meta.fund_family}", style="dim italic")
    console.print(Panel(header, title="[bold cyan]Fund Autopsy Analysis[/bold cyan]", border_style="cyan"))

    # --- Cost Breakdown Table ---
    table = Table(
        title="Hidden Cost Breakdown",
        show_header=True,
        header_style="bold",
        border_style="dim",
        title_style="bold yellow",
        padding=(0, 2),
    )
    table.add_column("Cost Component", style="white", min_width=30)
    table.add_column("bps", justify="right", style="cyan", min_width=12)
    table.add_column("Source", style="dim", min_width=12)

    # Brokerage commissions
    if cb.brokerage_commissions_bps and cb.brokerage_commissions_bps.is_available:
        table.add_row(
            "Brokerage Commissions",
            f"{cb.brokerage_commissions_bps.value:.2f}",
            _tag_label(cb.brokerage_commissions_bps.tag),
        )
    else:
        table.add_row(
            "Brokerage Commissions",
            "—",
            "[dim]unavailable[/dim]",
        )

    # Soft dollars
    if cb.soft_dollar_commissions_bps:
        if cb.soft_dollar_commissions_bps.tag == DataSourceTag.NOT_DISCLOSED:
            table.add_row(
                "  Soft Dollar Arrangements",
                "[yellow]ACTIVE[/yellow]",
                "[yellow]not disclosed $[/yellow]",
            )
        elif cb.soft_dollar_commissions_bps.is_available:
            table.add_row(
                "  Soft Dollar Commissions",
                f"{cb.soft_dollar_commissions_bps.value:.2f}",
                _tag_label(cb.soft_dollar_commissions_bps.tag),
            )

    # Bid-ask spread
    if cb.bid_ask_spread_cost and cb.bid_ask_spread_cost.tag != DataSourceTag.UNAVAILABLE:
        table.add_row(
            "Bid-Ask Spread Cost",
            f"{cb.bid_ask_spread_cost.low_bps:.1f} – {cb.bid_ask_spread_cost.high_bps:.1f}",
            _tag_label(cb.bid_ask_spread_cost.tag),
        )
    else:
        table.add_row("Bid-Ask Spread Cost", "—", "[dim]unavailable[/dim]")

    # Market impact
    if cb.market_impact_cost and cb.market_impact_cost.tag != DataSourceTag.UNAVAILABLE:
        table.add_row(
            "Market Impact Cost",
            f"{cb.market_impact_cost.low_bps:.1f} – {cb.market_impact_cost.high_bps:.1f}",
            _tag_label(cb.market_impact_cost.tag),
        )
    else:
        table.add_row("Market Impact Cost", "—", "[dim]unavailable[/dim]")

    # Separator and totals
    table.add_section()

    total_low = _sum_costs_low(cb)
    total_high = _sum_costs_high(cb)

    if total_low is not None and total_high is not None:
        table.add_row(
            "[bold]Estimated Hidden Costs[/bold]",
            f"[bold yellow]{total_low:.1f} – {total_high:.1f}[/bold yellow]",
            "[dim]composite[/dim]",
        )
    else:
        table.add_row(
            "[bold]Estimated Hidden Costs[/bold]",
            "[dim]insufficient data[/dim]",
            "",
        )

    console.print(table)

    # --- Fund Facts ---
    nport = result.nport_data
    if nport:
        facts_table = Table(
            title="Fund Facts",
            show_header=False,
            border_style="dim",
            title_style="bold",
            padding=(0, 2),
        )
        facts_table.add_column("Label", style="dim", min_width=25)
        facts_table.add_column("Value", style="white")

        if nport.total_net_assets:
            facts_table.add_row("Total Net Assets", _format_dollars(nport.total_net_assets))

        facts_table.add_row("Holdings Count", str(len(nport.holdings)))

        # Asset class mix
        weights = nport.asset_class_weights()
        if weights:
            mix_parts = []
            for cat, pct in sorted(weights.items(), key=lambda x: -x[1]):
                mix_parts.append(f"{cat}: {pct:.1f}%")
            facts_table.add_row("Asset Mix", ", ".join(mix_parts[:5]))

        if result.metadata.is_fund_of_funds:
            fund_count = len(nport.fund_holdings)
            facts_table.add_row("Structure", f"[yellow]Fund-of-Funds ({fund_count} underlying)[/yellow]")

        facts_table.add_row("N-PORT Period", str(nport.reporting_period_end))

        console.print(facts_table)

    # --- Data Notes ---
    if result.data_notes:
        console.print()
        console.print("[dim bold]Data Notes:[/dim bold]")
        for note in result.data_notes:
            console.print(f"  [dim]• {note}[/dim]")

    # --- Interpretation ---
    console.print()
    if total_low is not None and total_high is not None:
        console.print(
            f"[bold]Bottom line:[/bold] Beyond the stated expense ratio, "
            f"this fund incurs an estimated [yellow]{total_low:.1f} – {total_high:.1f} bps[/yellow] "
            f"in hidden trading costs annually. These costs reduce pre-fee returns "
            f"before the expense ratio is even deducted."
        )
    else:
        console.print(
            "[bold]Bottom line:[/bold] Insufficient data to compute full hidden cost estimate. "
            "See data notes above for details on what's missing."
        )

    console.print()
    console.print(
        "[dim]Methodology: Brokerage commissions from N-CEN. Spread and impact "
        "estimated from N-PORT asset class mix and assumed turnover. "
        "See github.com/Tombstone-Research/fund-autopsy/blob/main/docs/methodology.md for details.[/dim]"
    )
    console.print()


def _tag_label(tag: DataSourceTag) -> str:
    """Format a DataSourceTag for display."""
    labels = {
        DataSourceTag.REPORTED: "[green]SEC filing[/green]",
        DataSourceTag.CALCULATED: "[green]calculated[/green]",
        DataSourceTag.ESTIMATED: "[yellow]estimated[/yellow]",
        DataSourceTag.UNAVAILABLE: "[dim]unavailable[/dim]",
        DataSourceTag.NOT_DISCLOSED: "[red]not disclosed[/red]",
    }
    return labels.get(tag, str(tag))


def _sum_costs_low(cb) -> float | None:
    """Sum the low end of all available cost components."""
    total = 0.0
    has_any = False

    if cb.brokerage_commissions_bps and cb.brokerage_commissions_bps.is_available:
        total += cb.brokerage_commissions_bps.value
        has_any = True

    if cb.bid_ask_spread_cost and cb.bid_ask_spread_cost.tag != DataSourceTag.UNAVAILABLE:
        total += cb.bid_ask_spread_cost.low_bps
        has_any = True

    if cb.market_impact_cost and cb.market_impact_cost.tag != DataSourceTag.UNAVAILABLE:
        total += cb.market_impact_cost.low_bps
        has_any = True

    return total if has_any else None


def _sum_costs_high(cb) -> float | None:
    """Sum the high end of all available cost components."""
    total = 0.0
    has_any = False

    if cb.brokerage_commissions_bps and cb.brokerage_commissions_bps.is_available:
        total += cb.brokerage_commissions_bps.value
        has_any = True

    if cb.bid_ask_spread_cost and cb.bid_ask_spread_cost.tag != DataSourceTag.UNAVAILABLE:
        total += cb.bid_ask_spread_cost.high_bps
        has_any = True

    if cb.market_impact_cost and cb.market_impact_cost.tag != DataSourceTag.UNAVAILABLE:
        total += cb.market_impact_cost.high_bps
        has_any = True

    return total if has_any else None


def _format_dollars(amount: float) -> str:
    """Format a dollar amount with appropriate scale."""
    if abs(amount) >= 1_000_000_000_000:
        return f"${amount / 1_000_000_000_000:.1f}T"
    elif abs(amount) >= 1_000_000_000:
        return f"${amount / 1_000_000_000:.1f}B"
    elif abs(amount) >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    else:
        return f"${amount:,.0f}"
