"""Static site generator.

Renders batch snapshots into a static scorecard site: one index ledger
plus one autopsy report page per fund. Pure stdlib, no request-time
computation, no JavaScript. Design language: 19th-century financial
broadsheet ("Frontier Forensics") — aged paper, classical serif,
hairline and double rules, a single accent color used only where the
finding lives. Deliberately unlike a contemporary dashboard.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

_CSS = """
:root {
  --paper: #f2ead8;
  --paper-deep: #e9dfc8;
  --ink: #211a12;
  --ink-faded: #5c5142;
  --rule: #8d7f66;
  --accent: #7c2b23; /* weathered red: the investigator's pen */
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html { background: var(--paper-deep); }
body {
  font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
  background: var(--paper);
  color: var(--ink);
  max-width: 60rem;
  margin: 0 auto;
  padding: 2.5rem 1.5rem 4rem;
  line-height: 1.55;
  font-variant-numeric: oldstyle-nums tabular-nums;
}
a { color: var(--ink); text-decoration-color: var(--rule); text-underline-offset: 3px; }
a:hover { color: var(--accent); }

.masthead { text-align: center; border-top: 4px double var(--ink); border-bottom: 1px solid var(--ink); padding: 1.4rem 0 1rem; }
.masthead .org {
  font-size: 0.85rem; letter-spacing: 0.45em; text-transform: uppercase; color: var(--ink-faded);
}
.masthead h1 {
  font-size: 3rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; line-height: 1.1; margin: 0.4rem 0 0.2rem;
}
.masthead .motto { font-style: italic; color: var(--ink-faded); font-size: 1rem; }
.dateline {
  display: flex; justify-content: space-between; font-size: 0.78rem; letter-spacing: 0.12em;
  text-transform: uppercase; color: var(--ink-faded);
  border-bottom: 4px double var(--ink); padding: 0.35rem 0.2rem; margin-bottom: 2rem;
}

.prologue { max-width: 44rem; margin: 0 auto 2.2rem; font-size: 1.02rem; }
.prologue p + p { margin-top: 0.8rem; }
.prologue .smallcaps { font-variant: small-caps; letter-spacing: 0.04em; }

table.ledger { width: 100%; border-collapse: collapse; font-size: 0.95rem; }
table.ledger caption {
  font-variant: small-caps; letter-spacing: 0.25em; font-size: 0.85rem;
  border-bottom: 1px solid var(--ink); padding-bottom: 0.4rem; margin-bottom: 0.2rem;
}
table.ledger th {
  font-size: 0.72rem; letter-spacing: 0.14em; text-transform: uppercase; font-weight: 600;
  color: var(--ink-faded); text-align: right; padding: 0.5rem 0.6rem;
  border-bottom: 2px solid var(--ink);
}
table.ledger th.l, table.ledger td.l { text-align: left; }
table.ledger td { padding: 0.45rem 0.6rem; text-align: right; border-bottom: 1px dotted var(--rule); }
table.ledger tr:hover td { background: var(--paper-deep); }
td.gap, .gap { color: var(--accent); font-weight: 700; }
.caveat { font-size: 0.75rem; color: var(--ink-faded); font-style: italic; }

.report-head { border: 1px solid var(--ink); padding: 1.2rem 1.4rem; margin-bottom: 1.6rem; }
.report-head .no { font-size: 0.72rem; letter-spacing: 0.2em; text-transform: uppercase; color: var(--ink-faded); }
.report-head h2 { font-size: 1.7rem; text-transform: uppercase; letter-spacing: 0.04em; margin: 0.2rem 0 0.6rem; }
.subject-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: 0.4rem 1.4rem; font-size: 0.9rem; }
.subject-grid .k { font-size: 0.68rem; letter-spacing: 0.14em; text-transform: uppercase; color: var(--ink-faded); display: block; }

.verdict {
  border-top: 4px double var(--ink); border-bottom: 4px double var(--ink);
  margin: 1.8rem 0; padding: 1rem 0.4rem; display: flex; gap: 2.5rem; flex-wrap: wrap; justify-content: center; text-align: center;
}
.verdict .fig { font-size: 1.9rem; font-weight: 700; }
.verdict .lbl { font-size: 0.7rem; letter-spacing: 0.16em; text-transform: uppercase; color: var(--ink-faded); }

