"""Tax drag estimation for mutual funds.

Estimates the tax cost of fund ownership for taxable account holders using
after-tax return disclosures from 497K prospectus filings and turnover data.

Tax drag is the difference between pre-tax and after-tax returns, which
arises from:
  - Short-term capital gains distributions (taxed at ordinary income rates)
  - Long-term capital gains distributions (taxed at preferential LTCG rates)
  - Dividend distributions (taxed at qualified or ordinary rates depending on source)

High-turnover funds generate more short-term gains, creating a structural
tax disadvantage that is invisible in standard expense ratio comparisons.

Important: Tax drag applies only to taxable accounts. IRAs and 401(k)s are
tax-deferred and receive no benefit from tax-efficient fund management.

Data sources:
  - 497K: After-tax return disclosures (required by SEC)
  - N-PORT: Holdings turnover patterns
  - N-CEN: Portfolio turnover rate

Academic references:
  - Bergstresser & Poterba (2002) "Do After-Tax Returns Affect Mutual Fund Inflows?"
  - Dickson, Shoven & Sialm (2000) "Tax Externalities of Equity Mutual Funds"
  - Edelen, Evans, Kadlec (2013) "Shedding Light on 'Invisible' Costs"
"""

from __future__ import annotations

from dataclasses import dataclass

from fundautopsy.models.cost_breakdown import CostRange
from fundautopsy.models.filing_data import DataSourceTag

# Federal tax rate assumptions (2024-2025 brackets)
# Top federal ordinary income rate (37% bracket, married filing jointly)
# Applied to short-term capital gains and non-qualified dividends
FEDERAL_ORDINARY_INCOME_RATE = 0.37

# Preferred long-term capital gains rate (20% for top earners)
# Most mutual fund investors face 15% or 20% depending on income
# Conservative assumption: 20% for higher net worth, tax-conscious investors
FEDERAL_LTCG_RATE = 0.20

# Net Investment Income Tax: 3.8% on capital gains + dividends
# Applied to taxpayers with modified adjusted gross income above thresholds
# ($250k married, $200k single). Conservative: include as floor assumption.
NIIT_RATE = 0.038

# Qualified dividend rate: 20% federal + NIIT where applicable
FEDERAL_QUALIFIED_DIVIDEND_RATE = 0.20

# Non-qualified dividend rate: ordinary income rates + NIIT
# For equity funds, assume 70% qualified, 30% non-qualified
# For bond funds, almost all interest is non-qualified (taxed at ordinary rates)

# Average state and local tax on investment income
# Varies by state: CA ~13%, NY ~8.8%, TX/FL ~0%, national average ~5-6%
# Conservative middle estimate: 5% for state + local combined
STATE_TAX_ESTIMATE = 0.05


@dataclass
class TaxDragEstimate:
    """Tax cost estimate for a fund in a taxable account.

    Annual tax drag expressed as basis points of fund value.
    Only applies to taxable accounts; tax-deferred accounts (IRAs, 401ks) are unaffected.

    Attributes:
        estimated_tax_drag_low_bps: Conservative tax cost estimate (basis points)
        estimated_tax_drag_high_bps: Aggressive tax cost estimate (basis points)
        stcg_drag_bps: Short-term capital gains tax component
        ltcg_drag_bps: Long-term capital gains tax component
        dividend_drag_bps: Dividend distribution tax component
        turnover_rate_pct: Portfolio turnover rate (input)
        implied_stcg_share: Estimated fraction of realized gains that are short-term
        methodology: Detailed explanation of assumptions and methods
        is_estimated: True (indicates this is a model estimate, not disclosed)
    """

    # Annual tax drag in basis points
    estimated_tax_drag_low_bps: float = 0.0
    estimated_tax_drag_high_bps: float = 0.0

    # Component breakdown (in basis points)
    stcg_drag_bps: float = 0.0  # Short-term capital gains tax
    ltcg_drag_bps: float = 0.0  # Long-term capital gains tax
    dividend_drag_bps: float = 0.0  # Dividend tax cost

    # Turnover-based estimate
    turnover_rate_pct: float = 0.0
    implied_stcg_share: float = 0.0  # Estimated share of realized gains that are short-term

    # Metadata
    methodology: str = ""
    is_estimated: bool = True
    fund_type: str = ""  # "equity" or "bond" for context

    def as_cost_range(self) -> CostRange:
        """Convert to CostRange model for integration with CostBreakdown."""
        return CostRange(
            low_bps=self.estimated_tax_drag_low_bps,
            high_bps=self.estimated_tax_drag_high_bps,
            tag=DataSourceTag.ESTIMATED,
            methodology=self.methodology,
        )


