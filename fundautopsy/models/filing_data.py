"""SEC filing data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class DataSourceTag(str, Enum):
    """Transparency tag for every data point."""

    REPORTED = "REPORTED"  # Directly from SEC filing
    CALCULATED = "CALCULATED"  # Computed from reported data
    ESTIMATED = "ESTIMATED"  # Derived using assumptions/proxies
    UNAVAILABLE = "UNAVAILABLE"  # Expected but missing from filing
    NOT_DISCLOSED = "NOT_DISCLOSED"  # Fund acknowledged but didn't report amounts


@dataclass
class TaggedValue:
    """A numeric value paired with its data source tag."""

    value: float | None
    tag: DataSourceTag
    source_filing: str | None = None  # e.g., "N-CEN 2024-03-15"
    note: str | None = None

    @property
    def is_available(self) -> bool:
        """True if value exists and is not marked unavailable or not disclosed."""
        return self.value is not None and self.tag not in (
            DataSourceTag.UNAVAILABLE,
            DataSourceTag.NOT_DISCLOSED,
        )


@dataclass
class NCENData:
    """Parsed data from SEC Form N-CEN."""

    filing_date: date
    reporting_period_end: date
    series_id: str

    # Item C.6 — Brokerage and soft dollars
    has_soft_dollar_arrangements: bool | None = None  # C.6 yes/no
    total_brokerage_commissions: TaggedValue | None = None  # C.6.a ($)
    soft_dollar_commissions: TaggedValue | None = None  # C.6.b ($)
    soft_dollar_transaction_volume: TaggedValue | None = None  # C.6.c ($)

    # Item C.7 — Turnover
    portfolio_turnover_rate: TaggedValue | None = None

    # Item B.1 — Net assets
    total_net_assets: TaggedValue | None = None

    @property
    def soft_dollar_share_pct(self) -> float | None:
        """Soft dollar commissions as % of total commissions."""
        if (
            self.total_brokerage_commissions
            and self.soft_dollar_commissions
            and self.total_brokerage_commissions.is_available
            and self.soft_dollar_commissions.is_available
            and self.total_brokerage_commissions.value > 0
        ):
            return (
                self.soft_dollar_commissions.value
                / self.total_brokerage_commissions.value
                * 100
            )
        return None


@dataclass
class NPortHolding:
    """A single holding from N-PORT."""

    name: str
    cusip: str | None = None
    isin: str | None = None
    balance: float | None = None  # Shares/units
    value_usd: float | None = None  # Market value
    pct_of_net_assets: float | None = None
    asset_category: str | None = None
    issuer_category: str | None = None
    investment_country: str | None = None  # ISO-2 country code from <invCountry>

    # Fund-of-funds detection
    is_registered_investment_company: bool = False
    underlying_cik: str | None = None
    underlying_ticker: str | None = None

    # Derivatives (populated when assetCat is DE/DFE/DIR/DCR/DCO and
    # the invstOrSec element carries a <derivativeInfo> subtree).
    derivative_instrument_type: str | None = None  # fwdDeriv, swapDeriv, futrDeriv, optionSwaptionWarrantDeriv
    notional_usd: float | None = None
    counterparty_name: str | None = None
    counterparty_lei: str | None = None
    unrealized_appreciation_usd: float | None = None

    @property
    def is_derivative(self) -> bool:
        """True when this holding is a derivative position.

        N-PORT tags derivatives with an assetCat code beginning with 'D',
        excluding 'DBT' which is plain corporate debt. Known derivative
        codes: DE (equity), DFE (forward/FX), DIR (interest rate),
        DCR (credit), DCO (commodity), DO (other).
        """
        if not self.asset_category:
            return False
        cat = self.asset_category.upper()
        return cat.startswith("D") and cat != "DBT"

    @property
    def derivative_category(self) -> str | None:
        """Human-readable derivative category derived from asset_category.

        Returns None for non-derivative holdings.
        """
        if not self.is_derivative:
            return None
        mapping = {
            "DE": "Equity",
            "DFE": "Foreign Exchange / Forward",
            "DIR": "Interest Rate",
            "DCR": "Credit",
            "DCO": "Commodity",
            "DO": "Other",
        }
        return mapping.get(self.asset_category.upper(), self.asset_category)


@dataclass
class NPortData:
    """Parsed data from SEC Form N-PORT."""

    filing_date: date
    reporting_period_end: date
    series_id: str
    total_net_assets: float | None = None
    holdings: list[NPortHolding] = field(default_factory=list)

    @property
    def fund_holdings(self) -> list[NPortHolding]:
        """Holdings that are themselves registered investment companies."""
        return [h for h in self.holdings if h.is_registered_investment_company]

    @property
    def direct_holdings(self) -> list[NPortHolding]:
        """Holdings that are direct securities, not other funds."""
        return [h for h in self.holdings if not h.is_registered_investment_company]

    def asset_class_weights(self) -> dict[str, float]:
        """Compute allocation weights by asset category."""
        weights: dict[str, float] = {}
        for holding in self.holdings:
            cat = holding.asset_category or "UNKNOWN"
            weights[cat] = weights.get(cat, 0.0) + (holding.pct_of_net_assets or 0.0)
        return weights

    @property
    def derivatives(self) -> list[NPortHolding]:
        """Subset of holdings flagged as derivative positions."""
        return [h for h in self.holdings if h.is_derivative]

    @property
    def distinct_derivative_categories(self) -> list[str]:
        """Sorted list of distinct derivative category names the fund holds.

        Thread 6 ('derivatives mismatch') reports this count as a
        complexity signal against the fund's stated risk profile.
        """
        return sorted({
            h.derivative_category
            for h in self.derivatives
            if h.derivative_category
        })

    @property
    def distinct_derivative_instrument_types(self) -> list[str]:
        """Sorted list of distinct derivative instrument types.

        An instrument type is the N-PORT subtree kind — fwdDeriv,
        swapDeriv, futrDeriv, optionSwaptionWarrantDeriv. A fund using
        both swaps and options is running a more complex derivatives
        program than a fund using only forwards.
        """
        return sorted({
            h.derivative_instrument_type
            for h in self.derivatives
            if h.derivative_instrument_type
        })

    @property
    def aggregate_derivative_notional_usd(self) -> float:
        """Sum of notional amounts across all derivative holdings.

        Notional is the face value the derivative is written against,
        not the value of the position. A $10mm notional swap might have
        a $500k market value. Notional is the right scale for a
        'derivatives footprint' claim.
        """
        return sum(
            (h.notional_usd or 0.0)
            for h in self.derivatives
        )

    @property
    def derivative_category_counts(self) -> dict[str, int]:
        """Holding count per derivative category (Equity, Credit, etc.)."""
        counts: dict[str, int] = {}
        for h in self.derivatives:
            cat = h.derivative_category or "Unknown"
            counts[cat] = counts.get(cat, 0) + 1
        return counts

    def country_exposure_pct(
        self,
        mode: str = "net",
    ) -> dict[str, float]:
        """Weight allocation by issuer country as % of net assets.

        Uses the `<invCountry>` ISO-2 country code that N-PORT reports
        per holding (this is the issuer's country, not necessarily the
        country of risk or the trading venue).

        Modes:
          'net' (default): sums pctVal directly, which is signed in
            N-PORT — short positions contribute negative weight. For
            leveraged bond funds this produces the economically-correct
            net-exposure view and keeps country totals near 100%.
          'gross_long': filters to positions with positive pctVal only.
            Historical behavior; can exceed 100% for funds running
            synthetic shorts.
          'gross_absolute': sums absolute value of pctVal. Measures
            total issuer exposure regardless of direction.

        Returned dict is sorted descending by weight.
        """
        exposure: dict[str, float] = {}
        for h in self.holdings:
            country = (h.investment_country or "UNKNOWN").strip().upper() or "UNKNOWN"
            weight = h.pct_of_net_assets or 0.0
            if mode == "gross_long" and weight < 0:
                continue
            if mode == "gross_absolute":
                weight = abs(weight)
            exposure[country] = exposure.get(country, 0.0) + weight
        return dict(sorted(exposure.items(), key=lambda kv: -kv[1]))

    def country_concentration_pct(self, top_n: int = 1) -> float:
        """Concentration metric: weight share of the top-N countries.

        A single-country fund (U.S. large-cap index) typically reads
        >95% at top_n=1. A globally diversified fund might read 40-60%.
        Useful as a sanity check against a prospectus that claims
        'globally diversified' exposure.
        """
        exposure = self.country_exposure_pct()
        values = list(exposure.values())[:top_n]
        return sum(values)
