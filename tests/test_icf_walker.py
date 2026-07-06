"""Tests for the Investment Company Act filings walker.

Exercises the pure-text helpers in `fundautopsy.data.icf_walker`
without hitting EDGAR. The `resolve_ticker_via_walker` public entry
point is covered via the `resolve_ticker` integration path, which is
gated behind a live-EDGAR session.

The motivating case is BlackRock LifePath K-class tickers that are
registered in 485BPOS filings before SEC's daily
`company_tickers_mf.json` index catches up. The walker reads each
filing's SGML header for a `<CLASS-CONTRACT-TICKER-SYMBOL>` match,
then lifts the adjacent `<CLASS-CONTRACT-ID>` and enclosing
`<SERIES-ID>` values.
"""

from __future__ import annotations

from fundautopsy.data import icf_walker
from fundautopsy.data.icf_walker import (
    _CACHE_SENTINEL,
    _MAX_CANDIDATE_CIKS,
    _MAX_FILINGS_PER_TRUST,
    _cache_resolution,
    _cached_resolution,
    _iter_header_tokens,
    extract_cik_from_header,
    filter_icf_accessions,
    find_class_in_header,
    parse_candidate_ciks,
)


# ---------------------------------------------------------------------------
# Fixture: a minimal BlackRock Funds III 485BPOS SGML header listing two
# LifePath series, one with a K-class ticker. Real headers are ~30-60 KB
# but the walker only reads through </SEC-HEADER>, so this shape is
# representative of the parsing surface.

_BLACKROCK_SGML_HEADER = """<SEC-HEADER>
ACCESSION NUMBER: 0001193125-26-012345
CONFORMED SUBMISSION TYPE: 485BPOS
COMPANY CONFORMED NAME: BLACKROCK FUNDS III
CENTRAL INDEX KEY: 0001013761
<SERIES-AND-CLASSES-CONTRACTS-DATA>
<EXISTING-SERIES-AND-CLASSES-CONTRACTS>
<SERIES>
<SERIES-ID>S000050001
<SERIES-NAME>BlackRock LifePath Index Retirement Fund
<CLASS-CONTRACT>
<CLASS-CONTRACT-ID>C000160001
<CLASS-CONTRACT-NAME>BlackRock LifePath Index Retirement Fund Investor A
<CLASS-CONTRACT-TICKER-SYMBOL>LIRAX
</CLASS-CONTRACT>
<CLASS-CONTRACT>
<CLASS-CONTRACT-ID>C000160002
<CLASS-CONTRACT-NAME>BlackRock LifePath Index Retirement Fund Class K
<CLASS-CONTRACT-TICKER-SYMBOL>LIRKX
</CLASS-CONTRACT>
</SERIES>
<SERIES>
<SERIES-ID>S000050002
<SERIES-NAME>BlackRock LifePath Index 2065 Fund
<CLASS-CONTRACT>
<CLASS-CONTRACT-ID>C000160010
<CLASS-CONTRACT-NAME>BlackRock LifePath Index 2065 Fund Investor A
<CLASS-CONTRACT-TICKER-SYMBOL>LIPAX
</CLASS-CONTRACT>
<CLASS-CONTRACT>
<CLASS-CONTRACT-ID>C000160011
<CLASS-CONTRACT-NAME>BlackRock LifePath Index 2065 Fund Class K
<CLASS-CONTRACT-TICKER-SYMBOL>LIPSX
</CLASS-CONTRACT>
</SERIES>
</EXISTING-SERIES-AND-CLASSES-CONTRACTS>
</SERIES-AND-CLASSES-CONTRACTS-DATA>
</SEC-HEADER>
"""


# ---------------------------------------------------------------------------
# find_class_in_header

def test_find_class_in_header_returns_series_and_class_for_k_class_ticker():
    hit = find_class_in_header(_BLACKROCK_SGML_HEADER, "LIPSX")
    assert hit == ("S000050002", "C000160011")


