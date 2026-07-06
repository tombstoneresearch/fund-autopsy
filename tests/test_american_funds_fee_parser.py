"""Tests for the American Funds 485BPOS fee-table parser.

These tests exercise the pure-text helpers in
`fundautopsy.data.american_funds_fee_parser` without hitting EDGAR.
The `try_american_funds_fees` public entry point is exercised through
`retrieve_prospectus_fees` integration tests that are gated behind a
network marker.
"""

from __future__ import annotations

from fundautopsy.data.american_funds_fee_parser import (
    _clean_html,
    _extract_sgml_class_map,
    _extract_registrant_name,
    _find_fee_blocks,
    _is_american_funds,
    _normalize_class_label,
    _parse_fee_block,
)


# ---------------------------------------------------------------------------
# Fixture: a minimal American Funds 485BPOS SGML header

_SGML_HEADER = """<SEC-HEADER>
ACCESSION NUMBER: 0000051931-26-000001
COMPANY CONFORMED NAME: AMERICAN FUNDS MORTGAGE FUND
<SERIES-AND-CLASSES-CONTRACTS-DATA>
<EXISTING-SERIES-AND-CLASSES-CONTRACTS>
<SERIES>
<SERIES-ID>S000029873
<SERIES-NAME>American Funds Mortgage Fund
<CLASS-CONTRACT>
<CLASS-CONTRACT-ID>C000092898
<CLASS-CONTRACT-NAME>Class R-1
<CLASS-CONTRACT-TICKER-SYMBOL>RMAAX
</CLASS-CONTRACT>
<CLASS-CONTRACT>
<CLASS-CONTRACT-ID>C000092903
<CLASS-CONTRACT-NAME>Class R-6
<CLASS-CONTRACT-TICKER-SYMBOL>RMAGX
</CLASS-CONTRACT>
<CLASS-CONTRACT>
<CLASS-CONTRACT-ID>C000092904
<CLASS-CONTRACT-NAME>Class 529-C
<CLASS-CONTRACT-TICKER-SYMBOL>CLACX
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

def test_extract_sgml_class_map_returns_ticker_indexed_dict():
    filing = _FakeFiling(_SGML_HEADER)
    m = _extract_sgml_class_map(filing)
    assert m["RMAGX"] == ("C000092903", "Class R-6")
    assert m["RMAAX"] == ("C000092898", "Class R-1")
    assert m["CLACX"] == ("C000092904", "Class 529-C")


def test_extract_sgml_class_map_handles_missing_header():
    class _NoHeader:
        @property
        def header(self):
            raise AttributeError("no header")

    assert _extract_sgml_class_map(_NoHeader()) == {}


def test_extract_registrant_name():
    filing = _FakeFiling(_SGML_HEADER)
    assert _extract_registrant_name(filing) == "AMERICAN FUNDS MORTGAGE FUND"


# ---------------------------------------------------------------------------
# Detection

def test_is_american_funds_by_registrant_name():
    assert _is_american_funds("AMERICAN FUNDS MORTGAGE FUND", {}) is True
    assert _is_american_funds("AMCAP FUND INC", {}) is True
    assert _is_american_funds("INTERMEDIATE BOND FUND OF AMERICA", {}) is True
    assert _is_american_funds("VANGUARD INDEX FUNDS", {}) is False


def test_is_american_funds_by_sgml_signature():
    # No name match, but SGML has Class R-6 + Class 529-C → must be AF.
    class_map = {
        "RMAGX": ("C1", "Class R-6"),
        "CLACX": ("C2", "Class 529-C"),
    }
    assert _is_american_funds(None, class_map) is True


def test_is_american_funds_signature_requires_both_r6_and_529():
    # R-6 alone isn't sufficient; several fund families have R-6.
    class_map = {"RMAGX": ("C1", "Class R-6")}
    assert _is_american_funds("SOME OTHER FAMILY", class_map) is False


# ---------------------------------------------------------------------------
# HTML cleanup

def test_clean_html_strips_tags_and_entities():
    html = (
        "<table><tr><td>Management&nbsp;fees</td>"
        "<td>0.25&#160;%</td></tr></table>"
    )
    text = _clean_html(html)
    assert "<" not in text
    assert "&nbsp;" not in text
    assert "&#160;" not in text
    assert "Management fees" in text
    assert "0.25" in text


def test_clean_html_handles_smart_quotes_and_dashes():
    html = "<p>&ldquo;Fee&rdquo; &mdash; see &lsquo;waiver&rsquo;</p>"
    text = _clean_html(html)
    assert "\"Fee\"" in text
    assert "--" in text
    assert "'waiver'" in text


def test_normalize_class_label_strips_class_prefix():
    assert _normalize_class_label("Class R-6") == "R-6"
    assert _normalize_class_label("Class A") == "A"
    assert _normalize_class_label("Class 529-C") == "529-C"
    assert _normalize_class_label("R-6") == "R-6"  # already normalized


# ---------------------------------------------------------------------------
# Fee-block discovery and parsing

# A synthetic fee-table block in the same shape American Funds renders: a
# space-separated class-label row followed by a labelled fee-rows grid.
_FEE_BLOCK = (
    "Share class: A C F-2 R-6 "
    "Management fees 0.25 0.24 0.24 0.22 "
    "Distribution and/or service (12b-1) fees 0.24 1.00 0.00 0.00 "
    "Other expenses 0.10 0.09 0.14 0.04 "
    "Total annual fund operating expenses 0.59 1.33 0.38 0.26"
)


def test_parse_fee_block_extracts_r6_column():
    parsed = _parse_fee_block(_FEE_BLOCK, "R-6")
    assert parsed is not None
    assert parsed["class_label"] == "R-6"
    assert parsed["n_classes"] == 4
    assert parsed["management_fee"] == 0.22
    assert parsed["twelve_b1_fee"] == 0.00
    assert parsed["other_expenses"] == 0.04
    assert parsed["total_annual_expenses"] == 0.26


def test_parse_fee_block_extracts_retail_column():
    parsed = _parse_fee_block(_FEE_BLOCK, "C")
    assert parsed is not None
    assert parsed["management_fee"] == 0.24
    assert parsed["twelve_b1_fee"] == 1.00
    assert parsed["other_expenses"] == 0.09
    assert parsed["total_annual_expenses"] == 1.33


def test_parse_fee_block_returns_none_for_missing_label():
    assert _parse_fee_block(_FEE_BLOCK, "Z") is None


def test_parse_fee_block_handles_none_token():
    block = (
        "Share class: A R-6 "
        "Management fees 0.25 0.22 "
        "Distribution and/or service (12b-1) fees 0.25 none "
        "Other expenses 0.10 0.04 "
        "Total annual fund operating expenses 0.60 0.26"
    )
    parsed = _parse_fee_block(block, "R-6")
    assert parsed is not None
    assert parsed["twelve_b1_fee"] == 0.0  # 'none' -> 0.0


def test_find_fee_blocks_requires_management_fees_in_header_window():
    # A Shareholder fees block that starts with "Share class:" but does
    # not contain "Management fees" in the 200-char header window should
    # be rejected. The subsequent real fee block should still be found.
    # The Shareholder block is intentionally long so the MF header of
    # the next block falls outside the header window.
    shareholder_padding = (
        "Maximum sales charge imposed on purchases as a percentage "
        "of offering price 5.75 none Maximum deferred sales charge none "
        "none Maximum sales charge imposed on reinvested dividends none "
        "none Redemption or exchange fees none none "
    )
    text = (
        "Share class: A R-6 " + shareholder_padding +
        "Share class: A R-6 "
        "Management fees 0.25 0.22 "
        "Distribution and/or service (12b-1) fees 0.25 0.00 "
        "Other expenses 0.10 0.04 "
        "Total annual fund operating expenses 0.60 0.26 "
        "End of document"
    )
    blocks = _find_fee_blocks(text)
    # Only the real fee block should be picked up
    assert len(blocks) == 1
    parsed = _parse_fee_block(blocks[0], "R-6")
    assert parsed is not None
    assert parsed["total_annual_expenses"] == 0.26


def test_find_fee_blocks_terminates_at_total_annual_expenses():
    # Trailing narrative text after the fee table should be trimmed off
    # so downstream regex searches do not stray into other fund data.
    text = (
        "Share class: A R-6 "
        "Management fees 0.25 0.22 "
        "Distribution and/or service (12b-1) fees 0.25 0.00 "
        "Other expenses 0.10 0.04 "
        "Total annual fund operating expenses 0.60 0.26 "
        "Example. Assume an investor invests $10,000..."
    )
    blocks = _find_fee_blocks(text)
    assert len(blocks) == 1
    assert "Example." not in blocks[0]
    assert "0.26" in blocks[0]
