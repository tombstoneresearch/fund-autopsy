"""Tests for the Fidelity Series 485BPOS prose fee-table parser.

These tests exercise the pure-text helpers in
`fundautopsy.data.fidelity_series_fee_parser` without hitting EDGAR.
The `try_fidelity_series_fees` public entry point is exercised through
`retrieve_prospectus_fees` integration tests that are gated behind a
network marker.

Fidelity Series building-block funds (FSSJX, FSTSX, FEMSX, FHKFX, FSOSX,
FCNSX, FIGSX, FINVX, etc.) do not file standalone 497K summary
prospectuses; their fee tables live only inside the annual Fidelity
Investment Trust 485BPOS omnibus prospectus, in prose rather than
columnar form. The parser locates each fund's section by its
"Fund Summary Fund: Fidelity <Name>" marker, then extracts a labelled
prose fee table.
"""

from __future__ import annotations

from fundautopsy.data import fidelity_series_fee_parser as fsfp
from fundautopsy.data.fidelity_series_fee_parser import (
    _cache_clean_text,
    _cache_ticker_accession,
    _clean_html,
    _extract_registrant_name,
    _find_fund_section,
    _header_has_ticker,
    _is_fidelity_registrant,
    _is_fidelity_series_fund,
    _normalize_value,
    _parse_fidelity_section,
)


# ---------------------------------------------------------------------------
# Fixture: a minimal Fidelity Investment Trust 485BPOS SGML header

_SGML_HEADER = """<SEC-HEADER>
ACCESSION NUMBER: 0000315700-26-000001
COMPANY CONFORMED NAME: FIDELITY INVESTMENT TRUST
<SERIES-AND-CLASSES-CONTRACTS-DATA>
<EXISTING-SERIES-AND-CLASSES-CONTRACTS>
<SERIES>
<SERIES-ID>S000050772
<SERIES-NAME>Fidelity Series Large Cap Growth Index Fund
<CLASS-CONTRACT>
<CLASS-CONTRACT-ID>C000160197
<CLASS-CONTRACT-NAME>Fidelity Series Large Cap Growth Index Fund
<CLASS-CONTRACT-TICKER-SYMBOL>FSSJX
</CLASS-CONTRACT>
</SERIES>
<SERIES>
<SERIES-ID>S000050770
<SERIES-NAME>Fidelity Series Total Market Index Fund
<CLASS-CONTRACT>
<CLASS-CONTRACT-ID>C000160195
<CLASS-CONTRACT-NAME>Fidelity Series Total Market Index Fund
<CLASS-CONTRACT-TICKER-SYMBOL>FSTSX
</CLASS-CONTRACT>
</SERIES>
</EXISTING-SERIES-AND-CLASSES-CONTRACTS>
</SERIES-AND-CLASSES-CONTRACTS-DATA>
</SEC-HEADER>"""


class _FakeHeader:
    def __init__(self, text):
        self.text = text


class _FakeFiling:
    def __init__(self, header_text):
        self.header = _FakeHeader(header_text)


# ---------------------------------------------------------------------------
# SGML header parsing

def test_extract_registrant_name_returns_fidelity_investment_trust():
    filing = _FakeFiling(_SGML_HEADER)
    assert _extract_registrant_name(filing) == "FIDELITY INVESTMENT TRUST"


def test_extract_registrant_name_returns_none_for_empty_header():
    assert _extract_registrant_name(_FakeFiling("")) is None


def test_header_has_ticker_matches_canonical_ticker():
    filing = _FakeFiling(_SGML_HEADER)
    assert _header_has_ticker(filing, "FSSJX") is True
    assert _header_has_ticker(filing, "FSTSX") is True


def test_header_has_ticker_rejects_non_matching_ticker():
    filing = _FakeFiling(_SGML_HEADER)
    # FFFHX is a Freedom fund, not in this Series trust's SGML header.
    assert _header_has_ticker(filing, "FFFHX") is False