def estimate_tax_drag(
    turnover_rate_pct: float,
    expense_ratio_pct: float = 0.0,
    dividend_yield_pct: float = 0.0,
    is_equity: bool = True,
    is_tax_managed: bool = False,
    include_niit: bool = True,
) -> TaxDragEstimate:
    """Estimate annual tax drag from fund characteristics in a taxable account.

    Uses turnover rate as the primary driver of tax inefficiency.
    Higher turnover generates more realized gains, especially short-term gains
    that are taxed at ordinary income rates rather than preferential LTCG rates.

    This estimate applies only to taxable accounts. Tax-deferred accounts
    (IRAs, 401ks) receive no benefit from tax-efficient fund management.

    Args:
        turnover_rate_pct: Portfolio turnover rate (e.g., 50 for 50%).
        expense_ratio_pct: Expense ratio for context (not used in calculation).
        dividend_yield_pct: Estimated annual dividend/interest yield (%).
        is_equity: True for equity funds, False for bond/fixed-income funds.
        is_tax_managed: True if fund uses tax-loss harvesting or other tax management.
        include_niit: Include 3.8% Net Investment Income Tax (applies to higher earners).

    Returns:
        TaxDragEstimate with low/high range, component breakdown, and methodology.
    """
    fund_type = "equity" if is_equity else "bond"
    result: TaxDragEstimate = TaxDragEstimate(
        turnover_rate_pct=turnover_rate_pct,
        fund_type=fund_type,
    )
    turnover: float = turnover_rate_pct / 100.0

    if is_tax_managed:
        # Tax-managed funds minimize realized distributions through:
        # - Tax-loss harvesting (offset gains with losses)
        # - Strategic timing of sales
        # - Buying low-yielding securities
        # Assumption: 70% reduction in effective turnover-driven gains
        result.methodology = (
            "Tax-managed fund: 30% effective realization rate applied. "
            "Tax-loss harvesting and strategic selling reduce realized gains."
        )
        turnover *= 0.30

    # Estimate what fraction of realized gains are short-term
    # Relationship between turnover rate and STCG share is empirically established
    # in academic literature (Bergstresser & Poterba, 2002; Edelen et al., 2013)
    # High turnover -> more short-term (held < 1 year)
    # Low turnover -> more long-term (held >= 1 year)
    if turnover > 1.0:
        # 100%+ turnover: ~50% STCG (rapid trading)
        stcg_share: float = 0.50
    elif turnover > 0.5:
        # 50-100% turnover: ~35% STCG
        stcg_share = 0.35
    elif turnover > 0.2:
        # 20-50% turnover: ~20% STCG
        stcg_share = 0.20
    else:
        # <20% turnover: ~10% STCG (mostly long-term holds)
        stcg_share = 0.10

    result.implied_stcg_share = stcg_share

    # Calculate effective tax rates (federal + state + NIIT where applicable)
    # STCG: ordinary income rates + state tax + NIIT
    stcg_effective_rate: float = FEDERAL_ORDINARY_INCOME_RATE + STATE_TAX_ESTIMATE
    if include_niit:
        stcg_effective_rate += NIIT_RATE

    # LTCG: long-term rate + state tax + NIIT
    ltcg_effective_rate: float = FEDERAL_LTCG_RATE + STATE_TAX_ESTIMATE
    if include_niit:
        ltcg_effective_rate += NIIT_RATE

    # Qualified dividend: 20% federal + state + NIIT
    qualified_div_rate: float = FEDERAL_QUALIFIED_DIVIDEND_RATE + STATE_TAX_ESTIMATE
    if include_niit:
        qualified_div_rate += NIIT_RATE

    # Non-qualified dividend: ordinary income rates + state + NIIT
    nonqualified_div_rate: float = FEDERAL_ORDINARY_INCOME_RATE + STATE_TAX_ESTIMATE
    if include_niit:
        nonqualified_div_rate += NIIT_RATE

    if is_equity:
        # Equity fund assumed characteristics:
        # - ~7% average annual capital appreciation (long-term market average)
        # - When fund sells winners, gains are taxable
        # - Turnover drives both STCG and LTCG realizations
        avg_annual_gain: float = 0.07
        realized_gain: float = turnover * avg_annual_gain

        # Split into short-term and long-term based on implied STCG share
        stcg: float = realized_gain * stcg_share
        ltcg: float = realized_gain * (1 - stcg_share)

        # Tax drag = tax rate × gains as percent of NAV
        stcg_tax: float = stcg * stcg_effective_rate
        ltcg_tax: float = ltcg * ltcg_effective_rate

        result.stcg_drag_bps = round(stcg_tax * 10000, 1)
        result.ltcg_drag_bps = round(ltcg_tax * 10000, 1)

        # Dividend tax
        # Assume 70% of equity dividends are qualified (e.g., US large-cap stocks)
        # Remaining 30% are non-qualified (e.g., REITs, international dividends)
        if dividend_yield_pct > 0:
            div_yield: float = dividend_yield_pct / 100.0
            qualified_pct: float = 0.70
            nonqualified_pct: float = 1 - qualified_pct

            div_tax: float = (
                div_yield * qualified_pct * qualified_div_rate +
                div_yield * nonqualified_pct * nonqualified_div_rate
            )
            result.dividend_drag_bps = round(div_tax * 10000, 1)

    else:
        # Bond fund assumed characteristics:
        # - ~4% average yield (realistic for broad bond funds)
        # - Interest income taxed at ordinary income rates (never "qualified")
        # - Also trades bonds for duration/sector management (generates realized gains)
        avg_yield: float = 0.04
        # Interest is not "dividend" — it's interest income, fully taxable at ordinary rates
        interest_tax: float = avg_yield * FEDERAL_ORDINARY_INCOME_RATE + avg_yield * STATE_TAX_ESTIMATE
        if include_niit:
            interest_tax += avg_yield * NIIT_RATE
        result.dividend_drag_bps = round(interest_tax * 10000, 1)

        # Bond funds also generate capital gains/losses from trading
        # Assumed: ~2% annual price movement from duration and sector positioning
        avg_bond_gain: float = 0.02
        realized_gain = turnover * avg_bond_gain
        stcg = realized_gain * stcg_share
        ltcg = realized_gain * (1 - stcg_share)

        result.stcg_drag_bps = round(stcg * stcg_effective_rate * 10000, 1)
        result.ltcg_drag_bps = round(ltcg * ltcg_effective_rate * 10000, 1)

    # Total tax drag
    total: float = result.stcg_drag_bps + result.ltcg_drag_bps + result.dividend_drag_bps

    # Range estimates:
    # Low: 70% of midpoint (assumes lower realization, lower gains, lower turnover impact)
    # High: 130% of midpoint (assumes higher realization, bigger gains, market volatility)
    result.estimated_tax_drag_low_bps = round(total * 0.70, 1)
    result.estimated_tax_drag_high_bps = round(total * 1.30, 1)

    # Generate methodology if not already set
    if not result.methodology:
        tax_rates_desc = (
            f"{FEDERAL_ORDINARY_INCOME_RATE:.0%} federal ordinary income, "
            f"{FEDERAL_LTCG_RATE:.0%} federal LTCG"
        )
        if include_niit:
            tax_rates_desc += f", {NIIT_RATE:.1%} NIIT"
        tax_rates_desc += f", {STATE_TAX_ESTIMATE:.0%} state/local"

        result.methodology = (
            f"Tax drag estimated from {turnover_rate_pct:.0f}% turnover rate. "
            f"Assumes {tax_rates_desc}. "
            f"Short-term gain share estimated at {stcg_share:.0%} based on turnover. "
            f"Fund type: {fund_type}. "
            f"APPLIES ONLY TO TAXABLE ACCOUNTS. "
            f"IRAs, 401(k)s, and other tax-deferred accounts receive no benefit from "
            f"tax-efficient fund management — tax drag is zero in those contexts."
        )

    return result


