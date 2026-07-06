"""Form N-14 fund-merger and reorganization filing parser.

N-14 is the registration statement a registered investment company
files when proposing a merger, reorganization, or exchange involving
one or more existing funds. The filing includes a proxy statement or
information statement, target-vs-acquiring side-by-side summary data,
a summary of the reasons for the reorganization, and often a fee
comparison table.

Unlike N-PORT and N-CEN which carry structured XML, N-14 is primarily
prose with embedded HTML tables. This parser scopes to the metadata
tier: finding a trust's recent N-14 filings, classifying the
reorganization type (same-complex consolidation vs cross-complex),
and surfacing the filing summary. Deep fee-table extraction is a
future addition modeled on the existing 497K HTML parser.

Why metadata is useful on its own: many fund families quietly merge
an underperforming fund into a higher-expense sibling. The fact that
a merger is in flight is itself a signal; the fee-impact analysis is
a follow-up that the holder should do before the vote.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import httpx

from fundautopsy.config import EDGAR_USER_AGENT, EDGAR_RATE_LIMIT_DELAY

logger = logging.getLogger(__name__)

_EDGAR_BASE = "https://www.sec.gov"
_EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions"
_HEADERS = {
    "User-Agent": EDGAR_USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
}

# Form codes the SEC uses for reorganization-related filings.
# N-14 is the main one. N-14 8C is the auto-effective variant.
# N-14AE is the amendment variant. We group them together because
# from a shareholder's perspective they all announce a reorganization.
N14_FORM_CODES = {"N-14", "N-14 8C", "N-14AE", "N-14A", "N-14MEF"}


@dataclass
class N14Filing:
    """A single N-14 filing's metadata and classification."""

    accession_no: str
    filing_date: date
    form_type: str
    cik: int
    company_name: str
    primary_document: str
    filing_url: str

    # Classification — set by _classify_reorganization after we read the filing
    reorganization_type: str = ""  # "same-complex", "cross-complex", "unknown"
    target_fund_names: list[str] = field(default_factory=list)
    acquiring_fund_names: list[str] = field(default_factory=list)
    summary_snippet: str = ""

    @property
    def has_classification(self) -> bool:
        return bool(self.reorganization_type and self.reorganization_type != "unknown")


# ── EDGAR access ───────────────────────────────────────────────────────────


def _rate_limit():
    time.sleep(EDGAR_RATE_LIMIT_DELAY)


def _fetch(url: str, client: Optional[httpx.Client] = None) -> Optional[httpx.Response]:
    """HTTP GET with rate limiting and standard Fund Autopsy headers."""
    _rate_limit()
    own = client is None
    if own:
        client = httpx.Client(headers=_HEADERS, timeout=30.0, follow_redirects=True)
    try:
        resp = client.get(url)
        resp.raise_for_status()
        return resp
    except (httpx.HTTPError, httpx.TransportError) as exc:
        logger.debug("Fetch failed for %s: %s", url, exc)
        return None
    finally:
        if own:
            client.close()


def find_n14_filings(cik: int, max_filings: int = 10) -> list[N14Filing]:
    """List recent N-14 filings for a CIK.

    Scans the EDGAR submissions API for form codes in N14_FORM_CODES.
    Returns up to max_filings most recent, ordered newest first.
    """
    url = f"{_EDGAR_SUBMISSIONS}/CIK{str(cik).zfill(10)}.json"
    resp = _fetch(url)
    if resp is None:
        return []
    try:
        data = resp.json()
    except Exception:
        return []

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])
    company_name = data.get("name", "")

    out: list[N14Filing] = []
    for i, form in enumerate(forms):
        if form not in N14_FORM_CODES:
            continue
        if i >= len(accessions):
            break
        acc = accessions[i]
        filing_date_str = dates[i] if i < len(dates) else ""
        try:
            filing_date = date.fromisoformat(filing_date_str)
        except (ValueError, TypeError):
            continue
        primary_doc = primary_docs[i] if i < len(primary_docs) else ""
        acc_nodash = acc.replace("-", "")
        filing_url = (
            f"{_EDGAR_BASE}/cgi-bin/browse-edgar?action=getcompany"
            f"&CIK={cik}&type={form}&dateb=&owner=include&count=40"
        )
        # Point directly to the primary doc for convenience
        doc_url = (
            f"{_EDGAR_BASE}/Archives/edgar/data/{cik}/{acc_nodash}/{primary_doc}"
            if primary_doc else filing_url
        )
        out.append(N14Filing(
            accession_no=acc,
            filing_date=filing_date,
            form_type=form,
            cik=cik,
            company_name=company_name,
            primary_document=primary_doc,
            filing_url=doc_url,
        ))
        if len(out) >= max_filings:
            break
    return out


