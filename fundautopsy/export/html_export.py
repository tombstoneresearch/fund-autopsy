"""HTML export — self-contained, shareable Fund Autopsy report.

Generates a single HTML file with all styles and data inlined.
No external dependencies. Dark theme. Tombstone Research branding.
Designed to be screenshot-friendly and shareable on social media.
"""

from __future__ import annotations

import html
from datetime import date
from pathlib import Path

from fundautopsy.models.filing_data import DataSourceTag
from fundautopsy.models.holdings_tree import FundNode


def export_html(result: FundNode, output_path: Path) -> None:
    """Export analysis as a self-contained HTML report.

    Args:
        result: Completed FundNode with cost_breakdown populated.
        output_path: Where to write the HTML file.
    """
    data = _extract_report_data(result)
    html = _render_html(data)
    output_path.write_text(html, encoding="utf-8")


def _extract_report_data(result: FundNode) -> dict:
    """Pull all display data from the FundNode tree."""
    cb = result.cost_breakdown
    nport = result.nport_data
    meta = result.metadata

    data = {
        "ticker": meta.ticker,
        "name": meta.name,
        "family": meta.fund_family or "",
        "net_assets": nport.total_net_assets if nport else None,
        "holdings_count": len(nport.holdings) if nport else 0,
        "period_end": str(nport.reporting_period_end) if nport else None,
        "asset_mix": nport.asset_class_weights() if nport else {},
        "is_fof": meta.is_fund_of_funds,
        "data_notes": result.data_notes,
        "generated": str(date.today()),
    }

    if cb:
        data["brokerage_bps"] = (
            cb.brokerage_commissions_bps.value
            if cb.brokerage_commissions_bps and cb.brokerage_commissions_bps.is_available
            else None
        )
        data["brokerage_note"] = (
            cb.brokerage_commissions_bps.note if cb.brokerage_commissions_bps else None
        )
        data["soft_dollar_active"] = (
            cb.soft_dollar_commissions_bps is not None
            and cb.soft_dollar_commissions_bps.tag == DataSourceTag.NOT_DISCLOSED
        )
        data["spread_low"] = cb.bid_ask_spread_cost.low_bps if cb.bid_ask_spread_cost else None
        data["spread_high"] = cb.bid_ask_spread_cost.high_bps if cb.bid_ask_spread_cost else None
        data["impact_low"] = cb.market_impact_cost.low_bps if cb.market_impact_cost else None
        data["impact_high"] = cb.market_impact_cost.high_bps if cb.market_impact_cost else None

        # Totals
        low = (data.get("brokerage_bps") or 0)
        high = (data.get("brokerage_bps") or 0)
        if data.get("spread_low") is not None:
            low += data["spread_low"]
            high += data["spread_high"]
        if data.get("impact_low") is not None:
            low += data["impact_low"]
            high += data["impact_high"]
        data["total_low"] = round(low, 2)
        data["total_high"] = round(high, 2)
    else:
        data["brokerage_bps"] = None
        data["total_low"] = None
        data["total_high"] = None

    return data


def _format_dollars(amount: float) -> str:
    if abs(amount) >= 1_000_000_000_000:
        return f"${amount / 1_000_000_000_000:.1f}T"
    elif abs(amount) >= 1_000_000_000:
        return f"${amount / 1_000_000_000:.1f}B"
    elif abs(amount) >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    return f"${amount:,.0f}"


def _format_dollars_full(amount: float) -> str:
    return f"${amount:,.0f}"


def _esc(text: str) -> str:
    """HTML-escape user-controlled text to prevent XSS."""
    return html.escape(str(text), quote=True)


