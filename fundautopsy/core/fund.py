"""Stage 1: Fund identification and metadata retrieval."""

from __future__ import annotations

from fundautopsy.data.edgar import MutualFundIdentifier, get_edgar_client, resolve_ticker
from fundautopsy.models.fund_metadata import FundMetadata


def identify_fund(ticker: str) -> FundMetadata:
    """Resolve a ticker symbol to fund metadata via EDGAR.

    Uses SEC's company_tickers_mf.json to map ticker to CIK, series ID,
    and class ID. Then fetches basic metadata from the EDGAR submissions API.

    Args:
        ticker: Fund ticker symbol (e.g., "AGTHX", "FFFHX").

    Returns:
        Populated FundMetadata instance.

    Raises:
        ValueError: If ticker cannot be resolved to a registered fund.
    """
    client = get_edgar_client()
    try:
        fund_id: MutualFundIdentifier | None = resolve_ticker(ticker, client=client)
        if fund_id is None:
            raise ValueError(
                f"Could not resolve '{ticker}' to a registered mutual fund. "
                f"Verify the ticker is correct and that it's a mutual fund (not an ETF or stock)."
            )

        # Fetch fund name from submissions API
        from fundautopsy.data.edgar import EDGAR_SUBMISSIONS_URL, _rate_limit
        _rate_limit()
        resp = client.get(f"{EDGAR_SUBMISSIONS_URL}/CIK{fund_id.cik_padded}.json")
        resp.raise_for_status()
        sub = resp.json()

        fund_name: str = sub.get("name", ticker.upper())
        # The submissions name is the trust/registrant name, not the series name.
        # We'll refine once N-CEN is parsed, but this is fine for now.

        return FundMetadata(
            ticker=fund_id.ticker,
            name=fund_name,
            cik=str(fund_id.cik),
            series_id=fund_id.series_id,
            class_id=fund_id.class_id,
            fund_family="",  # Will be populated from N-CEN
        )
    finally:
        client.close()
