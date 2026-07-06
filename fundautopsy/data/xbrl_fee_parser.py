"""XBRL-based fee extraction from 485BPOS statutory prospectuses.

Primary data source for per-share-class fee data when the 497K (summary
prospectus) HTML parser cannot confidently attribute fees to the correct
share class. 485BPOS filings carry structured XBRL facts tagged per class,
which eliminates the umbrella-trust misattribution risk that plagues HTML
parsing of multi-class tables.

Registrants use one of two XBRL taxonomies interchangeably:
  * oef: (Open-ended Fund) — MFS, Janus, Fidelity Freedom, Capital Group
  * rr: (Risk/Return) — Fidelity core, Vanguard, older American Funds

Both taxonomies define the same concept names (ManagementFeesOverAssets,
ExpensesOverAssets, etc.); this parser tries both.

Context_ref encodes series and class identifiers but each registrant picks
its own format:
  * 'S000006027C000100045'                             (Fidelity core)
  * 'Pid_S000006037_Cid_C000016601'                    (Fidelity Freedom)
  * 'AdmiralMember_S000002839_C000007774'              (Vanguard)
  * 'Context_20250831_20250831_C000002259Member_S000000769Member_...'  (MFS)
  * 'S000009228Member_C000025064Member'                (Capital Group)

We match by substring — a context_ref is "ours" when it contains BOTH the
target series_id and class_id.
"""

from __future__ import annotations

import logging
from typing import Optional

from fundautopsy.data.fee_parser import (
    FEE_SANITY_THRESHOLD_PCT,
    ParsedFees,
)

logger = logging.getLogger(__name__)


# XBRL concepts for each fee field. Each field name maps to a list of
# (namespace, concept_local_name) pairs tried in order.
_FEE_CONCEPTS: dict[str, list[tuple[str, str]]] = {
    "management_fee": [
        ("oef", "ManagementFeesOverAssets"),
        ("rr", "ManagementFeesOverAssets"),
    ],
    "twelve_b1_fee": [
        ("oef", "DistributionAndService12b1FeesOverAssets"),
        ("rr", "DistributionAndService12b1FeesOverAssets"),
    ],
    "other_expenses": [
        ("oef", "OtherExpensesOverAssets"),
        ("rr", "OtherExpensesOverAssets"),
    ],
    "acquired_fund_fees": [
        ("oef", "AcquiredFundFeesAndExpensesOverAssets"),
        ("rr", "AcquiredFundFeesAndExpensesOverAssets"),
    ],
    "total_annual_expenses": [
        ("oef", "ExpensesOverAssets"),
        ("rr", "ExpensesOverAssets"),
    ],
    "fee_waiver": [
        ("oef", "FeeWaiverOrReimbursementOverAssets"),
        ("rr", "FeeWaiverOrReimbursementOverAssets"),
    ],
    "net_expenses": [
        ("oef", "NetExpensesOverAssets"),
        ("rr", "NetExpensesOverAssets"),
    ],
}


def _apply_scale(value: float) -> Optional[float]:
    """Convert XBRL decimal fraction to percent with sanity guarding.

    XBRL fee concepts are tagged as decimal fractions (e.g., 0.0044 for
    0.44%). We multiply by 100 to match the ParsedFees percent convention
    used throughout the codebase.
    """
    if value is None:
        return None
    # Round to 4 decimal places to kill IEEE-754 float noise from the
    # decimal-fraction → percent multiplication (e.g. 0.0092 * 100 -> 0.91999…).
    pct = round(float(value) * 100.0, 4)
    if pct < 0 and pct > -FEE_SANITY_THRESHOLD_PCT:
        # Legitimate negative value — fee waivers are negative by convention.
        return pct
    if 0 <= pct < FEE_SANITY_THRESHOLD_PCT:
        return pct
    if pct >= FEE_SANITY_THRESHOLD_PCT:
        logger.warning(
            "XBRL fee value %.2f%% exceeds %.0f%% sanity threshold — "
            "verify manually (raw=%s)",
            pct, FEE_SANITY_THRESHOLD_PCT, value,
        )
        return pct
    # pct <= -FEE_SANITY_THRESHOLD_PCT — implausible waiver magnitude
    logger.warning(
        "XBRL waiver value %.2f%% exceeds threshold — rejecting (raw=%s)",
        pct, value,
    )
    return None


