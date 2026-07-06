# Fund Autopsy ☠

**Open-source regulatory transparency engine for mutual funds.**

The expense ratio is the front door. Fund Autopsy reads the filings behind it. We parse the SEC filings a mutual fund is required to submit and surface the costs, conflicts, and structural incentives that never make it into the fee table, with every figure traced to its source filing.

<p align="center">
  <strong>Tombstone Research</strong><br>
  <em>Leave no stone unturned.</em>
</p>

---

## The Problem

Every mutual fund cost calculator stops at the expense ratio. That number covers management fees, 12b-1 fees, and administrative expenses. It does not cover brokerage commissions paid when the fund trades, soft dollar arrangements where the fund pays inflated commissions in exchange for research consumed by the adviser, securities lending revenue kept by affiliated agents, affiliated broker routing, or the estimated spread and market-impact costs of turning the portfolio over.

The data to examine all of this has been sitting in SEC filings since 2018, structured and machine-readable, filed by every fund in America. Almost nobody aggregates it. Fund Autopsy does, and publishes the method.

## How Fund Autopsy Works

Fund Autopsy is **publish-time, not request-time**. Analysis runs in batch against SEC EDGAR, writes dated JSON snapshots with full per-stage provenance, and renders them to a static ledger. Nothing on the published site is computed when you load it; every number was reviewed before it went up, carries its filing vintage, and can be regenerated from the snapshot.

```bash
pip install fundautopsy

# Diagnose one fund, stage by stage, in plain English
fundautopsy doctor FCNTX

# Analyze a universe and write dated snapshots with provenance
fundautopsy batch tickers.txt --timeout 180

# Render the static scorecard site from snapshots
fundautopsy site data/snapshots/2026-Q3 --out docs
```

There is also a local interactive app (`pip install fundautopsy[web]`, then `python -m fundautopsy.web`) for exploring single funds on your own machine. The published product is the static ledger.

### The pipeline, and why failures are legible

Every analysis runs staged: resolve (ticker to CIK/series/class, backed by SEC's ticker master and the authoritative series/class census), structure (filings retrieval, fund-of-funds detection), costs (N-CEN and N-PORT derived), rollup (recursive fund-of-funds unwind), and fees (stated expense ratio from the prospectus). Each stage reports OK, DEGRADED with the fallback named, or FAILED with what was tried. A fund either renders complete, renders with visible caveats, or is excluded with a stated reason. If a ticker does not exist in the SEC's census, the tool says exactly that.

## What Makes This Different

| Feature | FINRA Fund Analyzer | Morningstar | Fund Autopsy |
|---------|:------------------:|:-----------:|:--------:|
| Expense ratio | Yes | Yes | Yes |
| Brokerage commissions (actual $) | No | No | **N-CEN data** |
| Soft dollar arrangements | No | No | **Yes** |
| Affiliated broker conflicts | No | No | **Yes** |
| Securities lending revenue | No | No | **Yes** |
| Holdings-based cost modeling | No | Partial | **N-PORT data** |
| Fund-of-funds fee decomposition | No | No | **Yes** |
| Every figure cited to a filing | No | No | **Yes** |
| Open source | No | No | **Yes** |

**Reported before modeled.** The ledger's headline column counts only costs the fund itself filed in dollars: brokerage commissions and disclosed soft-dollar commissions from N-CEN. Modeled estimates (bid-ask spread, market impact) are shown separately, as ranges, tagged as estimates, because that is what they are.

## Data Sources

| Filing | What It Provides | Frequency |
|--------|-----------------|-----------|
| **N-CEN** | Brokerage commissions, soft dollar arrangements, affiliated broker usage, securities lending revenue, service providers, credit lines | Annual |
| **N-PORT** | Complete portfolio holdings, asset class breakdown, net assets | Quarterly |
| **497K / 485BPOS** | Expense ratio, management fee, 12b-1 fee, turnover, with XBRL fallback across both `oef:` and `rr:` taxonomies | Per share class |
| **SAI** | Broker-specific commission breakdowns, PM compensation, soft dollar detail | Annual |
| **N-CSR** | Realized commissions with multi-year history, board contract-approval basis | Semiannual |
| **N-14** | Fund merger fee impact | Per event |
| **Series/class census** | Authoritative registry of every live share class; dead tickers answered definitively | Annual |

Multi-series umbrella trusts (Fidelity, Vanguard, JPMorgan, Capital Group, BlackRock and similar) are handled through a layered resolution pipeline: ticker master, then the SEC series/class census, then an SGML-header walker over the registrant's filings, with family-specific fee-table parsers where registrants' filing conventions require them.

All data retrieved from SEC EDGAR. No proprietary data, no scraping, no third-party APIs required (an optional OpenFIGI CUSIP lookup assists fund-of-funds resolution and disables itself cleanly when unavailable).

## Known Limitations

1. N-CEN data starts in 2018 and is filed annually; commission data may be up to 12 months old. Every figure carries its filing vintage.
2. Bid-ask spread and market impact are model estimates, not observed execution costs. They are displayed as ranges, tagged, and kept out of the headline reported column. The assumption set and its academic anchors are documented in [docs/methodology.md](docs/methodology.md) and [docs/limitations.md](docs/limitations.md).
3. Soft dollar fields are inconsistently reported; blanks are flagged as not disclosed rather than treated as zero.
4. Fund-of-funds unwinding depends on resolving underlying holdings to registered funds; unresolved children are shown as unresolved weight, never silently zeroed.

## Contributing

Contributions welcome. Priority areas: empirical refinement of the spread and impact assumptions, additional filing coverage (N-PX proxy voting, Form ADV, Form CRS, N-8F deregistrations), and validation across additional fund families.

## Disclaimer

Fund Autopsy is provided for educational and informational purposes only. It does not constitute investment advice, a recommendation, or an offer to buy or sell any security. Hidden cost estimates are based on publicly available SEC filings and published academic models; actual costs vary. Consult a qualified financial advisor before making investment decisions. Tombstone Research is not a registered investment adviser, broker-dealer, or financial planner.

## License

MIT License. See [LICENSE](LICENSE).

---

**Tombstone Research** — *Leave no stone unturned.*
