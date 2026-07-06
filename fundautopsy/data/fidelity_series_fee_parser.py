"""Fidelity Series 485BPOS fee-table parser.

Fidelity Investment Trust's "Fidelity Series" funds (FSSJX, FSTSX,
FEMSX, FHKFX, FSOSX, FCNSX, FIGSX, FINVX, etc.) are single-class
building-block funds that exist only to service other Fidelity funds
(primarily Freedom target-date funds). They do not file standalone
497K summary prospectuses -- their fee tables live only inside the
annual 485BPOS omnibus prospectus for FIDELITY INVESTMENT TRUST, which
bundles dozens of Fidelity funds under one filing.

Unlike American Funds' columnar fee tables, Fidelity Series funds use
a **prose** fee format:

    Management fee 0.00 %
    Distribution and/or Service (12b-1) fees None
    Other expenses 0.01 %
    Total annual operating expenses 0.01 %

Each fund's section begins with a "Fund Summary Fund: Fidelity(R) <Name>"
marker. This module locates the section by series name (with flexible
trademark-sign handling), then extracts fee values from the prose.

The combined 485BPOS is large (~14 MB HTML, ~6 MB cleaned text) and is
not always the most recent 485BPOS filing on the series' feed -- the
feed surfaces every 485BPOS filed by the registrant, and Fidelity
Investment Trust files dozens per year for different fund cohorts. The
scanner iterates the 485BPOS feed via SGML header to find the filing
that actually contains the target ticker, then parses only that one.

Detection is conservative: the helper returns None for any non-Fidelity
registrant or any Fidelity fund whose series name does not start with
"Fidelity Series" (the Freedom target-date funds, advisor classes, and
other Fidelity products live in different filings and use the columnar
fee format that edgartools handles correctly).
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Iterable, Optional, Tuple

import edgar

logger = logging.getLogger(__name__)

# Deferred import of ProspectusFees inside try_fidelity_series_fees
# avoids a circular import with prospectus.py.


# ---------------------------------------------------------------------------
# Detection

_FIDELITY_REGISTRANT_SUBSTRINGS = (
    "FIDELITY INVESTMENT TRUST",
    "FIDELITY SELECT PORTFOLIOS",
    "FIDELITY CONCORD STREET TRUST",
)


def _is_fidelity_registrant(registrant_name: Optional[str]) -> bool:
    if not registrant_name:
        return False
    upper = registrant_name.upper()
    return any(sub in upper for sub in _FIDELITY_REGISTRANT_SUBSTRINGS)


def _is_fidelity_series_fund(series_name: Optional[str]) -> bool:
    """True for Fidelity Series building-block funds.

    These start with "Fidelity Series " and are single-class, no-12b-1
    funds that live only in the combined 485BPOS. Every other Fidelity
    fund family (Advisor, Freedom, Select, etc.) parses correctly via
    edgartools' 497K path and must fall through.
    """
    if not series_name:
        return False
    # Case-insensitive "Fidelity Series <rest>" prefix. Strip trademark
    # markers the series-name property may have been cleaned of.
    cleaned = series_name.strip()
    return bool(re.match(r"^Fidelity\s+Series\s+", cleaned, re.IGNORECASE))


# ---------------------------------------------------------------------------
# SGML header parsing

def _header_text(filing) -> str:
    try:
        return filing.header.text or ""
    except Exception:
        return ""


def _extract_registrant_name(filing) -> Optional[str]:
    text = _header_text(filing)
    if not text:
        return None
    m = re.search(r"COMPANY CONFORMED NAME:\s+(.+)", text)
    return m.group(1).strip() if m else None


def _header_has_ticker(filing, ticker_upper: str) -> bool:
    """True if the filing's SGML header lists the target ticker."""
    text = _header_text(filing)
    if not text:
        return False
    pattern = re.compile(
        rf"<CLASS-CONTRACT-TICKER-SYMBOL>\s*{re.escape(ticker_upper)}\b",
        re.IGNORECASE,
    )
    return bool(pattern.search(text))


def _find_485bpos_for_ticker(filings, ticker_upper: str, max_scan: int = 30):
    """Return the first 485BPOS in the feed whose SGML header carries
    the target ticker. Fidelity Investment Trust files ~30 485BPOSes
    per year covering different cohorts; the target fund's filing is
    typically within the most recent handful but not always position 0.

    Uses a module-level ticker -> accession cache so repeated calls for
    the same ticker inside a single decomposition do not repeat the
    expensive header scan.
    """
    cached_accession = _TICKER_ACCESSION_CACHE.get(ticker_upper)
    if cached_accession:
        for i in range(len(filings)):
            try:
                if getattr(filings[i], "accession_no", None) == cached_accession:
                    return filings[i]
            except Exception:
                continue
        # Cached accession no longer in feed; fall through and rescan.
        _TICKER_ACCESSION_CACHE.pop(ticker_upper, None)

    bound = min(max_scan, len(filings))
    for i in range(bound):
        try:
            if _header_has_ticker(filings[i], ticker_upper):
                accession = getattr(filings[i], "accession_no", None)
                if accession:
                    _cache_ticker_accession(ticker_upper, accession)
                return filings[i]
        except Exception as exc:
            logger.debug(
                "Fidelity 485BPOS SGML scan: header fetch failed at %d for %s: %s",
                i, ticker_upper, exc,
            )
            continue
    return None


