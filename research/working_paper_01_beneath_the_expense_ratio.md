# Beneath the Expense Ratio
### Ten Disclosure Dimensions in SEC Form N-CEN That Industry Cost Analysis Systematically Omits

**Tombstone Research Working Paper No. 1**
**E. J. Baldwin**
**April 2026**

---

## Abstract

The expense ratio is the dominant metric by which retail investors, advisors, and most academic researchers compare open-end mutual funds, and it is a misleading one. The expense ratio discloses management and 12b-1 fees. It does not disclose the economic effects of soft-dollar commission arrangements, affiliated broker-dealer routing, principal transactions with adviser-related parties, securities-lending revenue splits, credit-facility utilization, derivatives complexity, service-provider concentration, governance composition, proxy-voting delegation, or the relationship between portfolio turnover and capital-gains distribution behavior. Each of those dimensions is reported annually, in structured form, on SEC Form N-CEN. Each materially affects fund outcomes. None of them is systematically aggregated by the three constituencies that ought to be aggregating them: industry research providers, academic finance, and retail-facing comparison tools. This paper argues that the N-CEN is the most underutilized mutual fund disclosure currently in existence, identifies ten specific dimensions where its data exposes hidden economic substance, proposes a letter-grade scorecard that operationalizes total cost of ownership at the fund level, and explains the structural reasons that the disclosure gap has persisted for nearly a decade after N-CEN replaced N-SAR in 2018. The paper also identifies specific limitations of the methodology and surfaces a research agenda for work that the N-CEN makes newly tractable.

**JEL codes (suggested):** G23, G28, G34
**Keywords:** mutual funds; N-CEN; total cost of ownership; soft dollars; securities lending; fund governance; affiliated brokers; regulatory disclosure

---

## 1. Introduction

The open-end mutual fund in the United States is among the most heavily regulated financial products ever created, and the public conversation about what a mutual fund costs is one of the most impoverished features of U.S. retail finance. The Investment Company Act of 1940, together with its subsequent amendments and the body of SEC rules adopted under it, requires investment companies to disclose financial statements, portfolio holdings, fee structures, board composition, and a substantial set of operational and related-party details. The public filings through which these disclosures reach the market include the statutory prospectus, the statement of additional information (SAI), the N-1A registration form, the semi-annual and annual shareholder reports (N-CSR), the monthly and quarterly holdings filings (N-MFP, N-PORT), the proxy-voting record (N-PX), and the annual census of registered investment companies (N-CEN).

Despite this volume of disclosure, the public conversation about fund cost has narrowed almost to the single number printed in the fee table of the summary prospectus. The expense ratio captures management fees, 12b-1 distribution fees, and a handful of other operating items. It does not capture transaction costs, and it does not capture the economic effects of a broad set of related-party and operational arrangements that are disclosed elsewhere. For sophisticated institutional investors, the transaction-cost literature starting with Perold (1988) and refined in work by Edelen, Evans, and Kadlec (2007, 2013) and by Frazzini, Israel, and Moskowitz (2018) has been well-known for a generation. For retail investors, for the journalists who cover them, and for the substantial portion of academic finance that uses the expense ratio as the sole cost variable in regression, this literature might as well not exist.

The narrower problem of transaction costs merits its own treatment, and this paper takes a broader lens. The SEC's Form N-CEN, introduced in 2018 as the successor to the text-based N-SAR, contains structured annual disclosures covering soft-dollar commission arrangements, affiliated broker-dealer usage, principal transactions, securities-lending economics, credit-facility utilization, derivatives programs, service-provider identities, and board governance composition. Each of these disclosures is filed as XML, and each is available on EDGAR without subscription or authentication. Each is machine-readable. None of them is systematically aggregated in any retail-facing product.

Section 2 of this paper restates the gap between expense ratio and total cost of ownership that this exercise is designed to close. Section 3 documents what Form N-CEN is, what it contains, and why structural features of the form have caused it to be underutilized. Section 4 identifies ten distinct disclosure dimensions within N-CEN that deserve independent aggregation, with each dimension treated in its own sub-section covering the mechanism, the reporting field, the signal the data produces, and what the dimension tells a sophisticated observer that the expense ratio does not. Section 5 proposes a letter-grade scorecard that operationalizes these ten dimensions into a single fund-level assessment, with explicit weights and explicit limitations. Section 6 addresses the question of why industry research, academic finance, and retail platforms have not built this already. Section 7 notes the limitations of the methodology. Section 8 sketches a research agenda. The appendices index the specific N-CEN items referenced throughout and describe the data-access pipeline Fund Autopsy uses to produce these figures.

This paper does not argue that the fund industry is fraudulent, that regulators have been captured, or that the disclosures currently required are inadequate. The disclosures are adequate. It is the aggregation of those disclosures into cost-relevant and governance-relevant metrics that has been missing. The purpose of Tombstone Research and the open-source Fund Autopsy project is to supply that aggregation and to make its methodology auditable.

---

## 2. The Expense Ratio as a Ceiling, Not a Floor

