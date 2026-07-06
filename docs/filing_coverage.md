# Fund Autopsy — SEC Filing Coverage Reference

## Overview

Fund Autopsy parses regulatory filings to surface mutual fund costs, conflicts, and structural incentives. This document maps every filing type in scope, what data it provides, where it lives, and its implementation status.

## Tier 1 — Core Cost Engine (Current + Near-Term)

| Filing | Source | Format | Data Extracted | Status |
|--------|--------|--------|---------------|--------|
| **497K** (Prospectus Fee Table) | EDGAR, part of N-1A | HTML | Expense ratio, management fee, 12b-1 fee, other expenses, fee waivers, turnover rate | **Live** — Custom HTML parser handles 3 table format variants |
| **N-CEN** (Annual Census) | EDGAR | XML | Brokerage commissions ($), soft dollar amounts, affiliated broker usage, securities lending revenue, service providers | **Live** — via edgartools |
| **N-PORT** (Quarterly Holdings) | EDGAR | XML | Complete holdings, asset class mix, net assets, liquidity classification | **Live** — via edgartools |
| **SAI** (Statement of Additional Information) | EDGAR, Part B of N-1A / 485BPOS | HTML | Broker-specific commissions (named brokers, 3-year $), PM compensation structure, revenue sharing, commission recapture, detailed soft dollar arrangements | **Planned** — HTML parser needed, fuzzy section matching |
| **N-CSR** (Shareholder Reports) | EDGAR | HTML / Inline XBRL | Realized commissions (multi-year $), portfolio turnover, expense ratios by class, board advisory contract approval basis | **Planned** |

## Tier 2 — Conflict Detection

| Filing | Source | Format | Data Extracted | Status |
|--------|--------|--------|---------------|--------|
| **Form ADV Part 2A** (Adviser Brochure) | IAPD (adviserinfo.sec.gov) | PDF | Revenue sharing disclosures, 12b-1 conflicts (Item 5.E), advisory fee structure, disciplinary history | **Planned** — sec-api.io free tier (100 calls/month) or direct IAPD download |
| **Form CRS** (Client Relationship Summary) | FINRA BrokerCheck + IAPD | PDF / HTML | Distribution conflicts, pay-for-shelf-space, fee comparison across service types | **Planned** |
| **BrokerCheck Data** (FINRA Query API) | FINRA Developer Center | JSON (API) | Dual registration flags, disclosure events, disciplinary actions, customer complaints, employment history, firm data | **Planned** — Free tier: 10 GB/month, 1,200 req/min |

## Tier 3 — Fee Tracking & Governance

| Filing | Source | Format | Data Extracted | Status |
|--------|--------|--------|---------------|--------|
| **485A/B/C** (Post-Effective Amendments) | EDGAR | HTML | Fee changes between annual reports, expense ratio adjustments, policy amendments | **Planned** — Time-series fee change tracker |
| **N-PX** (Proxy Voting Records) | EDGAR | HTML / XML | Vote records on every shareholder proposal at every held company | **Planned** — Governance layer, ESG claim verification |
| **Form N-14** (Merger/Reorganization) | EDGAR | HTML | Side-by-side fee comparisons for merging funds, projected expense changes | **Planned** — Special situations |

## Tier 4 — Specialized Extensions

| Filing | Source | Format | Data Extracted | Status |
|--------|--------|--------|---------------|--------|
| **Form N-2** | EDGAR | HTML / XBRL | Closed-end fund fee structures, distribution costs (often 0.50-1.25%) | **Future** |
| **Form N-MFP** | EDGAR | XML | Money market fund holdings, repo rates, weighted avg maturity | **Future** |
| **Forms N-3, N-4, N-6** | EDGAR | HTML | Variable annuity/life insurance separate account costs, M&E charges | **Future** |
| **Form N-RN** | EDGAR (non-public) | — | Derivative risk / VaR threshold breaches | **Not accessible** |
| **Form N-LIQUID** | EDGAR (confidential) | — | Liquidity stress notifications (illiquid > 15% NAV) | **Not accessible** |

## API Access Summary

| Data Source | Endpoint | Auth | Free Tier | Rate Limits |
|-------------|----------|------|-----------|-------------|
| **SEC EDGAR** | data.sec.gov + efts.sec.gov | None (User-Agent required) | Unlimited | 10 req/sec |
| **FINRA Query API** | developer.finra.org | API key (free registration) | 10 GB/month | 1,200 sync/min, 20 async/min |
| **SEC IAPD** | adviserinfo.sec.gov | None | Unlimited | Standard crawl etiquette |
| **sec-api.io** (Form ADV) | sec-api.io | API key | 100 calls/month | Per tier |

## Parser Architecture

All parsers follow the same pattern established by the 497K fee table parser:

1. **Resolve** — Map ticker to entity identifiers (CIK, series ID, class ID, CRD number)
2. **Retrieve** — Pull the relevant filing from EDGAR/IAPD/FINRA
3. **Parse** — Extract structured data from HTML/XML/PDF using filing-specific logic
4. **Normalize** — Map extracted fields to a common schema regardless of fund family formatting
5. **Tag** — Label every data point with source filing, confidence level, and extraction method

The key challenge is format variation across fund families. The SAI, N-CSR, and Form ADV parsers will require fuzzy section header matching and multiple fallback extraction strategies, similar to the 497K parser's handling of Dodge & Cox, Oakmark, and Fidelity table variants.

## Academic References Supporting This Architecture

- Edelen, Evans, & Kadlec (2013) — Trading costs (1.44% avg) exceed expense ratios (1.21% avg)
- deHaan, Song, Xie, & Zhu (2021) — High-fee funds deliberately obfuscate disclosures
- Hong & Mao (2024) — ~1/3 of management fees flow to distributors as hidden client maintenance fees
- Erzurumlu & Kotomin (2016) — Soft dollar arrangements: no consistent performance benefit
- GAO (2000) — "Greater Transparency Needed in Disclosures to Investors"