# ---------------------------------------------------------------------------
# HTML cleanup

_ENTITY_REPLACEMENTS = (
    ("&nbsp;", " "), ("&#160;", " "),
    ("&#169;", "(c)"), ("&#174;", "(r)"),
    ("&copy;", "(c)"), ("&reg;", "(r)"),
    ("&mdash;", "--"), ("&ndash;", "-"),
    ("&amp;", "&"),
    ("&lsquo;", "'"), ("&rsquo;", "'"),
    ("&ldquo;", '"'), ("&rdquo;", '"'),
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_html(content: str) -> str:
    text = content
    for entity, sub in _ENTITY_REPLACEMENTS:
        text = text.replace(entity, sub)
    text = _TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text)
    return text


# ---------------------------------------------------------------------------
# Caches
#
# The Fidelity omnibus 485BPOS is ~14 MB HTML / ~6 MB cleaned text and
# contains 15-30 funds per filing. A fund-of-funds with N Fidelity Series
# underlyings would otherwise re-download and re-clean the same document
# N times during a three-layer decomposition. We cache by accession
# number; the caches are module-level and bounded in size to prevent
# runaway memory under a long-running process.

_CLEAN_TEXT_CACHE: dict[str, str] = {}
_CLEAN_TEXT_CACHE_MAX = 4  # <=4 * ~6 MB = ~24 MB cap

_TICKER_ACCESSION_CACHE: dict[str, str] = {}
_TICKER_ACCESSION_CACHE_MAX = 256

# End-to-end ticker -> parsed-fee cache. Most callers hit the parser
# multiple times for the same ticker during a decomposition (through
# the child-hydration loop inside portfolio.py). Caching the parsed
# dict bypasses both the EDGAR roundtrip and the HTML work on repeats.
# Keyed by ticker; value is the parsed fee dict (not the ProspectusFees
# dataclass, to keep the import graph free of the circular dep at
# module-import time).
_TICKER_FEES_CACHE: dict[str, dict] = {}
_TICKER_FEES_CACHE_MAX = 256


def _cache_ticker_fees(ticker: str, fees: dict) -> None:
    if ticker in _TICKER_FEES_CACHE:
        return
    if len(_TICKER_FEES_CACHE) >= _TICKER_FEES_CACHE_MAX:
        _TICKER_FEES_CACHE.pop(next(iter(_TICKER_FEES_CACHE)))
    _TICKER_FEES_CACHE[ticker] = fees


def _cache_clean_text(accession: str, text: str) -> None:
    if accession in _CLEAN_TEXT_CACHE:
        return
    if len(_CLEAN_TEXT_CACHE) >= _CLEAN_TEXT_CACHE_MAX:
        # Evict the oldest entry; dicts preserve insertion order in 3.7+.
        _CLEAN_TEXT_CACHE.pop(next(iter(_CLEAN_TEXT_CACHE)))
    _CLEAN_TEXT_CACHE[accession] = text


def _cache_ticker_accession(ticker: str, accession: str) -> None:
    if ticker in _TICKER_ACCESSION_CACHE:
        return
    if len(_TICKER_ACCESSION_CACHE) >= _TICKER_ACCESSION_CACHE_MAX:
        _TICKER_ACCESSION_CACHE.pop(next(iter(_TICKER_ACCESSION_CACHE)))
    _TICKER_ACCESSION_CACHE[ticker] = accession


# ---------------------------------------------------------------------------
# Section location + fee extraction

# Each fund's section starts with this marker. The "(r)" is the
# cleaned form of &#174; for Fidelity's registered-trademark sign.
_FUND_SECTION_RE = re.compile(r"Fund Summary Fund:\s*", re.IGNORECASE)

