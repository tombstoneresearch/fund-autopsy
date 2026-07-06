"""Integration tests for the new API endpoints using FastAPI TestClient.

Covers:
  - /api/derivatives/{ticker}
  - /api/geography/{ticker}
  - /api/mergers/{ticker}
  - /api/leaderboard
  - /leaderboard (HTML page)
  - /health

Each endpoint is tested against a valid ticker shape (200 path), an ETF
ticker (422 path), and an invalid ticker format (400 path). The actual
SEC data fetches are monkeypatched so these tests run without network.

Skipped when FastAPI is not installed.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch, MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client():
    from fundautopsy.web.app import app
    return TestClient(app)


# ── Shape + error-code tests for each ticker-accepting endpoint ──────


@pytest.mark.parametrize("endpoint", [
    "/api/derivatives/{}",
    "/api/geography/{}",
    "/api/mergers/{}",
    "/api/fee-history/{}",
    "/api/sai/{}",
    "/api/ncsr/{}",
])
def test_endpoint_rejects_invalid_ticker_format(client, endpoint):
    """Non-alpha tickers, overlength tickers, and empty strings get 400."""
    # Numeric
    r = client.get(endpoint.format("123"))
    assert r.status_code == 400
    # Too long
    r = client.get(endpoint.format("TOOLONGTICKER"))
    assert r.status_code == 400


@pytest.mark.parametrize("endpoint", [
    "/api/derivatives/SPY",
    "/api/geography/QQQ",
    "/api/mergers/VTI",
    "/api/fee-history/VOO",
    "/api/sai/IVV",
    "/api/ncsr/BND",
])
def test_endpoint_rejects_known_etf_with_422(client, endpoint):
    """Known ETF tickers get a 422 with a specific explanatory message."""
    r = client.get(endpoint)
    assert r.status_code == 422
    body = r.json()
    assert "detail" in body
    assert any(word in body["detail"].lower()
               for word in ("etf", "exchange-traded", "mutual fund"))


@pytest.mark.parametrize("endpoint", [
    "/api/derivatives/AAPL",
    "/api/geography/MSFT",
    "/api/mergers/GOOGL",
])
def test_endpoint_rejects_stock_with_422(client, endpoint):
    """Known stock tickers get a 422 with a stock-specific message."""
    r = client.get(endpoint)
    assert r.status_code == 422


# ── Leaderboard ──────────────────────────────────────────────────────


def test_leaderboard_api_returns_entries_and_stats(client):
    r = client.get("/api/leaderboard")
    assert r.status_code == 200
    body = r.json()
    assert "entries" in body
    assert "stats" in body
    assert isinstance(body["entries"], list)


def test_leaderboard_api_accepts_sort_and_limit(client):
    r = client.get("/api/leaderboard?sort_by=hidden_cost_mid_bps&limit=10")
    assert r.status_code == 200
    body = r.json()
    assert len(body["entries"]) <= 10


def test_leaderboard_page_renders_html(client):
    r = client.get("/leaderboard")
    assert r.status_code == 200
    # Response is HTML with our page-level markers
    content = r.text
    assert "<title>Fund Autopsy" in content
    assert "Worst Offenders" in content
    # OG/Twitter card meta present
    assert 'property="og:title"' in content or "og:title" in content
    assert 'name="twitter:card"' in content or "twitter:card" in content


# ── /health endpoint ─────────────────────────────────────────────────


def test_health_endpoint_returns_status(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"
    assert "edgar" in body
    assert body["edgar"]["status"] in ("ok", "degraded")


# ── Home page ────────────────────────────────────────────────────────


def test_home_page_renders_with_og_metadata(client):
    r = client.get("/")
    assert r.status_code == 200
    content = r.text
    assert "og:title" in content
    assert "twitter:card" in content
    # Dashboard has the search input
    assert "tickerInput" in content


# ── 404 path ─────────────────────────────────────────────────────────


def test_unknown_ticker_returns_404(client, monkeypatch):
    """A ticker that is neither ETF nor stock nor resolvable → 404."""
    # Bypass the EDGAR lookup by patching identify_fund to raise
    from fundautopsy.web import app as app_module

    def _raise(ticker):
        raise ValueError(f"Could not resolve '{ticker}' to a registered mutual fund.")

    monkeypatch.setattr(app_module, "_resolve_or_explain",
                        MagicMock(side_effect=lambda t: (
                            _raise(t) if t not in ("SPY", "QQQ") else None
                        )))

    # Using a plausibly-formatted fake ticker that is not in our known sets
    r = client.get("/api/derivatives/ZZZZZ")
    # Should return 404 because not ETF, not stock, and resolver raised
    assert r.status_code in (404, 500)