def test_header_has_ticker_respects_word_boundary():
    # A header with FSSJXABC should not match FSSJX.
    header = _SGML_HEADER.replace(">FSSJX\n", ">FSSJXABC\n")
    filing = _FakeFiling(header)
    assert _header_has_ticker(filing, "FSSJX") is False


def test_header_has_ticker_returns_false_for_missing_header():
    assert _header_has_ticker(_FakeFiling(""), "FSSJX") is False


# ---------------------------------------------------------------------------
# Detection

def test_is_fidelity_registrant_matches_investment_trust():
    assert _is_fidelity_registrant("FIDELITY INVESTMENT TRUST") is True


def test_is_fidelity_registrant_matches_select_portfolios():
    assert _is_fidelity_registrant("FIDELITY SELECT PORTFOLIOS") is True


def test_is_fidelity_registrant_matches_concord_street_trust():
    assert _is_fidelity_registrant("FIDELITY CONCORD STREET TRUST") is True


def test_is_fidelity_registrant_rejects_non_fidelity_families():
    assert _is_fidelity_registrant("VANGUARD INDEX FUNDS") is False
    assert _is_fidelity_registrant("AMERICAN FUNDS MORTGAGE FUND") is False
    assert _is_fidelity_registrant(None) is False
    assert _is_fidelity_registrant("") is False


def test_is_fidelity_series_fund_matches_series_prefix():
    assert _is_fidelity_series_fund("Fidelity Series Large Cap Growth Index Fund") is True
    assert _is_fidelity_series_fund("Fidelity Series Total Market Index Fund") is True
    # Case-insensitive.
    assert _is_fidelity_series_fund("fidelity series emerging markets") is True


def test_is_fidelity_series_fund_rejects_non_series_fidelity_funds():
    # Freedom target-date funds, Advisor classes, Select sector funds all
    # have standalone 497Ks and must fall through to the 497K pipeline.
    assert _is_fidelity_series_fund("Fidelity Freedom 2050 Fund") is False
    assert _is_fidelity_series_fund("Fidelity Advisor Growth Fund") is False
    assert _is_fidelity_series_fund("Fidelity Select Semiconductors Portfolio") is False
    assert _is_fidelity_series_fund("Fidelity Contrafund") is False


def test_is_fidelity_series_fund_rejects_empty_and_none():
    assert _is_fidelity_series_fund("") is False
    assert _is_fidelity_series_fund(None) is False


# ---------------------------------------------------------------------------
# HTML cleanup

def test_clean_html_strips_tags_and_entities():
    html = (
        "<table><tr><td>Management&nbsp;fee</td>"
        "<td>0.00&#160;%</td></tr></table>"
    )
    text = _clean_html(html)
    assert "<" not in text
    assert "&nbsp;" not in text
    assert "&#160;" not in text
    assert "Management fee" in text
    assert "0.00" in text


def test_clean_html_replaces_trademark_entities():
    html = "<p>Fidelity&#174; Series&reg;</p>"
    text = _clean_html(html)
    assert "(r)" in text
    assert "&#174;" not in text
    assert "&reg;" not in text


def test_clean_html_collapses_whitespace():
    html = "<p>Management\n\n fee     0.00</p>"
    text = _clean_html(html)
    assert "  " not in text
    assert "\n" not in text


# ---------------------------------------------------------------------------
# Value normalization

def test_normalize_value_converts_none_token_to_zero():
    # "None" on a 12b-1 line means the fee does not exist -> 0.0.
    assert _normalize_value("None") == 0.0
    assert _normalize_value("none") == 0.0
    assert _normalize_value("NONE") == 0.0


def test_normalize_value_parses_numeric_string():
    assert _normalize_value("0.00") == 0.0
    assert _normalize_value("0.01") == 0.01
    assert _normalize_value("0.12") == 0.12


def test_normalize_value_returns_none_for_unparseable():
    assert _normalize_value(None) is None
    assert _normalize_value("--") is None
    assert _normalize_value("n/a") is None


# ---------------------------------------------------------------------------
# Section location

