"""Statement of Additional Information (SAI) parser.

Extracts hidden cost and conflict data from the SAI portion of 485BPOS
filings on SEC EDGAR. The SAI is Part B of a fund's N-1A registration
statement and contains data not found in the prospectus:

  - Broker-specific commission breakdowns (3-year history, named brokers)
  - Portfolio manager compensation structures (salary, bonus, equity, incentive basis)
  - Soft dollar / Section 28(e) arrangement details
  - Commission recapture programs
  - Revenue sharing arrangements (where disclosed)

SAIs are embedded in large 485BPOS HTML filings (2-5 MB). The parser:
  1. Fetches the 485BPOS filing index from EDGAR
  2. Downloads the main HTM document
  3. Locates the SAI boundary within the combined prospectus+SAI document
  4. Extracts structured data from each target section using fuzzy matching
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class BrokerageCommissions:
    """Multi-year brokerage commission data from SAI."""
    fund_name: str = ""
    # {year: dollar_amount}
    annual_commissions: dict[int, float] = field(default_factory=dict)
    # Soft dollar / Section 28(e) commissions if broken out separately
    soft_dollar_commissions: dict[int, float] = field(default_factory=dict)
    # Affiliated broker commissions
    affiliated_broker_commissions: dict[int, float] = field(default_factory=dict)
    affiliated_broker_pct: Optional[float] = None


@dataclass
class PMCompensation:
    """Portfolio manager compensation structure from SAI."""
    has_base_salary: bool = False
    has_bonus: bool = False
    has_equity_ownership: bool = False
    has_deferred_comp: bool = False
    bonus_linked_to_performance: bool = False
    bonus_linked_to_aum: bool = False
    bonus_linked_to_firm_profit: bool = False
    compensation_not_linked_to_fund_performance: bool = False
    description: str = ""


@dataclass
class SoftDollarInfo:
    """Soft dollar / Section 28(e) arrangement details."""
    has_soft_dollar_arrangements: bool = False
    uses_commission_sharing: bool = False
    description: str = ""


@dataclass
class ParsedSAI:
    """Complete parsed SAI data."""
    fund_name: str = ""
    cik: int = 0
    filing_date: str = ""
    accession_no: str = ""
    # Multi-fund commission table
    commissions: list[BrokerageCommissions] = field(default_factory=list)
    pm_compensation: Optional[PMCompensation] = None
    soft_dollar_info: Optional[SoftDollarInfo] = None
    # Raw section text for downstream analysis
    brokerage_section_text: str = ""
    pm_comp_section_text: str = ""
    soft_dollar_section_text: str = ""

    @property
    def has_data(self) -> bool:
        """True if any commission or compensation data was parsed."""
        return bool(self.commissions) or self.pm_compensation is not None


# ── HTML cleaning utilities ───────────────────────────────────────────────────

_ENTITY_MAP = {
    "&#160;": " ", "&nbsp;": " ", "&#8217;": "'", "&#8216;": "'",
    "&#8220;": '"', "&#8221;": '"', "&amp;": "&", "&#38;": "&",
    "&mdash;": "—", "&#8212;": "—", "&ndash;": "–", "&#8211;": "–",
    "&#174;": "®", "&reg;": "®", "&lt;": "<", "&gt;": ">",
}


def _clean_text(html_fragment: str) -> str:
    """Strip HTML tags and normalize entities."""
    text = re.sub(r'<[^>]+>', ' ', html_fragment)
    for entity, char in _ENTITY_MAP.items():
        text = text.replace(entity, char)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _extract_dollars(text: str) -> list[tuple[str, float]]:
    """Extract all dollar amounts from text, returning (context, amount) pairs."""
    results = []
    for m in re.finditer(r'\$\s*([\d,]+(?:\.\d+)?)', text):
        try:
            amount = float(m.group(1).replace(',', ''))
            context = text[max(0, m.start()-50):m.end()+50]
            results.append((context, amount))
        except ValueError:
            continue
    return results


# ── EDGAR filing access ───────────────────────────────────────────────────────

from fundautopsy.config import EDGAR_USER_AGENT, EDGAR_RATE_LIMIT_DELAY

_EDGAR_HEADERS = {
    "User-Agent": EDGAR_USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
}

_RATE_LIMIT_DELAY = EDGAR_RATE_LIMIT_DELAY  # SEC rate limit: 10 req/sec


def _fetch_edgar(url: str) -> requests.Response:
    """Fetch from EDGAR with rate limiting and proper User-Agent."""
    time.sleep(_RATE_LIMIT_DELAY)
    return requests.get(url, headers=_EDGAR_HEADERS, timeout=30)


def _find_485bpos_filing(cik: int, max_filings: int = 5) -> Optional[dict]:
    """Find the most recent 485BPOS filing for a CIK.

    Returns dict with accession_no and primary_doc filename, or None.
    """
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

    for i, form in enumerate(forms):
        if form == "485BPOS" and i < len(accessions):
            return {
                "accession_no": accessions[i],
                "filing_date": dates[i] if i < len(dates) else "",
                "primary_doc": primary_docs[i] if i < len(primary_docs) else "",
                "cik": cik,
            }
    return None


def _fetch_485bpos_html(cik: int, accession_no: str, primary_doc: str) -> Optional[str]:
    """Download the full 485BPOS HTML document."""
    acc_nodash = accession_no.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{primary_doc}"
    r = _fetch_edgar(url)
    if r.status_code == 200:
        return r.text
    return None


# ── SAI boundary detection ────────────────────────────────────────────────────

def _find_sai_start(html: str) -> int:
    """Find where the SAI section begins in a combined prospectus+SAI document.

    The SAI typically starts with a centered bold header "Statement of Additional
    Information" after the prospectus sections. We look for the instance that
    appears to be the actual SAI header (not a cross-reference in prospectus text).
    """
    # Find all instances
    matches = list(re.finditer(
        r'(?i)>[\s]*Statement\s+of\s+Additional\s+Information[\s]*<',
        html
    ))

    if not matches:
        # Fallback: look for "This Statement of Additional Information"
        m = re.search(r'(?i)This\s+Statement\s+of\s+Additional\s+Information', html)
        return m.start() if m else 0

    # The SAI header is usually in the second half of the document
    # and is preceded by a page break or centered formatting
    midpoint = len(html) // 2
    for m in matches:
        if m.start() > midpoint:
            return m.start()

    # If no match past midpoint, use the last match
    return matches[-1].start()


# ── Section extraction ────────────────────────────────────────────────────────

def _extract_section(sai_html: str, start_patterns: list[str],
                     end_patterns: list[str], max_chars: int = 30000) -> str:
    """Extract a section of text between start and end patterns."""
    start_pos = None
    for pattern in start_patterns:
        m = re.search(pattern, sai_html, re.IGNORECASE)
        if m:
            start_pos = m.start()
            break

    if start_pos is None:
        return ""

    section = sai_html[start_pos:start_pos + max_chars]

    # Try to find a natural end point
    end_pos = len(section)
    for pattern in end_patterns:
        m = re.search(pattern, section[1000:], re.IGNORECASE)  # Skip at least 1000 chars
        if m:
            end_pos = min(end_pos, m.start() + 1000)
            break

    return section[:end_pos]


# ── Commission table parsing ─────────────────────────────────────────────────

def _parse_commission_table(sai_html: str) -> list[BrokerageCommissions]:
    """Extract the multi-year brokerage commission table.

    Looks for the standard "aggregate brokerage commissions" table with
    fund names in the first column and dollar amounts by year.
    """
    results = []

    # Find the aggregate commissions section
    section = _extract_section(
        sai_html,
        [r'(?i)aggregate\s+brokerage\s+commissions.*?(?:follows|table)',
         r'(?i)brokerage\s+commissions.*?(?:paid|following\s+table)'],
        [r'(?i)(?:changes\s+to\s+brokerage|securities\s+of\s+regular)',
         r'(?i)(?:the\s+funds?\s+did\s+not|portfolio\s+transactions)'],
        max_chars=15000
    )

    if not section:
        return results

    # Find tables in this section
    soup = BeautifulSoup(section, 'html.parser')
    tables = soup.find_all('table')

    for table in tables:
        rows = table.find_all('tr')
        if len(rows) < 2:
            continue

        # Try to identify year columns from header row
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

        # Parse data rows
        for row in rows:
            cells = row.find_all(['td', 'th'])
            cell_texts = [c.get_text(strip=True).replace('\xa0', ' ') for c in cells]

            # Skip empty rows and header rows
            if not cell_texts or all(not t for t in cell_texts):
                continue

            # First cell should be fund name
            fund_name = cell_texts[0]
            if not fund_name or re.match(r'^[\$\d,\.\s]+$', fund_name):
                continue
            if any(kw in fund_name.lower() for kw in ['total', 'aggregate', 'year',
                   'turnover', 'fund(s)', 'fiscal']):
                continue

            # Extract dollar amounts - skip year-like values (2020-2030) and percentages
            amounts = []
            for text in cell_texts[1:]:
                cleaned = text.replace('$', '').replace(',', '').replace(' ', '').strip()
                if cleaned and cleaned != '—' and cleaned != '-':
                    try:
                        val = float(cleaned)
                        # Skip years (2020-2030), small percentages, and zero
                        if val > 100 and not (2019 < val < 2031):
                            amounts.append(val)
                        elif val == 0:
                            amounts.append(0.0)  # Preserve zero-commission entries
                    except ValueError:
                        continue

            if amounts and fund_name:
                bc = BrokerageCommissions(fund_name=fund_name)
                for i, year in enumerate(years):
                    if i < len(amounts):
                        bc.annual_commissions[year] = amounts[i]
                results.append(bc)

    # If table parsing didn't work well, try Fidelity-style inline format
    # Fidelity uses a different table: Fund | Year | Broker | Affiliated With | $ | Amount | % | %
    if not results or (results and max(
        max(bc.annual_commissions.values(), default=0) for bc in results
    ) < 1000):
        results = _parse_fidelity_commission_table(sai_html, section)

    return results


def _parse_fidelity_commission_table(sai_html: str, section: str) -> list[BrokerageCommissions]:
    """Parse Fidelity-style commission table where each row is fund+year+broker+amount.

    Fidelity format (columns may be split across cells):
      Fund | Year | Broker | Affiliated With | $ | Amount | %Commissions | %Transactions
    Multiple rows per fund (one per broker per year). We aggregate by fund and year.
    """
    results_dict: dict[str, BrokerageCommissions] = {}

    soup = BeautifulSoup(section, 'html.parser')
    tables = soup.find_all('table')

    for table in tables:
        rows = table.find_all('tr')
        current_fund = ""
        current_year = 0

        for row in rows[1:]:  # Skip header
            cells = row.find_all(['td', 'th'])
            cell_texts = [c.get_text(strip=True).replace('\xa0', ' ') for c in cells]

            if len(cell_texts) < 3:
                continue

            # Join all cell text to find fund name, year, and dollar amounts
            row_text = ' '.join(cell_texts)

            # Check for fund name in first cell
            first = cell_texts[0]
            if first and not re.match(r'^[\d\$%,.\s\-]+$', first) and len(first) > 5:
                if not any(kw in first.lower() for kw in ['fund(s)', 'fiscal', 'broker',
                           'affiliated', 'percentage', 'commission', 'ommission']):
                    current_fund = first

            # Check for year in early cells
            for text in cell_texts[:3]:
                year_match = re.match(r'^(20\d{2})$', text.strip())
                if year_match:
                    current_year = int(year_match.group(1))

            if not current_fund or not current_year:
                continue

            # Find dollar amounts - look for $ followed by amount (may be split cells)
            # Join consecutive cells that look like "$" + "number"
            for i, text in enumerate(cell_texts):
                if text.strip() == '$' and i + 1 < len(cell_texts):
                    amount_text = cell_texts[i + 1].replace(',', '').strip()
                    try:
                        val = float(amount_text)
                        if val > 100:  # Real commission amounts
                            if current_fund not in results_dict:
                                results_dict[current_fund] = BrokerageCommissions(
                                    fund_name=current_fund
                                )
                            bc = results_dict[current_fund]
                            bc.annual_commissions[current_year] = (
                                bc.annual_commissions.get(current_year, 0) + val
                            )
                    except ValueError:
                        continue

    return list(results_dict.values())


# ── PM compensation parsing ──────────────────────────────────────────────────

def _parse_pm_compensation(sai_html: str) -> Optional[PMCompensation]:
    """Extract portfolio manager compensation structure.

    Looks for the standard compensation section and classifies the
    structure based on keywords.
    """
    section = _extract_section(
        sai_html,
        [r'(?i)compensation\s+generally\s+consists\s+of\s+a\s+fixed\s+base',
         r'(?i)portfolio\s+manager.*?compensation\s+generally\s+consists',
         r'(?i)compensation\s+of.*?investment\s+committee\s+members\s+includes',
         r'(?i)compensation\s+includes\s+a\s+base\s+salary',
         r'(?i)base\s+salary.*?bonus.*?(?:equity|deferred|incentive)'],
        [r'(?i)(?:fund\s+shares?\s+owned|dollar\s+range|other\s+accounts?\s+managed)',
         r'(?i)(?:proxy\s+voting|code\s+of\s+ethics)',
         r'(?i)(?:securities\s+held|potential\s+conflicts)'],
        max_chars=8000
    )

    if not section:
        return None

    text = _clean_text(section).lower()

    if len(text) < 100:
        return None

    pm = PMCompensation()

    # Detect components
    pm.has_base_salary = bool(re.search(r'base\s+salary', text))
    pm.has_bonus = bool(re.search(r'bonus', text))
    pm.has_equity_ownership = bool(re.search(r'equity\s+ownership|stock\s+option|restricted\s+stock|equity.based', text))
    pm.has_deferred_comp = bool(re.search(r'deferred\s+compensation', text))

    # What drives the bonus?
    pm.bonus_linked_to_performance = bool(re.search(
        r'(?:bonus|incentive|variable).*?(?:performance|benchmark|return|alpha|beat)',
        text
    )) or bool(re.search(
        r'(?:performance|investment\s+return).*?(?:bonus|incentive|variable)',
        text
    ))

    pm.bonus_linked_to_aum = bool(re.search(
        r'(?:bonus|compensation).*?(?:assets?\s+under|size\s+of|asset\s+growth)',
        text
    ))

    pm.bonus_linked_to_firm_profit = bool(re.search(
        r'(?:bonus|compensation).*?(?:profitability|firm.s?\s+profit|company\s+profit)',
        text
    ))

    # Check for explicit non-linkage to fund performance
    pm.compensation_not_linked_to_fund_performance = bool(re.search(
        r'(?:compensation|bonus).*?not\s+(?:linked|tied|based).*?(?:performance|return)',
        text
    )) or bool(re.search(
        r'not\s+(?:linked|tied).*?(?:distribution|volume\s+of\s+assets)',
        text
    ))

    # Store raw description (first 1500 chars of cleaned text)
    pm.description = _clean_text(section)[:1500]

    return pm


# ── Soft dollar parsing ──────────────────────────────────────────────────────

def _parse_soft_dollar_info(sai_html: str) -> Optional[SoftDollarInfo]:
    """Extract soft dollar / Section 28(e) arrangement details."""
    section = _extract_section(
        sai_html,
        [r'(?i)section\s+28\(e\)',
         r'(?i)soft\s+dollar',
         r'(?i)commission\s+uses?\s+program',
         r'(?i)research\s+services.*?brokerage'],
        [r'(?i)(?:regular\s+broker|affiliated\s+broker|commission\s+recapture)',
         r'(?i)(?:securities\s+of\s+regular|other\s+information)'],
        max_chars=8000
    )

    if not section:
        return None

    text = _clean_text(section).lower()

    if len(text) < 100:
        return None

    sd = SoftDollarInfo()
    sd.has_soft_dollar_arrangements = bool(re.search(
        r'(?:soft\s+dollar|section\s+28\(e\)|research\s+services.*?commission)', text
    ))
    sd.uses_commission_sharing = bool(re.search(
        r'(?:commission\s+sharing|commission\s+uses?\s+program|unbundle)', text
    ))
    sd.description = _clean_text(section)[:1500]

    return sd


# ── Main entry point ─────────────────────────────────────────────────────────

def parse_sai_for_cik(cik: int) -> Optional[ParsedSAI]:
    """Parse the most recent SAI filing for a given CIK.

    Fetches the 485BPOS filing from EDGAR, locates the SAI section,
    and extracts brokerage commissions, PM compensation, and soft dollar data.
    """
    # Find filing
    filing_info = _find_485bpos_filing(cik)
    if not filing_info:
        return None

    # Fetch HTML
    html = _fetch_485bpos_html(
        cik,
        filing_info["accession_no"],
        filing_info["primary_doc"]
    )
    if not html:
        return None

    return parse_sai_html(html, filing_info)


def parse_sai_html(html: str, filing_info: Optional[dict] = None) -> ParsedSAI:
    """Parse SAI data from raw 485BPOS HTML.

    Can be called directly with pre-fetched HTML or via parse_sai_for_cik().
    """
    result = ParsedSAI()
    if filing_info:
        result.cik = filing_info.get("cik", 0)
        result.filing_date = filing_info.get("filing_date", "")
        result.accession_no = filing_info.get("accession_no", "")

    # Find SAI boundary
    sai_start = _find_sai_start(html)
    sai_html = html[sai_start:]

    # Extract each section
    result.commissions = _parse_commission_table(sai_html)
    result.pm_compensation = _parse_pm_compensation(sai_html)

    # If PM comp not found in SAI section, search the full document
    # (Fidelity puts PM comp in the prospectus portion, not the SAI)
    if result.pm_compensation is None or not result.pm_compensation.has_base_salary:
        full_doc_pm = _parse_pm_compensation(html)
        if full_doc_pm and full_doc_pm.has_base_salary:
            result.pm_compensation = full_doc_pm

    result.soft_dollar_info = _parse_soft_dollar_info(sai_html)

    # Store raw section text for downstream use
    brok_section = _extract_section(
        sai_html,
        [r'(?i)brokerage\s+allocation\s+and\s+other\s+practices',
         r'(?i)brokerage\s+transactions'],
        [r'(?i)(?:capital\s+stock|tax\s+status|additional\s+information\s+about)',
         r'(?i)(?:other\s+information|financial\s+statements)'],
        max_chars=25000
    )
    result.brokerage_section_text = _clean_text(brok_section)[:5000] if brok_section else ""

    comp_section = _extract_section(
        sai_html,
        [r'(?i)compensation\s+of.*?(?:portfolio|investment)',
         r'(?i)portfolio\s+manager.*?compensation'],
        [r'(?i)(?:fund\s+shares?\s+owned|dollar\s+range|other\s+accounts)'],
        max_chars=8000
    )
    result.pm_comp_section_text = _clean_text(comp_section)[:3000] if comp_section else ""

    return result


# ── Convenience for testing ──────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cik = int(sys.argv[1]) if len(sys.argv) > 1 else 29440  # Dodge & Cox default

    print(f"Parsing SAI for CIK {cik}...")
    result = parse_sai_for_cik(cik)

    if not result or not result.has_data:
        print("No SAI data found.")
        sys.exit(1)

    print(f"\nFiling: {result.accession_no} ({result.filing_date})")

    if result.commissions:
        print(f"\n=== Brokerage Commissions ({len(result.commissions)} funds) ===")
        for bc in result.commissions:
            print(f"  {bc.fund_name}")
            for year, amount in sorted(bc.annual_commissions.items(), reverse=True):
                print(f"    {year}: ${amount:,.0f}")

    if result.pm_compensation:
        pm = result.pm_compensation
        print(f"\n=== PM Compensation Structure ===")
        print(f"  Base salary: {pm.has_base_salary}")
        print(f"  Bonus: {pm.has_bonus}")
        print(f"  Equity ownership: {pm.has_equity_ownership}")
        print(f"  Deferred comp: {pm.has_deferred_comp}")
        print(f"  Bonus linked to performance: {pm.bonus_linked_to_performance}")
        print(f"  Bonus linked to AUM: {pm.bonus_linked_to_aum}")
        print(f"  Bonus linked to firm profit: {pm.bonus_linked_to_firm_profit}")
        print(f"  Comp NOT linked to fund performance: {pm.compensation_not_linked_to_fund_performance}")

    if result.soft_dollar_info:
        sd = result.soft_dollar_info
        print(f"\n=== Soft Dollar Info ===")
        print(f"  Has soft dollar arrangements: {sd.has_soft_dollar_arrangements}")
        print(f"  Uses commission sharing: {sd.uses_commission_sharing}")
