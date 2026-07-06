"""Fee change tracker — 485A/485B/485C post-effective amendment parser.

Monitors prospectus amendments where funds quietly raise or lower fees
between annual reports. Builds a time-series of fee changes by walking
sequential 485BPOS filings and comparing per-class expense ratios.

Filing types:
  - 485APOS: Pre-effective amendment (proposed changes)
  - 485BPOS: Post-effective amendment (changes in effect)
  - 485BXT:  Extension for post-effective amendment

Extraction order per filing:
  1. If a series_id + class_id are known, try XBRL fee facts scoped to
     that class (oef: and rr: taxonomies, context_ref substring match).
  2. If XBRL returns nothing (e.g., older filings without inline XBRL),
     fall back to HTML parsing via `parse_497k_html(html, ticker)`.

The module keeps a legacy CIK-only code path for backward compatibility
with callers that have not yet been migrated to pass the class-scoped
identifiers. That path works for single-series registrants (Vanguard,
Dodge & Cox, TRP) but will misattribute fees on umbrella-trust 485BPOS
filings that cover many funds in one document — which is why the
class-scoped path exists.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from fundautopsy.config import EDGAR_RATE_LIMIT_DELAY
from fundautopsy.data.fee_parser import parse_497k_html, ParsedFees
from fundautopsy.data.xbrl_fee_parser import extract_fees_from_xbrl

logger = logging.getLogger(__name__)


@dataclass
class FeeSnapshot:
    """A single point-in-time fee snapshot from a prospectus amendment."""
    filing_date: str
    accession_no: str
    form_type: str  # 485APOS, 485BPOS, 485BXT

    management_fee: Optional[float] = None
    twelve_b1_fee: Optional[float] = None
    other_expenses: Optional[float] = None
    total_annual_expenses: Optional[float] = None
    fee_waiver: Optional[float] = None
    net_expenses: Optional[float] = None
    max_sales_load: Optional[float] = None
    portfolio_turnover: Optional[float] = None

    @property
    def effective_expense_ratio(self) -> Optional[float]:
        """Net expense ratio (after waivers) or total if no waiver."""
        if self.net_expenses is not None:
            return self.net_expenses
        return self.total_annual_expenses


@dataclass
class FeeChange:
    """A detected fee change between two filing dates."""
    field_name: str  # e.g., "management_fee", "total_annual_expenses"
    field_label: str  # Human-readable label
    old_value: float
    new_value: float
    change_bps: float  # Change in basis points
    old_filing_date: str
    new_filing_date: str
    direction: str  # "increase" or "decrease"


@dataclass
class FeeHistory:
    """Complete fee change history for a fund."""
    ticker: str = ""
    cik: int = 0
    snapshots: list[FeeSnapshot] = field(default_factory=list)
    changes: list[FeeChange] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """True if any fee changes detected."""
        return len(self.changes) > 0

    @property
    def net_change_bps(self) -> float:
        """Net fee change across all detected changes."""
        return sum(c.change_bps for c in self.changes)


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


def _find_485_filings(cik: int, max_filings: int = 10) -> list[dict]:
    """Find historical 485BPOS filings for a CIK."""
    url = f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json"
    r = _fetch_edgar(url)
    if r.status_code != 200:
        return []

    data = r.json()
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])

    results = []
    for i, form in enumerate(forms):
        if form in ("485BPOS", "485APOS", "485BXT") and i < len(accessions):
            results.append({
                "accession_no": accessions[i],
                "filing_date": dates[i] if i < len(dates) else "",
                "primary_doc": primary_docs[i] if i < len(primary_docs) else "",
                "form_type": form,
                "cik": cik,
            })
            if len(results) >= max_filings:
                break

    return results


def _fetch_filing_html(cik: int, accession_no: str, primary_doc: str) -> Optional[str]:
    """Download a filing's HTML."""
    acc_nodash = accession_no.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{primary_doc}"
    r = _fetch_edgar(url)
    if r.status_code == 200:
        return r.text
    return None


# ── Fee comparison ───────────────────────────────────────────────────────────

_TRACKED_FIELDS = [
    ("management_fee", "Management Fee"),
    ("twelve_b1_fee", "12b-1 Fee"),
    ("other_expenses", "Other Expenses"),
    ("total_annual_expenses", "Total Annual Expenses"),
    ("net_expenses", "Net Expenses (After Waivers)"),
    ("max_sales_load", "Maximum Sales Load"),
]