h3.section {
  font-variant: small-caps; letter-spacing: 0.22em; font-weight: 600; font-size: 0.95rem;
  border-bottom: 1px solid var(--ink); margin: 2rem 0 0.7rem; padding-bottom: 0.25rem;
}
ul.notes { list-style: none; font-size: 0.88rem; }
ul.notes li { padding: 0.25rem 0; border-bottom: 1px dotted var(--rule); }
ul.notes li::before { content: "— "; color: var(--ink-faded); }

.provenance { font-size: 0.85rem; }
.provenance .st-ok::before { content: "✓ "; }
.provenance .st-degraded::before { content: "△ "; color: var(--accent); }
.provenance .st-failed::before { content: "✕ "; color: var(--accent); }

.colophon {
  margin-top: 3rem; border-top: 1px solid var(--ink); padding-top: 0.9rem;
  font-size: 0.78rem; color: var(--ink-faded);
}
.colophon p + p { margin-top: 0.5rem; }
@media (max-width: 40rem) { .masthead h1 { font-size: 2rem; } body { padding: 1.2rem 0.8rem 3rem; } }
"""

_DISCLAIMER = (
    "Educational and informational purposes only. Not investment advice, not a "
    "recommendation, not an offer to buy or sell any security. Trading-cost "
    "figures are estimates derived from public SEC filings and published "
    "academic models; actual costs vary. Tombstone Research is not a "
    "registered investment adviser or broker-dealer."
)


@dataclass
class FundRow:
    """Flattened index-row view of one snapshot."""

    ticker: str
    name: str
    family: str
    stated_bps: float | None
    reported_hidden_bps: float | None
    est_low_bps: float | None
    est_high_bps: float | None
    gap_bps: float | None
    period: str
    caveats: int


def reported_hidden_bps(costs: dict[str, Any]) -> float | None:
    """Sum of hidden costs backed by reported filing dollars only.

    Brokerage commissions and disclosed soft-dollar commissions are
    figures a fund filed with the SEC; spreads and market impact are
    model estimates and are deliberately excluded here. The ledger
    leads with this number because it is immune to model criticism.
    """
    total = 0.0
    found = False
    bc = costs.get("brokerage_commissions_bps")
    if bc and bc.get("value") is not None:
        total += float(bc["value"])
        found = True
    soft = costs.get("soft_dollar_arrangements")
    if soft and soft.get("value_bps") is not None:
        total += float(soft["value_bps"])
        found = True
    return total if found else None


def _esc(text: Any) -> str:
    return html.escape(str(text)) if text is not None else ""


def _bps(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def _page(title: str, body: str, generated: str, depth: int = 0) -> str:
    css_href = ("../" * depth) + "style.css"
    home = ("../" * depth) + "index.html"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<link rel="stylesheet" href="{css_href}">
</head>
<body>
<header class="masthead">
  <div class="org">Tombstone Research</div>
  <h1><a href="{home}" style="text-decoration:none">Fund Autopsy</a></h1>
  <div class="motto">Leave no stone unturned.</div>
</header>
<div class="dateline"><span>A ledger of what funds actually cost</span><span>Prepared {_esc(generated)}</span></div>
{body}
<footer class="colophon">
  <p>{_esc(_DISCLAIMER)}</p>
  <p>Every figure on this page traces to a public SEC filing (N-CEN, N-PORT, 497K, 485BPOS, SAI, N-CSR) or to a
  disclosed estimation model. Methodology, limitations, and source code are published in full.
  Snapshots are precomputed and dated; nothing on this site is calculated at request time.</p>
</footer>
</body>
</html>"""


def _load_snapshots(snapshot_dir: Path) -> list[dict[str, Any]]:
    snaps = []
    for p in sorted(snapshot_dir.glob("*.json")):
        if p.name == "manifest.json":
            continue
        try:
            snaps.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return snaps


