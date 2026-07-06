"""Alternate Investment Company Act ticker-resolution walker.

Some share-class tickers appear in registered filings before SEC's
daily `company_tickers_mf.json` index catches up. The primary
`resolve_ticker()` path returns None for these tickers, which blocks
the analyze pipeline on funds that are otherwise in scope. The
motivating case is BlackRock LifePath Index K-class tickers (LIPSX
and siblings), which landed in the pipeline in 2026 before SEC
reindexed the MF universe, but the walker is deliberately
registrant-agnostic so the same fallback covers any newly-registered
share class whose ticker has not yet been published to the MF index.

Resolution proceeds in three steps:

1. **Seeded trust fast path.** Known registrant CIKs (BlackRock
   LifePath trusts, at the time of writing) are walked first. This
   is cheap, avoids hitting the full-text search, and handles the
   common case where a LifePath ticker was simply indexed late.

2. **Full-text search fallback.** If no seeded trust recognizes the
   ticker, EDGAR's `efts.sec.gov/LATEST/search-index` is queried for
   registration-statement filings containing the ticker as a
   quoted phrase. Candidate CIKs are pulled from the hits in rank
   order.

3. **SGML header confirmation.** For each candidate CIK, the walker
   downloads the recent-submissions feed, filters to Investment
   Company Act forms (485BPOS, 497K, N-CEN, N-1A), and reads each
   filing's SGML header for a
   `<CLASS-CONTRACT-TICKER-SYMBOL>TICKER</…>` hit. On a match, the
   adjacent `<CLASS-CONTRACT-ID>` and enclosing `<SERIES-ID>` are
   lifted out to assemble a `MutualFundIdentifier`.

Returns None when the ticker cannot be resolved. Callers should try
`resolve_ticker()` first and only fall here on a miss.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Iterable, Optional

import httpx

from fundautopsy.data.edgar import (
    EDGAR_ARCHIVES_URL,
    EDGAR_SUBMISSIONS_URL,
    MutualFundIdentifier,
    _request_with_retry,
    get_edgar_client,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration

# Forms that register share classes and therefore carry a
# CLASS-CONTRACT-TICKER-SYMBOL entry in their SGML header.
_ICF_FORMS: tuple[str, ...] = (
    "485BPOS", "485APOS", "497", "497K", "N-1A", "N-CEN",
)

# Full-text search endpoint. Returns JSON with hits keyed by CIK.
_EDGAR_FULL_TEXT_SEARCH_URL: str = "https://efts.sec.gov/LATEST/search-index"

# Known trust CIKs that house BlackRock LifePath Index series. Walking
# these first is much cheaper than a full-text search and catches the
# common case where a K-class ticker was simply indexed late. Each
# entry is a real trust CIK taken from BlackRock's LifePath filings as
# of 2026. New trusts can be appended without touching the rest of the
# walker; the list is consulted in order.
_SEEDED_BLACKROCK_LIFEPATH_CIKS: tuple[int, ...] = (
    893818,    # BlackRock Funds III — current LifePath Index Portfolios registrant,
               # housing K-class tickers (LIPSX, LIKKX, LIJKX, LINKX, etc.).
               # Confirmed 2026-04-22 via EDGAR full-text search for "BlackRock LifePath Index 2050".
    1398078,   # BlackRock Funds II — historical LifePath Active Retirement registrant.
    915092,    # Master Investment Portfolio — master-feeder structure some
               # LifePath feeder funds use. Included as a fallback search path.
)

# How many filings to scan per trust when hunting for the ticker. The
# recent-submissions feed is already ordered by date descending, so
# the target class's most recent filing is almost always in the top
# twenty. A small cap keeps SGML-header downloads bounded.
_MAX_FILINGS_PER_TRUST: int = 20

# How many candidate CIKs to consider from the full-text search. Most
# tickers surface under a single trust; a small bound keeps the walk
# from chasing stale EDGAR hits on defunct filings.
_MAX_CANDIDATE_CIKS: int = 5


# ---------------------------------------------------------------------------
# Pure-text helpers (exercised by unit tests without network)

# The SGML header embeds SERIES and CLASS-CONTRACT blocks in a fixed
# nesting order, one CLASS-CONTRACT under each SERIES. We walk the
# header linearly, track the most recently seen SERIES-ID, and return
# on the first CLASS-CONTRACT-TICKER-SYMBOL that matches the target
# ticker.
_SERIES_ID_RE = re.compile(r"<SERIES-ID>\s*(S\d+)\b", re.IGNORECASE)
_CLASS_ID_RE = re.compile(r"<CLASS-CONTRACT-ID>\s*(C\d+)\b", re.IGNORECASE)
_CLASS_TICKER_RE = re.compile(
    r"<CLASS-CONTRACT-TICKER-SYMBOL>\s*([A-Z0-9.\-]+)",
    re.IGNORECASE,
)
_CIK_RE = re.compile(r"CENTRAL INDEX KEY:\s*(\d+)", re.IGNORECASE)


def _iter_header_tokens(header: str) -> Iterable[tuple[str, str]]:
    """Yield (kind, value) for every SERIES-ID / CLASS-CONTRACT-ID /
    CLASS-CONTRACT-TICKER-SYMBOL match in document order.

    The three regexes are run once each, the matches are merged by
    start position, and the pairs are yielded in order. This single
    pass is cheaper than repeatedly scanning the header and also
    preserves the nesting the walker relies on.
    """
    matches: list[tuple[int, str, str]] = []
    for m in _SERIES_ID_RE.finditer(header):
        matches.append((m.start(), "series", m.group(1)))
    for m in _CLASS_ID_RE.finditer(header):
        matches.append((m.start(), "class_id", m.group(1)))
    for m in _CLASS_TICKER_RE.finditer(header):
        matches.append((m.start(), "ticker", m.group(1).upper()))
    matches.sort(key=lambda t: t[0])
    for _, kind, value in matches:
        yield kind, value


def find_class_in_header(
    header: str, ticker: str
) -> Optional[tuple[str, str]]:
    """Walk an SGML header and return (series_id, class_id) for the
    target ticker, or None if the ticker is not listed.

    The walker keeps the most recently seen series_id and class_id in
    scope and emits them the moment a matching ticker appears. This
    matches the fixed SERIES > CLASS-CONTRACT > TICKER nesting EDGAR
    uses in every Investment Company Act header we have seen.
    """
    if not header or not ticker:
        return None

    ticker_upper = ticker.upper()
    current_series: Optional[str] = None
    current_class: Optional[str] = None

    for kind, value in _iter_header_tokens(header):
        if kind == "series":
            current_series = value
            current_class = None  # reset when a new series block opens
        elif kind == "class_id":
            current_class = value
        elif kind == "ticker":
            if value == ticker_upper and current_series and current_class:
                return current_series, current_class

    return None


def extract_cik_from_header(header: str) -> Optional[int]:
    """Return the filer's CIK from an SGML header, or None.

    The header's first CENTRAL INDEX KEY is the filer — downstream
    blocks may repeat the CIK for each class owner, but the first
    hit is always the registrant's own CIK.
    """
    if not header:
        return None
    m = _CIK_RE.search(header)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def parse_candidate_ciks(search_body: dict) -> list[int]:
    """Return deduplicated CIKs from an EDGAR full-text search response.

    The endpoint returns a body of the shape
    ``{"hits": {"hits": [{"_source": {"ciks": ["0001013761", ...]}}]}}``.
    We walk hits in rank order and pull every CIK, keeping a seen-set
    so duplicate hits (common when a trust files multiple 485BPOSes
    for the same product line) do not fan the walk out unnecessarily.
    """
    if not isinstance(search_body, dict):
        return []
    hits_wrap = search_body.get("hits", {})
    if not isinstance(hits_wrap, dict):
        return []
    hits = hits_wrap.get("hits", [])
    if not isinstance(hits, list):
        return []

    seen: set[int] = set()
    ordered: list[int] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        source = hit.get("_source", {})
        if not isinstance(source, dict):
            continue
        raw_ciks = source.get("ciks") or []
        if not isinstance(raw_ciks, list):
            continue
        for raw in raw_ciks:
            try:
                cik_int = int(str(raw).lstrip("0") or "0")
            except (TypeError, ValueError):
                continue
            if cik_int <= 0 or cik_int in seen:
                continue
            seen.add(cik_int)
            ordered.append(cik_int)
            if len(ordered) >= _MAX_CANDIDATE_CIKS:
                return ordered
    return ordered


def filter_icf_accessions(submissions: dict) -> list[tuple[str, str]]:
    """Return (form, accession) pairs for every ICF form in the
    recent-submissions feed, capped at `_MAX_FILINGS_PER_TRUST`.

    The submissions feed lists filings in date-descending order, so
    the caller can walk the returned list linearly and break on the
    first hit without sorting.
    """
    if not isinstance(submissions, dict):
        return []
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", []) or []
    accessions = recent.get("accessionNumber", []) or []
    bound = min(len(forms), len(accessions))
    wanted = set(_ICF_FORMS)
    out: list[tuple[str, str]] = []
    for i in range(bound):
        form = forms[i]
        if form in wanted:
            out.append((form, accessions[i]))
            if len(out) >= _MAX_FILINGS_PER_TRUST:
                break
    return out


# ---------------------------------------------------------------------------
# Caches

# Resolved tickers are cached in-process so repeated lookups inside a
# single three-layer decomposition do not repeat the walk. Cache is
# negative-aware: a definite miss (ticker walked against every seeded
# trust AND the full-text search) is remembered as None so the next
# lookup short-circuits, but *transient* misses (network error, 5xx)
# are not cached.
_RESOLUTION_CACHE: dict[str, Optional[MutualFundIdentifier]] = {}
_RESOLUTION_CACHE_LOCK = threading.Lock()


def _cache_resolution(ticker: str, result: Optional[MutualFundIdentifier]) -> None:
    with _RESOLUTION_CACHE_LOCK:
        _RESOLUTION_CACHE[ticker.upper()] = result


def _cached_resolution(ticker: str) -> Optional[MutualFundIdentifier]:
    """Return a previously resolved identifier, or a sentinel.

    The two-level return is intentional: a literal `None` means
    "cache miss, go walk"; a cached definite-miss is tracked
    separately via the `_DEFINITE_MISS` sentinel.
    """
    with _RESOLUTION_CACHE_LOCK:
        return _RESOLUTION_CACHE.get(ticker.upper(), _CACHE_SENTINEL)


class _Sentinel:
    __slots__ = ()


_CACHE_SENTINEL = _Sentinel()


# ---------------------------------------------------------------------------
# Network helpers (thin wrappers; body parsing stays in pure helpers)

def _download_sgml_header(
    cik: int,
    accession_number: str,
    client: httpx.Client,
) -> Optional[str]:
    """Download the SGML header for a specific filing.

    Uses the full-submission `.txt` endpoint and returns only the
    leading `<SEC-HEADER>` block. We never read past the header
    boundary so the download stays small even on multi-hundred-MB
    omnibus filings.
    """
    accession_nodash = accession_number.replace("-", "")
    url = (
        f"{EDGAR_ARCHIVES_URL}/{cik}/{accession_nodash}/"
        f"{accession_number}.txt"
    )
    try:
        # Header is always in the first ~32 KB; a ranged-read keeps us
        # well inside the MAX_XML_DOWNLOAD_BYTES cap even when a
        # filing's full .txt is a hundred MB.
        resp = _request_with_retry(
            client, "GET", url,
            headers={"Range": "bytes=0-65535"},
        )
    except Exception as exc:  # noqa: BLE001 — walker is best-effort
        logger.debug(
            "SGML header download failed for CIK=%s accession=%s: %s",
            cik, accession_number, exc,
        )
        return None

    text = resp.text
    # Keep only through the end of the SEC-HEADER block. This is the
    # boundary every EDGAR submission uses between the header and the
    # document stream.
    end = text.find("</SEC-HEADER>")
    if end < 0:
        # Some older filings use a shorter END marker; fall back to
        # the 32 KB slice rather than failing outright.
        return text
    return text[: end + len("</SEC-HEADER>")]


def _fetch_submissions(
    cik: int, client: httpx.Client
) -> Optional[dict]:
    """Return the recent-submissions JSON for a CIK, or None on error."""
    cik_padded = str(cik).zfill(10)
    url = f"{EDGAR_SUBMISSIONS_URL}/CIK{cik_padded}.json"
    try:
        resp = _request_with_retry(client, "GET", url)
        return resp.json()
    except Exception as exc:  # noqa: BLE001 — walker is best-effort
        logger.debug(
            "Submissions feed fetch failed for CIK=%s: %s", cik, exc
        )
        return None


def _full_text_search(
    ticker: str, client: httpx.Client
) -> list[int]:
    """Query EDGAR full-text search for registration filings mentioning
    the ticker. Returns candidate CIKs in rank order.
    """
    params = {
        "q": f'"{ticker.upper()}"',
        "forms": ",".join(_ICF_FORMS),
    }
    try:
        resp = _request_with_retry(
            client, "GET", _EDGAR_FULL_TEXT_SEARCH_URL, params=params
        )
        body = resp.json()
    except Exception as exc:  # noqa: BLE001 — walker is best-effort
        logger.debug(
            "Full-text search failed for ticker=%s: %s", ticker, exc
        )
        return []
    return parse_candidate_ciks(body)


# ---------------------------------------------------------------------------
# Walker

def _walk_trust_for_ticker(
    cik: int,
    ticker: str,
    client: httpx.Client,
) -> Optional[MutualFundIdentifier]:
    """Walk a trust's recent ICF filings looking for the ticker.

    Returns a MutualFundIdentifier on the first matching SGML header,
    or None if the ticker is absent from every scanned filing under
    the given trust.
    """
    submissions = _fetch_submissions(cik, client)
    if submissions is None:
        return None

    accessions = filter_icf_accessions(submissions)
    for _, accession in accessions:
        header = _download_sgml_header(cik, accession, client)
        if header is None:
            continue
        hit = find_class_in_header(header, ticker)
        if hit is not None:
            series_id, class_id = hit
            return MutualFundIdentifier(
                ticker=ticker.upper(),
                cik=cik,
                series_id=series_id,
                class_id=class_id,
            )
    return None


def resolve_ticker_via_walker(
    ticker: str,
    client: Optional[httpx.Client] = None,
) -> Optional[MutualFundIdentifier]:
    """Resolve a ticker that is missing from company_tickers_mf.json.

    Tries seeded BlackRock LifePath trusts first, then falls back to
    EDGAR full-text search. Returns None if the ticker cannot be
    confirmed against any SGML header.

    Args:
        ticker: Fund share-class ticker.
        client: Optional httpx client (one is created if not supplied).

    Returns:
        MutualFundIdentifier on confirmed match, else None.
    """
    if not ticker:
        return None

    cached = _cached_resolution(ticker)
    if cached is not _CACHE_SENTINEL:
        return cached

    own_client = client is None
    if own_client:
        client = get_edgar_client()

    try:
        # Seeded trust fast path. BlackRock LifePath is the motivating
        # case and we can skip the full-text search on those tickers.
        for trust_cik in _SEEDED_BLACKROCK_LIFEPATH_CIKS:
            hit = _walk_trust_for_ticker(trust_cik, ticker, client)
            if hit is not None:
                _cache_resolution(ticker, hit)
                return hit

        # Full-text search fallback. Covers any other registrant whose
        # ticker has not propagated to the MF universe.
        for candidate_cik in _full_text_search(ticker, client):
            if candidate_cik in _SEEDED_BLACKROCK_LIFEPATH_CIKS:
                continue  # already walked above
            hit = _walk_trust_for_ticker(candidate_cik, ticker, client)
            if hit is not None:
                _cache_resolution(ticker, hit)
                return hit

        # Definite miss. Cache None so repeat lookups inside the same
        # process short-circuit without re-walking every trust.
        _cache_resolution(ticker, None)
        return None
    finally:
        if own_client:
            client.close()