def _compare_snapshots(old: FeeSnapshot, new: FeeSnapshot) -> list[FeeChange]:
    """Compare two fee snapshots and return detected changes."""
    changes = []

    for field_name, label in _TRACKED_FIELDS:
        old_val = getattr(old, field_name, None)
        new_val = getattr(new, field_name, None)

        if old_val is not None and new_val is not None:
            # Compare with a tolerance of 0.001% (0.1 bps) to avoid float noise
            diff = new_val - old_val
            if abs(diff) > 0.001:
                changes.append(FeeChange(
                    field_name=field_name,
                    field_label=label,
                    old_value=old_val,
                    new_value=new_val,
                    change_bps=round(diff * 100, 1),  # Convert % to bps
                    old_filing_date=old.filing_date,
                    new_filing_date=new.filing_date,
                    direction="increase" if diff > 0 else "decrease",
                ))

    return changes


# ── Main entry point ─────────────────────────────────────────────────────────

def _snapshot_from_parsed(
    parsed: ParsedFees,
    filing_date: str,
    accession_no: str,
    form_type: str,
) -> FeeSnapshot:
    """Build a FeeSnapshot from a ParsedFees + filing metadata."""
    return FeeSnapshot(
        filing_date=filing_date,
        accession_no=accession_no,
        form_type=form_type,
        management_fee=parsed.management_fee,
        twelve_b1_fee=parsed.twelve_b1_fee,
        other_expenses=parsed.other_expenses,
        total_annual_expenses=parsed.total_annual_expenses,
        fee_waiver=parsed.fee_waiver,
        net_expenses=parsed.net_expenses,
        max_sales_load=getattr(parsed, "max_sales_load", None),
        portfolio_turnover=getattr(parsed, "portfolio_turnover", None),
    )


def _extract_snapshot(
    filing,
    ticker: str,
    series_id: Optional[str],
    class_id: Optional[str],
) -> Optional[FeeSnapshot]:
    """Extract a per-class fee snapshot from a single edgartools filing.

    Tries XBRL first when (series_id, class_id) are known, since that
    path scopes cleanly to one share class even on umbrella-trust
    filings. Falls back to HTML parsing when XBRL is absent or does
    not carry a fact matching the target class.
    """
    filing_date = str(getattr(filing, "filing_date", ""))
    accession_no = str(getattr(filing, "accession_no", ""))
    form_type = str(getattr(filing, "form", "485BPOS"))

    # XBRL path: requires both IDs
    if series_id and class_id:
        try:
            obj = filing.obj()
            parsed = extract_fees_from_xbrl(obj, series_id, class_id)
            if parsed is not None and parsed.has_data:
                snapshot = _snapshot_from_parsed(
                    parsed, filing_date, accession_no, form_type
                )
                # Synthesize total from components when XBRL omitted the
                # aggregate tag. Classes without 12b-1 plans (Oakmark Investor,
                # institutional shares) legitimately omit twelve_b1_fee; we
                # treat its absence as zero rather than as a signal that the
                # component set is incomplete.
                if (
                    snapshot.total_annual_expenses is None
                    and snapshot.management_fee is not None
                    and snapshot.other_expenses is not None
                ):
                    snapshot.total_annual_expenses = round(
                        snapshot.management_fee
                        + (snapshot.twelve_b1_fee or 0.0)
                        + snapshot.other_expenses
                        + (parsed.acquired_fund_fees or 0.0),
                        4,
                    )
                # Sanity guard — reject impossible-value snapshots. No real
                # active share class has an expense ratio of exactly zero;
                # this filter catches context_ref substring collisions on
                # heavy umbrella trusts (Fidelity Concord Street, Fidelity
                # Aberdeen Street) where XBRL facts from unrelated classes
                # occasionally slip through the (series_id, class_id) match.
                if (
                    snapshot.total_annual_expenses == 0.0
                    and (snapshot.management_fee or 0.0) == 0.0
                    and (snapshot.net_expenses or 0.0) == 0.0
                ):
                    logger.debug(
                        "Rejecting zero-fee snapshot on %s — likely "
                        "context_ref collision", accession_no,
                    )
                    return None
                return snapshot
        except Exception as exc:
            logger.debug(
                "XBRL extraction raised on %s: %s",
                accession_no,
                exc,
            )

    # HTML path: ticker filter. Only run when the caller did NOT supply
    # series_id + class_id — the HTML path cannot reliably scope to a
    # specific class on umbrella-trust 485BPOS filings (multiple classes
    # appear in one document and tickers may be shared across fee tables).
    # The class-scoped XBRL path above is authoritative for the multi-
    # series case.
    if series_id and class_id:
        return None

    try:
        html = filing.html()
    except Exception as exc:
        logger.debug("filing.html() raised on %s: %s", accession_no, exc)
        return None
    if not html:
        return None

    fees = parse_497k_html(html, ticker)
    if not fees.has_data:
        return None

    return _snapshot_from_parsed(fees, filing_date, accession_no, form_type)


