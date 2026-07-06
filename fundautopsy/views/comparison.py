"""Multi-fund comparison view."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from fundautopsy.models.holdings_tree import FundNode


def _grade(low: float, high: float) -> str:
    """Letter grade from hidden cost range."""
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


def _fmt_bps(val: float | None) -> str:
    """Format a value in basis points."""
    if val is None:
        return "—"
    return f"{val:.1f}"


def _fmt_pct(val: float | None) -> str:
    """Format a percentage."""
    if val is None:
        return "—"
    return f"{val:.3f}%"


def _fmt_dollars(amount: float) -> str:
    """Format dollar amounts with suffixes."""
    if abs(amount) >= 1e12:
        return f"${amount / 1e12:.1f}T"
    if abs(amount) >= 1e9:
        return f"${amount / 1e9:.1f}B"
    if abs(amount) >= 1e6:
        return f"${amount / 1e6:.1f}M"
    return f"${amount:,.0f}"


def render_comparison(
    results: list[FundNode],
    investment: float,
    horizon: int,
    assumed_return: float,
    console: Console,
) -> None:
    """Render side-by-side comparison of 2-5 funds.

    Shows:
    - Normalized costs in basis points
    - Lowest/highest cost highlighting
    - Total cost gap
    - Dollar impact over the specified horizon
    """
    if not results:
        console.print("[yellow]No funds to compare.[/yellow]")
        return

    # Build comparison data
    funds = []
    for node in results:
        meta = node.metadata
        cb = node.cost_breakdown
        nport = node.nport_data

        er_bps = None
        if cb and cb.expense_ratio_bps and cb.expense_ratio_bps.is_available:
            er_bps = cb.expense_ratio_bps.value

        brokerage_bps = None
        if cb and cb.brokerage_commissions_bps and cb.brokerage_commissions_bps.is_available:
            brokerage_bps = cb.brokerage_commissions_bps.value

        spread_low = cb.bid_ask_spread_cost.low_bps if cb and cb.bid_ask_spread_cost else 0
        spread_high = cb.bid_ask_spread_cost.high_bps if cb and cb.bid_ask_spread_cost else 0
        impact_low = cb.market_impact_cost.low_bps if cb and cb.market_impact_cost else 0
        impact_high = cb.market_impact_cost.high_bps if cb and cb.market_impact_cost else 0

        hidden_low = (brokerage_bps or 0) + spread_low + impact_low
        hidden_high = (brokerage_bps or 0) + spread_high + impact_high

        true_low_bps = (er_bps or 0) + hidden_low if er_bps is not None else None
        true_high_bps = (er_bps or 0) + hidden_high if er_bps is not None else None

        na = nport.total_net_assets if nport else None
        turnover = node.prospectus_turnover
        holdings = len(nport.holdings) if nport else 0
        grade = _grade(hidden_low, hidden_high)

        # Dollar impact
        gross = assumed_return / 100
        dollar_true = None
        if true_high_bps is not None:
            true_drag = true_high_bps / 10000
            final = investment * ((1 + gross - true_drag) ** horizon)
            no_cost = investment * ((1 + gross) ** horizon)
            dollar_true = no_cost - final

        funds.append({
            "ticker": meta.ticker,
            "name": meta.name,
            "er_bps": er_bps,
            "brokerage_bps": brokerage_bps,
            "spread_low": spread_low,
            "spread_high": spread_high,
            "impact_low": impact_low,
            "impact_high": impact_high,
            "hidden_low": hidden_low,
            "hidden_high": hidden_high,
            "true_low_bps": true_low_bps,
            "true_high_bps": true_high_bps,
            "na": na,
            "turnover": turnover,
            "holdings": holdings,
            "grade": grade,
            "dollar_cost": dollar_true,
        })

    # Find best/worst
    true_highs = [f["true_high_bps"] for f in funds if f["true_high_bps"] is not None]
    best_ticker = None
    worst_ticker = None
    if true_highs:
        best_ticker = min(funds, key=lambda f: f["true_high_bps"] or float("inf"))["ticker"]
        worst_ticker = max(funds, key=lambda f: f["true_high_bps"] or 0)["ticker"]

    # Build table
    table = Table(
        title="Fund Autopsy — Side-by-Side Comparison",
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        pad_edge=True,
    )

    table.add_column("Metric", style="bold", min_width=22)
    for f in funds:
        badge = ""
        if f["ticker"] == best_ticker and len(funds) > 1:
            badge = " ✓"
        elif f["ticker"] == worst_ticker and len(funds) > 1:
            badge = " ✗"
        table.add_column(f["ticker"] + badge, justify="right", min_width=14)

    # Rows
    table.add_row("Fund Name", *[f["name"][:24] for f in funds])
    table.add_row("Net Assets", *[_fmt_dollars(f["na"]) if f["na"] else "—" for f in funds])
    table.add_row("Holdings", *[str(f["holdings"]) for f in funds])
    table.add_row(
        "Turnover",
        *[f"{f['turnover']:.1f}%" if f["turnover"] else "—" for f in funds],
    )
    table.add_section()
    table.add_row("Expense Ratio", *[_fmt_bps(f["er_bps"]) + " bps" for f in funds])
    table.add_row("Brokerage Commissions", *[_fmt_bps(f["brokerage_bps"]) + " bps" for f in funds])
    table.add_row(
        "Bid-Ask Spread",
        *[f"{f['spread_low']:.1f}–{f['spread_high']:.1f} bps" for f in funds],
    )
    table.add_row(
        "Market Impact",
        *[f"{f['impact_low']:.1f}–{f['impact_high']:.1f} bps" for f in funds],
    )
    table.add_section()
    table.add_row(
        "Hidden Cost Range",
        *[f"{f['hidden_low']:.1f}–{f['hidden_high']:.1f} bps" for f in funds],
        style="bold",
    )
    table.add_row(
        "True Total Cost",
        *[
            f"{f['true_low_bps']:.1f}–{f['true_high_bps']:.1f} bps"
            if f["true_low_bps"] is not None
            else "—"
            for f in funds
        ],
        style="bold red",
    )
    table.add_row("Grade", *[f["grade"] for f in funds])
    table.add_section()
    table.add_row(
        f"Dollar Cost ({horizon}yr, ${investment:,.0f})",
        *[_fmt_dollars(f["dollar_cost"]) if f["dollar_cost"] else "—" for f in funds],
        style="bold yellow",
    )

    console.print()
    console.print(table)

    # Summary
    if best_ticker and worst_ticker and best_ticker != worst_ticker:
        best = next(f for f in funds if f["ticker"] == best_ticker)
        worst = next(f for f in funds if f["ticker"] == worst_ticker)
        if best["dollar_cost"] is not None and worst["dollar_cost"] is not None:
            savings = worst["dollar_cost"] - best["dollar_cost"]
            console.print()
            console.print(Panel(
                f"[green]{best_ticker}[/green] saves [bold green]{_fmt_dollars(savings)}[/bold green] "
                f"vs [red]{worst_ticker}[/red] over {horizon} years on a "
                f"${investment:,.0f} investment at {assumed_return}% annual return.",
                title="Bottom Line",
                border_style="green",
            ))
    console.print()