def _render_html(d: dict) -> str:
    """Render the full HTML report."""

    net_assets_display = _format_dollars(d["net_assets"]) if d.get("net_assets") else "N/A"
    net_assets_full = _format_dollars_full(d["net_assets"]) if d.get("net_assets") else ""

    # Escape all user-controlled strings
    safe_name = _esc(d['name'])
    safe_ticker = _esc(d['ticker'])
    safe_family = _esc(d['family'])

    # Asset mix bars
    asset_cats = {
        "EC": ("Equity", "#4ade80"),
        "EP": ("Preferred", "#a78bfa"),
        "DBT": ("Debt", "#60a5fa"),
        "STIV": ("Cash/STIV", "#fbbf24"),
        "OTHER": ("Other", "#94a3b8"),
    }
    mix = d.get("asset_mix", {})
    asset_bars_html = ""
    for cat, pct in sorted(mix.items(), key=lambda x: -x[1]):
        label, color = asset_cats.get(cat, (cat, "#94a3b8"))
        bar_width = min(pct, 100)
        asset_bars_html += f"""
        <div class="asset-row">
          <span class="asset-label">{_esc(label)}</span>
          <div class="asset-bar-track">
            <div class="asset-bar-fill" style="width:{bar_width}%;background:{color}"></div>
          </div>
          <span class="asset-pct">{pct:.1f}%</span>
        </div>"""

    # Cost rows
    brokerage_val = f'{d["brokerage_bps"]:.2f}' if d.get("brokerage_bps") is not None else "—"
    brokerage_class = "val-reported" if d.get("brokerage_bps") is not None else "val-na"

    soft_dollar_html = ""
    if d.get("soft_dollar_active"):
        soft_dollar_html = """
        <tr class="cost-row sub-row">
          <td class="cost-label">Soft Dollar Arrangements</td>
          <td class="cost-value val-warning">ACTIVE</td>
          <td class="cost-tag"><span class="tag tag-warning">not disclosed $</span></td>
        </tr>"""

    spread_val = f'{d["spread_low"]:.1f} – {d["spread_high"]:.1f}' if d.get("spread_low") is not None else "—"
    impact_val = f'{d["impact_low"]:.1f} – {d["impact_high"]:.1f}' if d.get("impact_low") is not None else "—"

    total_val = f'{d["total_low"]:.1f} – {d["total_high"]:.1f}' if d.get("total_low") is not None else "N/A"

    # Data notes
    notes_html = ""
    for note in d.get("data_notes", []):
        notes_html += f'<li>{_esc(note)}</li>'

    # Commission breakdown callout
    comm_note = d.get("brokerage_note", "")
    comm_callout = ""
    if comm_note:
        comm_callout = f'<div class="callout">{_esc(comm_note)}</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fund Autopsy — {safe_ticker} | Tombstone Research</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap');

  :root {{
    --bg: #0b0d11;
    --surface: #12151c;
    --surface-2: #1a1e28;
    --border: #252a36;
    --text: #e4e2df;
    --text-dim: #8a8f9e;
    --text-muted: #5a5f6e;
    --accent: #c9a84c;
    --green: #4ade80;
    --red: #ef4444;
    --yellow: #fbbf24;
    --blue: #60a5fa;
    --purple: #a78bfa;
  }}

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Inter', -apple-system, sans-serif;
    line-height: 1.6;
    min-height: 100vh;
  }}

  .report {{
    max-width: 900px;
    margin: 0 auto;
    padding: 40px 24px 60px;
  }}

  /* Header */
  .header {{
    border-bottom: 1px solid var(--border);
    padding-bottom: 32px;
    margin-bottom: 40px;
  }}

  .brand {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 24px;
  }}

  .brand-icon {{
    width: 36px;
    height: 36px;
    background: var(--accent);
    border-radius: 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 800;
    font-size: 16px;
    color: #0b0d11;
  }}

  .brand-name {{
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--text-dim);
  }}

  .fund-name {{
    font-size: 36px;
    font-weight: 800;
    letter-spacing: -0.5px;
    line-height: 1.15;
    margin-bottom: 4px;
  }}

  .fund-ticker {{
    font-family: 'JetBrains Mono', monospace;
    color: var(--accent);
    font-weight: 700;
  }}

  .fund-family {{
    font-size: 16px;
    color: var(--text-dim);
    font-weight: 400;
  }}

  .fund-meta {{
    display: flex;
    gap: 32px;
    margin-top: 20px;
    flex-wrap: wrap;
  }}

  .meta-item {{
    display: flex;
    flex-direction: column;
  }}

  .meta-label {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--text-muted);
    font-weight: 600;
    margin-bottom: 2px;
  }}

  .meta-value {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 18px;
    font-weight: 700;
    color: var(--text);
  }}

  .meta-value-sub {{
    font-size: 12px;
    color: var(--text-dim);
    font-family: 'Inter', sans-serif;
    font-weight: 400;
  }}

  /* Hero number */
  .hero {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 36px 40px;
    text-align: center;
    margin-bottom: 32px;
    position: relative;
    overflow: hidden;
  }}

  .hero::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: linear-gradient(90deg, var(--accent), var(--yellow), var(--red));
  }}

  .hero-label {{
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--text-dim);
    font-weight: 600;
    margin-bottom: 12px;
  }}

  .hero-number {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 56px;
    font-weight: 700;
    color: var(--yellow);
    line-height: 1;
    margin-bottom: 12px;
  }}

  .hero-unit {{
    font-size: 24px;
    color: var(--text-dim);
  }}

  .hero-note {{
    font-size: 15px;
    color: var(--text-dim);
    max-width: 600px;
    margin: 0 auto;
    line-height: 1.5;
  }}

  .hero-note strong {{
    color: var(--text);
  }}

  /* Cost table */
  .section-title {{
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--text-muted);
    font-weight: 700;
    margin-bottom: 16px;
    margin-top: 40px;
  }}

  .cost-table {{
    width: 100%;
    border-collapse: collapse;
    background: var(--surface);
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid var(--border);
  }}

  .cost-table th {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--text-muted);
    font-weight: 600;
    padding: 14px 20px;
    text-align: left;
    background: var(--surface-2);
    border-bottom: 1px solid var(--border);
  }}

  .cost-table th:nth-child(2),
  .cost-table th:nth-child(3) {{
    text-align: right;
  }}

  .cost-row td {{
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    font-size: 15px;
  }}

  .cost-row:last-child td {{
    border-bottom: none;
  }}

  .cost-label {{
    font-weight: 500;
  }}

  .sub-row .cost-label {{
    padding-left: 24px;
    font-weight: 400;
    font-size: 14px;
    color: var(--text-dim);
  }}

  .cost-value {{
    font-family: 'JetBrains Mono', monospace;
    font-weight: 600;
    text-align: right;
    font-size: 15px;
  }}

  .val-reported {{ color: var(--green); }}
  .val-estimated {{ color: var(--yellow); }}
  .val-warning {{ color: var(--red); font-weight: 700; }}
  .val-na {{ color: var(--text-muted); }}
  .val-total {{ color: var(--yellow); font-size: 17px; font-weight: 700; }}

  .cost-tag {{
    text-align: right;
  }}

  .tag {{
    display: inline-block;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 3px 8px;
    border-radius: 4px;
    font-weight: 600;
  }}

  .tag-reported {{ background: rgba(74,222,128,0.12); color: var(--green); }}
  .tag-estimated {{ background: rgba(251,191,36,0.12); color: var(--yellow); }}
  .tag-warning {{ background: rgba(239,68,68,0.12); color: var(--red); }}

  .total-row {{
    background: var(--surface-2);
  }}

  .total-row td {{
    padding: 18px 20px;
    border-top: 2px solid var(--border);
    font-weight: 700;
  }}

  /* Callout */
  .callout {{
    background: var(--surface);
    border-left: 3px solid var(--accent);
    border-radius: 0 8px 8px 0;
    padding: 14px 20px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    color: var(--text-dim);
    margin-top: 12px;
  }}

  /* Asset allocation */
  .asset-grid {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 24px;
  }}

  .asset-row {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 10px;
  }}

  .asset-row:last-child {{ margin-bottom: 0; }}

  .asset-label {{
    width: 80px;
    font-size: 13px;
    font-weight: 500;
    color: var(--text-dim);
  }}

  .asset-bar-track {{
    flex: 1;
    height: 22px;
    background: var(--surface-2);
    border-radius: 4px;
    overflow: hidden;
  }}

  .asset-bar-fill {{
    height: 100%;
    border-radius: 4px;
    transition: width 0.8s ease;
  }}

  .asset-pct {{
    width: 60px;
    text-align: right;
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
  }}

  /* Notes */
  .notes {{
    margin-top: 32px;
    padding: 20px 24px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
  }}

  .notes-title {{
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--text-muted);
    font-weight: 600;
    margin-bottom: 10px;
  }}

  .notes ul {{
    list-style: none;
    padding: 0;
  }}

  .notes li {{
    font-size: 13px;
    color: var(--text-dim);
    padding: 4px 0;
    padding-left: 16px;
    position: relative;
  }}

  .notes li::before {{
    content: '\\2022';
    position: absolute;
    left: 0;
    color: var(--text-muted);
  }}

  /* Footer */
  .footer {{
    margin-top: 48px;
    padding-top: 24px;
    border-top: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    flex-wrap: wrap;
    gap: 16px;
  }}

  .footer-left {{
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.8;
  }}

  .footer-right {{
    text-align: right;
  }}

  .footer-brand {{
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--text-dim);
  }}

  .footer-url {{
    font-size: 12px;
    color: var(--text-muted);
    font-family: 'JetBrains Mono', monospace;
  }}

  /* Responsive */
  @media (max-width: 640px) {{
    .report {{ padding: 24px 16px 40px; }}
    .fund-name {{ font-size: 24px; }}
    .hero-number {{ font-size: 40px; }}
    .fund-meta {{ gap: 20px; }}
    .meta-value {{ font-size: 16px; }}
    .cost-row td {{ padding: 12px 14px; font-size: 14px; }}
  }}

  /* Print */
  @media print {{
    body {{ background: #fff; color: #111; }}
    .report {{ max-width: 100%; }}
  }}
</style>
</head>
<body>
<div class="report">

  <div class="header">
    <div class="brand">
      <div class="brand-icon">X</div>
      <span class="brand-name">Tombstone Research</span>
    </div>

    <div class="fund-name">
      {safe_name} <span class="fund-ticker">{safe_ticker}</span>
    </div>
    <div class="fund-family">{safe_family}</div>

    <div class="fund-meta">
      <div class="meta-item">
        <span class="meta-label">Net Assets</span>
        <span class="meta-value">{net_assets_display}</span>
        <span class="meta-value-sub">{net_assets_full}</span>
      </div>
      <div class="meta-item">
        <span class="meta-label">Holdings</span>
        <span class="meta-value">{d['holdings_count']}</span>
      </div>
      <div class="meta-item">
        <span class="meta-label">Filing Period</span>
        <span class="meta-value">{d.get('period_end', 'N/A')}</span>
      </div>
      <div class="meta-item">
        <span class="meta-label">Report Date</span>
        <span class="meta-value">{d['generated']}</span>
      </div>
    </div>
  </div>

  <div class="hero">
    <div class="hero-label">Estimated Hidden Costs</div>
    <div class="hero-number">{total_val} <span class="hero-unit">bps</span></div>
    <div class="hero-note">
      Beyond the stated expense ratio, this fund incurs an estimated
      <strong>{total_val} basis points</strong> in hidden trading costs annually.
      These costs reduce returns <em>before</em> the expense ratio is even deducted.
    </div>
  </div>

  <div class="section-title">Cost Breakdown</div>
  <table class="cost-table">
    <thead>
      <tr>
        <th>Component</th>
        <th>bps</th>
        <th>Source</th>
      </tr>
    </thead>
    <tbody>
      <tr class="cost-row">
        <td class="cost-label">Brokerage Commissions</td>
        <td class="cost-value {brokerage_class}">{brokerage_val}</td>
        <td class="cost-tag"><span class="tag tag-reported">SEC filing</span></td>
      </tr>
      {soft_dollar_html}
      <tr class="cost-row">
        <td class="cost-label">Bid-Ask Spread Cost</td>
        <td class="cost-value val-estimated">{spread_val}</td>
        <td class="cost-tag"><span class="tag tag-estimated">estimated</span></td>
      </tr>
      <tr class="cost-row">
        <td class="cost-label">Market Impact Cost</td>
        <td class="cost-value val-estimated">{impact_val}</td>
        <td class="cost-tag"><span class="tag tag-estimated">estimated</span></td>
      </tr>
      <tr class="cost-row total-row">
        <td class="cost-label">Total Hidden Costs</td>
        <td class="cost-value val-total">{total_val}</td>
        <td class="cost-tag"><span class="tag tag-estimated">composite</span></td>
      </tr>
    </tbody>
  </table>
  {comm_callout}

  <div class="section-title">Asset Allocation</div>
  <div class="asset-grid">
    {asset_bars_html}
  </div>

  {"" if not notes_html else f'''
  <div class="notes">
    <div class="notes-title">Data Notes</div>
    <ul>{notes_html}</ul>
  </div>'''}

  <div class="footer">
    <div class="footer-left">
      Methodology: Brokerage commissions from SEC Form N-CEN.<br>
      Spread and impact estimated from N-PORT asset class mix and portfolio turnover.<br>
      All data sourced from public SEC EDGAR filings. No proprietary data used.
    </div>
    <div class="footer-right">
      <div class="footer-brand">Tombstone Research</div>
      <div class="footer-url">github.com/tombstoneresearch/fundautopsy</div>
    </div>
  </div>

</div>
</body>
</html>"""