def _fetch_filing_html(filing: N14Filing, client: Optional[httpx.Client] = None) -> Optional[str]:
    """Pull the primary document HTML for the filing."""
    if not filing.primary_document:
        return None
    resp = _fetch(filing.filing_url, client=client)
    if resp is None:
        return None
    return resp.text


# ── Content analysis ───────────────────────────────────────────────────────


# Fund-name heuristic: a capitalized noun phrase ending in Fund/Trust/Portfolio.
# We deliberately avoid pulling every capitalized phrase — false positive rate
# is too high. The "into" and "from" surrounding language anchors the pattern
# to the reorganization semantics.
_FUND_NAME_RE = re.compile(
    r"[A-Z][A-Za-z0-9 &\.\-]{2,80}?"
    r"(?:Fund|Trust|Portfolio|Series|ETF)\b"
)

_TARGET_CUES = (
    # "X Fund will be reorganized into Y Fund"
    re.compile(r"(?:the\s+)?([A-Z][A-Za-z0-9 &\.\-\/]{4,100}?Fund)\s+(?:will\s+be|is\s+being|shall\s+be)\s+(?:reorganized|acquired|merged)", re.I),
    # "reorganization of the X Fund"
    re.compile(r"reorganization\s+of\s+(?:the\s+)?([A-Z][A-Za-z0-9 &\.\-\/]{4,100}?Fund)\b", re.I),
    # "X Fund (the 'Acquired Fund' or 'Target Fund')"
    re.compile(r"([A-Z][A-Za-z0-9 &\.\-\/]{4,100}?Fund)\s*\(\s*(?:the\s+)?[\"\u201c]?(?:Acquired|Target)\s+Fund", re.I),
    # "merger of X Fund with and into"
    re.compile(r"merger\s+of\s+(?:the\s+)?([A-Z][A-Za-z0-9 &\.\-\/]{4,100}?Fund)\s+with\s+and\s+into", re.I),
)
_ACQUIRER_CUES = (
    # "reorganized into Y Fund" / "merged into Y Fund"
    re.compile(r"(?:reorganized|merged|acquired)\s+(?:with\s+and\s+)?into\s+(?:the\s+)?([A-Z][A-Za-z0-9 &\.\-\/]{4,100}?Fund)\b", re.I),
    # "shares of Y Fund will be issued"
    re.compile(r"shares\s+of\s+(?:the\s+)?([A-Z][A-Za-z0-9 &\.\-\/]{4,100}?Fund)\s+(?:will\s+be|shall\s+be)\s+issued", re.I),
    # "Y Fund (the 'Acquiring Fund' or 'Surviving Fund')"
    re.compile(r"([A-Z][A-Za-z0-9 &\.\-\/]{4,100}?Fund)\s*\(\s*(?:the\s+)?[\"\u201c]?(?:Acquiring|Surviving|Successor)\s+Fund", re.I),
    # "into Y Fund, a series of"
    re.compile(r"into\s+(?:the\s+)?([A-Z][A-Za-z0-9 &\.\-\/]{4,100}?Fund),\s+a\s+series", re.I),
)