def test_find_class_in_header_is_case_insensitive():
    hit = find_class_in_header(_BLACKROCK_SGML_HEADER, "lipsx")
    assert hit == ("S000050002", "C000160011")


def test_find_class_in_header_picks_correct_class_within_series():
    # LIRKX is the second class in the Retirement series; the walker
    # must not leak the first class's C000160001 into the result.
    hit = find_class_in_header(_BLACKROCK_SGML_HEADER, "LIRKX")
    assert hit == ("S000050001", "C000160002")


def test_find_class_in_header_picks_first_class_within_series():
    hit = find_class_in_header(_BLACKROCK_SGML_HEADER, "LIRAX")
    assert hit == ("S000050001", "C000160001")


def test_find_class_in_header_ticker_in_second_series():
    # Walker must not freeze on the first SERIES-ID after seeing the
    # Retirement block — the scope has to shift to the LifePath 2065
    # series before LIPAX / LIPSX are matched.
    hit = find_class_in_header(_BLACKROCK_SGML_HEADER, "LIPAX")
    assert hit == ("S000050002", "C000160010")


def test_find_class_in_header_missing_ticker_returns_none():
    assert find_class_in_header(_BLACKROCK_SGML_HEADER, "ZZZZZ") is None


def test_find_class_in_header_empty_inputs():
    assert find_class_in_header("", "LIPSX") is None
    assert find_class_in_header(_BLACKROCK_SGML_HEADER, "") is None


def test_find_class_in_header_ignores_orphan_ticker_without_series_scope():
    # A CLASS-CONTRACT-TICKER-SYMBOL that appears before any SERIES-ID
    # has no enclosing series and must not resolve. The walker returning
    # a match here would silently attribute a class to the wrong trust.
    orphan = (
        "<CLASS-CONTRACT-TICKER-SYMBOL>NOPE\n"
        "<SERIES-ID>S123\n"
        "<CLASS-CONTRACT-ID>C456\n"
        "<CLASS-CONTRACT-TICKER-SYMBOL>YESX\n"
    )
    assert find_class_in_header(orphan, "NOPE") is None
    assert find_class_in_header(orphan, "YESX") == ("S123", "C456")


def test_find_class_in_header_resets_class_scope_across_series():
    # Class-id scope MUST reset when a new SERIES-ID opens. Otherwise a
    # ticker in series B would be mistakenly paired with the last
    # class-id seen in series A.
    header = (
        "<SERIES-ID>S001\n"
        "<CLASS-CONTRACT-ID>C001\n"
        "<CLASS-CONTRACT-TICKER-SYMBOL>AAAX\n"
        "<SERIES-ID>S002\n"
        # No class-id declared for this series — ticker should miss.
        "<CLASS-CONTRACT-TICKER-SYMBOL>BBBX\n"
    )
    assert find_class_in_header(header, "AAAX") == ("S001", "C001")
    assert find_class_in_header(header, "BBBX") is None


# ---------------------------------------------------------------------------
# _iter_header_tokens

def test_iter_header_tokens_preserves_document_order():
    tokens = list(_iter_header_tokens(_BLACKROCK_SGML_HEADER))
    # The LIRAX class line must appear before the LIRKX class line.
    ticker_order = [v for k, v in tokens if k == "ticker"]
    assert ticker_order == ["LIRAX", "LIRKX", "LIPAX", "LIPSX"]
    series_order = [v for k, v in tokens if k == "series"]
    assert series_order == ["S000050001", "S000050002"]


def test_iter_header_tokens_empty_header():
    assert list(_iter_header_tokens("")) == []


# ---------------------------------------------------------------------------
# extract_cik_from_header

def test_extract_cik_from_header_returns_registrant_cik():
    assert extract_cik_from_header(_BLACKROCK_SGML_HEADER) == 1013761


def test_extract_cik_from_header_strips_leading_zeros():
    header = "CENTRAL INDEX KEY: 0000315700"
    assert extract_cik_from_header(header) == 315700


