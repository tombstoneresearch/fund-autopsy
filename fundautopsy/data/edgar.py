"""EDGAR filing retrieval and base parsing utilities."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from fundautopsy.config import EDGAR_USER_AGENT, EDGAR_RATE_LIMIT_DELAY, MAX_XML_DOWNLOAD_BYTES

logger = logging.getLogger(__name__)

# SEC EDGAR endpoints
EDGAR_SUBMISSIONS_URL: str = "https://data.sec.gov/submissions"
EDGAR_ARCHIVES_URL: str = "https://www.sec.gov/Archives/edgar/data"
EDGAR_MF_TICKERS_URL: str = "https://www.sec.gov/files/company_tickers_mf.json"
EDGAR_BROWSE_URL: str = "https://www.sec.gov/cgi-bin/browse-edgar"

# Rate limiting: SEC requests max 10 requests/second
RATE_LIMIT_DELAY: float = EDGAR_RATE_LIMIT_DELAY

# Retry configuration
MAX_RETRIES: int = 3
RETRY_BACKOFF_BASE: float = 1.0  # seconds; doubles each retry
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# Thread-safe rate limiting
_rate_limit_lock = threading.Lock()
_last_request_time: float = 0.0

# Per-request EDGAR health tracking (thread-local)
_edgar_health = threading.local()


def reset_edgar_health() -> None:
    """Reset EDGAR health counters at the start of a pipeline run."""
    _edgar_health.retries = 0
    _edgar_health.errors = 0


def get_edgar_health() -> dict:
    """Return EDGAR health stats for the current request.

    Returns dict with 'retries' and 'errors' counts. If EDGAR needed
    retries, the dashboard can show a subtle indicator.
    """
    return {
        "retries": getattr(_edgar_health, "retries", 0),
        "errors": getattr(_edgar_health, "errors", 0),
    }


def pad_cik(cik: int | str) -> str:
    """Pad a CIK to 10 digits for EDGAR URL construction."""
    return str(cik).zfill(10)


@dataclass
class MutualFundIdentifier:
    """Resolved mutual fund identifiers from SEC."""

    ticker: str
    cik: int
    series_id: str
    class_id: str
    cik_padded: str = ""

    def __post_init__(self) -> None:
        """Pad CIK to 10 digits for EDGAR URL construction."""
        self.cik_padded = str(self.cik).zfill(10)


@dataclass
class FilingEntry:
    """A single filing from the EDGAR submissions index."""

    form_type: str
    filing_date: str
    accession_number: str
    primary_document: str = ""


def get_edgar_client() -> httpx.Client:
    """Create an HTTP client configured for EDGAR access."""
    return httpx.Client(
        headers={
            "User-Agent": EDGAR_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        },
        timeout=30.0,
        follow_redirects=True,
    )


def _rate_limit() -> None:
    """Enforce SEC rate limit of 10 requests/second. Thread-safe.

    Computes the required sleep duration inside the lock but releases it
    before sleeping, so concurrent threads can compute their own sleep
    times without blocking on each other's I/O wait.
    """
    global _last_request_time
    sleep_duration: float = 0.0
    with _rate_limit_lock:
        now: float = time.time()
        elapsed: float = now - _last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            sleep_duration = RATE_LIMIT_DELAY - elapsed
        # Reserve this time slot immediately so the next thread
        # sees the correct _last_request_time even before we sleep.
        _last_request_time = now + sleep_duration
    if sleep_duration > 0:
        time.sleep(sleep_duration)


def _request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    **kwargs,
) -> httpx.Response:
    """Make an HTTP request with rate limiting and exponential backoff retry.

    Retries on transient EDGAR errors (429, 5xx) and network failures.
    Logs warnings on retry and errors on final failure.

    Args:
        client: httpx.Client instance.
        method: HTTP method (GET, POST, etc.).
        url: Request URL.
        **kwargs: Additional arguments passed to client.request().

    Returns:
        httpx.Response on success.

    Raises:
        httpx.HTTPStatusError: If the request fails after all retries.
        httpx.TransportError: If a network-level error persists.
    """
    last_exc: Exception | None = None
    last_resp: httpx.Response | None = None
    for attempt in range(MAX_RETRIES):
        _rate_limit()
        try:
            resp = client.request(method, url, **kwargs)
            if resp.status_code in RETRYABLE_STATUS_CODES:
                last_resp = resp
                _edgar_health.retries = getattr(_edgar_health, "retries", 0) + 1
                wait = RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "EDGAR returned %d for %s (attempt %d/%d), retrying in %.1fs",
                    resp.status_code, url, attempt + 1, MAX_RETRIES, wait,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except httpx.TransportError as exc:
            last_exc = exc
            _edgar_health.retries = getattr(_edgar_health, "retries", 0) + 1
            wait = RETRY_BACKOFF_BASE * (2 ** attempt)
            logger.warning(
                "Network error fetching %s (attempt %d/%d): %s, retrying in %.1fs",
                url, attempt + 1, MAX_RETRIES, exc, wait,
            )
            time.sleep(wait)
        except httpx.HTTPStatusError:
            raise  # non-retryable HTTP errors propagate immediately

    # All retries exhausted
    _edgar_health.errors = getattr(_edgar_health, "errors", 0) + 1
    logger.error("EDGAR request failed after %d attempts: %s", MAX_RETRIES, url)
    if last_exc is not None:
        raise last_exc
    if last_resp is not None:
        last_resp.raise_for_status()
    raise httpx.TransportError(f"EDGAR request failed after {MAX_RETRIES} attempts: {url}")


import time as _time

# In-memory TTL cache on (ticker → MutualFundIdentifier).
# The SEC's share-class mapping is effectively stable; a new filing
# can cause a new class to appear but existing mappings do not change
# within a day. One-day TTL is safe and collapses the p95 latency on
# heavy umbrella trusts (walker path was measured at 186 s for LPRAX
# and 60 s for FIPFX on 2026-04-22). On cache hit the function
# returns in microseconds.
#
# Cache value is (MutualFundIdentifier|None, epoch_seconds). Negative
# cache entries (None) are kept at a shorter TTL so that newly-listed
# tickers resolve within ~1 hour of becoming valid.
_RESOLVE_CACHE: dict[str, tuple[Optional["MutualFundIdentifier"], float]] = {}
_RESOLVE_CACHE_TTL_HIT_SEC = 86400.0   # 24 hours for successful resolutions
_RESOLVE_CACHE_TTL_MISS_SEC = 3600.0   # 1 hour for negative cache entries


def _resolve_cache_get(ticker_upper: str) -> Optional[tuple[Optional["MutualFundIdentifier"], bool]]:
    """Return (value, hit) or None if no valid cache entry exists.

    Valid = within TTL for the success/miss kind that was stored.
    """
    entry = _RESOLVE_CACHE.get(ticker_upper)
    if entry is None:
        return None
    value, cached_at = entry
    ttl = _RESOLVE_CACHE_TTL_HIT_SEC if value is not None else _RESOLVE_CACHE_TTL_MISS_SEC
    if _time.time() - cached_at > ttl:
        return None
    return value, True


def _resolve_cache_put(
    ticker_upper: str,
    value: Optional["MutualFundIdentifier"],
) -> None:
    """Insert or refresh a cache entry."""
    _RESOLVE_CACHE[ticker_upper] = (value, _time.time())


def clear_resolve_cache() -> None:
    """Drop every cached resolution. For use in tests and admin hooks."""
    _RESOLVE_CACHE.clear()


def resolve_ticker(ticker: str, client: Optional[httpx.Client] = None) -> Optional[MutualFundIdentifier]:
    """Resolve a mutual fund ticker to CIK, series ID, and class ID.

    Uses SEC's company_tickers_mf.json which maps every mutual fund
    share class to its CIK, series ID, and class ID. Some newly
    registered share classes (notably BlackRock LifePath K-class
    tickers) appear in registered filings before SEC's daily index
    catches up; when the primary lookup misses, we fall through to an
    Investment Company Act filings walker that finds the class by its
    SGML header under the trust's recent 485BPOS / N-CEN feed.

    Results are cached in-memory with a 24-hour TTL on success and a
    1-hour TTL on misses. See `clear_resolve_cache()` to force refresh.

    Args:
        ticker: Fund ticker symbol (e.g., "AGTHX").
        client: Optional httpx client (creates one if not provided).

    Returns:
        MutualFundIdentifier if found, None otherwise.
    """
    ticker_upper: str = ticker.upper()

    cached = _resolve_cache_get(ticker_upper)
    if cached is not None:
        value, _hit = cached
        return value

    own_client: bool = client is None
    if own_client:
        client = get_edgar_client()

    try:
        resp = _request_with_retry(client, "GET", EDGAR_MF_TICKERS_URL)
        data: dict = resp.json()

        # Structure: {"fields": ["cik","seriesId","classId","symbol"], "data": [[...], ...]}
        for row in data["data"]:
            cik, series_id, class_id, symbol = row
            if symbol and symbol.upper() == ticker_upper:
                result = MutualFundIdentifier(
                    ticker=ticker_upper,
                    cik=cik,
                    series_id=series_id,
                    class_id=class_id,
                )
                _resolve_cache_put(ticker_upper, result)
                return result

        # MF-universe miss. Deferred import avoids a circular dependency
        # at module-load time — icf_walker imports MutualFundIdentifier
        # back from this module.
        from fundautopsy.data.icf_walker import resolve_ticker_via_walker
        walker_hit = resolve_ticker_via_walker(ticker_upper, client=client)
        if walker_hit is not None:
            logger.info(
                "Ticker %s resolved via ICF walker (not in MF universe): "
                "cik=%s series=%s class=%s",
                ticker_upper, walker_hit.cik, walker_hit.series_id, walker_hit.class_id,
            )
            _resolve_cache_put(ticker_upper, walker_hit)
            return walker_hit

        _resolve_cache_put(ticker_upper, None)
        return None
    finally:
        if own_client:
            client.close()


def get_filings(
    cik: int,
    form_type: str,
    client: Optional[httpx.Client] = None,
    count: int = 10,
) -> list[FilingEntry]:
    """Retrieve filing entries for a CIK filtered by form type.

    Uses the EDGAR submissions API:
    https://data.sec.gov/submissions/CIK{padded_cik}.json

    Args:
        cik: SEC CIK number.
        form_type: Filing type to filter (e.g., "N-CEN", "NPORT-P").
        client: Optional httpx client.
        count: Max filings to return.

    Returns:
        List of FilingEntry sorted by date descending (most recent first).
    """
    own_client: bool = client is None
    if own_client:
        client = get_edgar_client()

    try:
        cik_padded: str = str(cik).zfill(10)
        resp = _request_with_retry(client, "GET", f"{EDGAR_SUBMISSIONS_URL}/CIK{cik_padded}.json")
        sub: dict = resp.json()

        recent: dict = sub.get("filings", {}).get("recent", {})
        forms: list = recent.get("form", [])
        dates: list = recent.get("filingDate", [])
        accessions: list = recent.get("accessionNumber", [])
        primary_docs: list = recent.get("primaryDocument", [])

        # Validate list lengths are consistent before iterating
        min_len = min(len(forms), len(dates), len(accessions))
        if min_len < len(forms):
            logger.warning(
                "Inconsistent filing data lengths for CIK %s: forms=%d, dates=%d, accessions=%d",
                cik_padded, len(forms), len(dates), len(accessions),
            )

        entries: list[FilingEntry] = []
        for i in range(min_len):
            if form_type in forms[i] and len(entries) < count:
                entries.append(FilingEntry(
                    form_type=forms[i],
                    filing_date=dates[i],
                    accession_number=accessions[i],
                    primary_document=primary_docs[i] if i < len(primary_docs) else "",
                ))

        return entries
    finally:
        if own_client:
            client.close()


def get_filings_for_series(
    cik: int,
    series_id: str,
    form_type: str,
    client: Optional[httpx.Client] = None,
    count: int = 40,
) -> list[FilingEntry]:
    """Retrieve filings scoped to a single series under a trust CIK.

    The `data.sec.gov/submissions/CIKxxx.json` endpoint returns a
    trust-level feed with no way to filter by series. Umbrella trusts
    (iShares Trust has ~1,400 N-PORTs across hundreds of series;
    PIMCO Funds has ~2,800 497Ks) routinely bury a specific series'
    filings hundreds of entries deep, so a 50-count top-slice misses
    them entirely.

    EDGAR's legacy browse-edgar CGI accepts a series ID in the CIK
    parameter and returns only that series' filings, which is
    dramatically cheaper than downloading and parsing every trust-level
    filing looking for a series match. This function is the fast path
    for any filing lookup where the series_id is known.

    HTML is scraped with a strict accession + date regex. If the HTML
    shape changes, callers fall through to `get_filings()` and the
    existing brute-force scan.

    Args:
        cik: Trust CIK number (the archive URL still uses this, not the
            series id — series filings are stored under the trust).
        series_id: SEC series identifier (e.g., "S000023587" for AOR).
        form_type: Filing type (e.g., "NPORT-P", "N-CEN", "497").
        client: Optional httpx client.
        count: Max filings to return. Browse-edgar caps at 40 per page.

    Returns:
        List of FilingEntry sorted by filing date descending. Empty on
        parse failure or if the series has no filings of this type.
    """
    import re

    own_client: bool = client is None
    if own_client:
        client = get_edgar_client()

    try:
        params = {
            "action": "getcompany",
            "CIK": series_id,
            "type": form_type,
            "dateb": "",
            "owner": "include",
            "count": str(min(count, 40)),
        }
        try:
            resp = _request_with_retry(client, "GET", EDGAR_BROWSE_URL, params=params)
        except Exception as exc:  # noqa: BLE001 — fall back gracefully on HTTP failure
            logger.warning(
                "browse-edgar series lookup failed for series=%s cik=%s: %s",
                series_id, cik, exc,
            )
            return []

        html = resp.text
        # Each filing row carries an accession label adjacent to a
        # <td>YYYY-MM-DD</td> cell. We walk both in order and pair them
        # up. Accession numbers in this endpoint are duplicated (once
        # in the Documents link, once in the Acc-no label), so we
        # dedupe on first occurrence.
        acc_matches = list(re.finditer(r"Acc-no:\s*(\d{10}-\d{2}-\d{6})", html))
        date_matches = list(re.finditer(r"<td[^>]*>(\d{4}-\d{2}-\d{2})</td>", html))

        entries: list[FilingEntry] = []
        seen_acc: set[str] = set()

        # The browse-edgar table lists rows in reverse chronological
        # order. Each row has exactly one Acc-no and one filing date
        # column, interleaved in document order. Walk them in parallel.
        for acc_m, date_m in zip(acc_matches, date_matches):
            accession = acc_m.group(1)
            if accession in seen_acc:
                continue
            seen_acc.add(accession)
            entries.append(FilingEntry(
                form_type=form_type,
                filing_date=date_m.group(1),
                accession_number=accession,
                primary_document="primary_doc.xml",
            ))
            if len(entries) >= count:
                break

        return entries
    finally:
        if own_client:
            client.close()


_MF_UNIVERSE_LOCK = threading.Lock()
_MF_UNIVERSE: Optional[list[dict]] = None
_MF_UNIVERSE_FETCHED_AT: float = 0.0
_MF_UNIVERSE_TTL_SECONDS: float = 86400.0  # 24h — SEC updates this file daily


def _load_mf_universe(client: Optional[httpx.Client] = None) -> list[dict]:
    """Download and memoize the SEC mutual fund ticker universe.

    SEC's company_tickers_mf.json maps every mutual fund share class to
    its CIK, series ID, class ID, and ticker symbol. We normalize the
    raw rows into dicts for easier querying.

    Returns:
        List of dicts with keys: cik, series_id, class_id, ticker
    """
    global _MF_UNIVERSE, _MF_UNIVERSE_FETCHED_AT

    with _MF_UNIVERSE_LOCK:
        now = time.time()
        if _MF_UNIVERSE is not None and (now - _MF_UNIVERSE_FETCHED_AT) < _MF_UNIVERSE_TTL_SECONDS:
            return _MF_UNIVERSE

        own_client = client is None
        if own_client:
            client = get_edgar_client()
        try:
            resp = _request_with_retry(client, "GET", EDGAR_MF_TICKERS_URL)
            data = resp.json()
            rows = []
            for row in data.get("data", []):
                cik, series_id, class_id, symbol = row
                rows.append({
                    "cik": cik,
                    "series_id": series_id,
                    "class_id": class_id,
                    "ticker": (symbol or "").upper(),
                })
            _MF_UNIVERSE = rows
            _MF_UNIVERSE_FETCHED_AT = now
            return rows
        finally:
            if own_client:
                client.close()


def _normalize_fund_name(name: str) -> str:
    """Lower-case a fund name and strip share-class suffixes for matching.

    Holdings in N-PORT filings are usually reported with the investor-
    facing fund name without a share-class suffix, but the name can
    still differ from the official registrant name by punctuation,
    "The", or redundant "Fund" markers. We normalize aggressively so
    that "Vanguard Total Stock Market Index Fund - Investor Shares"
    matches "Vanguard Total Stock Market Index Fund" in the ticker map.
    """
    import re
    n = name.lower().strip()
    # Drop parentheticals and any share-class designators
    n = re.sub(r"\s*\([^)]*\)\s*", " ", n)
    # Strip common share-class tokens trailing the name
    class_tokens = (
        r"class [a-z0-9]+",
        r"investor shares?",
        r"admiral shares?",
        r"institutional shares?",
        r"retail shares?",
        r"- [a-z]+ shares?",
    )
    for tok in class_tokens:
        n = re.sub(rf"\b{tok}\b", " ", n, flags=re.IGNORECASE)
    # Normalize whitespace and common noise
    n = re.sub(r"[\.\,\;\:\-]+", " ", n)
    n = re.sub(r"\bthe\b", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def resolve_holding_name_to_fund(
    holding_name: str,
    client: Optional[httpx.Client] = None,
) -> Optional[MutualFundIdentifier]:
    """Resolve a holding's reported name to a MutualFundIdentifier.

    Looks up the SEC mutual fund ticker universe and matches by fund
    family prefix + canonical fund name. Returns the lowest-class
    match when multiple share classes exist (prefer Investor/Retail
    tickers to capture the representative expense profile).

    Args:
        holding_name: The "name" field of an NPortHolding (e.g.,
            "Vanguard Total Stock Market Index Fund").
        client: Optional httpx client.

    Returns:
        MutualFundIdentifier for the matched fund, or None if no
        confident match can be made.
    """
    if not holding_name or len(holding_name) < 5:
        return None

    target = _normalize_fund_name(holding_name)
    if not target:
        return None

    universe = _load_mf_universe(client)

    # Strategy 1: extract a ticker embedded in parentheses (e.g.
    # "Vanguard 500 Index Fund (VFIAX)"). Fastest path — company_tickers_mf
    # already has the full (ticker -> cik/series/class) mapping.
    #
    # IMPORTANT: require parenthetical context. An unparenthesized regex
    # that matches any 3-5 letter word ending in X produces false positives
    # against common English words that happen to be registered tickers
    # (e.g. "INDEX" is CIK 1345125, causing "TRP EQUITY INDEX 500 FD-Z"
    # to spuriously resolve to Index Funds S&P 500 Equal Weight No-Load).
    import re
    ticker_match = re.search(r"\(([A-Z]{3,5}X)\)", holding_name)
    if ticker_match:
        candidate_ticker = ticker_match.group(1)
        for row in universe:
            if row["ticker"] == candidate_ticker:
                return MutualFundIdentifier(
                    ticker=row["ticker"],
                    cik=int(row["cik"]),
                    series_id=row["series_id"],
                    class_id=row["class_id"],
                )

    # Strategy 2: name-based resolution via edgar.funds.find_funds. This
    # covers the common case where the N-PORT holding reports a pure
    # fund name without any ticker — target-date fund underlyings
    # (Vanguard Total Stock Market Index Fund, etc.) and ETF-of-ETF
    # holdings (iShares Core S&P 500 ETF, etc.).
    resolved = _find_fund_by_name(holding_name)
    if resolved is not None:
        return resolved

    # Strategy 3: abbreviation-expanded retry. N-PORT character-limit
    # truncation shortens common words ("Mkt" -> "Market", "Devs" ->
    # "Developed") which defeats the exact name match. We expand a
    # small set of known abbreviations and try once more.
    expanded = _expand_fund_abbreviations(holding_name)
    if expanded and expanded != holding_name:
        resolved = _find_fund_by_name(expanded)
        if resolved is not None:
            return resolved

    # Strategy 4: generate candidate names by peeling registrant
    # prefixes and share-class suffixes, then try each. Handles:
    #   "Vanguard Cmt Funds-Vanguard Market Liquidity Fund"
    #   "BlackRock Funds III: BlackRock Cash Funds: Institutional; SL
    #    Agency Shares"
    #   "iShares Trust - iShares Core S&P 500 ETF"
    for cand in _generate_candidate_names(holding_name):
        if cand == holding_name:
            continue
        resolved = _find_fund_by_name(cand)
        if resolved is not None:
            return resolved
        expanded_cand = _expand_fund_abbreviations(cand)
        if expanded_cand != cand:
            resolved = _find_fund_by_name(expanded_cand)
            if resolved is not None:
                return resolved

    return None


def _generate_candidate_names(name: str) -> list[str]:
    """Produce candidate resolvable names from an N-PORT holding name.

    Handles three transformations:
      - Prefix peel: "Trust - Fund Name" -> "Fund Name".
      - Tail strip: "Fund Name; SL Agency Shares" -> "Fund Name".
      - Iterative: apply peel then strip then peel-and-strip combined.

    Returns an ordered list of candidates, deduped, with the original
    name first.
    """
    import re
    seen: set[str] = set()
    out: list[str] = []

    def push(s: str) -> None:
        s = s.strip().strip(",; -:")
        if s and s not in seen and len(s) >= 5:
            seen.add(s)
            out.append(s)

    push(name)

    # Peel leading prefix segments separated by " - ", " : ", or ":".
    peeled = _strip_registrant_prefix(name)
    if peeled != name:
        push(peeled)
        # peel a second time in case of nested prefix
        peeled2 = _strip_registrant_prefix(peeled)
        if peeled2 != peeled:
            push(peeled2)

    # Strip trailing share-class qualifiers introduced with ";" or ",".
    # Examples: "; SL Agency Shares", "; Institutional Class".
    for candidate in list(out):
        for sep in (";", ","):
            if sep in candidate:
                tail_stripped = candidate.split(sep, 1)[0]
                push(tail_stripped)

    # Strip share-class designators matching a known share-class vocab.
    share_class_pattern = re.compile(
        r"\s*[,;:]?\s*\b("
        r"Institutional(?:\s+Shares?)?|"
        r"Institutional\s+Class|"
        r"Investor(?:\s+Shares?)?|"
        r"Admiral(?:\s+Shares?)?|"
        r"Retail(?:\s+Shares?)?|"
        r"Class\s+[A-Z0-9]+|"
        r"Service\s+Class|"
        r"SL\s+Agency\s+Shares?|"
        r"Agency\s+Shares?"
        r")\s*$",
        re.IGNORECASE,
    )
    for candidate in list(out):
        stripped = share_class_pattern.sub("", candidate).strip()
        if stripped and stripped != candidate:
            push(stripped)

    return out


def _strip_registrant_prefix(name: str) -> str:
    """Remove a 'registrant-' or 'trust:' prefix from an N-PORT name.

    Handles patterns seen in the field:
      "Vanguard Cmt Funds-Vanguard Market Liquidity Fund"
        -> "Vanguard Market Liquidity Fund"
      "BlackRock Funds III: BlackRock Cash Funds: Institutional"
        -> "BlackRock Cash Funds: Institutional"
      "iShares Trust - iShares Core S&P 500 ETF"
        -> "iShares Core S&P 500 ETF"

    Conservative: only strips the FIRST dash/colon separator and only
    when the remainder is itself a plausible fund name (starts with a
    capitalized word at least three characters long).
    """
    import re
    # Match 'X - Y' or 'X: Y' where Y starts with a capital letter word
    # First char can be uppercase OR a lowercase brand prefix like "i" or "e"
    # (iShares, eMaxx, etc.) as long as the second char is uppercase.
    m = re.match(
        r"^(.*?)\s*[-:]\s*((?:[A-Z]|[a-z][A-Z])[A-Za-z0-9].+)$",
        name.strip(),
    )
    if not m:
        return name
    remainder = m.group(2).strip()
    if len(remainder) < 5:
        return name
    return remainder


# Common N-PORT name abbreviations mapped to their expanded form. Keys
# are matched as whole words (case-insensitive). Values are the SEC
# registrant spelling used in edgar.funds.find_funds. This list is
# intentionally small — each entry should be grounded in a real
# observed mismatch rather than speculative expansion.
_FUND_NAME_ABBREVIATIONS: dict[str, str] = {
    "Mkt": "Markets",
    "Mkts": "Markets",
    "Dev": "Developed",
    "Devs": "Developed",
    "Intl": "International",
    "Int'l": "International",
    "Emg": "Emerging",
    "Em": "Emerging",
    "Sml": "Small",
    "Lg": "Large",
    "Mid": "Mid",
    "Cap": "Cap",
    "Corp": "Corporate",
    "Govt": "Government",
    "Tr": "Treasury",
    "Muni": "Municipal",
    "Univ": "Universal",
}


def _expand_fund_abbreviations(name: str) -> str:
    """Expand common N-PORT truncation abbreviations in place.

    Example: "iShares Core MSCI International Developed Mkt ETF" ->
    "iShares Core MSCI International Developed Markets ETF".

    Only whole-word matches are substituted. Case is preserved from the
    abbreviation dictionary so the expanded form reads naturally.
    """
    import re
    result = name
    for abbr, full in _FUND_NAME_ABBREVIATIONS.items():
        pattern = rf"\b{re.escape(abbr)}\b"
        result = re.sub(pattern, full, result, flags=re.IGNORECASE)
    return result


# LRU cache for name->FundSeriesRecord lookups. edgar.funds.find_funds
# hits a shared in-memory index, but each call still has marshalling
# overhead, so caching at the Python layer keeps the hot path cheap.
_find_funds_cache: dict[str, Optional[MutualFundIdentifier]] = {}
_find_funds_cache_lock = threading.Lock()


def _find_fund_by_name(holding_name: str) -> Optional[MutualFundIdentifier]:
    """Resolve a fund name to a MutualFundIdentifier via edgar.funds.

    Uses edgartools' in-memory fund index. Accepts the result only
    when exactly one FundSeriesRecord matches — multi-match cases are
    usually ambiguous (e.g., "Vanguard Total Bond" returns both the
    retail and II variants) and silently picking wrong is worse than
    returning None and surfacing the gap in the data_notes.

    class_id is filled in opportunistically from the mf_universe by
    looking up any class under the matched (cik, series_id) pair. The
    caller may override if they know a specific class.
    """
    if not holding_name:
        return None

    key = holding_name.strip()
    with _find_funds_cache_lock:
        if key in _find_funds_cache:
            return _find_funds_cache[key]

    result: Optional[MutualFundIdentifier] = None
    try:
        import edgar as _edgar  # lazy import; edgartools heavy
        from edgar.funds import find_funds
        # edgartools requires a User-Agent identity for any SEC call.
        # set_identity is idempotent, so it is safe to call repeatedly.
        # Without this, find_funds raises IdentityNotSetException whenever
        # edgar.py is loaded in isolation from prospectus.py — and the
        # broad except below would silently turn every lookup into a miss.
        _edgar.set_identity(EDGAR_USER_AGENT)
        matches = find_funds(key)
    except Exception as exc:  # noqa: BLE001 — resolver is best-effort
        logger.debug("edgar.funds.find_funds failed for %r: %s", key, exc)
        matches = []

    if matches and len(matches) == 1:
        rec = matches[0]
        cik_raw = getattr(rec, "cik", None)
        series_id = getattr(rec, "series_id", None)
        if cik_raw and series_id:
            try:
                cik_int = int(str(cik_raw).lstrip("0") or "0")
            except ValueError:
                cik_int = 0
            if cik_int > 0:
                # Try to pick a representative class id. The FoF holds the
                # series, not any specific class, but downstream logic
                # (prospectus parsing, fee lookup) needs a class anchor.
                # Prefer the institutional/admiral class when available;
                # fall back to the first class for this (cik, series) pair.
                class_id: Optional[str] = None
                ticker: Optional[str] = None
                try:
                    universe = _load_mf_universe()
                    pref_order = ["X", "X", "A", "I"]  # pref institutional
                    candidates = [
                        row for row in universe
                        if int(row["cik"]) == cik_int
                        and row["series_id"] == series_id
                    ]
                    if candidates:
                        # Prefer tickers ending with 'X' (open-end) then 'I'
                        candidates.sort(
                            key=lambda r: (
                                0 if r["ticker"].endswith("X") else 1,
                                r["ticker"],
                            )
                        )
                        class_id = candidates[0]["class_id"]
                        ticker = candidates[0]["ticker"]
                except Exception:  # noqa: BLE001 — class backfill is optional
                    pass
                result = MutualFundIdentifier(
                    ticker=ticker or "",
                    cik=cik_int,
                    series_id=series_id,
                    class_id=class_id,
                )

    # Only cache positive results. Caching None would poison the
    # lookup on transient SEC outages (503s, timeouts). A miss here
    # is cheap to retry; a wrong cached-None is not.
    if result is not None:
        with _find_funds_cache_lock:
            _find_funds_cache[key] = result
    return result


def resolve_holding_to_fund(
    holding_name: str,
    cusip: Optional[str] = None,
    isin: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> Optional[MutualFundIdentifier]:
    """Resolve an N-PORT holding to a MutualFundIdentifier.

    Resolution strategies, tried in order:
        1. Ticker extraction from the holding name (fastest, most
           reliable when a ticker is embedded in parentheses).
        2. CUSIP → CIK via EDGAR full-text search (future).
        3. Fuzzy name match against registrant names (future).

    Args:
        holding_name: Reported name from the N-PORT filing.
        cusip: Optional 9-character CUSIP.
        isin: Optional ISIN.
        client: Optional httpx client.

    Returns:
        MutualFundIdentifier for the matched underlying fund, or None
        if no confident resolution is possible.
    """
    # Strategy 1 (preferred when available): CUSIP → ticker → fund via
    # OpenFIGI. A CUSIP uniquely identifies a specific share class, so it
    # resolves to the exact class the N-PORT holding represents. The
    # name-based resolver below cannot do this — a series name matches
    # every class in the series and the class-picker must guess. For
    # American Funds in particular, retail classes (AFICX, AIBAX) sort
    # alphabetically before R-6 classes (RFNGX, RBOGX) and the name
    # resolver used to silently downgrade R-6 target-date holdings to
    # retail classes. CUSIP-first eliminates that entire class of bug.
    if cusip:
        resolved = _resolve_cusip_via_openfigi(cusip, client=client)
        if resolved is not None:
            return resolved

    # Strategy 2: name-based resolution via the MF ticker universe and
    # edgar.funds.find_funds. Handles holdings that report without a
    # usable CUSIP, or where OpenFIGI has no entry (some private funds,
    # newer class launches that have not propagated into OpenFIGI's
    # mutual-fund master yet).
    resolved = resolve_holding_name_to_fund(holding_name, client=client)
    if resolved is not None:
        return resolved

    # Strategy 3: ISIN as a last resort — for U.S. securities the ISIN
    # is just the CUSIP with a US prefix and a check digit, so we can
    # extract the CUSIP and retry.
    if isin and isin.startswith("US") and len(isin) == 12:
        derived_cusip = isin[2:11]
        resolved = _resolve_cusip_via_openfigi(derived_cusip, client=client)
        if resolved is not None:
            return resolved

    return None


# OpenFIGI CUSIP resolver cache. OpenFIGI data is security-master data
# that changes slowly, so a process-local cache with no TTL is fine.
# Negative results are cached so we don't burn rate limit on holdings
# that OpenFIGI genuinely does not know about (e.g. private funds).
_openfigi_cache: dict[str, Optional[str]] = {}
_openfigi_cache_lock = threading.Lock()
_OPENFIGI_URL: str = "https://api.openfigi.com/v3/mapping"
_OPENFIGI_TIMEOUT_SECONDS: float = 10.0


def _resolve_cusip_via_openfigi(
    cusip: str,
    client: Optional[httpx.Client] = None,
) -> Optional[MutualFundIdentifier]:
    """Resolve a CUSIP to a MutualFundIdentifier via OpenFIGI.

    OpenFIGI is Bloomberg's public security-master lookup. For U.S.
    registered funds it returns the issuer's composite ticker, which
    we then chain through the existing SEC mutual-fund ticker universe
    to get the CIK / series_id / class_id triple.

    Only accepts results where the resolved ticker appears in the SEC
    MF universe (i.e., a registered investment company). Equity,
    fixed-income, and other non-fund securities that happen to share
    a CUSIP with fund holdings are rejected — the resolver's contract
    is to return registered-fund identifiers only.

    Rate limits: OpenFIGI unauthenticated is 25 requests / minute, 100
    identifiers per batch. We only ever request one identifier at a
    time inside the resolver (called per N-PORT holding), but each
    response is cached so a second lookup on the same CUSIP is free.
    """
    if not cusip or len(cusip) != 9:
        return None

    key = cusip.upper()
    with _openfigi_cache_lock:
        if key in _openfigi_cache:
            resolved_ticker = _openfigi_cache[key]
            if resolved_ticker is None:
                return None
            # Fall through to MF-universe lookup below — we cache the
            # ticker, not the full MutualFundIdentifier, so that the
            # universe can refresh without invalidating CUSIP mappings.
            return _lookup_mf_by_ticker(resolved_ticker, client=client)

    import json
    # OpenFIGI is not an SEC endpoint — use a fresh httpx client with a
    # neutral User-Agent rather than the SEC-branded one from get_edgar_client.
    import httpx as _httpx

    resolved_ticker: Optional[str] = None
    is_definite_miss: bool = False
    try:
        payload = json.dumps([{"idType": "ID_CUSIP", "idValue": key}]).encode()
        # Retry up to twice on 429 with server-recommended backoff. The
        # unauthenticated limit is 25 req/min — on FoFs with 20-30
        # holdings we will hit it mid-run if we don't sleep.
        for attempt in range(3):
            with _httpx.Client(
                timeout=_OPENFIGI_TIMEOUT_SECONDS,
                headers={
                    "User-Agent": "FundAutopsy/0.1 (open-source research tool)",
                    "Content-Type": "application/json",
                },
            ) as _c:
                resp = _c.post(_OPENFIGI_URL, content=payload)
            if resp.status_code == 200:
                body = resp.json()
                data = body[0].get("data") if body and isinstance(body, list) else None
                if data:
                    raw_ticker = data[0].get("ticker")
                    if raw_ticker and isinstance(raw_ticker, str):
                        resolved_ticker = raw_ticker.strip().upper()
                    is_definite_miss = resolved_ticker is None
                elif body and isinstance(body, list) and body[0].get("warning"):
                    # No data and a warning — e.g. "No identifier found".
                    # Definite miss, safe to negative-cache.
                    is_definite_miss = True
                break
            if resp.status_code == 429:
                # Rate limit. Respect Retry-After when present, otherwise
                # wait 6 seconds (spreads a burst of 32 requests across
                # 3 minutes, well under the 25/min ceiling).
                retry_after = resp.headers.get("Retry-After")
                try:
                    sleep_s = float(retry_after) if retry_after else 6.0
                except ValueError:
                    sleep_s = 6.0
                logger.debug(
                    "OpenFIGI CUSIP %s rate-limited (attempt %d), sleeping %.1fs",
                    key, attempt + 1, sleep_s,
                )
                time.sleep(min(sleep_s, 10.0))
                continue
            # Other error — log and give up without caching.
            logger.debug(
                "OpenFIGI CUSIP %s returned HTTP %s",
                key, resp.status_code,
            )
            break
    except Exception as exc:  # noqa: BLE001 — resolver is best-effort
        logger.debug("OpenFIGI lookup failed for CUSIP %s: %s", key, exc)

    # Cache successful lookups (both positive hits AND definite misses
    # where OpenFIGI said the identifier is unknown). Do NOT cache
    # transient failures (timeouts, 5xx, unresolved rate-limit) — those
    # should be retried on the next call.
    if resolved_ticker is not None or is_definite_miss:
        with _openfigi_cache_lock:
            _openfigi_cache[key] = resolved_ticker

    if resolved_ticker is None:
        return None
    return _lookup_mf_by_ticker(resolved_ticker, client=client)


def _lookup_mf_by_ticker(
    ticker: str,
    client: Optional[httpx.Client] = None,
) -> Optional[MutualFundIdentifier]:
    """Look up a ticker in the SEC MF universe.

    Returns a MutualFundIdentifier when the ticker is registered with
    the SEC as a mutual fund or ETF; returns None for equity, fixed
    income, or other non-registered-fund securities. Used as the tail
    of the CUSIP → ticker → fund resolver.
    """
    if not ticker:
        return None
    try:
        universe = _load_mf_universe(client)
    except Exception:  # noqa: BLE001
        return None
    for row in universe:
        if row.get("ticker", "").upper() == ticker.upper():
            try:
                cik_int = int(row["cik"])
            except (KeyError, ValueError, TypeError):
                continue
            return MutualFundIdentifier(
                ticker=row.get("ticker", ""),
                cik=cik_int,
                series_id=row.get("series_id"),
                class_id=row.get("class_id"),
            )
    return None


def download_filing_xml(
    cik: int,
    accession_number: str,
    primary_document: str = "primary_doc.xml",
    client: Optional[httpx.Client] = None,
) -> bytes:
    """Download the XML content of a specific filing.

    Args:
        cik: SEC CIK number.
        accession_number: EDGAR accession number (e.g., "0001145549-24-069034").
        primary_document: Filename of the primary document.
        client: Optional httpx client.

    Returns:
        Raw XML bytes.

    Raises:
        httpx.HTTPStatusError: If the download fails.
    """
    own_client: bool = client is None
    if own_client:
        client = get_edgar_client()

    try:
        # Check cache first — filings are immutable so cached data is always valid
        from fundautopsy.data.cache import get_cache
        cache = get_cache()
        cached = cache.get_xml(cik, accession_number, primary_document)
        if cached is not None:
            return cached

        accession_path: str = accession_number.replace("-", "")
        url: str = f"{EDGAR_ARCHIVES_URL}/{cik}/{accession_path}/{primary_document}"
        resp = _request_with_retry(client, "GET", url)
        content = resp.content

        if len(content) > MAX_XML_DOWNLOAD_BYTES:
            logger.warning(
                "EDGAR response for %s/%s exceeds size limit (%d > %d bytes), discarding",
                accession_number, primary_document, len(content), MAX_XML_DOWNLOAD_BYTES,
            )
            raise httpx.TransportError(
                f"Filing content exceeds {MAX_XML_DOWNLOAD_BYTES} byte limit"
            )

        # Cache the response for future requests
        cache.put_xml(cik, accession_number, primary_document, content)

        return content
    finally:
        if own_client:
            client.close()
