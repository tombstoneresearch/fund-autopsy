# Fund Autopsy Cost Estimation Methodology

## Framework: Expense Ratio Plus Estimated Trading Costs

Fund Autopsy is built around a two-layer view of fund cost. The first layer is the expense ratio — management fee, 12b-1, administrative costs — which every fund screener already reports. The second layer is the trading costs the fund incurs when it buys and sells securities. These costs reduce the portfolio's value at the moment of execution and are therefore embedded in the NAV before any return is reported. The academic literature calls them *implementation shortfall* (Perold 1988) or *implicit trading costs* (Edelen, Evans, and Kadlec 2013); the CFA Institute curriculum categorizes the same phenomena as "implicit costs."

When a fund executes a trade, the portfolio pays brokerage commissions, crosses a bid-ask spread, and potentially moves the market against itself. These costs are not deducted from the fund's returns as a separate line item — they reduce the value of the portfolio at the moment of execution, so by the time the fund calculates its daily NAV they are already embedded in the number.

The standard return decomposition:

    Hypothetical gross return (what securities earned in a frictionless market)
    minus implicit trading costs (commissions, spreads, market impact, soft dollar effects)
    = Reported gross return (what the fund reports before fees)
    minus expense ratio (management fee, 12b-1, admin)
    = Net return to the investor

The academic literature has described these dynamics extensively. Edelen, Evans, and Kadlec (2013), in "Shedding Light on 'Invisible' Costs," estimated average annual trading costs of 144 basis points against an average expense ratio of 121 bps across their sample of 1995-2006 US equity funds. More recent estimates — Frazzini, Israel, and Moskowitz (2018), "Trading Costs," using 2003-2015 institutional execution data — show that costs have compressed materially, particularly in US large-cap equity, as spreads have tightened post-decimalization.

Fund Autopsy's contribution is not a new concept or a new label. It is a pipeline that reads structured SEC filings (N-CEN, N-PORT, 497K, 485BPOS, SAI, N-CSR) and presents the reported figures alongside estimated trading-cost layers on a per-fund basis, with every number tagged by its source filing. The underlying ideas belong to Perold, Edelen, Kadlec, and the broader market-microstructure literature; Fund Autopsy applies them to the retail mutual fund context using public regulatory data.

### Applicability Across Fund Types

Implicit trading costs apply to every pooled investment vehicle that trades securities. The mechanism is universal; only the magnitude and composition vary:

**Equity funds** experience sub-NAV drag through exchange-traded spreads, brokerage commissions, and market impact. These are the most well-studied costs and the initial focus of Fund Autopsy's estimation engine.

**Bond funds** face structurally worse conditions. Fixed income markets are over-the-counter, meaning there is no visible bid-ask spread on an exchange. Dealer markups are embedded directly in execution prices. There is no consolidated tape providing price transparency. Bond funds also incur roll costs as holdings mature and must be replaced, and odd-lot penalties when position sizes fall below institutional thresholds. The OTC structure means sub-NAV drag in bond funds is both larger and harder to observe than in equity funds.

**International and emerging market funds** add foreign exchange transaction costs and, in many jurisdictions, stamp duties or financial transaction taxes that are charged at the point of execution and absorbed into the portfolio.

**Small-cap funds** experience disproportionate sub-NAV drag because their holdings trade with wider spreads and thinner order books, amplifying market impact from the fund's own orders.

**Target-date and fund-of-funds vehicles** layer sub-NAV drag at two levels: the wrapper fund's own trading costs plus the inherited drag from each underlying fund.

**Commodity funds** face a distinct form of sub-NAV drag through futures roll costs, where the fund must regularly sell expiring contracts and buy longer-dated replacements at different prices.

Fund Autopsy currently estimates sub-NAV drag for equity and balanced funds using the methodology described below. Bond-specific and international cost models are planned expansions.

### Data Architecture

Fund Autopsy constructs its cost picture from three SEC filings, each providing a distinct layer:

| Filing | What It Provides | Sub-NAV Drag Components |
|--------|-----------------|------------------------|
| **N-CEN** | Brokerage commissions, soft dollar arrangements, securities lending, service providers | Reported trading costs, soft dollar magnitude, affiliated broker usage |
| **N-PORT** | Complete portfolio holdings, asset class breakdown, net assets | Asset mix for spread estimation, fund size for impact modeling |
| **497K** | Expense ratio, management fee, 12b-1 fee, turnover rate | Reported cost baseline, turnover rate for estimating trading frequency |

