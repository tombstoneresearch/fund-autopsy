"""Tests for N-PORT derivative and geography extraction.

Unit tests against fabricated minimal XML fragments to exercise the
parser's per-subtree logic without requiring network access. The full
live validation lives at Intelligence/_nport_deriv_validate_2026-04-23.py
and runs against real SEC filings.
"""
from __future__ import annotations

from lxml import etree

from fundautopsy.data.nport import _parse_holding, NPORT_NS
from fundautopsy.models.filing_data import NPortHolding, NPortData


NS = "http://www.sec.gov/edgar/nport"


def _make_invst(xml: str) -> etree._Element:
    """Wrap a fragment in the invstOrSec namespace for parsing."""
    wrapper = f"""<invstOrSec xmlns="{NS}">{xml}</invstOrSec>"""
    return etree.fromstring(wrapper.encode())


# ── Derivative classification ────────────────────────────────────────


def test_equity_holding_is_not_derivative():
    inv = _make_invst("""
      <name>APPLE INC</name>
      <cusip>037833100</cusip>
      <balance>1000</balance>
      <valUSD>175000</valUSD>
      <pctVal>1.5</pctVal>
      <assetCat>EC</assetCat>
      <issuerCat>CORP</issuerCat>
    """)
    h = _parse_holding(inv)
    assert h is not None
    assert h.is_derivative is False
    assert h.derivative_category is None


def test_debt_holding_not_derivative_despite_d_prefix():
    inv = _make_invst("""
      <name>CORPORATE BOND</name>
      <balance>500000</balance>
      <valUSD>495000</valUSD>
      <pctVal>0.8</pctVal>
      <assetCat>DBT</assetCat>
    """)
    h = _parse_holding(inv)
    assert h is not None
    assert h.is_derivative is False  # DBT is debt, not derivative


def test_fx_forward_is_derivative():
    inv = _make_invst("""
      <name>N/A</name>
      <balance>0</balance>
      <valUSD>18930</valUSD>
      <pctVal>0.0004</pctVal>
      <assetCat>DFE</assetCat>
      <derivativeInfo>
        <fwdDeriv>
          <counterpartyInfo>
            <counterpartyName>HSBC BANK PLC</counterpartyName>
            <counterpartyLei>MP6I5ZYZBEU3UXPYFY54</counterpartyLei>
          </counterpartyInfo>
          <amtCurSold>2048807.49</amtCurSold>
          <curSold>USD</curSold>
          <amtCurPur>1534000</amtCurPur>
          <curPur>GBP</curPur>
          <unrealizedAppr>18930.44</unrealizedAppr>
        </fwdDeriv>
      </derivativeInfo>
    """)
    h = _parse_holding(inv)
    assert h is not None
    assert h.is_derivative is True
    assert h.derivative_category == "Foreign Exchange / Forward"
    assert h.derivative_instrument_type == "fwdDeriv"
    assert h.counterparty_name == "HSBC BANK PLC"
    assert h.notional_usd == 2048807.49
    assert h.unrealized_appreciation_usd == 18930.44


def test_interest_rate_swap_is_derivative():
    inv = _make_invst("""
      <name>IRS USD</name>
      <balance>0</balance>
      <valUSD>-4165623.66</valUSD>
      <pctVal>-0.01</pctVal>
      <assetCat>DIR</assetCat>
      <derivativeInfo>
        <swapDeriv>
          <counterpartyInfo>
            <counterpartyName>LONDON CLEARING HOUSE</counterpartyName>
          </counterpartyInfo>
          <swapFlag>Y</swapFlag>
          <notionalAmt>471429000</notionalAmt>
          <curCd>USD</curCd>
          <unrealizedAppr>-4165623.66</unrealizedAppr>
        </swapDeriv>
      </derivativeInfo>
    """)
    h = _parse_holding(inv)
    assert h is not None
    assert h.is_derivative is True
    assert h.derivative_category == "Interest Rate"
    assert h.derivative_instrument_type == "swapDeriv"
    assert h.notional_usd == 471429000.0
    assert h.counterparty_name == "LONDON CLEARING HOUSE"


# ── Country exposure aggregation ─────────────────────────────────────


def _holding(country: str | None, pct: float | None) -> NPortHolding:
    h = NPortHolding(name="x")
    h.investment_country = country
    h.pct_of_net_assets = pct
    return h


def test_country_exposure_net_mode_sums_signed():
    d = NPortData(filing_date=None, reporting_period_end=None, series_id="S")
    d.holdings = [
        _holding("US", 50.0),
        _holding("US", 60.0),
        _holding("US", -5.0),  # synthetic short offset
        _holding("GB", 10.0),
    ]
    e = d.country_exposure_pct(mode="net")
    assert e["US"] == 105.0  # 50 + 60 - 5
    assert e["GB"] == 10.0


def test_country_exposure_gross_long_filters_negatives():
    d = NPortData(filing_date=None, reporting_period_end=None, series_id="S")
    d.holdings = [
        _holding("US", 50.0),
        _holding("US", 60.0),
        _holding("US", -5.0),  # filtered out
    ]
    e = d.country_exposure_pct(mode="gross_long")
    assert e["US"] == 110.0  # 50 + 60


def test_country_exposure_gross_absolute_sums_absolute():
    d = NPortData(filing_date=None, reporting_period_end=None, series_id="S")
    d.holdings = [
        _holding("US", 50.0),
        _holding("US", -5.0),
    ]
    e = d.country_exposure_pct(mode="gross_absolute")
    assert e["US"] == 55.0


def test_country_unknown_bucket():
    d = NPortData(filing_date=None, reporting_period_end=None, series_id="S")
    d.holdings = [_holding(None, 10.0), _holding("", 5.0)]
    e = d.country_exposure_pct()
    assert e["UNKNOWN"] == 15.0


# ── Derivative aggregation on NPortData ──────────────────────────────


def test_npdata_aggregates_derivatives():
    d = NPortData(filing_date=None, reporting_period_end=None, series_id="S")
    d.holdings = [
        _holding_with_cat("EC", False),
        _holding_with_cat("DFE", True, notional=1_000_000),
        _holding_with_cat("DIR", True, notional=2_000_000),
    ]
    assert len(d.derivatives) == 2
    assert d.aggregate_derivative_notional_usd == 3_000_000
    assert "Foreign Exchange / Forward" in d.distinct_derivative_categories
    assert "Interest Rate" in d.distinct_derivative_categories


def _holding_with_cat(
    cat: str, is_deriv: bool, notional: float | None = None
) -> NPortHolding:
    h = NPortHolding(name="x")
    h.asset_category = cat
    if is_deriv:
        h.notional_usd = notional
    return h
