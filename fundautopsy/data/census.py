"""SEC investment-company series/class census resolver.

The SEC publishes an authoritative annual CSV mapping every registered
investment company series and class, including class ticker symbols:

    https://www.sec.gov/files/investment/data/other/
        investment-company-series-class-information/
        investment-company-series-class-<YEAR>.csv

This is the second-line resolver after the daily ticker master misses.
Its distinctive value is the authoritative negative: when a ticker is
absent from the census, it does not exist as a live share class, and
the correct answer is "dead or renamed ticker", not another brute-force
scan. (Shakedown finding, 2026-07-05: v1's ICF walker spent weeks of
engineering chasing LIPSX, a ticker absent from the census.)
"""

from __future__ import annotations

import csv
import io
import logging
import threading
from datetime import date
from enum import Enum
from typing import TYPE_CHECKING, Optional

import httpx

if TYPE_CHECKING:  # pragma: no cover
    from fundautopsy.data.edgar import MutualFundIdentifier

logger = logging.getLogger(__name__)

CENSUS_URL_TEMPLATE = (
    "https://www.sec.gov/files/investment/data/other/"
    "investment-company-series-class-information/"
    "investment-company-series-class-{year}.csv"
)

# Column headers as published (BOM-stripped by the csv layer).
_COL_CIK = "CIK Number"
_COL_SERIES = "Series ID"
_COL_CLASS = "Class ID"
_COL_TICKER = "Class Ticker"


class CensusVerdict(Enum):
    """Tri-state so callers can distinguish a dead ticker from a dead network."""

    HIT = "hit"
    ABSENT = "absent"
    UNAVAILABLE = "unavailable"


_census_index: dict[str, tuple[str, str, str]] | None = None
_census_lock = threading.Lock()
_census_load_failed: bool = False


def parse_census_csv(text: str) -> dict[str, tuple[str, str, str]]:
    """Parse the census CSV into {TICKER: (cik, series_id, class_id)}.

    Rows without a class ticker (separate accounts, unlisted classes)
    are skipped. Later rows win on duplicate tickers, which matches the
    file's append-style maintenance.
    """
    index: dict[str, tuple[str, str, str]] = {}
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    for row in reader:
        ticker = (row.get(_COL_TICKER) or "").strip().upper()
        if not ticker:
            continue
        cik = (row.get(_COL_CIK) or "").strip().lstrip("0")
        series_id = (row.get(_COL_SERIES) or "").strip()
        class_id = (row.get(_COL_CLASS) or "").strip()
        if cik and series_id and class_id:
            index[ticker] = (cik, series_id, class_id)
    return index


def _download_census(client: httpx.Client) -> Optional[str]:
    """Fetch the current-year census, falling back one year (the new
    year's file appears with a lag)."""
    year = date.today().year
    for candidate in (year, year - 1):
        url = CENSUS_URL_TEMPLATE.format(year=candidate)
        try:
            resp = client.get(url)
            if resp.status_code == 200 and resp.text:
                logger.info("Loaded SEC series/class census %s", candidate)
                return resp.text
        except Exception as exc:  # noqa: BLE001 — tri-state handles it
            logger.warning("Census download failed for %s: %s", candidate, exc)
    return None


def _ensure_index(client: httpx.Client) -> Optional[dict[str, tuple[str, str, str]]]:
    global _census_index, _census_load_failed
    with _census_lock:
        if _census_index is not None:
            return _census_index
        if _census_load_failed:
            return None
        text = _download_census(client)
        if text is None:
            _census_load_failed = True
            return None
        _census_index = parse_census_csv(text)
        logger.info(
            "SEC census indexed: %d live class tickers", len(_census_index)
        )
        return _census_index


def resolve_via_census(
    ticker: str, client: httpx.Client
) -> tuple[CensusVerdict, Optional["MutualFundIdentifier"]]:
    """Resolve a ticker against the SEC census.

    Returns (HIT, identifier), (ABSENT, None) meaning the ticker does
    not exist as a live share class, or (UNAVAILABLE, None) when the
    census could not be loaded and no authoritative statement is
    possible.
    """
    index = _ensure_index(client)
    if index is None:
        return (CensusVerdict.UNAVAILABLE, None)
    row = index.get(ticker.upper())
    if row is None:
        return (CensusVerdict.ABSENT, None)
    cik, series_id, class_id = row
    from fundautopsy.data.edgar import MutualFundIdentifier

    return (
        CensusVerdict.HIT,
        MutualFundIdentifier(
            ticker=ticker.upper(),
            cik=int(cik),
            series_id=series_id,
            class_id=class_id,
        ),
    )


def clear_census_cache() -> None:
    """Test seam: forget the loaded census."""
    global _census_index, _census_load_failed
    with _census_lock:
        _census_index = None
        _census_load_failed = False