def test_extract_cik_from_header_missing_returns_none():
    assert extract_cik_from_header("no cik here") is None


def test_extract_cik_from_header_empty_input():
    assert extract_cik_from_header("") is None


# ---------------------------------------------------------------------------
# parse_candidate_ciks

def test_parse_candidate_ciks_extracts_and_dedupes():
    body = {
        "hits": {
            "hits": [
                {"_source": {"ciks": ["0001013761"]}},
                {"_source": {"ciks": ["0001013761"]}},  # duplicate
                {"_source": {"ciks": ["0001316132"]}},
            ]
        }
    }
    assert parse_candidate_ciks(body) == [1013761, 1316132]


def test_parse_candidate_ciks_preserves_rank_order():
    body = {
        "hits": {
            "hits": [
                {"_source": {"ciks": ["9999999"]}},
                {"_source": {"ciks": ["1111111"]}},
                {"_source": {"ciks": ["2222222"]}},
            ]
        }
    }
    # EDGAR ranks by relevance; the walker walks them in that order, so
    # the return must preserve the rank.
    assert parse_candidate_ciks(body) == [9999999, 1111111, 2222222]


def test_parse_candidate_ciks_caps_at_max_candidates():
    body = {
        "hits": {
            "hits": [
                {"_source": {"ciks": [str(i)]}} for i in range(1, 20)
            ]
        }
    }
    result = parse_candidate_ciks(body)
    assert len(result) == _MAX_CANDIDATE_CIKS
    # The cap must be applied on rank, not randomly.
    assert result == list(range(1, _MAX_CANDIDATE_CIKS + 1))


def test_parse_candidate_ciks_skips_malformed_rows():
    body = {
        "hits": {
            "hits": [
                {"_source": {"ciks": ["abc"]}},       # not numeric
                {"_source": {"ciks": [None]}},        # None
                {"_source": {"ciks": "not a list"}},  # wrong type
                "not a dict",                         # wrong type
                {"_source": {}},                      # no ciks
                {"_source": {"ciks": ["1013761"]}},   # valid
            ]
        }
    }
    assert parse_candidate_ciks(body) == [1013761]


def test_parse_candidate_ciks_empty_body():
    assert parse_candidate_ciks({}) == []
    assert parse_candidate_ciks({"hits": {}}) == []
    assert parse_candidate_ciks({"hits": {"hits": []}}) == []


def test_parse_candidate_ciks_non_dict_input():
    assert parse_candidate_ciks(None) == []
    assert parse_candidate_ciks("not a dict") == []
    assert parse_candidate_ciks([]) == []


def test_parse_candidate_ciks_ignores_zero_cik():
    body = {
        "hits": {
            "hits": [
                {"_source": {"ciks": ["0"]}},
                {"_source": {"ciks": ["0000000000"]}},
                {"_source": {"ciks": ["1013761"]}},
            ]
        }
    }
    assert parse_candidate_ciks(body) == [1013761]


# ---------------------------------------------------------------------------
# filter_icf_accessions

def test_filter_icf_accessions_returns_only_registration_forms():
    submissions = {
        "filings": {
            "recent": {
                "form": ["485BPOS", "N-PORT", "497K", "10-K", "N-CEN"],
                "accessionNumber": ["a1", "a2", "a3", "a4", "a5"],
            }
        }
    }
    result = filter_icf_accessions(submissions)
    assert result == [
        ("485BPOS", "a1"),
        ("497K", "a3"),
        ("N-CEN", "a5"),
    ]


def test_filter_icf_accessions_preserves_feed_order():
    # The submissions feed is date-descending. Filter must not reorder.
    submissions = {
        "filings": {
            "recent": {
                "form": ["497K", "485BPOS", "497K"],
                "accessionNumber": ["most-recent", "middle", "oldest"],
            }
        }
    }
    result = filter_icf_accessions(submissions)
    assert [acc for _, acc in result] == ["most-recent", "middle", "oldest"]


