"""Fund metadata data model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class FundMetadata:
    """Core identifying information for a mutual fund."""

    ticker: str
    name: str
    cik: str
    series_id: str
    class_id: str
    fund_family: str
    fiscal_year_end: date | None = None
    total_net_assets: float | None = None
    inception_date: date | None = None
    category: str | None = None
    is_fund_of_funds: bool = False

    @property
    def ticker_upper(self) -> str:
        """Uppercase version of ticker symbol."""
        return self.ticker.upper()