def extract_fees_from_xbrl(
    obj,
    series_id: str,
    class_id: str,
) -> Optional[ParsedFees]:
    """Extract per-class fees from an edgartools XBRL object.

    Args:
        obj: edgartools XBRL object from filing.obj() on a 485BPOS filing.
        series_id: EDGAR series identifier (e.g., 'S000006027').
        class_id: EDGAR share class identifier (e.g., 'C000100045').

    Returns:
        ParsedFees populated with whatever concepts the filing provides,
        or None if the XBRL has no fact matching the target class.
    """
    if obj is None:
        return None

    facts = getattr(obj, "facts", None)
    if facts is None:
        return None

    try:
        df = facts.to_dataframe()
    except Exception as exc:
        logger.debug("facts.to_dataframe() raised: %r", exc)
        return None

    if df is None or len(df) == 0:
        return None

    if "concept" not in df.columns or "context_ref" not in df.columns:
        return None

    # Substring-match the class_id and series_id in context_ref.
    # Each registrant uses a different context_ref format; the class_id
    # alone is unique across SEC, but requiring both is an extra guard
    # against cross-series collisions within the same trust filing.
    ctx_mask = (
        df["context_ref"].str.contains(class_id, na=False)
        & df["context_ref"].str.contains(series_id, na=False)
    )
    if not ctx_mask.any():
        return None

    class_df = df[ctx_mask]
    fees = ParsedFees()

    for field_name, candidates in _FEE_CONCEPTS.items():
        value = None
        for namespace, local_name in candidates:
            concept = f"{namespace}:{local_name}"
            rows = class_df[class_df["concept"] == concept]
            if len(rows) == 0:
                continue
            # Prefer numeric_value; fall back to value
            numeric = rows["numeric_value"].dropna()
            if len(numeric) == 0 and "value" in rows.columns:
                # Try to coerce
                try:
                    numeric = rows["value"].astype(float).dropna()
                except (ValueError, TypeError):
                    continue
            if len(numeric) == 0:
                continue
            # If multiple matches, take the first. In practice a single
            # (series, class, concept) triple yields one fact per filing.
            value = numeric.iloc[0]
            break
        if value is not None:
            scaled = _apply_scale(value)
            if scaled is not None:
                setattr(fees, field_name, scaled)

    if not fees.has_data:
        return None

    return fees


def extract_fees_from_485bpos_filings(
    filings_iter,
    series_id: str,
    class_id: str,
    max_depth: int = 15,
) -> Optional[ParsedFees]:
    """Walk 485BPOS filings in order, returning fees from the first XBRL match.

    Older 485BPOS filings often lack XBRL attachments. We iterate recent
    filings until we find one whose XBRL carries facts for our target class.

    Args:
        filings_iter: Iterable of edgartools Filing objects (e.g., output of
            series.get_filings().filter(form='485BPOS')).
        series_id: EDGAR series identifier.
        class_id: EDGAR share class identifier.
        max_depth: Maximum number of 485BPOS filings to open before giving up.

    Returns:
        ParsedFees from the first filing that yields a class-matched fact,
        or None if no filing in the search window works.
    """
    for i, filing in enumerate(filings_iter):
        if i >= max_depth:
            break
        try:
            obj = filing.obj()
        except Exception as exc:
            logger.debug(
                "filing.obj() raised for %s: %r",
                getattr(filing, "accession_no", "?"), exc,
            )
            continue
        if obj is None:
            continue
        fees = extract_fees_from_xbrl(obj, series_id, class_id)
        if fees is not None:
            logger.info(
                "XBRL fees extracted from %s (depth=%d) for class %s",
                getattr(filing, "accession_no", "?"), i, class_id,
            )
            return fees
    return None