The argument that the expense ratio is an incomplete measure of mutual fund cost has been made repeatedly over the past twenty-five years, most notably by Bogle (1999) in book-length form and by Swensen (2005) for an institutional readership. The commercial research providers, Morningstar and Lipper, license data products that report an expense ratio alongside transaction-cost proxies, though those transaction-cost figures are rarely surfaced in the retail-facing comparison tools built on the same underlying data. The FINRA Fund Analyzer reports an expense ratio and an over-holding-period total-cost computation but does not incorporate transaction costs at all, and the SEC's own Mutual Fund Cost Calculator models only disclosed expenses. The result is that the comparison tools a retail investor is most likely to use report a number that understates total economic cost, and that the data required to correct the understatement is known to exist but is not placed in front of the investor.

When retail investors compare the Vanguard Total Stock Market Index Fund Admiral Shares (VTSAX) against a typical actively managed equity fund, the expense ratio gap appears as 80 to 120 basis points. That gap is real, and in compound terms it is enormous. It is also, for most pairs of funds, only part of the full cost differential. Edelen, Evans, and Kadlec (2013) estimated that trading costs for actively managed equity funds averaged 144 basis points annually, a figure in the same order of magnitude as the average expense ratio. Frazzini, Israel, and Moskowitz (2018), working with live AQR trading data, estimated lower figures than the literature's academic-sample averages, though those lower figures are conditional on institutional-quality execution that not every fund receives. The more conservative reading of the literature, and the reading this paper adopts, is that transaction costs of the same rough order of magnitude as the expense ratio apply across the active-management universe, with meaningful dispersion within it.

When one fund carries a 1.00% expense ratio and a 1.40% estimated transaction cost, and another carries a 0.40% expense ratio and a 0.60% estimated transaction cost, the disclosed-cost gap of 60 basis points understates the true-cost gap of 140 basis points by more than half. That understatement is conservative. In funds where securities-lending revenue is kept disproportionately by an affiliated agent, where brokerage is routed heavily to affiliated dealers, where principal transactions are used to move inventory from an affiliated bank into the fund, where a credit facility is drawn to manage redemptions in a stressed quarter, or where service-provider fees are negotiated below arm's length because of business-relationship capture, the effective cost is further degraded in ways the expense ratio will never reveal.

This paper does not argue that those degradations are pervasive. For most funds, most of the time, they are not. The argument is that the data required to identify the funds where they are pervasive is already being filed under SEC rule. The aggregation is what is missing.

---

## 3. What Form N-CEN Is, and Why It Has Been Ignored

Form N-CEN is the annual census form that every registered investment company is required to file under Rule 30a-1 of the Investment Company Act. It replaced Form N-SAR effective for fiscal years ending on or after June 1, 2018. Where N-SAR was a mixed text-and-tabular report filed semi-annually, N-CEN is structured XML filed annually, and its design is intended for machine ingestion. The form is organized into sections that cover general registrant information, the funds the registrant operates, service providers, securities-lending arrangements, derivatives use, lines of credit, affiliated-broker activity, principal transactions, governance, and a closing section for exhibits.

Several structural features of the N-CEN explain why it has remained underutilized relative to its informational content. It is worth addressing each in turn, because the explanation is not mysterious, but it is structural, and the structural character of the problem is what makes an independent aggregation project both necessary and sustainable.

The first feature is that the filing window is seventy-five days after fiscal-year end. A fund whose fiscal year ends December 31 files its N-CEN by mid-March of the following year, which means the most recent N-CEN data is always at least three months old, and for funds with non-calendar fiscal years the vintage varies further. For journalism focused on this quarter's market moves, and for traders looking for short-horizon signals, a three-to-fifteen-month stale data source has limited appeal. For multi-year trend analysis and for structural risk assessment, the staleness is immaterial, because the relationships this paper is interested in move on the order of quarters and years, not days.

The second feature is that the form is not narrative. It is a schema-bound XML document with codified enumerations, dollar amounts, and Yes/No toggles. Reading a single fund's N-CEN in raw form is uninformative; the data becomes informative only when rendered against a population. This raises the table stakes for any aggregator, because a meaningful output requires parsing the full industry rather than a sample, and the fixed cost of building that pipeline is not trivial while the marginal cost of each subsequent fund query is low. This is the economic shape of a public good, and public goods are reliably underprovided by commercial actors.

The third feature is that the data licensing of the large commercial research providers (Morningstar, Lipper, ISS) does not prioritize N-CEN fields. Their client base consists predominantly of fund sponsors, wealth-management platforms, and retirement plan sponsors, none of which has a commercial interest in highlighting affiliated-broker concentration ratios or soft-dollar intensity. The data these providers surface, and the scorecards they publish, reflect the demands of their paying customers. When the customer is the institution being assessed, the scorecard tends not to surface embarrassments.

The fourth feature is that academic finance typically does not work with industry-wide N-CEN aggregation, for a mix of reasons that include data-access friction, the sample-driven conventions of the field, and citation incentives that reward novel tests of existing theories over descriptive work on new regulatory data. When fund-governance researchers such as Khorana, Servaes, and Wedge (2007) or Ferris and Yan (2009) have done board-composition and fee analysis, it has typically been at the fund-family level rather than the full census level, and using older N-SAR data or hand-collected samples. The N-CEN makes a full-census approach newly feasible, but the academic citation machinery has not yet shifted its attention in that direction.

