"""Unit tests for the N-14 merger/reorganization parser.

Covers the HTML-stripping helper, the target/acquirer regex patterns
against realistic filing prose, and the reorganization_type
classification logic. Uses fabricated minimal input to avoid network
dependencies.
"""
from __future__ import annotations

from datetime import date

from fundautopsy.data.n14_parser import (
    N14Filing,
    N14_FORM_CODES,
    _strip_html,
    classify_reorganization,
    _TARGET_CUES,
    _ACQUIRER_CUES,
)


def _make_filing(body_text: str = "", company: str = "Acme Trust") -> N14Filing:
    """Build an N14Filing with injected body text bypassing fetch."""
    f = N14Filing(
        accession_no="0001234567-25-000001",
        filing_date=date(2025, 3, 15),
        form_type="N-14",
        cik=1234567,
        company_name=company,
        primary_document="primary_doc.htm",
        filing_url="https://example.com",
    )
    return f


def test_form_codes_include_n14_variants():
    assert "N-14" in N14_FORM_CODES
    assert "N-14 8C" in N14_FORM_CODES
    assert "N-14AE" in N14_FORM_CODES


def test_strip_html_removes_tags():
    html = "<p>Hello <b>world</b></p>"
    assert _strip_html(html) == "Hello world"


def test_strip_html_collapses_whitespace():
    html = "<div>a\n\n  \t b</div>"
    assert _strip_html(html) == "a b"


def test_strip_html_decodes_common_entities():
    assert _strip_html("A&nbsp;&amp;&nbsp;B") == "A & B"


def test_target_cue_matches_will_be_reorganized():
    text = "The ABC Value Fund will be reorganized into the XYZ Growth Fund."
    hits = []
    for pat in _TARGET_CUES:
        for m in pat.finditer(text):
            if m.groups():
                hits.append(m.group(1).strip())
    assert any("ABC Value Fund" in h for h in hits), hits


def test_acquirer_cue_matches_reorganized_into():
    text = "The ABC Value Fund will be reorganized into the XYZ Growth Fund."
    hits = []
    for pat in _ACQUIRER_CUES:
        for m in pat.finditer(text):
            if m.groups():
                hits.append(m.group(1).strip())
    assert any("XYZ Growth Fund" in h for h in hits), hits


def test_target_cue_matches_acquired_fund_parenthetical():
    text = (
        "The Vanguard Windsor Fund (the \"Target Fund\") will combine "
        "with the Vanguard Windsor II Fund."
    )
    hits = []
    for pat in _TARGET_CUES:
        for m in pat.finditer(text):
            if m.groups():
                hits.append(m.group(1).strip())
    assert any("Vanguard Windsor Fund" in h for h in hits), hits


def test_acquirer_cue_matches_acquiring_fund_parenthetical():
    text = (
        "Shares will be issued by the Fidelity Contrafund "
        "(the \"Acquiring Fund\")."
    )
    hits = []
    for pat in _ACQUIRER_CUES:
        for m in pat.finditer(text):
            if m.groups():
                hits.append(m.group(1).strip())
    assert any("Fidelity Contrafund" in h for h in hits), hits


# ── classify_reorganization direct-call branches ─────────────────────
# Can't run the full function without mocking the fetch, so test the
# classification branches with a stub approach.


def test_classify_branches_when_body_empty(monkeypatch):
    import fundautopsy.data.n14_parser as m
    monkeypatch.setattr(m, "_fetch_filing_html", lambda filing, client=None: None)
    f = _make_filing()
    classify_reorganization(f)
    assert f.reorganization_type == "unknown"


def test_classify_same_complex_when_both_names_share_filer_root(monkeypatch):
    import fundautopsy.data.n14_parser as m
    html = (
        "<p>The Vanguard Windsor Fund will be reorganized into the "
        "Vanguard Windsor II Fund.</p>"
        "<p>The purpose of the reorganization is efficiency.</p>"
    )
    monkeypatch.setattr(m, "_fetch_filing_html", lambda filing, client=None: html)
    f = _make_filing(company="Vanguard Variable Insurance Funds")
    classify_reorganization(f)
    assert f.reorganization_type == "same-complex"
    assert any("Vanguard Windsor Fund" in t for t in f.target_fund_names)
    assert any("Vanguard Windsor II Fund" in a for a in f.acquiring_fund_names)


def test_classify_cross_complex_when_names_diverge(monkeypatch):
    import fundautopsy.data.n14_parser as m
    html = (
        "<p>The Acme Small Cap Fund will be reorganized into the "
        "Zenith Core Equity Fund.</p>"
    )
    monkeypatch.setattr(m, "_fetch_filing_html", lambda filing, client=None: html)
    f = _make_filing(company="Acme Trust")
    classify_reorganization(f)
    assert f.reorganization_type == "cross-complex"


def test_classify_falls_back_to_reorganization_when_only_snippet(monkeypatch):
    import fundautopsy.data.n14_parser as m
    # Prose triggers the summary-snippet regex but has no
    # extractable fund names in the target/acquirer patterns.
    html = (
        "<p>The proposed reorganization as described in this document "
        "concerns operational consolidation. No fund names.</p>"
    )
    monkeypatch.setattr(m, "_fetch_filing_html", lambda filing, client=None: html)
    f = _make_filing()
    classify_reorganization(f)
    # Should land on "reorganization" (body reviewed, snippet extracted)
    # rather than "unknown"
    assert f.reorganization_type == "reorganization"
    assert f.summary_snippet != ""
