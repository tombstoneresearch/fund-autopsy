"""Direct 497K fee table HTML parser.

Fallback parser that extracts fee data directly from 497K filing HTML
when edgartools' built-in parser returns None values. Handles three
known HTML layout patterns:

1. Standard SEC table (most fund families) — <TR> rows with label + percent cells
2. Multi-column trust filings (Oakmark, etc.) — header row identifies share class columns
3. Div-based layouts (Fidelity) — nested <div> with inline styles instead of <table>

Also handles multi-fund trusts that file separate 497Ks per share class
by searching through filings to find the one containing the target ticker.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from lxml import html as lxml_html

logger = logging.getLogger(__name__)


# Fee percentage sanity threshold. Values above this trigger a warning log
# but are still returned. Set high enough that legitimate high-cost funds
# (CEFs with leverage, multi-layer FoFs) pass through while catching
# obvious parse errors like extracting a year (e.g., "2024" → 2024%).
FEE_SANITY_THRESHOLD_PCT: float = 20.0

# Canonical fee row labels and their field mappings
_LABEL_MAP = {
    "management fee": "management_fee",
    "management fees": "management_fee",
    "distribution and/or service": "twelve_b1_fee",
    "distribution (12b": "twelve_b1_fee",
    "12b-1": "twelve_b1_fee",
    "other expense": "other_expenses",
    "acquired fund fee": "acquired_fund_fees",
    "total annual fund operating": "total_annual_expenses",
    "total annual operating": "total_annual_expenses",
    "total fund operating": "total_annual_expenses",
    "fee waiver": "fee_waiver",
    "expense reimbursement": "fee_waiver",
    "net expense": "net_expenses",
    "net annual": "net_expenses",
    "total annual fund operating expenses after": "net_expenses",
}

_TURNOVER_PATTERN = re.compile(
    r"(?:portfolio\s+turnover|turnover\s+rate).*?(\d+)\s*%", re.IGNORECASE | re.DOTALL
)

_LOAD_PATTERN = re.compile(
    r"maximum\s+(?:initial\s+)?sales\s+(?:charge|load).*?(\d+\.?\d*)\s*%",
    re.IGNORECASE | re.DOTALL,
)

_PCT_PATTERN = re.compile(r"(\d+\.?\d*)\s*%")
_NUM_PATTERN = re.compile(r"(\d+\.?\d*)")

# Strips an XML processing instruction (e.g. `<?xml version="1.0" encoding="UTF-8"?>`)
# from the head of an HTML document. lxml_html.fromstring() refuses to parse a
# unicode string that declares an encoding, and 485BPOS filings from some
# registrants (Fidelity Concord Street Trust, Oakmark, MFS) ship with one.
_XML_DECL_PATTERN = re.compile(r"^\s*<\?xml[^>]*\?>\s*", re.IGNORECASE)


def _parse_html(html_str: str):
    """lxml_html.fromstring with XML-decl stripping.

    Mutual-fund registrants ship prospectus HTML with a leading
    <?xml ... encoding="UTF-8"?> processing instruction, which lxml
    rejects when given a unicode string. We strip it before parsing
    so downstream lxml code runs on any registrant's HTML.
    """
    cleaned = _XML_DECL_PATTERN.sub("", html_str, count=1)
    return lxml_html.fromstring(cleaned)


@dataclass
class ParsedFees:
    """Fee data extracted directly from 497K HTML."""

    management_fee: Optional[float] = None
    twelve_b1_fee: Optional[float] = None
    other_expenses: Optional[float] = None
    acquired_fund_fees: Optional[float] = None
    total_annual_expenses: Optional[float] = None
    fee_waiver: Optional[float] = None
    net_expenses: Optional[float] = None
    max_sales_load: Optional[float] = None
    portfolio_turnover: Optional[float] = None
    fee_threshold_warning: bool = False  # True if any parsed value exceeded FEE_SANITY_THRESHOLD_PCT

    @property
    def has_data(self) -> bool:
        """True if at least management_fee or total_annual_expenses was parsed."""
        return self.management_fee is not None or self.total_annual_expenses is not None


def _extract_pct(text: str) -> Optional[float]:
    """Pull the first percentage value from a cell's text content."""
    text = text.strip()
    if not text or text.lower() in ("none", "n/a", "—", "–", "-"):
        return None
    m = _PCT_PATTERN.search(text)
    if m:
        return float(m.group(1))
    m = _NUM_PATTERN.search(text)
    if m:
        val = float(m.group(1))
        # Values >= 100 are almost certainly years or other non-fee numbers
        # (no fund charges 100%+ annual fees). Reject them outright.
        if val >= 100:
            logger.debug(
                "Rejecting extracted value %.0f (likely year or non-fee number) from: %r",
                val, text[:80],
            )
            return None
        if val < FEE_SANITY_THRESHOLD_PCT:
            return val
        # Value exceeds soft threshold but is plausible (CEFs with leverage,
        # layered FoFs). Log warning but still return it.
        logger.warning(
            "Parsed fee value %.2f%% exceeds %.0f%% sanity threshold — "
            "verify manually (source text: %r)",
            val, FEE_SANITY_THRESHOLD_PCT, text[:80],
        )
        return val
    return None