The fifth feature is that retail platforms surface the data their users search on. The Vanguard, Fidelity, and Schwab screeners, the fund-comparison tools inside 401(k) plan interfaces, and the brokerage platforms' mutual fund profile pages all accommodate user search patterns that focus on expense ratio, Morningstar rating, and past performance. The platforms have no commercial reason to add fields that users are not asking about. There has been no market demand for a data field that says this fund routes 42% of its commissions to its own affiliated broker-dealer, because retail investors do not know to ask.

The combined result is a regulatory disclosure that is comprehensive, structured, and publicly available, and that virtually nobody outside a handful of academic specialists and regulatory staff has read at scale. The Tombstone Research argument, in its simplest form, is that the N-CEN deserves to be read.

---

## 4. Ten Disclosure Dimensions That Deserve Independent Aggregation

This section presents ten distinct dimensions of fund economics that the N-CEN makes tractable, either on its own or in cross-reference with N-PORT, N-PX, and N-MFP, and that this paper argues deserve their own aggregation and scoring. The dimensions are presented in approximate order of the cost magnitude they imply, with the first several most likely to produce material expense-ratio-equivalent degradations and the later ones more oriented toward governance and systemic risk. For each dimension, the treatment below identifies the relevant N-CEN item or items, explains the economic mechanism, notes the signal the data produces, and indicates what the Fund Autopsy project aggregates in the dimension's scoring.

### 4.1 Soft-Dollar Commission Arrangements

*N-CEN Item references: commissions to brokers providing research services; Item C on brokerage and related commissions.*

The economic mechanism is straightforward, and that straightforwardness is part of the reason the arrangement has persisted largely unchallenged in retail-facing analysis. The fund pays a brokerage commission to execute a trade, the commission is higher than the rate the broker would charge for execution alone, and the broker returns the incremental portion as research credits that the adviser uses to purchase research products and services. Under Section 28(e) of the Securities Exchange Act of 1934, this arrangement is protected by a safe harbor, provided the research is reasonably and in good faith determined to be helpful to the adviser's decision-making.

The substantive issue is that the adviser consumes the research, not the fund, while the fund pays for it through elevated commissions. The adviser would otherwise pay for the same research out of its management fee. The soft-dollar arrangement therefore shifts cost from the adviser's income statement to the fund's trading book, where it is disclosed as a commission rather than as a fee, and where it does not appear in the expense ratio. That is the mechanism by which a cost that is economically an adviser expense becomes an invisible cost to the fund shareholder.

The N-CEN requires that funds report both total commissions and the portion of commissions paid to brokers providing research services. The ratio of these two figures is a soft-dollar intensity measure, and scaled against net assets it produces a soft-dollar basis-point drag that is directly comparable across funds. Funds whose soft-dollar commissions exceed the peer-category median by more than one standard deviation are flagged as outliers. This is not an allegation of misconduct; the arrangement is legal, and it is used responsibly by a substantial portion of the industry. It is a disclosure that should be visible in the total cost of ownership view a fund investor sees, and currently is not.

### 4.2 Affiliated Broker-Dealer Routing

*N-CEN Item references: Item C on brokerage, with specific fields for commissions paid to affiliated brokers.*

Fund advisers frequently operate within larger financial-services holding companies that also operate broker-dealers. Rule 17e-1 under the 1940 Act permits the adviser to route fund trades through the affiliated broker-dealer, subject to best-execution obligations and board oversight. The N-CEN requires disclosure of commissions paid to affiliated brokers, by broker name and by amount.

The economic question is not whether the structure is legal, because it plainly is, and has been for decades. The economic question is whether best execution is being delivered, and at what rate, and this is ordinarily unknowable from outside the fund. The commissions paid and the execution quality are matters the adviser's board is supposed to police. What the N-CEN does make visible is the concentration of routing, and that is a separate question that stands on its own. A fund family whose affiliated-broker share of total commissions is 5% is structurally different from a fund family whose affiliated share is 45%. The former has a de facto policy of preferring independent brokers; the latter has a de facto policy of channeling fund commission flow into the parent company's revenue statement.

The Tombstone scorecard aggregates affiliated-broker commission share at both the fund level and the complex level, ranks against peers, and flags outliers above the ninetieth percentile. Flagging is not allegation. It is visibility. The investor decision of whether to care about a 45% affiliated-broker share is not being made on the current platforms because the figure is not being displayed.

### 4.3 Principal Transactions with Affiliates

*N-CEN Item references: Item C on principal transactions; reporting of counterparty affiliation and dollar volumes.*

A principal transaction occurs when the fund trades a security directly with a counterparty acting in its own account, rather than as a broker on someone else's account. The economic significance of a principal transaction with an affiliate arises from Section 17(a) of the Investment Company Act, which generally prohibits such trades except under specified exemptive conditions. Rule 17a-7 permits cross-trades between affiliated funds managed by the same adviser, subject to strict pricing conditions that require independent pricing and no commissions. Rule 17a-10 permits related-party securities lending. Other exemptive orders cover specific affiliated-counterparty scenarios.

