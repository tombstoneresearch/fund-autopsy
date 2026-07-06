"""N-CSR (Annual/Semi-Annual Shareholder Report) parser.

Extracts realized brokerage commission data from N-CSR filings on SEC EDGAR.
N-CSR contains the audited financial statements and supplementary schedules
that funds are required to include in shareholder reports:

  - Brokerage commissions paid (multi-year dollar history)
  - Commissions directed for research (soft dollar breakout)
  - Portfolio turnover rate (realized, not projected)
  - Expense ratios by share class (actual vs. prospectus)
  - Board basis for approving advisory contracts

N-CSR filings are HTML on EDGAR, filed annually (N-CSR) or semi-annually
(N-CSRS). They complement N-CEN by providing audited commission figures
with year-over-year comparisons.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

from fundautopsy.config import EDGAR_RATE_LIMIT_DELAY


@dataclass
class NCSRCommissions:
    """Brokerage commission data from N-CSR financial statements."""
    fund_name: str = ""
    # {year: dollar_amount} — realized commissions from audited financials
    annual_commissions: dict[int, float] = field(default_factory=dict)
    # Soft dollar / research-directed commissions if broken out
    research_commissions: dict[int, float] = field(default_factory=dict)
    # Commission recapture amounts if disclosed
    recapture_amounts: dict[int, float] = field(default_factory=dict)


@dataclass
class NCSRTurnover:
    """Portfolio turnover rates from N-CSR."""
    fund_name: str = ""
    # {year: turnover_pct} — realized turnover from financial highlights
    annual_turnover: dict[int, float] = field(default_factory=dict)


@dataclass
class NCSRExpenseRatio:
    """Actual expense ratios from N-CSR financial highlights."""
    fund_name: str = ""
    share_class: str = ""
    # {year: pct} — actual (not prospectus) expense ratios
    annual_ratios: dict[int, float] = field(default_factory=dict)
    # Net investment income ratio
    annual_net_income_ratios: dict[int, float] = field(default_factory=dict)


@dataclass
class ParsedNCSR:
    """Complete parsed N-CSR data."""
    fund_name: str = ""
    cik: int = 0
    filing_date: str = ""
    accession_no: str = ""
    is_annual: bool = True  # N-CSR (annual) vs N-CSRS (semi-annual)

    commissions: list[NCSRCommissions] = field(default_factory=list)
    turnover: list[NCSRTurnover] = field(default_factory=list)
    expense_ratios: list[NCSRExpenseRatio] = field(default_factory=list)

    # Board advisory contract approval narrative
    board_approval_text: str = ""

    @property
    def has_data(self) -> bool:
        """True if any commission or turnover data was parsed."""
        return bool(self.commissions) or bool(self.turnover)


# ── EDGAR access ─────────────────────────────────────────────────────────────

def _fetch_edgar(url: str):
    """Fetch from EDGAR with rate limiting."""
    import httpx
    from fundautopsy.config import EDGAR_USER_AGENT

    time.sleep(EDGAR_RATE_LIMIT_DELAY)
    with httpx.Client(
        headers={
            "User-Agent": EDGAR_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        },
        timeout=30.0,
        follow_redirects=True,
    ) as client:
        return client.get(url)


def _find_ncsr_filing(cik: int, annual_only: bool = False) -> Optional[dict]:
    """Find the most recent N-CSR or N-CSRS filing for a CIK."""
    url = f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json"
    r = _fetch_edgar(url)
    if r.status_code != 200:
        return None

    data = r.json()
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])

    target_forms = ["N-CSR"] if annual_only else ["N-CSR", "N-CSRS"]

    for i, form in enumerate(forms):
        if form in target_forms and i < len(accessions):
            return {
                "accession_no": accessions[i],
                "filing_date": dates[i] if i < len(dates) else "",
                "primary_doc": primary_docs[i] if i < len(primary_docs) else "",
                "cik": cik,
                "is_annual": form == "N-CSR",
            }
    return None


def _fetch_ncsr_html(cik: int, accession_no: str, primary_doc: str) -> Optional[str]:
    """Download the N-CSR HTML document."""
    acc_nodash = accession_no.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{primary_doc}"
    r = _fetch_edgar(url)
    if r.status_code == 200:
        return r.text
    return None


# ── HTML parsing utilities ───────────────────────────────────────────────────

def _clean_text(html_fragment: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    text = re.sub(r'<[^>]+>', ' ', html_fragment)
    text = re.sub(r'&nbsp;|&#160;', ' ', text)
    text = re.sub(r'&amp;|&#38;', '&', text)
    text = re.sub(r'&mdash;|&#8212;', '—', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _extract_section(html: str, start_patterns: list[str],
                     end_patterns: list[str], max_chars: int = 30000) -> str:
    """Extract a section of text between start and end patterns."""
    start_pos = None
    for pattern in start_patterns:
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            start_pos = m.start()
            break

    if start_pos is None:
        return ""

    section = html[start_pos:start_pos + max_chars]

    end_pos = len(section)
    for pattern in end_patterns:
        m = re.search(pattern, section[1000:], re.IGNORECASE)
        if m:
            end_pos = min(end_pos, m.start() + 1000)
            break

    return section[:end_pos]


# ── Commission parsing ───────────────────────────────────────────────────────

def _parse_commission_schedule(html: str) -> list[NCSRCommissions]:
    """Extract brokerage commission schedule from N-CSR.

    N-CSR commission schedules typically appear in a section titled
    "Brokerage Commissions" or "Portfolio Transactions" with a table
    showing fund name, year, and dollar amounts. Many include a
    breakdown of research-directed commissions.
    """
    results = []

    section = _extract_section(
        html,
        [r'(?i)brokerage\s+commissions?\s+paid',
         r'(?i)aggregate\s+brokerage\s+commissions',
         r'(?i)total\s+brokerage\s+commissions',
         r'(?i)commissions?\s+on\s+portfolio\s+transactions'],
        [r'(?i)(?:securities\s+of\s+regular|directed\s+brokerage)',
         r'(?i)(?:other\s+information|financial\s+highlights)',
         r'(?i)(?:additional\s+information|board\s+of)'],
        max_chars=20000
    )

    if not section:
        return results

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return results

    soup = BeautifulSoup(section, 'html.parser')
    tables = soup.find_all('table')

    for table in tables:
        rows = table.find_all('tr')
        if len(rows) < 2:
            continue

        # Identify year columns from header
        years = []
        for row in rows[:3]:
            cells = row.find_all(['td', 'th'])
            for cell in cells:
                text = cell.get_text(strip=True)
                year_match = re.search(r'20\d{2}', text)
                if year_match:
                    years.append(int(year_match.group()))

        if not years:
            continue

        years = sorted(set(years), reverse=True)

        for row in rows:
            cells = row.find_all(['td', 'th'])
            cell_texts = [c.get_text(strip=True).replace('\xa0', ' ') for c in cells]

            if not cell_texts or all(not t for t in cell_texts):
                continue

            fund_name = cell_texts[0]
            if not fund_name or re.match(r'^[\$\d,\.\s]+$', fund_name):
                continue
            if any(kw in fund_name.lower() for kw in ['total', 'aggregate', 'year',
                   'fiscal', 'fund(s)', 'directed']):
                continue

            amounts = []
            for text in cell_texts[1:]:
                cleaned = text.replace('$', '').replace(',', '').replace(' ', '').strip()
                if cleaned and cleaned not in ('—', '-', 'N/A'):
                    try:
                        val = float(cleaned)
                        if not (2019 < val < 2031):
                            amounts.append(val)
                        elif val == 0:
                            amounts.append(0.0)
                    except ValueError:
                        continue

            if amounts and fund_name:
                nc = NCSRCommissions(fund_name=fund_name)
                for i, year in enumerate(years):
                    if i < len(amounts):
                        nc.annual_commissions[year] = amounts[i]
                results.append(nc)

    return results


# ── Turnover parsing ─────────────────────────────────────────────────────────

def _parse_financial_highlights_turnover(html: str) -> list[NCSRTurnover]:
    """Extract portfolio turnover rates from Financial Highlights tables.

    Financial Highlights are standardized tables in every N-CSR showing
    per-share data over 5+ years including turnover rate.
    """
    results = []

    # Financial highlights sections repeat per fund/class
    highlights_sections = re.finditer(
        r'(?i)(financial\s+highlights.*?)(?=financial\s+highlights|$)',
        html, re.DOTALL
    )

    for match in highlights_sections:
        section = match.group(1)[:15000]

        # Try to find fund name near the top of the section
        fund_name = ""
        name_match = re.search(
            r'(?i)(?:fund|portfolio|class)\s*[:\-—]\s*([A-Za-z][\w\s&\-]+)',
            section[:500]
        )
        if name_match:
            fund_name = _clean_text(name_match.group(1))[:80]

        # Look for turnover rate row
        turnover_match = re.search(
            r'(?i)(portfolio\s+turnover\s+rate.*?)(?:</tr>|$)',
            section, re.DOTALL
        )
        if not turnover_match:
            continue

        row_text = turnover_match.group(1)
        # Extract percentages
        pcts = re.findall(r'(\d+)\s*%', row_text)
        if not pcts:
            continue

        # Try to find corresponding years from nearby header
        years = sorted(
            set(int(y) for y in re.findall(r'20\d{2}', section[:2000])),
            reverse=True
        )

        if years and pcts:
            nt = NCSRTurnover(fund_name=fund_name)
            for i, year in enumerate(years):
                if i < len(pcts):
                    nt.annual_turnover[year] = float(pcts[i])
            results.append(nt)

    return results


# ── Board approval parsing ───────────────────────────────────────────────────

def _parse_board_approval(html: str) -> str:
    """Extract the board's basis for approving the advisory contract.

    This section reveals how fund boards justify the management fee and
    is required in annual N-CSR filings. It often contains explicit
    comparisons to peer group fees and performance.
    """
    section = _extract_section(
        html,
        [r'(?i)basis\s+for\s+(?:the\s+)?board.s?\s+approv',
         r'(?i)board\s+consideration\s+of\s+(?:the\s+)?(?:investment|advisory)',
         r'(?i)approval\s+of\s+(?:the\s+)?(?:investment|advisory)\s+(?:management|advisory)\s+(?:contract|agreement)'],
        [r'(?i)(?:financial\s+statements|report\s+of\s+independent)',
         r'(?i)(?:proxy\s+voting|shareholder\s+meeting)'],
        max_chars=15000
    )

    if not section:
        return ""

    return _clean_text(section)[:5000]


# ── Main entry point ─────────────────────────────────────────────────────────

def parse_ncsr_for_cik(cik: int, annual_only: bool = False) -> Optional[ParsedNCSR]:
    """Parse the most recent N-CSR filing for a given CIK.

    Fetches the N-CSR filing from EDGAR and extracts commission schedules,
    turnover data, and board approval narratives.
    """
    filing_info = _find_ncsr_filing(cik, annual_only=annual_only)
    if not filing_info:
        return None

    html = _fetch_ncsr_html(
        cik,
        filing_info["accession_no"],
        filing_info["primary_doc"]
    )
    if not html:
        return None

    return parse_ncsr_html(html, filing_info)


def parse_ncsr_html(html: str, filing_info: Optional[dict] = None) -> ParsedNCSR:
    """Parse N-CSR data from raw HTML.

    Can be called directly with pre-fetched HTML or via parse_ncsr_for_cik().
    """
    result = ParsedNCSR()
    if filing_info:
        result.cik = filing_info.get("cik", 0)
        result.filing_date = filing_info.get("filing_date", "")
        result.accession_no = filing_info.get("accession_no", "")
        result.is_annual = filing_info.get("is_annual", True)

    # Extract each data type
    result.commissions = _parse_commission_schedule(html)
    result.turnover = _parse_financial_highlights_turnover(html)
    result.board_approval_text = _parse_board_approval(html)

    return result


# ── CLI convenience ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cik = int(sys.argv[1]) if len(sys.argv) > 1 else 29440  # Dodge & Cox

    print(f"Parsing N-CSR for CIK {cik}...")
    result = parse_ncsr_for_cik(cik)

    if not result or not result.has_data:
        print("No N-CSR data found.")
        sys.exit(1)

    print(f"\nFiling: {result.accession_no} ({result.filing_date})")
    print(f"Type: {'Annual (N-CSR)' if result.is_annual else 'Semi-Annual (N-CSRS)'}")

    if result.commissions:
        print(f"\n=== Brokerage Commissions ({len(result.commissions)} funds) ===")
        for nc in result.commissions:
            print(f"  {nc.fund_name}")
            for year, amount in sorted(nc.annual_commissions.items(), reverse=True):
                print(f"    {year}: ${amount:,.0f}")

    if result.turnover:
        print(f"\n=== Portfolio Turnover ({len(result.turnover)} funds) ===")
        for nt in result.turnover:
            print(f"  {nt.fund_name}")
            for year, pct in sorted(nt.annual_turnover.items(), reverse=True):
                print(f"    {year}: {pct:.0f}%")

    if result.board_approval_text:
        print(f"\n=== Board Approval (first 500 chars) ===")
        print(f"  {result.board_approval_text[:500]}...")