def _match_label(text: str) -> Optional[str]:
    """Match a row label to a ParsedFees field name."""
    # Normalize whitespace, line breaks, and non-breaking spaces
    lower = re.sub(r"[\s\xa0]+", " ", text.lower().strip())
    for pattern, field_name in _LABEL_MAP.items():
        if pattern in lower:
            return field_name
    return None


def _find_class_column(header_texts: list[str], ticker: str) -> int:
    """Identify which column index corresponds to the target share class.

    In multi-class tables, the header row contains class names or tickers.
    Returns 0-based index into the data columns (excluding the label column).
    """
    ticker_upper = ticker.upper()
    for i, text in enumerate(header_texts):
        if ticker_upper in text.upper():
            return i
    # Fall back: check for class name patterns
    # "Investor Class", "Class I", etc.
    for i, text in enumerate(header_texts):
        for label in ("investor", "class i ", "class i\xa0", "class a"):
            if label in text.lower():
                return i
    return 0  # default to first column


def _parse_table_rows(
    html_str: str, ticker: str, start_offset: int = 0
) -> ParsedFees:
    """Parse fee data from standard HTML table rows."""
    fees = ParsedFees()

    # Find the fee table region
    lower = html_str.lower()
    anchors = [
        "annual fund operating expense",
        "annual operating expense",
        "fee table",
    ]
    table_start = -1
    for anchor in anchors:
        idx = lower.find(anchor, start_offset)
        if idx >= 0:
            table_start = idx
            break

    if table_start < 0:
        return fees

    # Extract a generous region around the fee table
    region = html_str[max(0, table_start - 500) : table_start + 8000]
    tree = lxml_html.fromstring(region)
    rows = tree.xpath(".//tr")

    if not rows:
        return fees

    # Detect multi-class header to find the right column
    target_col = 0
    for row in rows[:5]:
        cells = row.xpath(".//td")
        texts = [c.text_content().strip() for c in cells]
        texts_clean = [t for t in texts if t]
        # Header row typically has class names or tickers
        if len(texts_clean) >= 2 and not any(
            kw in " ".join(texts_clean).lower()
            for kw in ("management", "distribution", "expense", "fee")
        ):
            target_col = _find_class_column(texts_clean, ticker)

    # Parse fee rows
    for row in rows:
        cells = row.xpath(".//td")
        texts = [c.text_content().strip() for c in cells]
        if not texts:
            continue

        # Try matching the label from the first cell
        label_text = texts[0]
        field_name = _match_label(label_text)
        if field_name is None:
            # Some filings split the label with <BR> tags across the first cell.
            # Only try full-row matching if the first cell looks like a split label,
            # NOT a footnote. Footnotes start with *, **, †, (1), etc.
            first = texts[0].strip()
            is_footnote = bool(re.match(r"^[\*†\(\d]", first))
            if not is_footnote and len(first) < 60:
                full_row_text = " ".join(t for t in texts if not _PCT_PATTERN.fullmatch(t.strip()))
                field_name = _match_label(full_row_text)
            if field_name is None:
                continue

        # Collect all value cells (skip the label cell)
        value_texts = [t for t in texts[1:] if t]

        if not value_texts:
            continue

        # For multi-column tables, pick the right column
        # Value cells might be split: ["0.50", "%"] or combined: ["0.50%"]
        # Reconstruct by joining consecutive cells
        joined = " ".join(value_texts)
        # Split by column boundaries (look for multiple percentages)
        col_values = _PCT_PATTERN.findall(joined)

        if col_values and target_col < len(col_values):
            val = float(col_values[target_col])
        elif col_values:
            val = float(col_values[0])
        else:
            val = _extract_pct(joined)

        if val is not None:
            setattr(fees, field_name, val)

    return fees


def _parse_div_layout(html_str: str, ticker: str) -> ParsedFees:
    """Parse fee data from div-based layouts (Fidelity style)."""
    fees = ParsedFees()
    tree = _parse_html(html_str)

    # In div-based layouts, fee rows are table rows where the first cell
    # has the label and the second has the value, but styled with <div>/<font>
    rows = tree.xpath(".//tr")
    for row in rows:
        cells = row.xpath(".//td")
        if len(cells) < 2:
            continue
        label_text = cells[0].text_content().strip()
        field_name = _match_label(label_text)
        if field_name is None:
            continue
        value_text = cells[1].text_content().strip()
        val = _extract_pct(value_text)
        if val is not None:
            setattr(fees, field_name, val)

    return fees