def _row_from_snapshot(snap: dict[str, Any]) -> FundRow | None:
    analysis = snap.get("analysis")
    if not analysis:
        return None
    costs = analysis.get("costs", {})
    # Stated = the prospectus expense ratio, and only that. Never
    # substitute total_reported_bps (a hidden-cost composite) here.
    er = costs.get("expense_ratio_bps") or {}
    stated = er.get("value")
    low = costs.get("total_estimated_low_bps")
    high = costs.get("total_estimated_high_bps")
    gap = costs.get("hidden_cost_gap_bps")
    return FundRow(
        ticker=analysis.get("ticker") or snap.get("ticker", "?"),
        name=analysis.get("name") or "",
        family=analysis.get("fund_family") or "",
        stated_bps=stated,
        reported_hidden_bps=reported_hidden_bps(costs),
        est_low_bps=low,
        est_high_bps=high,
        gap_bps=gap,
        period=str(analysis.get("reporting_period_end") or ""),
        caveats=len(snap.get("provenance", {}).get("quality_notes", [])),
    )


def _render_index(rows: list[FundRow], generated: str, quarter: str) -> str:
    rows_sorted = sorted(
        rows,
        key=lambda r: (
            r.reported_hidden_bps is None,
            -(r.reported_hidden_bps or 0),
            -(r.gap_bps or 0),
        ),
    )
    body_rows = []
    for i, r in enumerate(rows_sorted, 1):
        est = (
            f"{_bps(r.est_low_bps)}–{_bps(r.est_high_bps)}"
            if r.est_low_bps is not None or r.est_high_bps is not None
            else "—"
        )
        caveat = f' <span class="caveat">({r.caveats} notes)</span>' if r.caveats else ""
        body_rows.append(
            f'<tr><td>{i}</td>'
            f'<td class="l"><a href="funds/{_esc(r.ticker)}.html">{_esc(r.name) or _esc(r.ticker)}</a>{caveat}</td>'
            f'<td class="l">{_esc(r.ticker)}</td>'
            f"<td>{_bps(r.stated_bps)}</td>"
            f'<td class="gap">{_bps(r.reported_hidden_bps)}</td>'
            f"<td>{est}</td>"
            f'<td class="l">{_esc(r.period)}</td></tr>'
        )
    prologue = f"""
<div class="prologue">
  <p><span class="smallcaps">The expense ratio is the front door.</span> Behind it sit brokerage commissions,
  soft dollar arrangements, bid-ask spreads, and market impact — costs that reduce a fund's return before its
  NAV is ever struck. The data to estimate them has been sitting in SEC filings since 2018. This ledger
  aggregates it, fund by fund, with every figure tagged to its source filing or estimation model.</p>
  <p>Figures are in basis points per year. "Reported hidden" counts only costs the fund itself filed in
  dollars (brokerage commissions and disclosed soft-dollar commissions from N-CEN); it is the number no model
  can be blamed for. "Estimated total" adds modeled spread and market-impact ranges on top, tagged as
  estimates because that is what they are. The methodology and its limitations are published in full.</p>
</div>"""
    table = f"""
<table class="ledger">
  <caption>Snapshot {_esc(quarter)}</caption>
  <thead><tr>
    <th>No.</th><th class="l">Fund</th><th class="l">Ticker</th>
    <th>Stated (bps)</th><th>Reported hidden (bps)</th><th>Estimated total (bps)</th><th class="l">Filing period</th>
  </tr></thead>
  <tbody>{''.join(body_rows)}</tbody>
</table>"""
    return _page("Fund Autopsy — The Ledger", prologue + table, generated)


