"""Tests for the SEC series/class census resolver."""

from __future__ import annotations

import pytest

from fundautopsy.data import census as census_mod
from fundautopsy.data.census import (
    CensusVerdict,
    clear_census_cache,
    parse_census_csv,
    resolve_via_census,
)

_SAMPLE = """﻿Reporting File Number,CIK Number,Entity Name,Entity Org Type,Series ID,Series Name,Class ID,Class Name,Class Ticker,Address_1,Address_2,City,State,Zip Code
811-01234,0000893818,BlackRock Funds III,30,S000001111,LifePath Index 2040,C000002222,Class K,LIKKX,100 BELLEVUE PKWY,,WILMINGTON,DE,19809
811-05678,0000048200,Nassau Life Separate Account B,32,S000007561,Separate Account B,C000020626,PHOENIX LIFE B,,ONE AMERICAN ROW,,HARTFORD,CT,06102
811-09999,0000102909,Vanguard Index Funds,30,S000002839,500 Index Fund,C000012345,Admiral,VFIAX,PO BOX 2600,,VALLEY FORGE,PA,19482
"""


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_census_cache()
    yield
    clear_census_cache()


class TestParse:
    def test_parses_ticker_rows_and_skips_untickered(self) -> None:
        idx = parse_census_csv(_SAMPLE)
        assert idx["LIKKX"] == ("893818", "S000001111", "C000002222")
        assert idx["VFIAX"] == ("102909", "S000002839", "C000012345")
        assert len(idx) == 2  # separate-account row has no ticker

    def test_bom_and_leading_zero_handling(self) -> None:
        idx = parse_census_csv(_SAMPLE)
        assert all(not cik.startswith("0") for cik, _s, _c in idx.values())


class TestResolve:
    def _prime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            census_mod, "_download_census", lambda _client: _SAMPLE
        )

    def test_hit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._prime(monkeypatch)
        verdict, ident = resolve_via_census("likkx", client=None)  # type: ignore[arg-type]
        assert verdict is CensusVerdict.HIT
        assert ident is not None
        assert ident.cik == 893818
        assert ident.series_id == "S000001111"
        assert ident.class_id == "C000002222"

    def test_absent_is_authoritative(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._prime(monkeypatch)
        verdict, ident = resolve_via_census("LIPSX", client=None)  # type: ignore[arg-type]
        assert verdict is CensusVerdict.ABSENT
        assert ident is None

    def test_unavailable_when_download_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            census_mod, "_download_census", lambda _client: None
        )
        verdict, ident = resolve_via_census("VFIAX", client=None)  # type: ignore[arg-type]
        assert verdict is CensusVerdict.UNAVAILABLE
        assert ident is None

    def test_download_not_retried_after_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[int] = []

        def failing(_client):
            calls.append(1)
            return None

        monkeypatch.setattr(census_mod, "_download_census", failing)
        resolve_via_census("VFIAX", client=None)  # type: ignore[arg-type]
        resolve_via_census("AGTHX", client=None)  # type: ignore[arg-type]
        assert len(calls) == 1  # failure memoized for the process

    def test_index_loaded_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[int] = []

        def counting(_client):
            calls.append(1)
            return _SAMPLE

        monkeypatch.setattr(census_mod, "_download_census", counting)
        resolve_via_census("VFIAX", client=None)  # type: ignore[arg-type]
        resolve_via_census("LIKKX", client=None)  # type: ignore[arg-type]
        assert len(calls) == 1
