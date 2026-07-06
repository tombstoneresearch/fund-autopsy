"""Tests for fund-of-funds recursive hydration in core.structure.

The resolver and EDGAR filing retrieval are mocked so these tests run
without network access. The focus is on verifying that:

1. A wrapper holding its siblings as underlying funds produces children
   with allocation weights that sum to 1.0 across the unwindable pool.
2. Recursion stops at MAX_RECURSION_DEPTH.
3. Unresolved holdings are noted but don't crash the build.
4. The detected fund-of-funds flag on FundMetadata is set.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from fundautopsy.core.structure import detect_structure
from fundautopsy.data.edgar import MutualFundIdentifier
from fundautopsy.data.ncen import NCENFullData
from fundautopsy.models.filing_data import NPortData, NPortHolding
from fundautopsy.models.fund_metadata import FundMetadata
from fundautopsy.models.holdings_tree import MAX_RECURSION_DEPTH


def _wrapper_metadata() -> FundMetadata:
    return FundMetadata(
        ticker="TGTDX",
        name="Example Target Date 2040 Fund",
        cik="1111111",
        series_id="S000000100",
        class_id="C000000100",
        fund_family="Example Funds",
    )


def _child_metadata(ticker: str, series: str) -> FundMetadata:
    return FundMetadata(
        ticker=ticker,
        name=f"{ticker} Underlying Fund",
        cik=f"222{series[-4:]}",
        series_id=series,
        class_id="C000000200",
        fund_family="Example Funds",
    )


def _make_fof_nport() -> NPortData:
    """Construct an N-PORT payload for a fund-of-funds holding two
    sibling share classes."""
    nport = NPortData(
        filing_date=date(2026, 3, 31),
        reporting_period_end=date(2026, 3, 31),
        series_id="S000000100",
        total_net_assets=100_000_000,
    )
    nport.holdings = [
        NPortHolding(
            name="Example 500 Index Fund (EXAMX)",
            issuer_category="RF",
            cusip="111111111",
            pct_of_net_assets=60.0,
            value_usd=60_000_000,
        ),
        NPortHolding(
            name="Example Intl Equity Fund (INTLX)",
            issuer_category="RF",
            cusip="222222222",
            pct_of_net_assets=40.0,
            value_usd=40_000_000,
        ),
    ]
    return nport


class TestRecursiveHydration:
    def test_wrapper_gains_two_children_when_resolvable(self):
        """FoF with two resolvable holdings produces two normalized children."""
        fake_nport = _make_fof_nport()

        # Resolver returns different identifiers based on holding name
        def fake_resolver(holding_name, cusip=None, isin=None, client=None):
            if "EXAMX" in holding_name:
                return MutualFundIdentifier(
                    ticker="EXAMX", cik=2220001,
                    series_id="S000000201", class_id="C000000201",
                )
            if "INTLX" in holding_name:
                return MutualFundIdentifier(
                    ticker="INTLX", cik=2220002,
                    series_id="S000000202", class_id="C000000202",
                )
            return None

        with (
            patch("fundautopsy.core.structure.retrieve_nport",
                  side_effect=lambda fid: fake_nport if fid.series_id == "S000000100" else None),
            patch("fundautopsy.core.structure.retrieve_ncen", return_value=None),
            patch("fundautopsy.core.structure.resolve_holding_to_fund",
                  side_effect=fake_resolver),
        ):
            root = detect_structure(_wrapper_metadata())

        assert root.metadata.is_fund_of_funds is True
        assert len(root.children) == 2

        # Weights are the holding's share of the unwindable pool
        weights = sorted(c.allocation_weight for c in root.children)
        assert weights == pytest.approx([0.4, 0.6], rel=1e-6)
        assert sum(c.allocation_weight for c in root.children) == pytest.approx(1.0)

    def test_unresolved_holding_produces_note(self):
        """When a holding can't be resolved, note it but don't fail."""
        fake_nport = _make_fof_nport()

        def fake_resolver(holding_name, cusip=None, isin=None, client=None):
            # Only resolve one of the two holdings
            if "EXAMX" in holding_name:
                return MutualFundIdentifier(
                    ticker="EXAMX", cik=2220001,
                    series_id="S000000201", class_id="C000000201",
                )
            return None

        with (
            patch("fundautopsy.core.structure.retrieve_nport",
                  side_effect=lambda fid: fake_nport if fid.series_id == "S000000100" else None),
            patch("fundautopsy.core.structure.retrieve_ncen", return_value=None),
            patch("fundautopsy.core.structure.resolve_holding_to_fund",
                  side_effect=fake_resolver),
        ):
            root = detect_structure(_wrapper_metadata())

        assert len(root.children) == 1
        # Note should explicitly call out the unresolved holding
        assert any("unresolved" in n.lower() for n in root.data_notes)

    def test_recursion_depth_capped(self):
        """detect_structure should not recurse past MAX_RECURSION_DEPTH."""
        # Construct a fund that always returns the same N-PORT (itself
        # holding the same fund) so infinite recursion would be possible
        # if the cap weren't enforced.
        loopy_nport = NPortData(
            filing_date=date(2026, 3, 31),
            reporting_period_end=date(2026, 3, 31),
            series_id="S000000100",
            total_net_assets=100_000_000,
        )
        loopy_nport.holdings = [
            NPortHolding(
                name="Looping Fund (LOOPX)",
                issuer_category="RF",
                cusip="999999999",
                pct_of_net_assets=100.0,
                value_usd=100_000_000,
            ),
        ]

        call_counter = {"n": 0}

        def fake_resolver(holding_name, cusip=None, isin=None, client=None):
            call_counter["n"] += 1
            return MutualFundIdentifier(
                ticker="LOOPX", cik=9999999,
                series_id="S000000100", class_id="C000000100",
            )

        with (
            patch("fundautopsy.core.structure.retrieve_nport",
                  return_value=loopy_nport),
            patch("fundautopsy.core.structure.retrieve_ncen", return_value=None),
            patch("fundautopsy.core.structure.resolve_holding_to_fund",
                  side_effect=fake_resolver),
        ):
            root = detect_structure(_wrapper_metadata())

        # Walk the tree and verify no node exceeds MAX_RECURSION_DEPTH
        for node in root.walk():
            assert node.depth < MAX_RECURSION_DEPTH

        # The recursion should terminate, and a max-depth note should
        # exist somewhere in the tree.
        all_notes = []
        for node in root.walk():
            all_notes.extend(node.data_notes)
        assert any("max recursion depth" in n.lower() for n in all_notes)