The risk being priced here is inventory-dumping risk. An affiliated broker-dealer's trading desk holds an inventory position that is proving difficult to unwind, and a principal transaction sells the position to an affiliated fund at a price that is difficult for the fund's shareholders to verify. The 17a-7 pricing conditions exist precisely to prevent this outcome. Compliance with 17a-7 is the adviser's responsibility, and the N-CEN disclosure of principal transaction volume and counterparty affiliation is what makes the question auditable after the fact.

The Tombstone scorecard aggregates principal transaction dollar volume scaled to fund net assets, flags counterparty concentration with affiliates, and notes the presence of principal transactions in funds whose mandates (for example, passive index) make such activity unusual.

### 4.4 Securities-Lending Revenue Splits

*N-CEN Item references: Section on securities lending, gross income, agent fees, net income, lending agent identity, affiliation flag, collateral type, average value on loan.*

A fund that engages in securities lending earns fees from short sellers who borrow securities from the fund's portfolio. The fund's net revenue from the program equals gross revenue less the share retained by the lending agent, less the costs of collateral management. The ratio of net revenue to gross revenue varies substantially across funds and across lending agents. Reported splits range from roughly 50% retained by the fund to roughly 90% retained by the fund, with the most common industry term sheet being an 80/20 split in the fund's favor.

The economic significance of the split is that securities lending is a non-trivial revenue source for passive index funds with high-demand constituent securities, and the split translates directly to basis points of return. A fund whose lending program produces 15 basis points of gross revenue and retains 50% of it generates 7.5 basis points of net return for its shareholders; a fund with the same gross revenue that retains 85% generates 12.75 basis points. The 5.25-basis-point difference is half again the stated expense ratio of the cheapest index funds in the market, and it is invisible to anyone using expense ratio as the sole comparison metric.

The governance twist is the affiliation flag. When the lending agent is affiliated with the fund's custodian or with the adviser, the arm's-length negotiation pressure on the split is weaker, and the agent has a structural incentive to maximize lending volume, which is its fee base, rather than to optimize risk-adjusted return to the fund, which is its fiduciary responsibility. Empirical work in this area by Blocher, Reed, and Van Wesep (2013) and others is consistent with this incentive pattern, though the work has not been extended to the full N-CEN universe.

The Tombstone scorecard computes gross lending revenue as a share of average value on loan, the split retained by the fund, the split retained by the agent, and the net-to-gross ratio, and flags affiliated-agent arrangements.

### 4.5 Credit-Facility Utilization and Liquidity Stress

*N-CEN Item references: Item on whether the fund has a line of credit, facility size, shared-facility flag, lending institutions, and maximum amount outstanding during the period.*

Open-end mutual funds offer daily redemption, and when redemption requests arrive faster than portfolio liquidity can satisfy them without forced selling at unfavorable prices, the fund has two non-gating options: selling liquidity reserves, or drawing on a credit facility. Most fund complexes maintain committed credit facilities for precisely this contingency, often shared across the complex under a master agreement with a syndicate of banks.

The N-CEN disclosure of maximum amount outstanding during the period, scaled to facility size, is a direct measure of how hard the fund leaned on its facility during that year. A fund that never drew its facility reports zero maximum outstanding. A fund that drew heavily reports an amount that, when divided by facility size, produces a utilization ratio.

The cost of drawn facility balances is interest expense, and the cost does appear in the expense ratio in the "other expenses" line if it was incurred during the period. The signal value of utilization is not about cost, however. It is about liquidity-stress detection. A passive index fund that tapped its credit line at 40% of facility size during a particular year was experiencing redemption pressure, market-dislocation-forced selling, or both. That history is informative about future behavior in similar stress scenarios.

The shared-facility flag adds a systemic wrinkle. A fund family whose entire fund complex draws on the same facility exposes each fund in the complex to the aggregate redemption behavior of the others. One fund's crisis can reduce another fund's contingent liquidity, and the N-CEN makes the existence of this shared arrangement visible where the prospectus and shareholder report typically do not.

The Tombstone scorecard aggregates utilization as a percentage of facility size, flags high-utilization events, notes shared-facility arrangements, and cross-references against the corresponding N-PORT liquidity classifications.

### 4.6 Derivatives Program Complexity and Rule 18f-4 Compliance

*N-CEN Item references: Item on derivatives types used (futures, options, swaps, forwards), purposes of use; together with the fund's 18f-4-related disclosures and the VaR-based limitations framework.*

Rule 18f-4 under the 1940 Act, adopted in 2020 and effective in 2022, restructured the regulatory treatment of mutual-fund derivatives use. The rule replaced the asset-coverage framework that had constrained derivatives since the 1979 Dreyfus letter with a VaR-based limit framework, subject to derivatives risk management programs, board-approved risk limits, and structured reporting. Funds that exceed defined leverage thresholds must designate themselves as derivatives users and comply with additional requirements.

