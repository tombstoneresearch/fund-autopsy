# Fund Autopsy Known Limitations

## Data Coverage

1. **N-CEN data starts in 2018.** No structured soft dollar data is available before that year without parsing legacy N-SAR filings, which use a different XML schema. Fund Autopsy currently targets N-CEN (2018-present) only.

2. **N-CEN is filed annually.** The most recent brokerage commission and soft dollar data may be up to 12 months old. Fund Autopsy displays the filing period prominently in all output.

3. **Soft dollar fields are inconsistently reported.** Some funds mark N-CEN Item C.6 as "yes" (indicating soft dollar arrangements exist) but leave Items C.6.b and C.6.c blank. Fund Autopsy flags this as `NOT_DISCLOSED` and offers an industry-average estimate as a fallback.

## Estimation Uncertainty

4. **Bid-ask spread costs are estimates, not measurements.** Fund Autopsy uses asset-class-specific assumptions applied to portfolio turnover. Actual spreads vary by security, order size, market conditions, and execution quality. All spread estimates are reported as ranges and tagged as `ESTIMATED`.

5. **Market-impact costs are the least precise component.** The Edelen, Evans, and Kadlec (2007) proxy framework provides directional estimates only. Actual market impact depends on order size relative to average daily volume, timing, and broker execution algorithms. Always treat these figures as rough indicators.

## Fund-of-Funds Detection

6. **CUSIP-to-CIK mapping has gaps.** If an underlying holding's CUSIP cannot be resolved to a registered investment company CIK via EDGAR, it will be treated as a direct security holding and excluded from recursive cost analysis. This may undercount costs for wrapper funds holding unregistered pooled vehicles or non-US funds.

## Costs Not Captured

7. **Revenue sharing arrangements** between fund companies and distribution platforms are not disclosed in any SEC filing and cannot be estimated.

8. **Payment for order flow (PFOF)** at the broker level is not reflected in fund-level filings.

9. **Administrative cost allocations** beyond what is captured in the expense ratio are not separately identifiable.

10. **Tax drag is excluded** from the current scope. Capital gains distributions and tax efficiency are important cost components but are already addressed by existing tools (Morningstar tax cost ratio, PersonalFund tax estimates). Fund Autopsy focuses on the gap those tools miss: transaction costs and soft dollars.

## Technical

11. **SEC rate limiting.** EDGAR enforces a 10 requests/second limit. Analysis of large fund-of-funds structures with many underlying holdings may take several seconds.

12. **Multi-layer nesting.** Recursive unwinding is capped at 3 levels. If a fund-of-funds holds another fund-of-funds that itself holds a third layer, costs below the cap are flagged but not resolved.