# A synthetic two-fund omnibus slice in the shape the parser sees after
# `_clean_html`. Each fund's section begins with "Fund Summary Fund:"
# followed by the series name. FSSJX has the registered-trademark "(r)",
# FSTSX does not, to exercise the flexible-trademark matcher.
_OMNIBUS_TEXT = (
    "Fund Summary Fund: Fidelity(r) Series Large Cap Growth Index Fund "
    "Investment Objective The fund seeks to provide investment results "
    "that correspond to the total return of stocks of large "
    "capitalization United States companies. "
    "Fee Table "
    "Management fee 0.00 % "
    "Distribution and/or Service (12b-1) fees None "
    "Other expenses 0.01 % "
    "Total annual operating expenses 0.01 % "
    "During the most recent fiscal year, the fund's portfolio turnover "
    "rate was 15.00 % of the average value of its portfolio. "
    "Fund Summary Fund: Fidelity Series Total Market Index Fund "
    "Fee Table "
    "Management fee 0.00 % "
    "Distribution and/or Service (12b-1) fees None "
    "Other expenses 0.02 % "
    "Total annual operating expenses 0.02 % "
    "During the most recent fiscal year, the fund's portfolio turnover "
    "rate was 7.00 % of the average value of its portfolio."
)


def test_find_fund_section_locates_fssjx_with_trademark():
    section = _find_fund_section(
        _OMNIBUS_TEXT, "Fidelity Series Large Cap Growth Index Fund"
    )
    assert section is not None
    assert "Large Cap Growth" in section
    # Must stop at the next fund marker; FSTSX's Other expenses (0.02)
    # must not leak into FSSJX's section.
    assert "Other expenses 0.01" in section
    assert "Other expenses 0.02" not in section


def test_find_fund_section_locates_fstsx_without_trademark():
    section = _find_fund_section(
        _OMNIBUS_TEXT, "Fidelity Series Total Market Index Fund"
    )
    assert section is not None
    assert "Total Market" in section
    assert "Other expenses 0.02" in section


def test_find_fund_section_case_insensitive():
    section = _find_fund_section(
        _OMNIBUS_TEXT, "fidelity series large cap growth index fund"
    )
    assert section is not None


def test_find_fund_section_returns_none_for_missing_series():
    section = _find_fund_section(
        _OMNIBUS_TEXT, "Fidelity Series Nonexistent Fund"
    )
    assert section is None


def test_find_fund_section_bounded_by_five_thousand_chars():
    # A single-fund omnibus has no next-fund marker, so the cap kicks in.
    single = (
        "Fund Summary Fund: Fidelity Series Only Fund "
        "Management fee 0.00 % "
        "Distribution and/or Service (12b-1) fees None "
        "Other expenses 0.03 % "
        "Total annual operating expenses 0.03 % "
        + ("padding " * 2000)
    )
    section = _find_fund_section(single, "Fidelity Series Only Fund")
    assert section is not None
    assert len(section) <= 5000


# ---------------------------------------------------------------------------
# Fee-section parsing

def test_parse_fidelity_section_extracts_all_four_rows():
    section = (
        "Fund Summary Fund: Fidelity(r) Series Example "
        "Management fee 0.00 % "
        "Distribution and/or Service (12b-1) fees None "
        "Other expenses 0.01 % "
        "Total annual operating expenses 0.01 %"
    )
    parsed = _parse_fidelity_section(section)
    assert parsed is not None
    assert parsed["management_fee"] == 0.0
    assert parsed["twelve_b1_fee"] == 0.0  # "None" -> 0.0
    assert parsed["other_expenses"] == 0.01
    assert parsed["total_annual_expenses"] == 0.01


def test_parse_fidelity_section_extracts_portfolio_turnover():
    section = (
        "Fund Summary Fund: Fidelity Series Example "
        "Management fee 0.00 % "
        "Distribution and/or Service (12b-1) fees None "
        "Other expenses 0.01 % "
        "Total annual operating expenses 0.01 % "
        "During the most recent fiscal year, the fund's portfolio "
        "turnover rate was 42.00 % of the average value"
    )
    parsed = _parse_fidelity_section(section)
    assert parsed is not None
    assert parsed["portfolio_turnover"] == 42.00


