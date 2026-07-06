"""Tests for the XBRL fee parser's scale conversion and context matching.

Unit tests exercise the deterministic helpers without requiring network
or real XBRL documents. The live validation at
Intelligence/_xbrl_module_validate_2026-04-22.py runs the full extractor
against real SEC filings.
"""
from __future__ import annotations

import pytest

from fundautopsy.data.xbrl_fee_parser import (
    _apply_scale,
    _FEE_CONCEPTS,
)


# ── _apply_scale: decimal fraction → basis-point percentage ──────────


def test_scale_converts_decimal_fraction():
    # 0.0092 (92 bps as decimal) should convert to 0.92%
    assert _apply_scale(0.0092) == 0.92


def test_scale_handles_zero():
    assert _apply_scale(0.0) == 0.0


def test_scale_rounds_ieee_float_noise():
    # 0.0044 * 100 = 0.44 (but IEEE can produce 0.4399999...)
    result = _apply_scale(0.0044)
    assert result == 0.44  # rounded to 4 decimal places


def test_scale_small_negative_fee_waiver_preserved():
    # Fee waivers are reported as negative decimals; the scale helper
    # preserves them within the sanity threshold.
    result = _apply_scale(-0.0050)
    assert result == -0.50


def test_scale_logs_warning_on_sanity_threshold_breach(caplog):
    # Outlandish value (50000%) is beyond the sanity threshold. The
    # scale helper preserves the raw value so downstream logic can
    # decide what to do, but emits a WARNING so auditors see it.
    import logging
    with caplog.at_level(logging.WARNING):
        _apply_scale(500.0)
    assert any(
        "sanity" in r.message.lower() or "threshold" in r.message.lower()
        for r in caplog.records
    )


def test_scale_none_input_returns_none():
    assert _apply_scale(None) is None


# ── _FEE_CONCEPTS taxonomy ───────────────────────────────────────────


def test_fee_concepts_covers_key_categories():
    """Essential fee concepts are represented in the taxonomy map."""
    expected_keys = {
        "management_fee",
        "twelve_b1_fee",
        "other_expenses",
        "acquired_fund_fees",
        "total_annual_expenses",
        "fee_waiver",
        "net_expenses",
    }
    assert expected_keys.issubset(_FEE_CONCEPTS.keys())


def test_fee_concepts_each_have_both_namespaces():
    """Every concept declares both oef: and rr: taxonomies so the
    extractor can handle either registrant convention."""
    for field_name, candidates in _FEE_CONCEPTS.items():
        namespaces = {ns for ns, _concept in candidates}
        assert "oef" in namespaces, f"{field_name} missing oef namespace"
        assert "rr" in namespaces, f"{field_name} missing rr namespace"


def test_fee_concepts_concept_names_consistent_across_namespaces():
    """The concept localname should be the same in both namespaces."""
    for field_name, candidates in _FEE_CONCEPTS.items():
        concept_names = {concept for _ns, concept in candidates}
        # Both oef: and rr: should point at the same concept name
        assert len(concept_names) == 1, (
            f"{field_name} has divergent concept names across namespaces: "
            f"{concept_names}"
        )


def test_management_fee_concept_correct():
    """Spot check: management_fee should map to ManagementFeesOverAssets."""
    candidates = _FEE_CONCEPTS["management_fee"]
    names = {concept for _ns, concept in candidates}
    assert "ManagementFeesOverAssets" in names


def test_total_expenses_concept_correct():
    candidates = _FEE_CONCEPTS["total_annual_expenses"]
    names = {concept for _ns, concept in candidates}
    assert "ExpensesOverAssets" in names
