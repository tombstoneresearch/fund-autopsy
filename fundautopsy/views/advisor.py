"""Tier 2: Financial advisor view — full cost breakdown."""

from __future__ import annotations

from rich.console import Console

from fundautopsy.models.holdings_tree import FundNode


def render(result: FundNode, console: Console) -> None:
    """Render Tier 2 advisor output.

    Shows everything in Tier 1 plus:
    - Cost breakdown by component
    - Fund-of-funds drill-down table
    - Soft dollar disclosure status
    - Data freshness indicators
    """
    # TODO: Implement advisor view
    console.print("[yellow]Tier 2 advisor view not yet implemented[/yellow]")