def track_fee_changes(
    cik: int,
    ticker: str,
    series_id: Optional[str] = None,
    class_id: Optional[str] = None,
    max_filings: int = 5,
) -> FeeHistory:
    """Track fee changes across historical prospectus amendments.

    Uses the class-scoped pipeline (XBRL first, HTML fallback) when
    series_id and class_id are known. Falls back to a CIK-scoped
    HTML-only walk for legacy callers.

    Args:
        cik: SEC CIK number for the fund trust.
        ticker: Fund ticker for share class matching.
        series_id: EDGAR series identifier (e.g., 'S000006027'). When
            provided together with class_id, enables XBRL extraction on
            umbrella-trust 485BPOS filings.
        class_id: EDGAR share class identifier (e.g., 'C000100045').
        max_filings: Maximum number of historical filings to check.

    Returns:
        FeeHistory with snapshots and detected changes.
    """
    history = FeeHistory(ticker=ticker, cik=cik)

    # Class-scoped path: use edgartools' series-level filings iterator.
    # This avoids the misattribution risk on umbrella trusts and unlocks
    # XBRL extraction per snapshot.
    if series_id and class_id:
        try:
            import edgar
            from fundautopsy.config import EDGAR_USER_AGENT
            # edgartools silently fails series resolution if identity isn't
            # set in its global state. The fee_tracker module may be invoked
            # without prospectus.py having been touched first, so set it
            # here defensively.
            try:
                edgar.set_identity(EDGAR_USER_AGENT)
            except Exception:
                pass
        except ImportError:
            edgar = None  # Fall through to legacy path

        if edgar is not None:
            try:
                series = edgar.Fund(series_id)
                all_filings = series.get_filings()
                bpos = all_filings.filter(form="485BPOS")
            except Exception as exc:
                logger.debug(
                    "edgar.Fund(%s).get_filings() raised: %s",
                    series_id, exc,
                )
                bpos = None

            if bpos is not None:
                count = 0
                for filing in bpos:
                    if count >= max_filings:
                        break
                    snapshot = _extract_snapshot(
                        filing, ticker, series_id, class_id
                    )
                    if snapshot is not None:
                        history.snapshots.append(snapshot)
                        count += 1
                _build_changes(history)
                return history

    # Legacy CIK-only path: preserved for backward compatibility.
    # Works for single-series registrants whose 485BPOS documents carry
    # one fund's fee table per filing. Will misattribute on umbrella
    # trusts — callers should pass series_id + class_id when known.
    filings = _find_485_filings(cik, max_filings=max_filings)
    if not filings:
        return history

    for filing_meta in filings:
        html = _fetch_filing_html(
            cik, filing_meta["accession_no"], filing_meta["primary_doc"]
        )
        if not html:
            continue

        fees = parse_497k_html(html, ticker)
        if not fees.has_data:
            continue

        history.snapshots.append(_snapshot_from_parsed(
            fees,
            filing_meta["filing_date"],
            filing_meta["accession_no"],
            filing_meta["form_type"],
        ))

    _build_changes(history)
    return history


def _build_changes(history: FeeHistory) -> None:
    """Populate history.changes by comparing sequential snapshots."""
    for i in range(len(history.snapshots) - 1):
        newer = history.snapshots[i]
        older = history.snapshots[i + 1]
        changes = _compare_snapshots(older, newer)
        history.changes.extend(changes)


# ── CLI convenience ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python -m fundautopsy.data.fee_tracker <CIK> <TICKER>")
        sys.exit(1)

    cik = int(sys.argv[1])
    ticker = sys.argv[2].upper()

    print(f"Tracking fee changes for CIK {cik} ({ticker})...")
    history = track_fee_changes(cik, ticker, max_filings=5)

    if not history.snapshots:
        print("No fee data found in recent 485BPOS filings.")
        sys.exit(1)

    print(f"\n=== Fee Snapshots ({len(history.snapshots)} filings) ===")
    for snap in history.snapshots:
        er = snap.effective_expense_ratio
        print(f"  {snap.filing_date} ({snap.form_type}): "
              f"ER={er:.3f}%" if er else f"  {snap.filing_date}: N/A")

    if history.changes:
        print(f"\n=== Fee Changes ({len(history.changes)} detected) ===")
        for change in history.changes:
            arrow = "+" if change.direction == "increase" else ""
            print(f"  {change.field_label}: {change.old_value:.3f}% -> {change.new_value:.3f}% "
                  f"({arrow}{change.change_bps:.1f} bps) "
                  f"[{change.old_filing_date} -> {change.new_filing_date}]")
        print(f"\n  Net change: {history.net_change_bps:+.1f} bps")
    else:
        print("\nNo fee changes detected across recent filings.")