def tax_drag_comparison_text(
    fund_ticker: str,
    tax_drag: TaxDragEstimate,
    expense_ratio_pct: float | None = None,
) -> str:
    """Generate a plain-text comparison of tax drag vs expense ratio.

    Useful for X thread content and reports.
    """
    low: float = tax_drag.estimated_tax_drag_low_bps
    high: float = tax_drag.estimated_tax_drag_high_bps

    text: str = f"{fund_ticker}: Estimated tax drag {low:.0f}–{high:.0f} bps"

    if expense_ratio_pct is not None:
        er_bps: float = expense_ratio_pct * 100
        midpoint: float = (low + high) / 2
        if midpoint > er_bps:
            text += f" (exceeds the {er_bps:.0f} bps expense ratio)"
        elif midpoint > er_bps * 0.5:
            text += f" (adds {midpoint/er_bps:.0%} to the {er_bps:.0f} bps expense ratio)"

    text += (
        f"\n  STCG: {tax_drag.stcg_drag_bps:.0f} bps | LTCG: {tax_drag.ltcg_drag_bps:.0f} bps"
        f" | Dividends: {tax_drag.dividend_drag_bps:.0f} bps"
    )
    text += f"\n  Turnover: {tax_drag.turnover_rate_pct:.0f}% | Est. STCG share: {tax_drag.implied_stcg_share:.0%}"

    return text
