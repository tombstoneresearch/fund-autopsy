"""Ticker -> 497K filing resolution cache.

`find_filing_for_ticker` is the single slowest component in the analyze
pipeline because large registrant trusts (PIMCO Funds ~2,800 filings,
Fidelity Concord Street Trust ~340) force a walk through up to 50
filings, each of which calls `.obj()` — an HTML parse. Cold-path
latencies of 25-60 s were measured in the 2026-04-22 consumer stress
test for PIMIX, PIMGX, and similar umbrella-trust tickers.

SEC filings are immutable once filed and the (ticker -> 497K filing)
relationship for a given share class is stable across time except when
a new 497K is filed. That makes this a nearly-perfect caching target.

The cache stores, per uppercase ticker:

    {"accession": str, "class_id": str|None, "cached_at": iso_date}

On lookup, we scan the current filings list by the cheap
`accession_number` attribute. If the cached accession is present, we
return that filing without parsing any HTML. If absent or the cache
entry is older than CACHE_TTL_DAYS, we fall through to the full
search and refresh the cache on success.

This module is deliberately tolerant of I/O failures: if the cache
file is corrupted, missing, or unwritable, we log and continue
without the cache. Caching is an optimization, not a correctness
requirement.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Default cache file co-located with the existing EDGAR xml cache so ops
# only has one directory to manage.
DEFAULT_CACHE_FILE: Path = Path.home() / ".fundautopsy" / "cache" / "filing_lookup.json"

# Entries older than this are re-verified. 60 days is chosen so that any
# freshly-filed 497K (the usual annual amendment cadence) gets picked up
# within a reasonable window. Filings themselves are immutable, so the
# failure mode of a stale cache entry is "we served the previous-year
# 497K" — which on ER is often still correct and on other fields is the
# same data we would have returned last week. The cost of a cache miss
# is a single slow call.
CACHE_TTL_DAYS: int = 60

# Negative-result cache TTL. When a ticker's 497K cannot be found after
# an exhaustive scan (Fidelity Series building-block funds that file
# only in combined 485BPOS rather than standalone 497K are the known
# problem case), remember the miss briefly so that repeated resolver
# calls inside a single bottom-up decomposition do not each re-scan
# hundreds of filings. 7 days is short enough that a newly-filed 497K
# for a previously-missing ticker will be picked up on the next weekly
# autopilot run.
NEG_CACHE_TTL_DAYS: int = 7


class FilingLookupCache:
    """File-backed cache for the ticker -> accession-number mapping.

    Thread-safe; safe to instantiate once at module import and share
    across the FastAPI worker pool. All operations are guarded by an
    instance-level lock so concurrent `/api/analyze/{ticker}` requests
    do not corrupt the JSON file.
    """

    def __init__(
        self,
        cache_file: Path = DEFAULT_CACHE_FILE,
        ttl_days: int = CACHE_TTL_DAYS,
        enabled: bool = True,
    ) -> None:
        self.cache_file = cache_file
        self.ttl = timedelta(days=ttl_days)
        self.enabled = enabled
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        if self.enabled:
            self._load()

    # ---------- private I/O ----------

    def _load(self) -> None:
        try:
            if self.cache_file.exists():
                self._data = json.loads(self.cache_file.read_text())
            else:
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                self._data = {}
        except Exception as exc:
            logger.warning(
                "FilingLookupCache failed to load %s; starting empty: %s",
                self.cache_file, exc,
            )
            self._data = {}

    def _persist(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True))
            tmp.replace(self.cache_file)
        except Exception as exc:
            logger.warning(
                "FilingLookupCache failed to persist %s: %s",
                self.cache_file, exc,
            )

    # ---------- public API ----------

    def lookup(self, ticker: str) -> Optional[dict[str, Any]]:
        """Return the cached entry for `ticker` if present and fresh.

        Returns `None` on miss, expired, or any read failure. The cache
        is advisory — callers must be prepared to fall through to the
        slow path.

        Returns a sentinel `{"not_found": True}` entry when a prior
        exhaustive scan determined the ticker has no 497K available.
        Callers should treat this as an authoritative miss and skip
        the search rather than re-scan.
        """
        if not self.enabled:
            return None
        with self._lock:
            entry = self._data.get(ticker.upper())
            if entry is None:
                return None
            try:
                cached_at = datetime.fromisoformat(entry["cached_at"])
            except Exception:
                return None
            # Negative entries expire on the shorter TTL.
            if entry.get("not_found"):
                neg_ttl = timedelta(days=NEG_CACHE_TTL_DAYS)
                if datetime.now(timezone.utc) - cached_at > neg_ttl:
                    return None
                return dict(entry)
            if datetime.now(timezone.utc) - cached_at > self.ttl:
                return None
            return dict(entry)  # copy — never hand out internal state

    def store(
        self,
        ticker: str,
        accession: str,
        class_id: Optional[str] = None,
    ) -> None:
        """Record the successful (ticker -> accession) match.

        Overwrites any prior entry. Persists immediately so ephemeral
        worker restarts cannot lose the learning.
        """
        if not self.enabled:
            return
        with self._lock:
            self._data[ticker.upper()] = {
                "accession": accession,
                "class_id": class_id,
                "cached_at": datetime.now(timezone.utc).isoformat(),
            }
            self._persist()

    def store_not_found(self, ticker: str) -> None:
        """Record that `ticker` has no resolvable 497K in the current
        registrant (e.g., Fidelity Series building blocks that file
        only in combined 485BPOS). Expires on the short NEG_CACHE_TTL.
        """
        if not self.enabled:
            return
        with self._lock:
            self._data[ticker.upper()] = {
                "not_found": True,
                "cached_at": datetime.now(timezone.utc).isoformat(),
            }
            self._persist()

    def evict(self, ticker: str) -> None:
        """Remove the entry for `ticker`. Used when a cached accession
        no longer matches any filing in the current list (which usually
        means the trust has retired or renamed that filing)."""
        if not self.enabled:
            return
        with self._lock:
            self._data.pop(ticker.upper(), None)
            self._persist()

    def __len__(self) -> int:  # pragma: no cover
        return len(self._data)


# Singleton — the app instantiates this once at import.
_default_cache: Optional[FilingLookupCache] = None


def get_default_cache() -> FilingLookupCache:
    """Process-wide default cache. Lazily constructed."""
    global _default_cache
    if _default_cache is None:
        _default_cache = FilingLookupCache()
    return _default_cache