def parse_497k_html(
    html_str: str,
    ticker: str,
    fund_name: Optional[str] = None,
) -> ParsedFees:
    """Extract fee data from raw 497K filing HTML.

    Tries table-based parsing first, falls back to div-based for
    Fidelity-style filings.

    Args:
        html_str: Raw HTML content of the 497K filing.
        ticker: Fund ticker to match the correct share class column.
        fund_name: Optional fund name for multi-fund filings.

    Returns:
        ParsedFees with extracted values.
    """
    # Try standard table parsing
    fees = _parse_table_rows(html_str, ticker)
    if fees.has_data:
        # Extract turnover and load from the full document
        _extract_turnover_and_load(html_str, fees)
        return fees

    # Try div-based layout
    fees = _parse_div_layout(html_str, ticker)
    if fees.has_data:
        _extract_turnover_and_load(html_str, fees)
        return fees

    return fees


def _extract_turnover_and_load(html_str: str, fees: ParsedFees) -> None:
    """Extract portfolio turnover and sales load from full document text."""
    text = _parse_html(html_str).text_content()

    m = _TURNOVER_PATTERN.search(text)
    if m:
        fees.portfolio_turnover = float(m.group(1))

    m = _LOAD_PATTERN.search(text)
    if m:
        fees.max_sales_load = float(m.group(1))