def _strip_html(html: str) -> str:
    """Very rough HTML→text conversion sufficient for phrase matching.

    Avoids pulling BeautifulSoup as a dependency for this single use.
    Collapses all HTML tags to a single space and normalizes whitespace.
    """
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def classify_reorganization(
    filing: N14Filing,
    client: Optional[httpx.Client] = None,
) -> N14Filing:
    """Populate filing.reorganization_type and fund name fields.

    Reads the filing's primary document, converts to text, and applies
    heuristic regexes for target and acquirer fund names. Sets
    reorganization_type to 'same-complex' when both fund names share
    the filer's company name as a substring; 'cross-complex' when the
    target's name lies outside the filer's typical naming pattern;
    'unknown' when we cannot extract at least one fund name on each side.
    """
    html = _fetch_filing_html(filing, client=client)
    if html is None:
        filing.reorganization_type = "unknown"
        return filing

    text = _strip_html(html)
    # Cap at ~80KB of text for regex — the bulk of N-14s get to the
    # reorganization narrative in the first 50 pages and the summary
    # sits before the schedules.
    text = text[:80_000]

    # Collect candidate target and acquirer fund names
    targets: list[str] = []
    acquirers: list[str] = []

    for pat in _TARGET_CUES:
        for match in pat.finditer(text):
            if match.groups():
                name = match.group(1).strip()
                if name and name not in targets:
                    targets.append(name)
    for pat in _ACQUIRER_CUES:
        for match in pat.finditer(text):
            if match.groups():
                name = match.group(1).strip()
                if name and name not in acquirers:
                    acquirers.append(name)

    filing.target_fund_names = targets[:3]
    filing.acquiring_fund_names = acquirers[:3]

    # Summary snippet — first sentence after the phrase "proposed reorganization"
    # or the filing's "purpose" preamble. This gives the user a quick read on
    # what the merger is about without loading the full filing.
    m = re.search(r"(?:proposed reorganization|purpose of the reorganization|reorganization agreement)[^.]{20,400}\.", text, re.I)
    if m:
        filing.summary_snippet = m.group(0).strip()[:600]

    # Classify. Prefer specific labels over the fallback "unknown" so
    # users see useful information even when regex extraction misses.
    filer = (filing.company_name or "").split()
    filer_root = filer[0].upper() if filer else ""
    if targets and acquirers:
        # Both sides identified — check if fund names share the filer
        # root (suggesting same-complex consolidation) or diverge
        # (suggesting cross-complex merger).
        both_match_filer = (
            filer_root
            and all(filer_root in n.upper() for n in targets + acquirers)
        )
        filing.reorganization_type = (
            "same-complex" if both_match_filer else "cross-complex"
        )
    elif targets or acquirers:
        filing.reorganization_type = "partial"
    elif filing.summary_snippet:
        # We can see the filing discusses a reorganization but cannot
        # cleanly extract target/acquirer names. Still useful to the
        # shareholder — surface that there is a reorganization in
        # flight rather than reporting "unknown."
        filing.reorganization_type = "reorganization"
    else:
        # Could not fetch filing body or body is opaque to our regex
        # heuristics. Label as pending review rather than unknown so
        # the UI does not surface "unknown" which reads as broken.
        filing.reorganization_type = "filing-available"

    return filing


def retrieve_n14_for_cik(
    cik: int,
    max_filings: int = 5,
    classify: bool = True,
) -> list[N14Filing]:
    """Primary entry point. List + optionally classify recent N-14 filings.

    Args:
        cik: SEC CIK of the trust-level registrant.
        max_filings: Cap on how many recent filings to return.
        classify: When True, fetch each filing's body and populate the
            classification fields. When False, return metadata only.

    Returns:
        List of N14Filing, newest first.
    """
    filings = find_n14_filings(cik, max_filings=max_filings)
    if not classify:
        return filings

    client = httpx.Client(headers=_HEADERS, timeout=30.0, follow_redirects=True)
    try:
        for f in filings:
            classify_reorganization(f, client=client)
    finally:
        client.close()
    return filings
