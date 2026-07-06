"""Supplementary data sources: Yahoo Finance, Morningstar fallbacks.

PLANNED — not yet implemented.

This module will provide fallback metadata sources when SEC filings don't
contain enough detail:

  - Yahoo Finance ticker lookup for basic fund metadata (AUM, NAV, category)
  - Morningstar fund category resolution for asset class disambiguation
  - Historical pricing for NAV-based spread estimation

These are lower-priority integrations — core analysis works with SEC data alone.

When implemented, functions should return Optional values (not raise
NotImplementedError) so callers can gracefully fall back to SEC-only data.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def get_fund_metadata_yahoo(ticker: str) -> Optional[dict]:
    """Retrieve basic fund metadata from Yahoo Finance.

    Returns None until this integration is implemented.
    """
    logger.debug("Yahoo Finance metadata lookup not yet implemented for %s", ticker)
    return None


def get_fund_category(ticker: str) -> Optional[str]:
    """Resolve fund category (e.g., Large Blend, Target Date 2040).

    Returns None until this integration is implemented.
    """
    logger.debug("Fund category lookup not yet implemented for %s", ticker)
    return None