The N-CEN, in conjunction with the 18f-4 framework, provides disclosure of which derivatives types a fund uses and the stated purpose of their use. Cross-referenced against the fund's investment objective, prospectus-disclosed strategy, and category classification, the derivatives disclosure surfaces a specific signal: the gap between what the fund says it does and what its derivatives footprint suggests it actually does.

A conservative balanced fund with a fifty-fifty stock-bond mandate that reports interest-rate swaps, index futures, and variance swaps is running a more complex strategy than its marketing materials imply. That is not necessarily a problem, because sophisticated overlay strategies exist and are defensible, but it is a disclosure that a retail investor who accepted the conservative balanced label at face value should be able to see. The Tombstone scorecard computes a derivatives complexity index based on type diversity, and a mandate-derivatives mismatch index that flags disclosed derivatives activity inconsistent with the fund's objective classification.

### 4.7 Service-Provider Concentration and Systemic Infrastructure Risk

*N-CEN Item references: Items on administrator, custodian, transfer agent, pricing services, auditor identities; together with corresponding fields at the trust and fund levels.*

The U.S. fund industry operates on a small number of service-provider platforms. A handful of custodians, including BNY Mellon, State Street, Northern Trust, JPMorgan, and Citi, hold the substantial majority of industry AUM in custody. A similar concentration exists among fund administrators, transfer agents, and the largest audit firms for fund engagements. Much of this concentration is efficient, because large custodians have infrastructure that smaller custodians cannot replicate economically. The concentration has a systemic face, however, that does not typically get aggregated.

If the custodian for a third of mutual fund AUM has a significant operational incident, whether a data-center outage, a cyber intrusion, a ransomware event, or a regulatory sanction, the downstream effect on NAV calculation, shareholder record-keeping, and trade settlement is not priced into any fund's expense ratio. The regulatory framework requires the adviser to have operational-resilience plans, and the 2022 SEC proposed rule on service-provider due diligence would add further requirements, but the concentration signal itself does not appear in any public scorecard.

The Tombstone framework aggregates service-provider identity at the trust and fund level, computes concentration ratios by service type, and maps the largest dependency graphs.

### 4.8 Governance Composition and Board Interlocks

*N-CEN Item references: Item on directors/trustees, count, independence ratio, chair independence.*

The 1940 Act requires a majority of directors to be independent of the adviser, and for funds relying on newer exemptive orders the threshold rises to three-quarters. The economic literature on fund governance, including work by Tufano and Sevick (1997), Khorana, Servaes, and Wedge (2007), and Ferris and Yan (2009), has documented correlations between governance structure and fee levels, with more-independent boards associated with lower fees and with more-aggressive fee renegotiation. The finding is not universal, but it is robust across specifications.

The N-CEN provides board composition data at the registrant level that can be combined with director-level data from the corresponding SAI to produce governance indices. Director tenure, overlapping directorships across the complex, compensation levels relative to fund AUM, and chair independence are the main variables of interest.

The Tombstone scorecard computes a governance quality score that weights independence ratio, chair independence, and tenure distribution, and cross-tabulates the resulting score against fee levels and soft-dollar intensity.

### 4.9 Proxy-Voting Delegation and Stewardship

*N-CEN Item references: proxy-voting policy disclosures; cross-reference to Form N-PX on actual votes cast.*

A large fund holding a large stake in a publicly traded company controls a nontrivial block of votes in that company's corporate-governance elections. The 1940 Act requires the fund to vote its shares in the interest of its shareholders, and in practice the fund delegates voting to a proxy advisor, most commonly Institutional Shareholder Services or Glass Lewis, or to an in-house stewardship team, or to the adviser. The N-CEN surfaces the policy selection; the N-PX surfaces the actual votes cast.

For index funds, this delegation is the mechanism through which passive management exercises corporate-governance influence. Critics of what has been labeled the Big Three problem, referring to BlackRock, Vanguard, and State Street holding a plurality of votes in a substantial fraction of S&P 500 companies, have written at length about the structure. What has been less well-aggregated is the divergence between stated policy and actual voting behavior, and the question of when and how fund boards review the delegation.

The Tombstone scorecard flags funds that delegate voting fully, funds that retain in-house stewardship, and funds whose N-PX votes diverge materially from the adviser's public stewardship statements.

### 4.10 Turnover, Tax Drag, and Capital-Gains Distribution Behavior

*N-CEN and related-filing cross-reference: portfolio turnover rate; realized gains reporting; capital-gains distribution percent of NAV, via N-CEN and N-CSR.*

Portfolio turnover is a transaction-cost driver, and that relationship is well-established in the literature. The separate tax-efficiency channel is that realized gains are distributed to shareholders as capital gains, and in taxable accounts those distributions create tax liabilities that reduce after-tax return without affecting pre-tax return. For funds held in taxable accounts, a fund with 60% turnover distributing 12% of NAV as capital gains in a given year is producing materially worse after-tax outcomes than a fund with 8% turnover distributing 1% of NAV, even if pre-tax returns are identical.

Morningstar publishes a tax cost ratio that approximates after-tax return impact, and the public methodology is not a secret. The exposure of the ratio in retail-facing tools is uneven, and the cross-sectional visibility of funds that are dramatically worse than their peer category on this dimension is nearly zero.