def _render_fund(snap: dict[str, Any], generated: str, number: int) -> str:
    analysis = snap.get("analysis") or {}
    prov = snap.get("provenance", {})
    costs = analysis.get("costs", {})
    ticker = analysis.get("ticker") or snap.get("ticker", "?")

    def cost_cell(key: str) -> str:
        c = costs.get(key)
        if not c:
            return "<td>—</td><td>—</td><td class='l'>—</td>"
        if "low_bps" in c:
            rng = f"{_bps(c.get('low_bps'))}–{_bps(c.get('high_bps'))}"
            return f"<td>{rng}</td><td>{_bps(c.get('mid_bps'))}</td><td class='l'>{_esc(c.get('tag'))}</td>"
        return f"<td>{_bps(c.get('value'))}</td><td>—</td><td class='l'>{_esc(c.get('tag'))}</td>"

    components = [
        ("Expense ratio (stated)", "expense_ratio_bps"),
        ("Management fee", "management_fee_bps"),
        ("12b-1 fee", "twelve_b1_fee_bps"),
        ("Brokerage commissions", "brokerage_commissions_bps"),
        ("Bid-ask spread cost", "bid_ask_spread_cost"),
        ("Market impact", "market_impact_cost"),
    ]
    comp_rows = "".join(
        f'<tr><td class="l">{_esc(label)}</td>{cost_cell(key)}</tr>'
        for label, key in components
    )
    soft = costs.get("soft_dollar_arrangements")
    soft_line = ""
    if soft:
        state = "ACTIVE" if soft.get("active") else "none disclosed"
        val = _bps(soft.get("value_bps"))
        soft_line = (
            f'<tr><td class="l">Soft dollar arrangements</td>'
            f"<td>{val}</td><td>—</td><td class='l'>{_esc(soft.get('tag'))} · {state}</td></tr>"
        )

    stages = "".join(
        f'<li class="st-{_esc(s.get("status"))}">{_esc(s.get("label"))}'
        f'{" — " + _esc(s.get("detail")) if s.get("detail") else ""}</li>'
        for s in prov.get("stages", [])
    )
    notes = "".join(
        f"<li>{_esc(n)}</li>" for n in prov.get("quality_notes", [])
    ) or "<li>None recorded.</li>"

    net_assets = analysis.get("net_assets")
    na = f"${net_assets:,.0f}" if isinstance(net_assets, (int, float)) else "—"

    body = f"""
<div class="report-head">
  <div class="no">Autopsy report No. {number:03d} · Snapshot {_esc(snap.get('quarter', ''))}</div>
  <h2>{_esc(analysis.get('name') or ticker)}</h2>
  <div class="subject-grid">
    <div><span class="k">Ticker</span>{_esc(ticker)}</div>
    <div><span class="k">Family</span>{_esc(analysis.get('fund_family')) or "—"}</div>
    <div><span class="k">CIK</span>{_esc(analysis.get('cik')) or "—"}</div>
    <div><span class="k">Series / Class</span>{_esc(analysis.get('series_id')) or "—"} / {_esc(analysis.get('class_id')) or "—"}</div>
    <div><span class="k">Net assets</span>{na}</div>
    <div><span class="k">Holdings period</span>{_esc(analysis.get('reporting_period_end')) or "—"}</div>
  </div>
</div>
<div class="verdict">
  <div><div class="fig">{_bps(costs.get('total_reported_bps'))}</div><div class="lbl">Stated cost (bps)</div></div>
  <div><div class="fig">{_bps(costs.get('total_estimated_low_bps'))}–{_bps(costs.get('total_estimated_high_bps'))}</div><div class="lbl">Estimated total (bps)</div></div>
  <div><div class="fig gap">{_bps(costs.get('hidden_cost_gap_bps'))}</div><div class="lbl">The Gap (bps)</div></div>
</div>
<h3 class="section">Findings</h3>
<table class="ledger">
  <thead><tr><th class="l">Component</th><th>bps</th><th>Midpoint</th><th class="l">Source</th></tr></thead>
  <tbody>{comp_rows}{soft_line}</tbody>
</table>
<h3 class="section">Data notes</h3>
<ul class="notes">{notes}</ul>
<h3 class="section">Chain of custody</h3>
<ul class="notes provenance">{stages}</ul>
"""
    return _page(f"{ticker} — Fund Autopsy", body, generated, depth=1)


def build_site(snapshot_dir: Path, out_dir: Path) -> dict[str, int]:
    """Render the static site from a snapshot directory.

    Returns counts: {"funds": n, "excluded": m}.
    """
    snapshot_dir = Path(snapshot_dir)
    out_dir = Path(out_dir)
    (out_dir / "funds").mkdir(parents=True, exist_ok=True)

    snaps = _load_snapshots(snapshot_dir)
    generated = str(date.today())
    quarter = snaps[0].get("quarter", "") if snaps else ""

    rows: list[FundRow] = []
    excluded = 0
    number = 0
    for snap in snaps:
        row = _row_from_snapshot(snap)
        if row is None:
            excluded += 1
            continue
        number += 1
        rows.append(row)
        (out_dir / "funds" / f"{row.ticker}.html").write_text(
            _render_fund(snap, generated, number), encoding="utf-8"
        )

    (out_dir / "index.html").write_text(
        _render_index(rows, generated, quarter), encoding="utf-8"
    )
    (out_dir / "style.css").write_text(_CSS, encoding="utf-8")
    return {"funds": len(rows), "excluded": excluded}
