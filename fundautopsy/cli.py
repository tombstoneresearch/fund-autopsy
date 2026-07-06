"""Fund Autopsy command-line interface."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(
    name="fundautopsy",
    help="Mutual fund total cost of ownership analyzer. Uncovers hidden costs beyond the expense ratio.",
    add_completion=False,
)
console = Console()


class DetailLevel(str, Enum):
    """Output detail level for fund analysis results."""

    retail = "retail"
    advisor = "advisor"
    researcher = "researcher"


class ExportFormat(str, Enum):
    """Supported export formats for analysis results."""

    json = "json"
    csv = "csv"
    html = "html"


@app.command()
def analyze(
    ticker: str = typer.Argument(..., help="Fund ticker symbol (e.g., AGTHX, FFFHX)"),
    detail: DetailLevel = typer.Option(
        DetailLevel.retail, "--detail", "-d", help="Output detail level"
    ),
    export: ExportFormat | None = typer.Option(
        None, "--export", "-e", help="Export format"
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Output file path for export"
    ),
    history: str | None = typer.Option(
        None, "--history", help="Date range for time series (e.g., 2018-2025)"
    ),
) -> None:
    """Analyze a single fund's total cost of ownership."""
    console.print(f"\n[bold]Fund Autopsy[/bold] — Analyzing [cyan]{ticker.upper()}[/cyan]\n")

    # Pipeline stages
    from fundautopsy.core.costs import compute_costs
    from fundautopsy.core.fund import identify_fund
    from fundautopsy.core.rollup import rollup_costs
    from fundautopsy.core.structure import detect_structure
    from fundautopsy.models.fund_metadata import FundMetadata
    from fundautopsy.models.holdings_tree import FundNode

    with console.status("[bold green]Stage 1: Identifying fund..."):
        fund: FundMetadata = identify_fund(ticker)

    with console.status("[bold green]Stage 2: Retrieving SEC filings..."):
        tree: FundNode = detect_structure(fund)

    with console.status("[bold green]Stage 3: Computing costs..."):
        costs: FundNode = compute_costs(tree)

    with console.status("[bold green]Stage 4: Rolling up fund-of-funds..."):
        result: FundNode = rollup_costs(costs)

    # Render output
    if detail == DetailLevel.retail:
        from fundautopsy.views.retail import render
    elif detail == DetailLevel.advisor:
        from fundautopsy.views.advisor import render
    else:
        from fundautopsy.views.researcher import render

    render(result, console)

    # Export if requested
    if export and output:
        if export == ExportFormat.json:
            from fundautopsy.export.json_export import export_json

            export_json(result, output)
        elif export == ExportFormat.csv:
            from fundautopsy.export.csv_export import export_csv

            export_csv(result, output)
        elif export == ExportFormat.html:
            from fundautopsy.export.html_export import export_html

            export_html(result, output)

        console.print(f"\n[green]Exported to {output}[/green]")


@app.command()
def compare(
    tickers: list[str] = typer.Argument(..., help="2-5 fund ticker symbols to compare"),
    investment: float = typer.Option(100_000, "--investment", "-i", help="Investment amount in dollars"),
    horizon: int = typer.Option(20, "--horizon", help="Investment horizon in years"),
    assumed_return: float = typer.Option(0.07, "--return", "-r", help="Assumed annual return (decimal)"),
    detail: DetailLevel = typer.Option(
        DetailLevel.advisor, "--detail", "-d", help="Output detail level"
    ),
) -> None:
    """Compare total cost of ownership across 2-5 funds side by side."""
    if len(tickers) < 2:
        console.print("[red]Error: comparison requires at least 2 tickers.[/red]")
        raise typer.Exit(1)
    if len(tickers) > 5:
        console.print("[red]Error: comparison supports up to 5 tickers.[/red]")
        raise typer.Exit(1)

    console.print(
        f"\n[bold]Fund Autopsy[/bold] — Comparing "
        f"[cyan]{', '.join(t.upper() for t in tickers)}[/cyan]\n"
    )

    from fundautopsy.models.holdings_tree import FundNode
    from fundautopsy.views.comparison import render_comparison

    results: list[FundNode] = []
    for ticker in tickers:
        from fundautopsy.core.costs import compute_costs
        from fundautopsy.core.fund import identify_fund
        from fundautopsy.core.rollup import rollup_costs
        from fundautopsy.core.structure import detect_structure
        from fundautopsy.models.fund_metadata import FundMetadata

        with console.status(f"[bold green]Analyzing {ticker.upper()}..."):
            fund: FundMetadata = identify_fund(ticker)
            tree: FundNode = detect_structure(fund)
            costs: FundNode = compute_costs(tree)
            result: FundNode = rollup_costs(costs)
            results.append(result)

    render_comparison(results, investment, horizon, assumed_return, console)


if __name__ == "__main__":
    app()