The Tombstone scorecard aggregates N-CEN-reported turnover, computes a multi-year capital-gains distribution intensity as a percentage of average NAV, and produces a tax-efficiency score keyed to the fund's default shareholder account context, which for most categories is taxable, and for money-market and stable-value funds is tax-deferred.

---

## 5. A Letter-Grade Scorecard Methodology

The ten dimensions described above each produce a numeric measure, and the Fund Autopsy scorecard maps these measures into a letter-grade assessment on the A through F scale, with an explicit weighting and an explicit set of tie-breakers. The design goal is a single summary that is defensible, auditable, and resistant to reverse-engineering of the individual component scores.

The proposed weights reflect the current paper's judgment on relative economic magnitude, and they are not a claim about optimal weighting. The weights are published, they are versioned, and the underlying component scores are visible to any user of the tool.

| Dimension | Weight | Rationale |
|---|---:|---|
| Soft-dollar intensity | 15% | Direct commission-equivalent cost; comparable to expense ratio in magnitude for high-turnover funds. |
| Affiliated broker routing | 10% | Best-execution concern; structural conflict quantified. |
| Principal transactions with affiliates | 8% | Inventory-risk channel; Section 17(a) exposure. |
| Securities-lending revenue split | 10% | Direct return-equivalent; affiliated-agent conflict. |
| Credit-facility utilization | 5% | Liquidity-stress signal; higher weight in periods of market stress. |
| Derivatives complexity | 7% | Strategy-disclosure fidelity; 18f-4 risk framework. |
| Service-provider concentration | 3% | Systemic and operational-resilience factor. |
| Governance composition | 10% | Secondary through fee-negotiation channel; primary oversight proxy. |
| Proxy-voting delegation | 7% | Stewardship fidelity; applicable particularly to index funds. |
| Turnover and tax drag | 15% | Direct after-tax return channel for taxable accounts. |
| **Expense ratio (retained as anchor)** | **10%** | The disclosed cost retains a meaningful weight. It is not discarded; it is placed in context. |

The ten N-CEN-derived dimensions are weighted at 90% of the total, and the expense ratio is weighted at 10%. The design intent is to invert the current industry convention, in which the expense ratio is the only cost metric surfaced to retail investors and the ten dimensions above are invisible.

The letter grade is assigned from the weighted score as follows: A for the top 10%, B for the next 25%, C for the next 35%, D for the next 20%, and F for the bottom 10%. Grading is relative to peer category, such as equity large-cap blend, intermediate-term bond, or international developed, rather than to the full open-end fund universe. A passive index fund and a leveraged daily 3x fund are not usefully compared.

The scorecard surfaces, alongside the letter grade, each of the ten component scores, each underlying N-CEN data field, the specific filing from which the data was drawn, and the fiscal year of that filing. Every figure is traceable to the source SEC filing. The scorecard methodology is published as open source, and the weights are versioned so that historical weights remain accessible and prior grades can be reproduced.

---

## 6. Why This Has Not Been Done

The question of why a publicly available data source as rich as the N-CEN has not produced a widely used scorecard over the eight years since its introduction deserves a direct answer. The answer is structural, and it has four principal components.

The first component is that the commercial research providers whose clients are fund sponsors have a disincentive to surface data that embarrasses those sponsors. This is not a conspiracy; it is a commercial reality. Morningstar's Analyst Rating, the Lipper Leader system, and the major retirement-plan fiduciary scorecards are financed by data licensing arrangements in which fund sponsors and plan sponsors are the paying customers. Data fields that reduce the sponsor's standing do not serve the commercial relationship, and the providers accommodate.

The second component is that academic finance has institutional conventions that do not reward descriptive work on new regulatory data. The citation incentive rewards novel empirical tests of established theories, ideally using datasets peers already trust. Building a new data pipeline on N-CEN, validating it, and publishing the descriptive cross-section is high-fixed-cost work that produces limited citation return. The pattern has been shifting at the margin, because a small but growing literature does use N-CEN data, but the industry-level aggregation work this paper proposes is still underrepresented in the top journals.

The third component is that retail-facing comparison platforms surface what their users search on. Users search on past performance, Morningstar rating, and expense ratio, and the platforms provide. The feedback loop is closed, and breaking it requires an independent aggregator that does not depend on platform advertising or on sponsor data licensing.

The fourth component is that the technical work required to parse N-CEN at industry scale is nontrivial. The schema has been revised multiple times since 2018. The XML is well-formed but is not schema-validated on submission, and funds occasionally make reporting errors. A production-grade pipeline requires error detection, schema-change monitoring, and a quality-assurance layer. This is engineering work that does not have an obvious funding model outside a commercial data product, which returns the argument to the first two components.

The combination of these four factors is why, despite the N-CEN being fully public and fully machine-readable for eight years, no widely adopted industry-level aggregation has emerged. The Tombstone Research and Fund Autopsy project is an attempt to fill the gap by operating outside the commercial-licensing incentive structure and outside the academic-citation incentive structure.

---

## 7. Limitations

Several limitations deserve explicit acknowledgment, because a scorecard of the kind this paper proposes is useful only to the extent that its weaknesses are visible to the reader alongside its strengths.

