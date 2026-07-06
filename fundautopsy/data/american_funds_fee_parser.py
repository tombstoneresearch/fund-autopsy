"""American Funds 485BPOS fee-table parser.

edgartools.filing.obj() pairs correct SGML-sourced tickers and class_ids
with scrambled fee-row data on American Funds 497K supplements,
producing impossible results like R-6 classes with 1.00% 12b-1 fees.
This module bypasses edgartools for the American Funds family by
reading the annual 485BPOS (statutory prospectus) directly, extracting
fee-table blocks from the HTML, and aligning the target ticker's column
via the SGML submission header's authoritative class_name.

Detection is by registrant name substring ("American Funds", "AMCAP",
"Fundamental Investors", "Intermediate Bond Fund of America", etc.) and
by SGML class-signature (presence of Class R-6 plus a Class 529-* in
the same series, a lineup unique to American Funds).

Detection is conservative — the helper returns None on any mismatch so
the caller falls through to the existing pipeline. It is not a general
replacement for edgartools.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable, Optional, Tuple

import edgar

logger = logging.getLogger(__name__)

# Deferred import of ProspectusFees happens inside try_american_funds_fees
# to avoid a circular import: prospectus.py imports this module at top level
# to route American Funds through the 485BPOS parser.


# ---------------------------------------------------------------------------
# SGML header parsing

_SGML_CLASS_RE = re.compile(
    r"<CLASS-CONTRACT>\s*"
    r"<CLASS-CONTRACT-ID>([^\n<]+)\s*"
    r"<CLASS-CONTRACT-NAME>([^\n<]+)\s*"
    r"<CLASS-CONTRACT-TICKER-SYMBOL>([^\n<]+)",
)


def _extract_sgml_class_map(filing) -> dict[str, Tuple[str, str]]:
    """Return {ticker_upper: (class_id, class_name)} from filing SGML header."""
    try:
        text = filing.header.text
    except Exception:
        return {}
    out: dict[str, Tuple[str, str]] = {}
    for m in _SGML_CLASS_RE.finditer(text):
        class_id, class_name, ticker = (s.strip() for s in m.groups())
        out[ticker.upper()] = (class_id, class_name)
    return out


def _extract_registrant_name(filing) -> Optional[str]:
    """Pull COMPANY CONFORMED NAME from filing SGML header."""
    try:
        text = filing.header.text
    except Exception:
        return None
    m = re.search(r"COMPANY CONFORMED NAME:\s+(.+)", text)
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# American Funds detection

# Registrant-name substrings that unambiguously identify American Funds
# sub-registrants. Capital Group files each sub-fund under a distinct CIK,
# so detection cannot use a single CIK — name is the lingua franca.
_AF_NAME_SUBSTRINGS = (
    "AMERICAN FUNDS",
    "AMCAP FUND",
    "FUNDAMENTAL INVESTORS",
    "CAPITAL INCOME BUILDER",
    "CAPITAL WORLD GROWTH",
    "GROWTH FUND OF AMERICA",
    "INCOME FUND OF AMERICA",
    "INVESTMENT COMPANY OF AMERICA",
    "WASHINGTON MUTUAL INVESTORS",
    "BOND FUND OF AMERICA",
    "INTERMEDIATE BOND FUND OF AMERICA",
    "NEW PERSPECTIVE FUND",
    "NEW WORLD FUND",
    "EUROPACIFIC GROWTH",
    "SMALLCAP WORLD",
    "AMERICAN BALANCED",
    "AMERICAN HIGH-INCOME",
    "AMERICAN MUTUAL",
    "TAX-EXEMPT BOND FUND OF AMERICA",
    "U.S. GOVERNMENT SECURITIES FUND",
)


def _is_american_funds(
    registrant_name: Optional[str], class_map: dict[str, Tuple[str, str]]
) -> bool:
    if registrant_name:
        upper = registrant_name.upper()
        if any(sub in upper for sub in _AF_NAME_SUBSTRINGS):
            return True
    # Fallback: SGML signature. American Funds uniquely pairs "Class R-6"
    # with one or more "Class 529-*" classes in a single series.
    names = [cn for _, cn in class_map.values()]
    if any(n.strip().lower() == "class r-6" for n in names) and any(
        n.strip().startswith("Class 529-") for n in names
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# HTML cleanup + fee-table extraction

_ENTITY_REPLACEMENTS = (
    ("&nbsp;", " "), ("&#160;", " "),
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


def _normalize_class_label(class_name: str) -> str:
    """SGML uses 'Class R-6'; fee-table header uses 'R-6'."""
    name = class_name.strip()
    if name.lower().startswith("class "):
        return name[6:].strip()
    return name


_SHARE_CLASS_RE = re.compile(r"Share class:\s")
_FEE_BLOCK_END_RE = re.compile(
    r"Total annual fund operating expenses"
    r"(?:\s+after fee waiver)?"
    r"\s+(?:\d+\.\d+|none)(?:\s+(?:\d+\.\d+|none))*"
)


def _find_fee_blocks(text: str) -> list[str]:
    """Return fee-table blocks. A block begins at 'Share class:' and
    contains 'Management fees' within 200 chars; it ends at the next
    'Share class:' or at the last number of the 'Total annual fund
    operating expenses' row."""
    positions = [m.start() for m in _SHARE_CLASS_RE.finditer(text)]
    blocks: list[str] = []
    for i, start in enumerate(positions):
        header_window = text[start : start + 200]
        if "Management fees" not in header_window:
            continue  # not a fee block (shareholder-fees or example table)
        end_boundary = positions[i + 1] if i + 1 < len(positions) else len(text)
        block = text[start:end_boundary]
        end_mo = _FEE_BLOCK_END_RE.search(block)
        if end_mo:
            block = block[: end_mo.end()]
        blocks.append(block)
    return blocks


