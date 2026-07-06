"""Prospectus fee data retrieval via edgartools 497K parsing.

Extracts expense ratio components and portfolio turnover from
SEC Form 497K (Summary Prospectus) filings.

Strategy:
1. Try edgartools' built-in 497K parser (works for most fund families)
2. If edgartools returns all-None fee fields, fall back to our custom
   HTML parser that handles Dodge & Cox, Oakmark, Fidelity, and other
   non-standard table formats
3. For multi-fund trusts that file separate 497Ks per share class,
   search through recent filings to find the one containing the ticker
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import edgar

logger = logging.getLogger(__name__)

from fundautopsy.data.fee_parser import find_filing_for_ticker, parse_497k_html
from fundautopsy.data.american_funds_fee_parser import try_american_funds_fees
from fundautopsy.data.fidelity_series_fee_parser import try_fidelity_series_fees
from fundautopsy.data.xbrl_fee_parser import extract_fees_from_485bpos_filings


# Set identity for EDGAR access
from fundautopsy.config import EDGAR_USER_AGENT as _EDGAR_UA
edgar.set_identity(_EDGAR_UA)


@dataclass
class ProspectusFees:
    """Fee data extracted from 497K summary prospectus."""

    ticker: str
    class_name: str

    # Fee components (as percentages, e.g., 0.59 = 0.59%)
    total_annual_expenses: Optional[float] = None
    net_expenses: Optional[float] = None  # After waivers
    management_fee: Optional[float] = None
    twelve_b1_fee: Optional[float] = None
    other_expenses: Optional[float] = None
    acquired_fund_fees: Optional[float] = None
    fee_waiver: Optional[float] = None

    # Loads
    max_sales_load: Optional[float] = None
    max_deferred_sales_load: Optional[float] = None
    redemption_fee: Optional[float] = None

    # Portfolio turnover (as percentage, e.g., 32 = 32%)
    portfolio_turnover: Optional[float] = None

    @property
    def expense_ratio_pct(self) -> Optional[float]:
        """Net expense ratio (after waivers), falling back to gross."""
        if self.net_expenses is not None:
            return self.net_expenses
        return self.total_annual_expenses

    @property
    def expense_ratio_bps(self) -> Optional[float]:
        """Expense ratio in basis points."""
        er = self.expense_ratio_pct
        if er is not None:
            return er * 100
        return None


def _edgartools_has_fees(target_class) -> bool:
    """Check if edgartools actually parsed fee values (not all None)."""
    return any(
        getattr(target_class, attr, None) is not None
        for attr in (
            "management_fee",
            "total_annual_expenses",
            "net_expenses",
        )
    )


def retrieve_prospectus_fees(
    ticker: str,
    series_id: Optional[str] = None,
    class_id: Optional[str] = None,
) -> Optional[ProspectusFees]:
    """Retrieve fee data from the most recent 497K filing.

    Uses edgartools to find the fund and locate 497K filings. If the
    built-in parser returns empty fee fields, falls back to our custom
    HTML parser. For multi-fund trusts, searches through filings to
    find the one containing the specific ticker.

    Args:
        ticker: Fund ticker symbol.
        series_id: Optional series ID for matching.
        class_id: Optional class ID for matching.

    Returns:
        ProspectusFees if found, None otherwise.
    """
    try:
        ticker_upper = ticker.upper()
        # edgartools raises CompanyNotFoundError for tickers it cannot
        # resolve (e.g. NWDAX, where the ticker doesn't appear in the
        # SEC ticker universe), rather than returning None. Catch that
        # specific raise so the walker fallback below gets a chance.
        try:
            fund_class = edgar.find_fund(ticker_upper)
        except Exception as exc:
            logger.info(
                "edgar.find_fund raised for %s (%s); falling through to walker",
                ticker_upper, exc,
            )
            fund_class = None

        # Resolved identifiers: may be upgraded by the walker path below if
        # the caller didn't supply them. Downstream the edgartools parser
        # uses resolved_class_id as a backup match key when the filing's
        # share-class list carries no ticker on the row we care about. The
        # XBRL fallback uses both resolved_series_id and resolved_class_id
        # to match per-class fee facts in 485BPOS statutory prospectuses.
        resolved_class_id = class_id
        resolved_series_id = series_id

        if fund_class is None:
            # Walker fallback. edgar.find_fund misses tickers whose SGML
            # class row doesn't appear under the trust's primary CIK — common
            # for multi-series trusts where the ticker lives under a
            # sub-series filer (Fidelity Concord Street, Oakmark Funds, MFS
            # Series Trust I, etc.). Our resolve_ticker hits the MF universe
            # file first and falls through to the ICF walker, which recovers
            # CIK + series_id + class_id directly from 497/485BPOS SGML
            # headers. With a series_id in hand we can reconstruct a series
            # object via edgar.get_fund(series_id) and rejoin the existing
            # pipeline.
            from fundautopsy.data.edgar import resolve_ticker as _resolve_ticker
            mfid = _resolve_ticker(ticker_upper)
            if mfid is None:
                return None
            # edgar.Fund(series_id) returns a FundSeries object with
            # get_filings() support, letting the rest of the pipeline
            # stay identical to the find_fund path. edgartools >=4.0
            # exposes neither get_fund nor a direct FundSeries(...)
            # constructor that takes only an ID, so Fund(ID) is the
            # stable public entry point.
            try:
                series = edgar.Fund(mfid.series_id)
            except Exception as exc:
                logger.warning(
                    "Walker-path series construction failed for %s (%s): %s",
                    ticker_upper, mfid.series_id, exc,
                )
                return None
            if series is None:
                return None
            fund_name = getattr(series, "name", None)
            if resolved_class_id is None:
                resolved_class_id = mfid.class_id
            if resolved_series_id is None:
                resolved_series_id = mfid.series_id
            logger.info(
                "Walker fallback engaged for %s: series=%s class=%s",
                ticker_upper, mfid.series_id, mfid.class_id,
            )
        else:
            # American Funds: edgartools' 497K parser scrambles fee rows against
            # share-class columns (e.g. R-6 classes report 1.00% 12b-1 fees, which
            # by definition do not exist). Route American Funds tickers through a
            # dedicated 485BPOS parser that aligns the target column using the SGML
            # submission header's authoritative class_name. Returns None for any
            # non-American-Funds registrant, so the rest of the pipeline runs
            # normally.
            af_result = try_american_funds_fees(ticker, fund_class=fund_class)
            if af_result is not None:
                return af_result

            # Fidelity Series building-block funds (FSSJX, FSTSX, FEMSX, etc.)
            # do not file 497Ks; their fee tables live only inside the annual
            # Fidelity Investment Trust 485BPOS omnibus prospectus. Route
            # these tickers through the 485BPOS prose-fee parser. Returns
            # None for any non-Fidelity-Series fund so the 497K pipeline
            # continues to handle Freedom target-date, Advisor, Select, and
            # every other Fidelity product as before.
            fs_result = try_fidelity_series_fees(ticker, fund_class=fund_class)
            if fs_result is not None:
                return fs_result

            series = fund_class.series
            fund_name = series.name if hasattr(series, "name") else None
            if resolved_class_id is None:
                resolved_class_id = getattr(fund_class, "class_id", None)
            if resolved_series_id is None:
                resolved_series_id = (
                    getattr(series, "series_id", None)
                    or getattr(series, "series", None)
                )

        filings = series.get_filings()
        k497_filings = filings.filter(form="497K")

        if len(k497_filings) == 0:
            # No 497K path available — try XBRL fallback on 485BPOS.
            # Fidelity Series building-block funds, some Vanguard direct-sold
            # funds, and a handful of older TDFs file only statutory
            # prospectuses. XBRL facts in 485BPOS carry per-class fee data
            # tagged by series_id + class_id context_refs.
            return _try_xbrl_fallback(
                filings, ticker, resolved_series_id, resolved_class_id
            )

        # --- Pick the right filing FIRST ---
        # Multi-fund trusts (Fidelity, Schwab, etc.) file many separate 497Ks
        # under the same series. Selecting k497_filings[0] blindly can feed
        # a completely different fund into edgartools, producing an
        # authoritative-looking but wrong expense ratio. We search all
        # recent filings for the requested ticker before parsing.
        matched_filing = find_filing_for_ticker(k497_filings, ticker)

        # --- Try edgartools built-in parser on the MATCHED filing first ---
        # If we didn't find an exact ticker match in any filing, fall back to
        # the most recent filing (behaviour preserved for single-fund trusts
        # where find_filing_for_ticker returns None because the HTML substring
        # search misses the ticker in the specific 497K format).
        filings_to_try = (
            [matched_filing] if matched_filing is not None
            else list(k497_filings[:5])
        )
        result = _try_edgartools_parser(filings_to_try, ticker, resolved_class_id)
        if result is not None:
            return result

        # --- Fall back to custom HTML parser ---
        # Only trust the HTML parser when find_filing_for_ticker actually
        # matched the requested ticker. Falling back to k497_filings[0]
        # when no match was found reintroduces the umbrella-trust
        # misattribution bug: multi-class series (Fidelity Freedom Index
        # 2050, Oakmark Fund, MFS Value, etc.) file one 497K per share
        # class, and _find_class_column defaults to column 0 when the
        # ticker is absent from the headers — silently returning a
        # different class's expense ratio as if it were the target
        # ticker's. A None return is strictly better than wrong data.
        if matched_filing is None:
            logger.info(
                "Skipping HTML fallback for %s: no ticker-matched 497K in series — "
                "attempting XBRL fallback",
                ticker,
            )
            return _try_xbrl_fallback(
                filings, ticker, resolved_series_id, resolved_class_id
            )
        filing = matched_filing

        html = filing.html()
        if not html:
            return _try_xbrl_fallback(
                filings, ticker, resolved_series_id, resolved_class_id
            )

        parsed = parse_497k_html(html, ticker, fund_name)
        if not parsed.has_data:
            # 497K exists and we matched the right one, but the HTML is a
            # sticker / supplement (common for FXAIX, JTSAX-class stickers).
            # Fall through to structured XBRL data in the 485BPOS.
            return _try_xbrl_fallback(
                filings, ticker, resolved_series_id, resolved_class_id
            )

        # Compute total from components if not directly available.
        # Only sum components when all major fields are present to avoid
        # understating the total if a component was missed during parsing.
        total = parsed.total_annual_expenses
        if total is None and parsed.management_fee is not None:
            # At minimum, management fee + 12b-1 + other expenses should all be present
            # for a reliable synthetic total. If any are missing, just use management fee alone.
            if parsed.twelve_b1_fee is not None and parsed.other_expenses is not None:
                total = parsed.management_fee + parsed.twelve_b1_fee + parsed.other_expenses
                total = round(total, 2)
            else:
                logger.debug(
                    "Skipping synthetic total for %s: incomplete fee components "
                    "(mgmt=%.2f, 12b1=%s, other=%s)",
                    ticker, parsed.management_fee, parsed.twelve_b1_fee, parsed.other_expenses,
                )

        # Build the 497K-path ProspectusFees.
        html_fees = ProspectusFees(
            ticker=ticker.upper(),
            class_name="",
            total_annual_expenses=total,
            net_expenses=parsed.net_expenses,
            management_fee=parsed.management_fee,
            twelve_b1_fee=parsed.twelve_b1_fee,
            other_expenses=parsed.other_expenses,
            acquired_fund_fees=parsed.acquired_fund_fees,
            fee_waiver=parsed.fee_waiver,
            max_sales_load=parsed.max_sales_load,
            portfolio_turnover=parsed.portfolio_turnover,
        )

        # If the HTML parser extracted components but neither a total nor a
        # net expense ratio, downstream consumers can't produce an expense
        # ratio from the result. Try the XBRL path — it carries the
        # structured aggregate concepts (ExpensesOverAssets,
        # NetExpensesOverAssets) and will commonly succeed where the HTML
        # anchor-based parser tripped on an unusual row layout. If the
        # XBRL path also fails, surface the HTML-partial result so the
        # component data (management_fee, turnover, etc.) isn't lost.
        if html_fees.expense_ratio_pct is None:
            xbrl_fees = _try_xbrl_fallback(
                filings, ticker, resolved_series_id, resolved_class_id
            )
            if xbrl_fees is not None and xbrl_fees.expense_ratio_pct is not None:
                # Merge: prefer XBRL's aggregate ratios, preserve HTML's
                # turnover and loads when XBRL omitted them.
                if xbrl_fees.portfolio_turnover is None:
                    xbrl_fees.portfolio_turnover = html_fees.portfolio_turnover
                if xbrl_fees.max_sales_load is None:
                    xbrl_fees.max_sales_load = html_fees.max_sales_load
                return xbrl_fees

        return html_fees

    except Exception as exc:
        # Prospectus parsing is best-effort — don't crash the pipeline
        logger.warning("Prospectus retrieval failed for %s: %s", ticker, exc)
        return None


def _try_xbrl_fallback(
    filings,
    ticker: str,
    series_id: Optional[str],
    class_id: Optional[str],
) -> Optional[ProspectusFees]:
    """XBRL-based fee extraction from 485BPOS when 497K path yields nothing.

    Walks the series' 485BPOS statutory prospectus filings looking for one
    with XBRL facts scoped to our target (series_id, class_id). 485BPOS
    filings carry per-class fee concepts under the oef: or rr: taxonomies;
    this path handles umbrella trusts cleanly because each class has its
    own context_ref.

    Returns None when series_id or class_id is unknown (we cannot match
    context_refs without both) or when no 485BPOS in the search window
    carries XBRL for this class.
    """
    if not series_id or not class_id:
        logger.debug(
            "Skipping XBRL fallback for %s: missing series_id=%r class_id=%r",
            ticker, series_id, class_id,
        )
        return None
    try:
        bpos = filings.filter(form="485BPOS")
    except Exception as exc:
        logger.debug("485BPOS filter raised for %s: %s", ticker, exc)
        return None
    if len(bpos) == 0:
        return None

    parsed = extract_fees_from_485bpos_filings(bpos, series_id, class_id)
    if parsed is None:
        return None

    # Synthesize total from components when XBRL omitted the aggregate tag.
    # Require management_fee + other_expenses to be present; treat
    # twelve_b1_fee and acquired_fund_fees as zero if absent. Classes
    # without 12b-1 plans (Oakmark Investor, institutional shares,
    # direct-only classes) legitimately omit the tag; requiring it would
    # leave their total as None even when the real aggregate is available
    # from mgmt + other alone.
    total = parsed.total_annual_expenses
    if (
        total is None
        and parsed.management_fee is not None
        and parsed.other_expenses is not None
    ):
        total = round(
            parsed.management_fee
            + (parsed.twelve_b1_fee or 0.0)
            + parsed.other_expenses
            + (parsed.acquired_fund_fees or 0.0),
            4,
        )

    return ProspectusFees(
        ticker=ticker.upper(),
        class_name="",
        total_annual_expenses=total,
        net_expenses=parsed.net_expenses,
        management_fee=parsed.management_fee,
        twelve_b1_fee=parsed.twelve_b1_fee,
        other_expenses=parsed.other_expenses,
        acquired_fund_fees=parsed.acquired_fund_fees,
        fee_waiver=parsed.fee_waiver,
        max_sales_load=parsed.max_sales_load,
        portfolio_turnover=parsed.portfolio_turnover,
    )


def _try_edgartools_parser(
    k497_filings, ticker: str, class_id: Optional[str]
) -> Optional[ProspectusFees]:
    """Attempt to extract fees using edgartools' built-in 497K parser.

    Iterates through the provided filings (already narrowed to the most
    likely candidates) and only accepts a result when the matched share
    class's ticker matches the requested ticker exactly. This prevents
    multi-fund-trust 497Ks from returning fee data for the wrong fund.
    """
    ticker_upper = ticker.upper()
    for filing in k497_filings:
        try:
            prospectus = filing.obj()
            if prospectus is None:
                continue

            # Strict: require an exact ticker match on a share class.
            target_class = None
            for sc in prospectus.share_classes:
                if sc.ticker and sc.ticker.upper() == ticker_upper:
                    target_class = sc
                    break

            # Fall-back 1: class_id match (caller-provided hint).
            if target_class is None and class_id:
                for sc in prospectus.share_classes:
                    if sc.class_id == class_id:
                        target_class = sc
                        break

            # Fall-back 2: a single-class filing. Only accept this when the
            # filing itself is unambiguously about one fund. We do NOT fall
            # back on the first class of a multi-class filing — that was
            # the root cause of multi-fund-trust misattribution.
            if target_class is None and len(prospectus.share_classes) == 1:
                sc = prospectus.share_classes[0]
                if sc.ticker is None or sc.ticker.upper() == ticker_upper:
                    target_class = sc

            if target_class is None:
                continue

            # Final safety check: if the selected class has a ticker, it
            # must match. A None-ticker on a single-class filing is the only
            # permitted unknown.
            if target_class.ticker and target_class.ticker.upper() != ticker_upper:
                continue

            if not _edgartools_has_fees(target_class):
                continue

            return ProspectusFees(
                ticker=ticker_upper,
                class_name=target_class.class_name or "",
                total_annual_expenses=_to_float(target_class.total_annual_expenses),
                net_expenses=_to_float(target_class.net_expenses),
                management_fee=_to_float(target_class.management_fee),
                twelve_b1_fee=_to_float(target_class.twelve_b1_fee),
                other_expenses=_to_float(target_class.other_expenses),
                acquired_fund_fees=_to_float(target_class.acquired_fund_fees),
                fee_waiver=_to_float(target_class.fee_waiver),
                max_sales_load=_to_float(target_class.max_sales_load),
                max_deferred_sales_load=_to_float(
                    target_class.max_deferred_sales_load
                ),
                redemption_fee=_to_float(target_class.redemption_fee),
                portfolio_turnover=_to_float(prospectus.portfolio_turnover),
            )
        except Exception as exc:
            logger.debug(
                "edgartools 497K parser failed for %s on filing %s: %s",
                ticker, getattr(filing, "accession_no", "?"), exc,
            )
            continue
    return None


def _to_float(val) -> Optional[float]:
    """Convert Decimal or other numeric to float, or None."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
