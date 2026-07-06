"""Tier 3: Researcher/developer view — raw data, time series, exports."""

from __future__ import annotations

from rich.console import Console

from fundautopsy.models.holdings_tree import FundNode


def render(result: FundNode, console: Console) -> None:
    """Render Tier 3 researcher output.

    Shows everything in Tier 2 plus:
    - Raw N-CEN dollar amounts
    - Time series across filing periods
    - Security-level N-PORT data
    - Confidence indicators per component
    - Direct EDGAR filing links
    """
    # TODO: Implement researcher view
    console.print("[yellow]Tier 3 researcher view not yet implemented[/yellow]")