# Fee-row patterns. All four rows appear within ~400-600 chars of the
# section start for Fidelity Series funds, so we bound the search window
# to avoid cross-contamination with the next fund's section.
_MGMT_RE = re.compile(r"Management fee\s+([\d.]+|[Nn]one)", re.IGNORECASE)
_12B1_RE = re.compile(
    r"Distribution and/or Service \(12b-1\) fees\s+([\d.]+|[Nn]one)",
    re.IGNORECASE,
)
_OTHER_RE = re.compile(r"Other expenses\s+([\d.]+|[Nn]one)", re.IGNORECASE)
_TOTAL_RE = re.compile(
    r"Total annual (?:fund )?operating expenses\s+([\d.]+|[Nn]one)",
    re.IGNORECASE,
)
_NET_RE = re.compile(
    r"Total annual (?:fund )?operating expenses after fee waiver(?:s)?\s+"
    r"([\d.]+|[Nn]one)",
    re.IGNORECASE,
)
_WAIVER_RE = re.compile(
    r"Fee waiver(?:s)?(?: and/or expense reimbursement)?\s+([\d.]+|[Nn]one)",
    re.IGNORECASE,
)
_TURNOVER_RE = re.compile(
    r"fund's portfolio turnover rate was\s+([\d.]+)\s*%",
    re.IGNORECASE,
)
_SHAREHOLDER_LOAD_RE = re.compile(
    r"Maximum sales charge.*?([\d.]+|[Nn]one)",
    re.IGNORECASE,
)


def _normalize_value(raw: Optional[str]) -> Optional[float]:
    """Convert a prose-extracted token to a float percent, or None.

    - "None" / "none" -> 0.0 (the fee does not exist for this class)
    - numeric string -> float
    - None / unparseable -> None
    """
    if raw is None:
        return None
    stripped = raw.strip().lower()
    if stripped == "none":
        return 0.0
    try:
        return float(stripped)
    except ValueError:
        return None


def _find_fund_section(text: str, series_name: str) -> Optional[str]:
    """Return the slice of cleaned text starting at the target fund's
    'Fund Summary Fund:' marker and ending at the next fund's marker,
    the next 'Fund Basics' (post-summary section), or +5000 chars --
    whichever comes first. Returns None if the fund's section is not
    located.
    """
    # Build a flexible series-name matcher: Fidelity Series funds' section
    # headers include a "(r)" trademark sign that edgartools' series.name
    # property strips out. The pattern tolerates either form.
    rest = series_name.strip()
    if rest.lower().startswith("fidelity "):
        rest = rest[len("fidelity "):]
    pattern = re.compile(
        r"Fund Summary Fund:\s*Fidelity(?:\s*\(r\))?\s+" + re.escape(rest),
        re.IGNORECASE,
    )
    mo = pattern.search(text)
    if not mo:
        return None
    start = mo.start()
    # Next-fund boundary: the nearest subsequent "Fund Summary Fund:" marker.
    next_section_mo = _FUND_SECTION_RE.search(text, pos=start + 1)
    end_next = next_section_mo.start() if next_section_mo else len(text)
    # Hard cap at +5000 to keep regex work bounded even if the omnibus
    # is a one-fund document.
    end_cap = start + 5000
    end = min(end_next, end_cap, len(text))
    return text[start:end]


def _parse_fidelity_section(section: str) -> Optional[dict]:
    """Return fee components parsed from a single Fidelity Series fund's
    section, or None if the minimum required rows are not present.
    """
    mgmt_m = _MGMT_RE.search(section)
    total_m = _TOTAL_RE.search(section)
    if not mgmt_m or not total_m:
        return None

    twelve_b1 = _normalize_value(
        m.group(1) if (m := _12B1_RE.search(section)) else None
    )
    other = _normalize_value(
        m.group(1) if (m := _OTHER_RE.search(section)) else None
    )
    waiver = _normalize_value(
        m.group(1) if (m := _WAIVER_RE.search(section)) else None
    )
    net = _normalize_value(
        m.group(1) if (m := _NET_RE.search(section)) else None
    )
    turnover = None
    if (m := _TURNOVER_RE.search(section)) is not None:
        try:
            turnover = float(m.group(1))
        except ValueError:
            turnover = None

    return {
        "management_fee": _normalize_value(mgmt_m.group(1)),
        "twelve_b1_fee": twelve_b1,
        "other_expenses": other,
        "total_annual_expenses": _normalize_value(total_m.group(1)),
        "fee_waiver": waiver,
        "net_expenses": net,
        "portfolio_turnover": turnover,
    }


# ---------------------------------------------------------------------------
# Public entry point

