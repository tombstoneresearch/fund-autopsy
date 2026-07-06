"""Tests for ETF and stock-ticker detection in the web layer.

The `_resolve_or_explain` helper returns a specific 422 HTTPException
for ETF tickers and a different 422 for well-known stock tickers,
rather than a generic 404 that leaves the user confused. Verifies
both lists are non-empty, correctly shaped, and that the helper
raises with the right status code and message substring.

Skipped when FastAPI is not installed in the local environment.
"""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")


def test_known_etfs_constant_is_populated():
    from fundautopsy.web.app import _KNOWN_ETF_TICKERS
    assert isinstance(_KNOWN_ETF_TICKERS, frozenset)
    assert len(_KNOWN_ETF_TICKERS) >= 30
    # Smoke check some canonical entries
    assert "SPY" in _KNOWN_ETF_TICKERS
    assert "QQQ" in _KNOWN_ETF_TICKERS
    assert "VTI" in _KNOWN_ETF_TICKERS


def test_known_stocks_constant_is_populated():
    from fundautopsy.web.app import _KNOWN_STOCKS
    assert isinstance(_KNOWN_STOCKS, frozenset)
    assert len(_KNOWN_STOCKS) >= 10
    assert "AAPL" in _KNOWN_STOCKS
    assert "MSFT" in _KNOWN_STOCKS


def test_resolve_etf_raises_with_422_and_etf_message():
    from fundautopsy.web.app import _resolve_or_explain
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        _resolve_or_explain("SPY")
    assert exc_info.value.status_code == 422
    detail = str(exc_info.value.detail).lower()
    assert "etf" in detail or "exchange-traded" in detail
    # Suggests alternative mutual fund tickers to try
    assert any(
        t in str(exc_info.value.detail)
        for t in ("VFIAX", "FXAIX", "AGTHX", "DODGX", "PTTRX")
    )


def test_resolve_stock_raises_with_422_and_stock_message():
    from fundautopsy.web.app import _resolve_or_explain
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        _resolve_or_explain("AAPL")
    assert exc_info.value.status_code == 422
    detail = str(exc_info.value.detail).lower()
    assert "stock" in detail or "not a mutual fund" in detail


def test_resolve_etf_is_case_insensitive():
    from fundautopsy.web.app import _resolve_or_explain
    from fastapi import HTTPException
    # Lowercase input should still match
    with pytest.raises(HTTPException) as exc_info:
        _resolve_or_explain("spy")
    assert exc_info.value.status_code == 422
    assert "ETF" in str(exc_info.value.detail) or "exchange-traded" in str(exc_info.value.detail).lower()


def test_resolve_whitespace_trimmed():
    from fundautopsy.web.app import _resolve_or_explain
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        _resolve_or_explain("  QQQ  ")
    assert exc_info.value.status_code == 422