No single filing contains the full picture. Fund Autopsy is, to our knowledge, the first tool to systematically combine all three into a unified total cost of ownership.

### Expanded Filing Architecture (Planned)

Fund Autopsy's roadmap extends well beyond these three core filings. The following additional data sources will be integrated to build a comprehensive regulatory transparency engine:

| Filing | What It Provides | Cost/Conflict Layer |
|--------|-----------------|---------------------|
| **SAI** (Statement of Additional Information) | Broker-specific commission breakdowns (named brokers, dollar amounts, 3-year history), portfolio manager compensation structures, revenue sharing arrangements, commission recapture programs, detailed soft dollar disclosures | Conflict detection, incentive alignment scoring, distribution cost exposure |
| **N-CSR** (Annual/Semi-Annual Shareholder Reports) | Realized brokerage commissions with multi-year dollar amounts, portfolio turnover rates, expense ratios by share class, board basis for approving advisory contracts | Historical cost validation, turnover trend analysis, governance quality signals |
| **Form CRS** (Client Relationship Summary) | Distribution conflicts, revenue sharing between fund companies and broker-dealer platforms, pay-for-shelf-space arrangements | Distribution conflict flagging, recommendation integrity scoring |
| **485A/B/C** (Post-Effective Amendments) | Fee changes between annual reporting periods, expense ratio adjustments, policy amendments | Fee change tracking, silent fee increase detection |
| **Form N-PX** (Proxy Voting Records) | How the fund voted on every shareholder proposal at every company it owns | Governance alignment, ESG claim verification |
| **Form ADV** (Investment Adviser Disclosure) | Adviser conflicts of interest, fee arrangements, disciplinary history | Adviser-level conflict mapping (IAPD database, separate from EDGAR) |
| **Form N-14** (Fund Merger/Reorganization) | Side-by-side fee comparisons for merging funds, projected expense changes | Merger cost impact analysis |

SAIs are filed as Part B of the N-1A registration statement in HTML format. Section headers vary across fund families, requiring fuzzy matching similar to Fund Autopsy's existing 497K parser. The key extraction targets are brokerage commission tables, portfolio manager compensation descriptions, and revenue sharing arrangement disclosures.

N-CSR filings are available in HTML format on EDGAR and contain structured financial data increasingly tagged with Inline XBRL. The primary extraction targets are the brokerage commission schedule and the board's discussion of advisory contract approval.

Form CRS and Form ADV are filed through the IAPD (Investment Adviser Public Disclosure) system, a separate database from EDGAR maintained by the SEC and FINRA. Programmatic access requires a different data pipeline.

The goal is to parse every filing a fund is required to submit and surface the costs, conflicts, and structural incentives that are technically disclosed but practically invisible. Academic research supports this approach: deHaan, Song, Xie, and Zhu (2021) found that high-fee funds deliberately increase narrative and structural complexity in their filings to obfuscate costs. Fund Autopsy's role is to reverse that obfuscation.

---

## Cost Categories

Fund Autopsy computes two categories of costs: **reported costs** derived directly from SEC filings, and **estimated costs** derived using assumptions and academic methodologies. Every data point carries a transparency tag indicating its source and confidence level.

## Reported Costs

### Expense Ratio
Source: Fund prospectus or N-CSR filing. Tag: `REPORTED`.

The net expense ratio as disclosed in the fund's fee table. This is the number every existing tool reports.

### Brokerage Commissions
Source: SEC Form N-CEN, Item C.6.a. Tag: `REPORTED` or `CALCULATED`.

Total brokerage commissions paid during the reporting period, divided by total net assets (Item B.1), expressed in basis points. This cost is incurred by the fund on behalf of shareholders but is not included in the expense ratio.

### Soft Dollar Commissions
Source: SEC Form N-CEN, Items C.6.b and C.6.c. Tag: `REPORTED`, `ESTIMATED`, or `NOT_DISCLOSED`.

The portion of brokerage commissions directed to brokers who provide research services (soft dollar arrangements). When reported, this is a direct measure of how much of the fund's trading costs subsidize research that the advisor would otherwise pay for out of its own management fee.