The data is annual and filed with a lag. The N-CEN is not a real-time signal. For governance and structural-risk analysis the lag is immaterial, but for short-horizon signals the lag makes the N-CEN unsuitable, and a reader looking for a this-week trading signal should look elsewhere.

Cross-fund comparability is complicated by fiscal-year differences. A fund with a June fiscal year is reporting a different twelve-month period than a fund with a December fiscal year, and period-matched peer comparisons must account for the vintage difference explicitly. The Fund Autopsy methodology does account for it, though the result is that peer statistics are themselves computed on a rolling-twelve-month basis rather than on a clean calendar year.

Not every field is required in every case. Securities-lending disclosures, for example, apply only to funds that engage in securities lending, and credit-facility disclosures apply only where a facility exists. The scorecard treats non-applicability correctly by dropping the dimension from the weighting and renormalizing the remaining weights, though the resulting letter grade for a fund that does not engage in securities lending and does not have a credit facility is computed on a narrower basis than for a fund that does.

Data quality in any regulatory filing system is imperfect. The Fund Autopsy schema monitor, described in the companion methodology note, produces daily PASS/FAIL checks against known schema invariants. Cases of reporting error will occasionally distort individual fund scores, and when a fund's score moves materially period over period, the tool surfaces the underlying data change rather than presenting the score in isolation.

The scorecard is not a buy-sell-hold recommendation, and it should not be read as one. It does not incorporate expected return. It does not evaluate the adviser's skill. It measures cost and governance exposure against peer category. A fund with an A grade on this scorecard may still underperform, and a fund with a D grade may still outperform. The scorecard is a cost-and-governance lens, not a full investment-decision tool, and the materials that accompany the scorecard are written to make that distinction clear.

---

## 8. Research Agenda

The N-CEN as a data source enables a set of research questions that have been difficult to pursue at scale. A partial list is given here, and each item is the subject of ongoing work or a forthcoming paper in this series.

The first question is whether affiliated-broker routing share predicts future risk-adjusted return, controlling for expense ratio and other fund characteristics. Prior work by Ferris and Yan (2009) has found limited effects in older data, and the N-CEN permits a much larger and more recent sample.

The second question is how the securities-lending revenue split evolves with the identity of the lending agent, and whether the introduction of a new securities-lending agent produces a step change in the net revenue to the fund. A cross-sectional panel of N-CEN securities-lending data permits this question in a way that a small-sample study cannot.

The third question is whether credit-facility utilization at the fund or complex level predicts subsequent periods of underperformance or of NAV volatility. This is a liquidity-stress-transmission question of direct policy relevance, particularly in environments of rising rates or sudden redemptions.

The fourth question is how the post-2022 Rule 18f-4 framework has changed derivatives use in the funds that adopted the limited-derivatives-user classification versus those that adopted the full derivatives-risk-management regime. This is a regulatory-impact question that the N-CEN combined with the fund-specific 18f-4 disclosures makes newly tractable.

The fifth question is whether the governance structure of a fund complex, including independent chair, independence ratio, and interlocking directorships, predicts fee renegotiation outcomes during adviser contract renewal periods. Older work by Khorana, Servaes, and Tufano (2004) has answered this partially, and the N-CEN makes a comprehensive test feasible.

These and adjacent questions are the subject of forthcoming Tombstone Research working papers. Paper 2 in this series will address soft-dollar intensity in the post-MiFID II landscape, with particular attention to the asymmetric regulatory environment between U.S. and European fund execution. Paper 3 will cover securities-lending revenue splits across the industry. Paper 4 will address affiliated-broker routing trends since 2018. The Fund Autopsy open-source repository publishes data and code for each paper alongside the narrative.

---

## 9. Conclusion

The argument of this paper is not novel in its individual parts. The deficiencies of the expense ratio as a total-cost measure have been argued for fifty years. The conflicts of interest in affiliated-broker routing and securities-lending arrangements have been the subject of enforcement actions and academic papers for a generation. The Rule 18f-4 framework is current regulatory reality. The fund governance literature has been a continuous stream since Tufano and Sevick (1997).

What the N-CEN changes is the accessibility of the data required to operationalize any of these arguments at industry scale, with machine-readable structure, and in a format that a determined non-commercial researcher can aggregate without the data-licensing gatekeeping that has traditionally mediated industry-level fund research. The disclosure exists. The aggregation is the missing piece. Tombstone Research and the Fund Autopsy project have been built to supply that aggregation and to publish the methodology open source so that the work can be audited, challenged, and improved.

A fund investor today, armed with an expense ratio and a Morningstar star rating, is making a decision with roughly a tenth of the cost-and-governance information that the SEC has already required to be disclosed. The gap is closable. This paper is an attempt to describe its shape, and the companion repository is an attempt to close it.

---

## References

Blocher, J., Reed, A. V., and Van Wesep, E. D. (2013). Connecting two markets: An equilibrium framework for shorts, longs, and stock loans. *Journal of Financial Economics*, 108(2), 302–322.

Bogle, J. C. (1999). *Common Sense on Mutual Funds: New Imperatives for the Intelligent Investor*. John Wiley and Sons.