def try_fidelity_series_fees(
    ticker: str,
    fund_class=None,
):
    """Attempt to extract prospectus fees for a Fidelity Series ticker.

    Returns a ProspectusFees on success, None if the ticker is not a
    Fidelity Series building-block fund or if its section cannot be
    parsed from the annual omnibus 485BPOS.

    Args:
        ticker: Fund ticker symbol.
        fund_class: Optional edgartools FundClass (avoids a duplicate
            find_fund call when the caller already has one).
    """
    # Deferred import avoids circular dependency with prospectus.py.
    from fundautopsy.data.prospectus import ProspectusFees

    ticker_upper = ticker.upper()

    # End-to-end cache short-circuit. When a fund-of-funds walks through
    # multiple Fidelity Series underlyings, repeated calls for the same
    # ticker would otherwise repeat the full EDGAR + HTML parse cycle.
    cached = _TICKER_FEES_CACHE.get(ticker_upper)
    if cached is not None:
        if cached.get("__negative__"):
            return None
        return ProspectusFees(
            ticker=ticker_upper,
            class_name=cached.get("class_name") or "",
            total_annual_expenses=cached.get("total_annual_expenses"),
            net_expenses=cached.get("net_expenses"),
            management_fee=cached.get("management_fee"),
            twelve_b1_fee=cached.get("twelve_b1_fee"),
            other_expenses=cached.get("other_expenses"),
            fee_waiver=cached.get("fee_waiver"),
            portfolio_turnover=cached.get("portfolio_turnover"),
        )

    try:
        fc = fund_class if fund_class is not None else edgar.find_fund(ticker_upper)
        if fc is None:
            _cache_ticker_fees(ticker_upper, {"__negative__": True})
            return None

        # Fast-path gate: only proceed for Fidelity Series funds. Every
        # other Fidelity product either has its own 497K or parses via
        # edgartools' 497K pipeline correctly.
        series_name = None
        try:
            series_name = fc.series.name
        except Exception:
            pass
        if not _is_fidelity_series_fund(series_name):
            # Negative-cache so repeated walks of the same non-Fidelity-Series
            # ticker during a decomposition skip the find_fund round-trip on
            # the second and subsequent calls.
            _cache_ticker_fees(ticker_upper, {"__negative__": True})
            return None

        filings = fc.series.get_filings(form="485BPOS")
        if len(filings) == 0:
            _cache_ticker_fees(ticker_upper, {"__negative__": True})
            return None

        filing = _find_485bpos_for_ticker(filings, ticker_upper)
        if filing is None:
            _cache_ticker_fees(ticker_upper, {"__negative__": True})
            return None

        registrant = _extract_registrant_name(filing)
        if not _is_fidelity_registrant(registrant):
            _cache_ticker_fees(ticker_upper, {"__negative__": True})
            return None

        # Accession-keyed cache: the omnibus 485BPOS is ~14 MB and the
        # same filing covers every Fidelity Series fund in a given
        # cohort. Skip the download + HTML-clean cost on repeat hits.
        accession = getattr(filing, "accession_no", None)
        text = _CLEAN_TEXT_CACHE.get(accession) if accession else None
        if text is None:
            primary = filing.homepage.primary_html_document
            if primary is None:
                _cache_ticker_fees(ticker_upper, {"__negative__": True})
                return None
            content = primary.download()
            text = _clean_html(content)
            if accession:
                _cache_clean_text(accession, text)

        section = _find_fund_section(text, series_name)
        if section is None:
            logger.debug(
                "Fidelity Series parser: section not found for %s (%s) in %s",
                ticker_upper, series_name, filing.accession_no,
            )
            _cache_ticker_fees(ticker_upper, {"__negative__": True})
            return None

        parsed = _parse_fidelity_section(section)
        if parsed is None or parsed.get("total_annual_expenses") is None:
            logger.debug(
                "Fidelity Series parser: fee rows not parseable for %s in %s",
                ticker_upper, filing.accession_no,
            )
            _cache_ticker_fees(ticker_upper, {"__negative__": True})
            return None

        # Positive cache populated on the success path. Stored as a dict
        # (not the ProspectusFees dataclass) to keep the cache module free
        # of the circular import at load time.
        _cache_ticker_fees(
            ticker_upper,
            {
                "class_name": series_name,
                "total_annual_expenses": parsed["total_annual_expenses"],
                "net_expenses": parsed["net_expenses"],
                "management_fee": parsed["management_fee"],
                "twelve_b1_fee": parsed["twelve_b1_fee"],
                "other_expenses": parsed["other_expenses"],
                "fee_waiver": parsed["fee_waiver"],
                "portfolio_turnover": parsed["portfolio_turnover"],
            },
        )

        return ProspectusFees(
            ticker=ticker_upper,
            class_name=series_name,  # Fidelity Series funds are single-class
            total_annual_expenses=parsed["total_annual_expenses"],
            net_expenses=parsed["net_expenses"],
            management_fee=parsed["management_fee"],
            twelve_b1_fee=parsed["twelve_b1_fee"],
            other_expenses=parsed["other_expenses"],
            fee_waiver=parsed["fee_waiver"],
            portfolio_turnover=parsed["portfolio_turnover"],
        )
    except Exception as exc:
        logger.warning(
            "Fidelity Series fee parser failed for %s: %s", ticker_upper, exc
        )
        # Don't negative-cache transient failures — an EDGAR hiccup on
        # one call shouldn't poison the cache for subsequent retries.
        return None