When N-CEN Item C.6.b is not reported despite C.6 being marked "yes," Fund Autopsy applies the industry average soft dollar share of 45% (Erzurumlu & Kotomin, 2016) as a fallback estimate.

## Estimated Costs

### Bid-Ask Spread Cost
Tag: `ESTIMATED`. Confidence: Moderate.

The bid-ask spread is the difference between buy and sell prices for a security. Every trade the fund executes incurs this cost, but it is not reported anywhere in fund disclosures.

**Methodology:**
1. Classify the fund's holdings by asset class using N-PORT `assetCat` field.
2. Apply asset-class-specific average one-way spread assumptions (see table below).
3. Compute weighted average one-way spread based on asset class mix.
4. Apply formula: `Spread_Cost = Turnover_Rate × 2 × Weighted_Avg_One_Way_Spread`

The factor of 2 accounts for both sides of each trade: selling the old position and buying the replacement.

**Spread Assumptions (one-way):**

| Asset Class | Low | High |
|-------------|-----|------|
| US Large Cap Equity | 0.05% | 0.10% |
| US Mid Cap Equity | 0.10% | 0.20% |
| US Small Cap Equity | 0.20% | 0.40% |
| International Developed | 0.10% | 0.25% |
| Emerging Markets | 0.25% | 0.50% |
| Investment Grade Bonds | 0.02% | 0.10% |
| High Yield Bonds | 0.10% | 0.25% |
| Government Bonds | 0.01% | 0.05% |

### Market-Impact Cost
Tag: `ESTIMATED`. Confidence: Low.

Market impact is the adverse price movement caused by a fund's own trading activity. This is the least precise estimate in Fund Autopsy.

**Methodology:**
Simplified proxy based on Edelen, Evans, and Kadlec (2007):
1. Classify fund by size category (large-cap vs. small-cap) using N-PORT holdings.
2. Classify turnover as low (<50%) or high (>50%).
3. Apply impact factor to turnover rate.

**Impact Factors (% of turnover):**

| Category | Low | High |
|----------|-----|------|
| Large-cap, low turnover | 0.10% | 0.20% |
| Large-cap, high turnover | 0.20% | 0.50% |
| Small-cap, low turnover | 0.30% | 0.60% |
| Small-cap, high turnover | 0.50% | 1.50% |

## Fund-of-Funds Roll-Up

For fund-of-funds structures, each cost metric is weighted by the underlying fund's allocation:

```
Wrapper_Total_Cost = Wrapper_Direct_Cost + Σ(Fund_Cost[i] × Allocation_Weight[i])
```

Where `Allocation_Weight[i] = Market_Value[i] / Total_Net_Assets_of_Wrapper`.

## References

- Edelen, R.B., Evans, R.B., & Kadlec, G.B. (2013). "Shedding Light on 'Invisible' Costs: Trading Costs and Mutual Fund Performance." *Financial Analysts Journal*, 69(1), 33-44.
- Edelen, R.B., Evans, R.B., & Kadlec, G.B. (2007). "Scale Effects in Mutual Fund Performance: The Role of Trading Costs." Working paper.
- Chalmers, J., Edelen, R.M., & Kadlec, G.B. (2001). "An Analysis of Mutual Fund Trading Costs." Working paper, University of Oregon.
- deHaan, E., Song, Y., Xie, C., & Zhu, C. (2021). "Obfuscation in Mutual Funds." *Journal of Accounting and Economics*, 72(2-3).
- Hong, C. & Mao, M. (2024). "Hidden Costs within Management Fees: The Role of Client Maintenance Fees in Mutual Funds." SSRN Working Paper.
- Erzurumlu, Y.O. & Kotomin, V. (2016). "Mutual Funds' Soft Dollar Arrangements: Determinants, Impact on Shareholder Wealth, and Relation to Governance."
- Haslem, J.A. (2011). "Issues in Mutual Fund Soft-Dollar Trades." *Journal of Index Investing*.
- SEC (1998). "Inspection Report on the Soft Dollar Practices of Broker-Dealers, Investment Advisers and Mutual Funds."
- SEC (2003). "Request for Comments on Measures to Improve Disclosure of Mutual Fund Transaction Costs."
- GAO (2000). "Mutual Funds: Greater Transparency Needed in Disclosures to Investors."
- CFA Institute (2026). "Trading Costs and Electronic Markets." *CFA Program Curriculum*.