Edelen, R., Evans, R., and Kadlec, G. (2007). Scale effects in mutual fund performance: The role of trading costs. Working paper, University of Virginia.

Edelen, R., Evans, R., and Kadlec, G. (2013). Shedding light on "invisible" costs: Trading costs and mutual fund performance. *Financial Analysts Journal*, 69(1), 33–44.

Ferris, S. P., and Yan, X. (2009). Agency conflicts in delegated portfolio management: Evidence from namesake mutual funds. *Journal of Financial Research*, 32(2), 199–225.

Frazzini, A., Israel, R., and Moskowitz, T. J. (2018). Trading costs of asset pricing anomalies. Working paper, AQR Capital Management.

Khorana, A., Servaes, H., and Tufano, P. (2004). Mutual fund fees around the world. In *The Economic Consequences of the Investment Company Act of 1940* (conference volume).

Khorana, A., Servaes, H., and Wedge, L. (2007). Portfolio manager ownership and fund performance. *Journal of Financial Economics*, 85(1), 179–204.

Perold, A. F. (1988). The implementation shortfall: Paper versus reality. *Journal of Portfolio Management*, 14(3), 4–9.

Swensen, D. F. (2005). *Unconventional Success: A Fundamental Approach to Personal Investment*. Free Press.

Tufano, P., and Sevick, M. (1997). Board structure and fee-setting in the U.S. mutual fund industry. *Journal of Financial Economics*, 46(3), 321–355.

U.S. Securities and Exchange Commission (2016). Investment Company Reporting Modernization, Final Rule. Release Nos. 33-10231; IC-32314. (Adoption of Form N-CEN.)

U.S. Securities and Exchange Commission (2020). Use of Derivatives by Registered Investment Companies and Business Development Companies, Final Rule. Release No. IC-34084. (Adoption of Rule 18f-4.)

---

## Appendix A — Index of N-CEN Fields Referenced

The table below cross-references the ten disclosure dimensions discussed in Section 4 with the corresponding N-CEN reporting items. Item lettering follows the current N-CEN schema in effect as of 2026-04-22. Prior schema versions had different item lettering, and the Fund Autopsy parser handles the versioning.

| Dimension | Primary N-CEN field family | Cross-reference filings |
|---|---|---|
| Soft-dollar intensity | Brokerage commissions, research-services commissions | Form N-1A soft-dollar disclosure |
| Affiliated-broker routing | Brokerage commissions by broker, affiliation flag | SAI for relationship descriptions |
| Principal transactions | Principal transaction volumes and counterparty affiliation | Rule 17a-7 board-approval records |
| Securities lending | Gross income, agent fees, net income, collateral, agent affiliation | Custody agreements referenced in SAI |
| Credit-facility utilization | Facility size, maximum outstanding, shared-facility flag | N-PORT liquidity classifications |
| Derivatives program | Derivative types, purposes | 18f-4 derivatives-risk disclosures |
| Service-provider concentration | Administrator, custodian, transfer agent, pricing service identities | Trust-level cross-references |
| Governance | Board size, independence ratio, chair independence | SAI for director biographies and compensation |
| Proxy-voting delegation | Proxy-voting policy disclosures | Form N-PX for actual votes |
| Turnover and tax drag | Portfolio turnover rate | N-CSR for realized-gain distributions |

Current N-CEN schema documentation is maintained by the SEC and is available through EDGAR. The Fund Autopsy repository includes a parser test suite that validates extraction of each field against the current schema and reports schema drift when the SEC revises the form.

---

## Appendix B — Data Access

All N-CEN filings are available without authentication on EDGAR. Raw XML can be retrieved by CIK and accession number at predictable URL patterns. Bulk retrieval requires respecting the SEC's rate-limit guidance, which historically has been ten requests per second with an identifying User-Agent, though current SEC guidance is authoritative and should be consulted before building any production pipeline.

The Fund Autopsy repository at `github.com/tombstoneresearch/fund-autopsy` contains the following components. It includes an N-CEN parser that extracts the field families listed in Appendix A, a scoring module that implements the methodology of Section 5, a schema monitor that checks parser assumptions against current filings daily and reports breakage before it affects scorecard output, and a web interface at fund-autopsy.onrender.com that renders per-fund scorecards against the current data snapshot.

The repository is licensed permissively under MIT. Pull requests improving parser coverage, methodology, or documentation are welcomed. Issues flagging data anomalies or schema drift are especially welcomed.

---

## Acknowledgments

This working paper is the product of the Tombstone Research open-source project. The author acknowledges the public availability of the SEC EDGAR system as the foundational data infrastructure without which this line of work would not be possible. Errors and omissions are the author's alone.

---

*Tombstone Research is an independent research project focused on fund transparency. The project has no institutional affiliation, accepts no commercial sponsorship, and takes no advertising. The author writes under a pseudonym. All data and methodology are published under open-source licenses at github.com/tombstoneresearch.*

*This working paper is released under the Creative Commons Attribution 4.0 International License (CC-BY-4.0). The paper and the underlying Fund Autopsy software may be freely redistributed with attribution.*