def test_parse_fidelity_section_extracts_fee_waiver_and_net():
    section = (
        "Fund Summary Fund: Fidelity Series Example "
        "Management fee 0.45 % "
        "Distribution and/or Service (12b-1) fees None "
        "Other expenses 0.10 % "
        "Total annual operating expenses 0.55 % "
        "Fee waiver and/or expense reimbursement 0.10 % "
        "Total annual operating expenses after fee waivers 0.45 %"
    )
    parsed = _parse_fidelity_section(section)
    assert parsed is not None
    assert parsed["fee_waiver"] == 0.10
    assert parsed["net_expenses"] == 0.45


def test_parse_fidelity_section_returns_none_without_management_fee():
    section = "Fund Summary Fund: Fidelity Series Example " \
              "Other expenses 0.01 % " \
              "Total annual operating expenses 0.01 %"
    assert _parse_fidelity_section(section) is None


def test_parse_fidelity_section_returns_none_without_total_expenses():
    section = "Fund Summary Fund: Fidelity Series Example " \
              "Management fee 0.00 % " \
              "Other expenses 0.01 %"
    assert _parse_fidelity_section(section) is None


def test_parse_fidelity_section_handles_fund_variant_wording():
    # The "Total annual fund operating expenses" variant appears in some
    # filings; the parser must accept both.
    section = (
        "Fund Summary Fund: Fidelity Series Example "
        "Management fee 0.00 % "
        "Distribution and/or Service (12b-1) fees None "
        "Other expenses 0.01 % "
        "Total annual fund operating expenses 0.01 %"
    )
    parsed = _parse_fidelity_section(section)
    assert parsed is not None
    assert parsed["total_annual_expenses"] == 0.01


# ---------------------------------------------------------------------------
# Caches

def test_cache_clean_text_evicts_in_insertion_order():
    # Clear module-level state before poking at it, restore after.
    saved = dict(fsfp._CLEAN_TEXT_CACHE)
    fsfp._CLEAN_TEXT_CACHE.clear()
    try:
        for i in range(fsfp._CLEAN_TEXT_CACHE_MAX + 1):
            _cache_clean_text(f"acc-{i}", f"text-{i}")
        # First entry must have been evicted.
        assert "acc-0" not in fsfp._CLEAN_TEXT_CACHE
        assert f"acc-{fsfp._CLEAN_TEXT_CACHE_MAX}" in fsfp._CLEAN_TEXT_CACHE
    finally:
        fsfp._CLEAN_TEXT_CACHE.clear()
        fsfp._CLEAN_TEXT_CACHE.update(saved)


def test_cache_clean_text_is_idempotent_on_repeat_key():
    saved = dict(fsfp._CLEAN_TEXT_CACHE)
    fsfp._CLEAN_TEXT_CACHE.clear()
    try:
        _cache_clean_text("acc-x", "first")
        _cache_clean_text("acc-x", "second")
        # First write wins; repeat is a no-op so the eviction counter is
        # not disturbed by a caller that checks then re-writes.
        assert fsfp._CLEAN_TEXT_CACHE["acc-x"] == "first"
    finally:
        fsfp._CLEAN_TEXT_CACHE.clear()
        fsfp._CLEAN_TEXT_CACHE.update(saved)


def test_cache_ticker_accession_evicts_in_insertion_order():
    saved = dict(fsfp._TICKER_ACCESSION_CACHE)
    fsfp._TICKER_ACCESSION_CACHE.clear()
    try:
        for i in range(fsfp._TICKER_ACCESSION_CACHE_MAX + 1):
            _cache_ticker_accession(f"TKR{i}", f"acc-{i}")
        assert "TKR0" not in fsfp._TICKER_ACCESSION_CACHE
        assert f"TKR{fsfp._TICKER_ACCESSION_CACHE_MAX}" in fsfp._TICKER_ACCESSION_CACHE
    finally:
        fsfp._TICKER_ACCESSION_CACHE.clear()
        fsfp._TICKER_ACCESSION_CACHE.update(saved)