def test_filter_icf_accessions_respects_max_cap():
    many_forms = ["485BPOS"] * (_MAX_FILINGS_PER_TRUST + 10)
    many_accessions = [f"a{i}" for i in range(len(many_forms))]
    submissions = {
        "filings": {
            "recent": {
                "form": many_forms,
                "accessionNumber": many_accessions,
            }
        }
    }
    result = filter_icf_accessions(submissions)
    assert len(result) == _MAX_FILINGS_PER_TRUST


def test_filter_icf_accessions_handles_missing_feed():
    assert filter_icf_accessions({}) == []
    assert filter_icf_accessions({"filings": {}}) == []
    assert filter_icf_accessions({"filings": {"recent": {}}}) == []


def test_filter_icf_accessions_handles_mismatched_lengths():
    # Defensive — if EDGAR ever ships a truncated feed we must not
    # raise on a zip-length mismatch.
    submissions = {
        "filings": {
            "recent": {
                "form": ["485BPOS", "497K", "N-CEN"],
                "accessionNumber": ["a1", "a2"],  # shorter
            }
        }
    }
    result = filter_icf_accessions(submissions)
    assert result == [("485BPOS", "a1"), ("497K", "a2")]


def test_filter_icf_accessions_non_dict_input():
    assert filter_icf_accessions(None) == []
    assert filter_icf_accessions("nope") == []


# ---------------------------------------------------------------------------
# Resolution cache

def test_cache_resolution_roundtrip():
    # Clear to start from a known state.
    icf_walker._RESOLUTION_CACHE.clear()
    assert _cached_resolution("LIPSX") is _CACHE_SENTINEL

    from fundautopsy.data.edgar import MutualFundIdentifier
    hit = MutualFundIdentifier(
        ticker="LIPSX", cik=1013761,
        series_id="S000050002", class_id="C000160011",
    )
    _cache_resolution("LIPSX", hit)
    cached = _cached_resolution("LIPSX")
    assert cached is hit


def test_cache_resolution_is_case_insensitive():
    icf_walker._RESOLUTION_CACHE.clear()
    from fundautopsy.data.edgar import MutualFundIdentifier
    hit = MutualFundIdentifier(
        ticker="LIPSX", cik=1013761,
        series_id="S000050002", class_id="C000160011",
    )
    _cache_resolution("lipsx", hit)
    # Lookup must succeed regardless of input case.
    assert _cached_resolution("LIPSX") is hit
    assert _cached_resolution("Lipsx") is hit


def test_cache_resolution_records_definite_miss():
    icf_walker._RESOLUTION_CACHE.clear()
    _cache_resolution("ZZZZZ", None)
    # A cached None must be distinguishable from "not in cache" so
    # callers short-circuit on repeat lookups.
    assert _cached_resolution("ZZZZZ") is None
    assert _cached_resolution("NEVERHIT") is _CACHE_SENTINEL


# ---------------------------------------------------------------------------
# Real-world ticker shape sanity

def test_find_class_in_header_handles_dashed_tickers():
    # A few multi-class funds use hyphenated ticker punctuation
    # ("BRK-B"-style) that the regex must not truncate.
    header = (
        "<SERIES-ID>S999\n"
        "<CLASS-CONTRACT-ID>C999\n"
        "<CLASS-CONTRACT-TICKER-SYMBOL>TGT-K\n"
    )
    assert find_class_in_header(header, "TGT-K") == ("S999", "C999")


def test_find_class_in_header_tolerates_mixed_whitespace():
    # Real SGML uses inconsistent whitespace between the tag and the
    # value. The regex tolerates one or more spaces; this guards
    # against a future tightening that would break real filings.
    header = (
        "<SERIES-ID>    S001\n"
        "<CLASS-CONTRACT-ID>\tC001\n"
        "<CLASS-CONTRACT-TICKER-SYMBOL>   LIPSX\n"
    )
    assert find_class_in_header(header, "LIPSX") == ("S001", "C001")
