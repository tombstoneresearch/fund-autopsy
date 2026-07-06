"""Tests for the resolve_ticker in-memory TTL cache.

Covers: cache hit/miss identity, success-vs-miss TTL branching,
explicit-clear behavior, and the guarantee that the cached value
survives stringly-equal across calls.
"""
from __future__ import annotations

import time

import pytest

from fundautopsy.data.edgar import (
    MutualFundIdentifier,
    _RESOLVE_CACHE,
    _RESOLVE_CACHE_TTL_HIT_SEC,
    _RESOLVE_CACHE_TTL_MISS_SEC,
    _resolve_cache_get,
    _resolve_cache_put,
    clear_resolve_cache,
)


def test_cache_clear_empties_state():
    _resolve_cache_put("FAKE", MutualFundIdentifier(
        ticker="FAKE", cik=1, series_id="S000000001", class_id="C000000001"
    ))
    assert "FAKE" in _RESOLVE_CACHE
    clear_resolve_cache()
    assert _RESOLVE_CACHE == {}


def test_cache_hit_returns_cached_value():
    clear_resolve_cache()
    mfid = MutualFundIdentifier(
        ticker="FCNTX", cik=24238, series_id="S000006037", class_id="C000001234"
    )
    _resolve_cache_put("FCNTX", mfid)
    result = _resolve_cache_get("FCNTX")
    assert result is not None
    value, hit = result
    assert value == mfid
    assert hit is True


def test_cache_miss_cached_separately_from_success():
    clear_resolve_cache()
    _resolve_cache_put("BOGUS", None)
    result = _resolve_cache_get("BOGUS")
    assert result is not None
    value, hit = result
    assert value is None  # negative cache entry


def test_expired_success_entry_returns_none():
    clear_resolve_cache()
    # Stuff the cache with an entry whose timestamp is one TTL + 1 ago
    mfid = MutualFundIdentifier(
        ticker="OLD", cik=1, series_id="S000000001", class_id="C000000001"
    )
    _RESOLVE_CACHE["OLD"] = (mfid, time.time() - _RESOLVE_CACHE_TTL_HIT_SEC - 1)
    assert _resolve_cache_get("OLD") is None


def test_expired_negative_entry_returns_none():
    clear_resolve_cache()
    _RESOLVE_CACHE["EXPIRED_NEG"] = (
        None, time.time() - _RESOLVE_CACHE_TTL_MISS_SEC - 1
    )
    assert _resolve_cache_get("EXPIRED_NEG") is None


def test_negative_entry_still_fresh_returns_none_value():
    clear_resolve_cache()
    _RESOLVE_CACHE["FRESH_NEG"] = (None, time.time())
    result = _resolve_cache_get("FRESH_NEG")
    assert result is not None
    value, hit = result
    assert value is None


def test_nonexistent_key_returns_none():
    clear_resolve_cache()
    assert _resolve_cache_get("NEVERHEARDOFIT") is None


def test_ttl_constants_are_sensible():
    # Success TTL should be longer than miss TTL so new listings
    # get a chance to resolve on the next hour rather than waiting
    # 24 hours.
    assert _RESOLVE_CACHE_TTL_HIT_SEC > _RESOLVE_CACHE_TTL_MISS_SEC
    # Both should be non-zero and positive
    assert _RESOLVE_CACHE_TTL_HIT_SEC > 0
    assert _RESOLVE_CACHE_TTL_MISS_SEC > 0