def find_filing_for_ticker(
    filings_497k, ticker: str, max_search: int = 50
) -> Optional[object]:
    """Search through 497K filings to find the one containing the target ticker.

    Some trusts file separate 497Ks per share class or per fund. Large
    fund families (Fidelity, Vanguard, American Funds) file dozens of
    separate 497Ks under the same registrant, and the filing that
    corresponds to the requested ticker may not be near the top of the
    list. Fidelity Investment Trust (CIK 744822) carries ~750 497Ks
    across dozens of series, so a 50-filing cap silently failed for
    every Fidelity Series ticker.

    Strategy, in order:
      0. Cache hit on a previously-resolved accession number. O(N)
         metadata scan over the current filings list with no HTML parse.
      1. SGML submission-header scan. Every 497K carries a
         <SERIES-AND-CLASSES-CONTRACTS-DATA> block that names the
         SERIES-ID, CLASS-CONTRACT-ID, and CLASS-CONTRACT-TICKER-SYMBOL
         the filing covers. This is authoritative (filed directly to
         EDGAR), cheap (~150 ms per filing, no HTML parse), and so it
         scans the full filings list rather than a narrow window.
      2. edgartools share-class parse — fallback for the rare filing
         where the SGML block is absent but the parsed object carries
         ticker data.
      3. HTML substring search — last-resort cheap grep.

    Args:
        filings_497k: edgartools filing collection filtered to 497K.
        ticker: Target fund ticker.
        max_search: Maximum filings for the expensive fallback passes
            (edgartools .obj() and HTML substring). The cheap SGML
            pass scans the full list regardless.

    Returns:
        The matching filing object, or None.
    """
    from fundautopsy.data.filing_lookup_cache import get_default_cache

    ticker_upper = ticker.upper()
    total = len(filings_497k)
    bound = min(max_search, total)
    cache = get_default_cache()

    # Pass 0: cache-assisted lookup. Accession numbers are immutable, so a
    # previously-matched accession still present in the current filings
    # list is a valid answer without re-parsing any HTML. Negative cache
    # entries short-circuit to None so repeat failures do not re-scan.
    cached = cache.lookup(ticker_upper)
    if cached is not None:
        if cached.get("not_found"):
            logger.debug(
                "find_filing_for_ticker negative cache hit for %s", ticker_upper,
            )
            return None
        target_accession = cached.get("accession")
        if target_accession:
            # Scan by accession_number only — cheap metadata attribute.
            for i in range(total):
                try:
                    if getattr(filings_497k[i], "accession_number", None) == target_accession:
                        logger.debug(
                            "find_filing_for_ticker cache hit for %s -> %s",
                            ticker_upper, target_accession,
                        )
                        return filings_497k[i]
                except Exception:
                    continue
            # Cached accession no longer in list; evict and fall through.
            cache.evict(ticker_upper)

    # Resolve class_id/series_id hints for the target ticker so that
    # umbrella trusts (PIMCO Funds, Fidelity Investment Trust, Fidelity
    # Concord Street) can be matched even when ticker text is missing
    # from a filing's body.
    target_class_id: Optional[str] = None
    target_series_id: Optional[str] = None
    try:
        import edgar as _edgar
        fc = _edgar.find_fund(ticker_upper)
        if fc is not None:
            target_class_id = getattr(fc, "class_id", None)
            s = getattr(fc, "series", None)
            target_series_id = getattr(s, "series_id", None) if s is not None else None
    except Exception:
        pass

    # Pass 1: SGML submission-header scan.
    # Scans a generous window of filings because header fetches are
    # cheap (~120 ms) and the target 497K for a given share class in
    # a large umbrella trust (Fidelity Investment Trust, ~750 filings)
    # will not sit near the top of the list. Cap the scan at
    # SGML_SCAN_CAP to bound worst-case cold-lookup latency when a
    # ticker genuinely has no 497K (e.g., Fidelity Series building-
    # block funds that appear only in 485BPOS combined prospectuses).
    # Matching in priority order: ticker tag first (unambiguous),
    # then class-id (handles ticker-symbol elisions), then series-id
    # (only accepted when the target series has exactly one share
    # class, which makes the match unambiguous).
    SGML_SCAN_CAP: int = 400
    sgml_bound = min(SGML_SCAN_CAP, total)
    single_class_series = False
    if target_class_id and target_series_id:
        # Single-share-class series: series-id match is sufficient.
        # Detected via edgartools' class list on the series object.
        try:
            classes = fc.series.get_classes() if fc is not None else []
            single_class_series = len(classes) == 1
        except Exception:
            single_class_series = False

    ticker_re = re.compile(
        rf"<CLASS-CONTRACT-TICKER-SYMBOL>\s*{re.escape(ticker_upper)}\b",
        re.IGNORECASE,
    )
    class_id_re = (
        re.compile(
            rf"<CLASS-CONTRACT-ID>\s*{re.escape(target_class_id)}\b",
            re.IGNORECASE,
        )
        if target_class_id else None
    )
    series_id_re = (
        re.compile(
            rf"<SERIES-ID>\s*{re.escape(target_series_id)}\b",
            re.IGNORECASE,
        )
        if (target_series_id and single_class_series) else None
    )

    for i in range(sgml_bound):
        try:
            hdr_text = filings_497k[i].header.text
        except Exception as exc:
            logger.debug(
                "find_filing_for_ticker: header fetch failed on filing %d for %s: %s",
                i, ticker_upper, exc,
            )
            continue
        if not hdr_text:
            continue
        if ticker_re.search(hdr_text):
            _cache_hit(cache, ticker_upper, filings_497k[i], target_class_id)
            return filings_497k[i]
        if class_id_re is not None and class_id_re.search(hdr_text):
            _cache_hit(cache, ticker_upper, filings_497k[i], target_class_id)
            return filings_497k[i]
        if series_id_re is not None and series_id_re.search(hdr_text):
            _cache_hit(cache, ticker_upper, filings_497k[i], target_class_id)
            return filings_497k[i]

    # Pass 2: edgartools share-class parse (bounded fallback).
    for i in range(bound):
        try:
            obj = filings_497k[i].obj()
            if obj is None:
                continue
            for sc in obj.share_classes:
                if sc.ticker and sc.ticker.upper() == ticker_upper:
                    _cache_hit(cache, ticker_upper, filings_497k[i], target_class_id)
                    return filings_497k[i]
                if target_class_id and getattr(sc, "class_id", None) == target_class_id:
                    _cache_hit(cache, ticker_upper, filings_497k[i], target_class_id)
                    return filings_497k[i]
        except Exception as exc:
            logger.debug(
                "Error inspecting 497K filing %d share classes for %s: %s",
                i, ticker, exc,
            )
            continue

    # Pass 3: HTML substring fallback (bounded).
    for i in range(bound):
        try:
            html = filings_497k[i].html()
            if html and ticker_upper in html:
                _cache_hit(cache, ticker_upper, filings_497k[i], target_class_id)
                return filings_497k[i]
        except Exception as exc:
            logger.debug(
                "Error searching 497K filing %d HTML for %s: %s",
                i, ticker, exc,
            )
            continue
    # Record a negative result so repeated resolver calls for the same
    # ticker inside a single bottom-up decomposition do not each repeat
    # the exhaustive scan.
    try:
        cache.store_not_found(ticker_upper)
    except Exception as exc:
        logger.debug(
            "find_filing_for_ticker failed to record not-found for %s: %s",
            ticker_upper, exc,
        )
    return None


def _cache_hit(cache, ticker_upper: str, filing, class_id: Optional[str]) -> None:
    """Record a successful resolution so future calls skip the expensive pass."""
    try:
        accession = getattr(filing, "accession_number", None)
        if accession:
            cache.store(ticker_upper, accession, class_id)
    except Exception as exc:
        logger.debug(
            "find_filing_for_ticker failed to cache %s: %s",
            ticker_upper, exc,
        )
