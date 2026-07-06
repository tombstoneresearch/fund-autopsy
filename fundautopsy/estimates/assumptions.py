"""Default assumptions and asset-class mappings for cost estimation.

These assumptions are grounded in academic literature and industry data.
All spread values are one-way (half-spread). Multiply by 2 for round-trip.

Sources:
- Edelen, Evans, Kadlec (2007) for market impact ranges
- Industry consensus for bid-ask spread assumptions
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpreadAssumption:
    """Bid-ask spread assumption for an asset class."""

    asset_class: str
    low_one_way_pct: float  # Low estimate, one-way
    high_one_way_pct: float  # High estimate, one-way
    description: str = ""


@dataclass(frozen=True)
class ImpactAssumption:
    """Market impact assumption based on fund size and turnover."""

    category: str
    low_pct_of_turnover: float
    high_pct_of_turnover: float
    description: str = ""


# Bid-ask spread assumptions by asset class
# These map to N-PORT assetCat codes
SPREAD_ASSUMPTIONS: dict[str, SpreadAssumption] = {
    "EC": SpreadAssumption("US Large Cap Equity", 0.0005, 0.0010, "S&P 500 constituents, highly liquid"),
    "EC_MID": SpreadAssumption("US Mid Cap Equity", 0.0010, 0.0020, "Russell Midcap range"),
    "EC_SMALL": SpreadAssumption("US Small Cap Equity", 0.0020, 0.0040, "Russell 2000 range"),
    "EC_INTL": SpreadAssumption("International Developed Equity", 0.0010, 0.0025, "EAFE markets"),
    "EC_EM": SpreadAssumption("Emerging Market Equity", 0.0025, 0.0050, "EM markets, wider spreads"),
    "DBT_IG": SpreadAssumption("Investment Grade Bonds", 0.0002, 0.0010, "IG corporate and agency"),
    "DBT_HY": SpreadAssumption("High Yield Bonds", 0.0010, 0.0025, "Below-IG corporate"),
    "DBT_GOV": SpreadAssumption("Government Bonds", 0.0001, 0.0005, "Treasuries and agencies"),
    "DBT_MUNI": SpreadAssumption("Municipal Bonds", 0.0005, 0.0015, "State and local"),
}

# Default spread when asset class is unknown
DEFAULT_SPREAD = SpreadAssumption("Unknown", 0.0010, 0.0025, "Default assumption")

# Market impact assumptions by fund category
IMPACT_ASSUMPTIONS: dict[str, ImpactAssumption] = {
    "large_low_turnover": ImpactAssumption(
        "Large-cap, low turnover (<50%)", 0.0010, 0.0020,
        "Large-cap funds with moderate trading activity"
    ),
    "large_high_turnover": ImpactAssumption(
        "Large-cap, high turnover (>50%)", 0.0020, 0.0050,
        "Large-cap funds with active trading strategies"
    ),
    "small_low_turnover": ImpactAssumption(
        "Small-cap, low turnover (<50%)", 0.0030, 0.0060,
        "Small-cap funds with moderate trading activity"
    ),
    "small_high_turnover": ImpactAssumption(
        "Small-cap, high turnover (>50%)", 0.0050, 0.0150,
        "Small-cap funds with active trading strategies"
    ),
}

# Industry average soft dollar share (Erzurumlu & Kotomin, 2016)
# Used as fallback when N-CEN C.6.b is missing but C.6.a is reported
INDUSTRY_AVG_SOFT_DOLLAR_SHARE = 0.45  # 45% of total commissions

# N-PORT asset category code mappings
# Maps N-PORT assetCat values to our spread assumption keys
NPORT_ASSET_CAT_MAP: dict[str, str] = {
    "EC": "EC",  # Equity common
    "EP": "EC",  # Equity preferred (use equity spread)
    "DBT": "DBT_IG",  # Debt (default to IG, refine with credit quality)
    "STIV": "EC",  # Short-term investment vehicle
    "OTHER": "EC",  # Other — conservative default
    # ABS / MBS categories
    "ABS-MBS": "DBT_IG",  # Agency MBS — tight spreads, IG-like
    "ABS-O": "DBT_IG",  # Other ABS
    "ABS-CBDO": "DBT_HY",  # CLO/CDO tranches — wider spreads
    "ABS-A": "DBT_IG",  # Auto ABS
    # Derivatives and cash
    "DIR": "DBT_GOV",  # Derivatives — use govt as proxy (low friction)
    "LOAN": "DBT_HY",  # Loans — illiquid, HY-like spreads
    "CASH": "DBT_GOV",  # Cash equivalents
}

# Turnover threshold for low vs high classification
TURNOVER_LOW_HIGH_THRESHOLD = 0.50  # 50% for equity funds

# Bond funds use a higher turnover threshold — 100% is normal for
# active fixed income due to roll-down, coupon reinvestment, and duration mgmt
BOND_TURNOVER_LOW_HIGH_THRESHOLD = 1.00  # 100%

# Bond fund market impact is structurally lower than equity impact.
# Fixed income markets are dealer-intermediated with narrower price impact
# per unit of turnover. These are separate from the equity impact assumptions.
BOND_IMPACT_ASSUMPTIONS: dict[str, ImpactAssumption] = {
    "bond_low_turnover": ImpactAssumption(
        "Bond fund, low turnover (<100%)", 0.0005, 0.0010,
        "IG-heavy bond funds with normal turnover"
    ),
    "bond_high_turnover": ImpactAssumption(
        "Bond fund, high turnover (>100%)", 0.0010, 0.0025,
        "Active bond funds, PIMCO-style high-turnover strategies"
    ),
}