_LABELS_RE = re.compile(r"Share class:\s+(.+?)\s+Management fees")
_NUM_RE = re.compile(r"\d+\.\d+|none")
_MGMT_RE = re.compile(r"Management fees(?:\s+\d)?\s")
_12B1_RE = re.compile(r"Distribution and/or service \(12b-1\) fees\s")
_OTHER_RE = re.compile(r"Other expenses\s")
_TOTAL_RE = re.compile(r"Total annual fund operating expenses\s")
_NET_RE = re.compile(r"Total annual fund operating expenses after fee waiver\s")
_WAIVER_RE = re.compile(r"Fee waiver(?:\s+\d)?\s")


def _parse_fee_block(block_text: str, target_label: str) -> Optional[dict]:
    """Return fee components for the target class label, or None if this
    block does not contain the label."""
    m = _LABELS_RE.search(block_text)
    if not m:
        return None
    labels = m.group(1).split()
    if target_label not in labels:
        return None
    col = labels.index(target_label)
    n_classes = len(labels)

    def extract_row(pattern: re.Pattern) -> Optional[float]:
        mo = pattern.search(block_text)
        if not mo:
            return None
        rest = block_text[mo.end() : mo.end() + 400]
        tokens = _NUM_RE.findall(rest)
        if len(tokens) < n_classes:
            return None
        val = tokens[col]
        if val == "none":
            return 0.0
        try:
            return float(val)
        except ValueError:
            return None

    return {
        "management_fee": extract_row(_MGMT_RE),
        "twelve_b1_fee": extract_row(_12B1_RE),
        "other_expenses": extract_row(_OTHER_RE),
        "total_annual_expenses": extract_row(_TOTAL_RE),
        "net_expenses": extract_row(_NET_RE),
        "fee_waiver": extract_row(_WAIVER_RE),
        "class_label": target_label,
        "n_classes": n_classes,
    }


# ---------------------------------------------------------------------------
# Public entry point


def try_american_funds_fees(
    ticker: str,
    fund_class=None,
):
    """Attempt to extract prospectus fees for an American Funds ticker.

    Returns a ProspectusFees on success, None if the ticker is not
    American Funds or if the fee table cannot be parsed from the most
    recent 485BPOS.

    Args:
        ticker: Fund ticker symbol.
        fund_class: Optional edgartools FundClass (avoids a duplicate
            find_fund call when the caller already has one).
    """
    # Deferred import avoids circular dependency with prospectus.py.
    from fundautopsy.data.prospectus import ProspectusFees

    ticker_upper = ticker.upper()
    try:
        fc = fund_class if fund_class is not None else edgar.find_fund(ticker_upper)
        if fc is None:
            return None
        filings = fc.series.get_filings(form="485BPOS")
        if len(filings) == 0:
            return None
        filing = filings[0]

        class_map = _extract_sgml_class_map(filing)
        registrant = _extract_registrant_name(filing)
        if not _is_american_funds(registrant, class_map):
            return None

        meta = class_map.get(ticker_upper)
        if not meta:
            # Ticker not present in SGML — the 485BPOS is for a different
            # fund. Let caller fall through to normal 497K pipeline.
            return None
        class_id, class_name = meta
        target_label = _normalize_class_label(class_name)

        primary = filing.homepage.primary_html_document
        if primary is None:
            return None
        content = primary.download()
        text = _clean_html(content)

        for block in _find_fee_blocks(text):
            parsed = _parse_fee_block(block, target_label)
            if parsed and parsed.get("total_annual_expenses") is not None:
                return ProspectusFees(
                    ticker=ticker_upper,
                    class_name=class_name,
                    total_annual_expenses=parsed["total_annual_expenses"],
                    net_expenses=parsed["net_expenses"],
                    management_fee=parsed["management_fee"],
                    twelve_b1_fee=parsed["twelve_b1_fee"],
                    other_expenses=parsed["other_expenses"],
                    fee_waiver=parsed["fee_waiver"],
                )
        logger.debug(
            "American Funds parser found no matching fee block for %s (target=%s) "
            "in 485BPOS %s",
            ticker_upper, target_label, filing.accession_no,
        )
        return None
    except Exception as exc:
        logger.warning(
            "American Funds fee parser failed for %s: %s", ticker_upper, exc
        )
        return None