def test_cache_ticker_fees_evicts_in_insertion_order():
    saved = dict(fsfp._TICKER_FEES_CACHE)
    fsfp._TICKER_FEES_CACHE.clear()
    try:
        for i in range(fsfp._TICKER_FEES_CACHE_MAX + 1):
            fsfp._cache_ticker_fees(f"TKR{i}", {"total_annual_expenses": i * 0.01})
        assert "TKR0" not in fsfp._TICKER_FEES_CACHE
        assert f"TKR{fsfp._TICKER_FEES_CACHE_MAX}" in fsfp._TICKER_FEES_CACHE
    finally:
        fsfp._TICKER_FEES_CACHE.clear()
        fsfp._TICKER_FEES_CACHE.update(saved)


def test_cache_ticker_fees_is_idempotent_on_repeat_key():
    saved = dict(fsfp._TICKER_FEES_CACHE)
    fsfp._TICKER_FEES_CACHE.clear()
    try:
        fsfp._cache_ticker_fees("FSSJX", {"total_annual_expenses": 0.01})
        fsfp._cache_ticker_fees("FSSJX", {"total_annual_expenses": 0.99})
        # First write wins.
        assert fsfp._TICKER_FEES_CACHE["FSSJX"]["total_annual_expenses"] == 0.01
    finally:
        fsfp._TICKER_FEES_CACHE.clear()
        fsfp._TICKER_FEES_CACHE.update(saved)


def test_try_fidelity_series_fees_negative_cache_short_circuits_find_fund():
    """When a prior call negative-cached a ticker, subsequent calls must
    return None without invoking edgar.find_fund.

    This is the load-bearing optimization that lets a fund-of-funds with
    many non-Fidelity-Series underlyings avoid 30+ redundant find_fund
    calls during a single decomposition.
    """
    saved = dict(fsfp._TICKER_FEES_CACHE)
    fsfp._TICKER_FEES_CACHE.clear()
    try:
        fsfp._cache_ticker_fees("VFIAX", {"__negative__": True})

        # Poison edgar.find_fund so any real call would raise — if the
        # cache short-circuit fails, the test fails loudly.
        import edgar

        called = {"count": 0}

        def _boom(*_args, **_kwargs):
            called["count"] += 1
            raise RuntimeError("find_fund should not be called")

        original = edgar.find_fund
        edgar.find_fund = _boom
        try:
            result = fsfp.try_fidelity_series_fees("VFIAX")
        finally:
            edgar.find_fund = original

        assert result is None
        assert called["count"] == 0
    finally:
        fsfp._TICKER_FEES_CACHE.clear()
        fsfp._TICKER_FEES_CACHE.update(saved)


def test_try_fidelity_series_fees_positive_cache_rehydrates_dataclass():
    """A cached positive result must rebuild a ProspectusFees without
    calling edgar.find_fund."""
    from fundautopsy.data.prospectus import ProspectusFees

    saved = dict(fsfp._TICKER_FEES_CACHE)
    fsfp._TICKER_FEES_CACHE.clear()
    try:
        fsfp._cache_ticker_fees(
            "FSSJX",
            {
                "class_name": "Fidelity Series Large Cap Growth Index Fund",
                "total_annual_expenses": 0.01,
                "net_expenses": 0.01,
                "management_fee": 0.00,
                "twelve_b1_fee": 0.00,
                "other_expenses": 0.01,
                "fee_waiver": None,
                "portfolio_turnover": 15.00,
            },
        )
        import edgar

        def _boom(*_args, **_kwargs):
            raise RuntimeError("find_fund should not be called")

        original = edgar.find_fund
        edgar.find_fund = _boom
        try:
            result = fsfp.try_fidelity_series_fees("FSSJX")
        finally:
            edgar.find_fund = original

        assert isinstance(result, ProspectusFees)
        assert result.ticker == "FSSJX"
        assert result.total_annual_expenses == 0.01
        assert result.other_expenses == 0.01
        assert result.portfolio_turnover == 15.00
    finally:
        fsfp._TICKER_FEES_CACHE.clear()
        fsfp._TICKER_FEES_CACHE.update(saved)
