"""Tests for the batch snapshot runner and static site generator.

These use the injection seams in run_batch so no network, no EDGAR, and
no heavy dependencies are required.
"""

from __future__ import annotations

import json
from pathlib import Path

from fundautopsy.batch import default_quarter_label, run_batch
from fundautopsy.doctor import PipelineReport, StageResult
from fundautopsy.site import build_site


def _ok_report(ticker: str, notes: list[str] | None = None) -> PipelineReport:
    report = PipelineReport(ticker=ticker)
    for name, label in [
        ("resolve", "Resolve ticker to CIK / series / class"),
        ("structure", "Retrieve filings, detect fund structure"),
        ("costs", "Extract fees, compute cost estimates"),
        ("rollup", "Roll up fund-of-funds cost tree"),
    ]:
        report.stages.append(StageResult(name, label, "ok", 0.1))
    report.result = object()  # non-None sentinel; serializer is injected
    report.quality_notes = notes or []
    return report


def _failed_report(ticker: str) -> PipelineReport:
    report = PipelineReport(ticker=ticker)
    report.stages.append(
        StageResult("resolve", "Resolve ticker to CIK / series / class", "failed",
                    0.2, detail="KeyError: 'ZZZZX'", hint="Check the ticker.")
    )
    for name, label in [
        ("structure", "Retrieve filings, detect fund structure"),
        ("costs", "Extract fees, compute cost estimates"),
        ("rollup", "Roll up fund-of-funds cost tree"),
    ]:
        report.stages.append(StageResult(name, label, "skipped"))
    return report


def _fake_analysis(ticker: str, gap: float) -> dict:
    return {
        "ticker": ticker,
        "name": f"Test Fund {ticker}",
        "fund_family": "Test Family",
        "cik": "0000000000",
        "series_id": "S000000001",
        "class_id": "C000000001",
        "net_assets": 1_000_000_000,
        "reporting_period_end": "2025-12-31",
        "costs": {
            "total_reported_bps": 65.0,
            "total_estimated_low_bps": 80.0,
            "total_estimated_high_bps": 120.0,
            "hidden_cost_gap_bps": gap,
            "expense_ratio_bps": {"value": 65.0, "tag": "REPORTED"},
            "brokerage_commissions_bps": {"value": 12.0, "tag": "REPORTED", "note": None},
            "bid_ask_spread_cost": {
                "low_bps": 5.0, "high_bps": 20.0, "mid_bps": 12.5,
                "tag": "ESTIMATED", "methodology": "asset-class assumptions",
            },
            "soft_dollar_arrangements": {"active": True, "value_bps": 3.0, "tag": "REPORTED"},
        },
        "data_notes": [],
    }


class TestBatch:
    def test_quarter_label(self) -> None:
        from datetime import date

        assert default_quarter_label(date(2026, 7, 5)) == "2026-Q3"
        assert default_quarter_label(date(2026, 1, 1)) == "2026-Q1"
        assert default_quarter_label(date(2026, 12, 31)) == "2026-Q4"

    def test_run_batch_writes_snapshots_and_manifest(self, tmp_path: Path) -> None:
        gaps = {"AAAAX": 40.0, "BBBBX": 55.0}

        def pipeline(ticker: str) -> PipelineReport:
            if ticker == "ZZZZX":
                return _failed_report(ticker)
            if ticker == "CCCCX":
                return _ok_report(ticker, notes=["CCCCX: soft dollar fields blank"])
            return _ok_report(ticker)

        out_root = tmp_path / "snaps"
        for ticker in ["AAAAX", "BBBBX", "CCCCX", "ZZZZX"]:
            run_batch(
                [ticker], out_root,
                pipeline=pipeline,
                serializer=lambda _n, t=ticker: _fake_analysis(t, gaps.get(t, 30.0)),
            )

        qdir = out_root / default_quarter_label()
        assert (qdir / "AAAAX.json").exists()
        assert (qdir / "ZZZZX.json").exists()
        assert (qdir / "manifest.json").exists()

        zzz = json.loads((qdir / "ZZZZX.json").read_text())
        assert zzz["analysis"] is None
        assert "excluded_reason" in zzz
        assert "KeyError" in zzz["excluded_reason"]

        ccc = json.loads((qdir / "CCCCX.json").read_text())
        assert ccc["analysis"] is not None
        assert ccc["provenance"]["quality_notes"] == ["CCCCX: soft dollar fields blank"]

    def test_run_batch_skips_existing_without_force(self, tmp_path: Path) -> None:
        out_root = tmp_path / "snaps"
        kwargs = dict(
            pipeline=lambda t: _ok_report(t),
            serializer=lambda _n: _fake_analysis("AAAAX", 40.0),
        )
        first = run_batch(["AAAAX"], out_root, **kwargs)
        second = run_batch(["AAAAX"], out_root, **kwargs)
        forced = run_batch(["AAAAX"], out_root, force=True, **kwargs)
        assert first.complete == ["AAAAX"]
        assert second.skipped == ["AAAAX"]
        assert forced.complete == ["AAAAX"]

    def test_run_batch_ignores_comments_and_blanks(self, tmp_path: Path) -> None:
        summary = run_batch(
            ["# header", "", "AAAAX"], tmp_path / "snaps",
            pipeline=lambda t: _ok_report(t),
            serializer=lambda _n: _fake_analysis("AAAAX", 40.0),
        )
        assert summary.complete == ["AAAAX"]


class TestSite:
    def _write_snapshot(self, qdir: Path, ticker: str, gap: float | None,
                        excluded: bool = False, notes: list[str] | None = None) -> None:
        qdir.mkdir(parents=True, exist_ok=True)
        report = _failed_report(ticker) if excluded else _ok_report(ticker, notes)
        snap = {
            "snapshot_version": "2.0",
            "generated": "2026-07-05",
            "quarter": "2026-Q3",
            "ticker": ticker,
            "provenance": report.to_dict(),
            "analysis": None if excluded else _fake_analysis(ticker, gap or 0.0),
        }
        if excluded:
            snap["excluded_reason"] = "resolution failed"
        (qdir / f"{ticker}.json").write_text(json.dumps(snap))

    def test_build_site_renders_index_and_fund_pages(self, tmp_path: Path) -> None:
        qdir = tmp_path / "2026-Q3"
        self._write_snapshot(qdir, "AAAAX", 40.0)
        self._write_snapshot(qdir, "BBBBX", 90.0)
        self._write_snapshot(qdir, "ZZZZX", None, excluded=True)

        out = tmp_path / "site"
        counts = build_site(qdir, out)

        assert counts == {"funds": 2, "excluded": 1}
        index = (out / "index.html").read_text()
        assert "Tombstone Research" in index
        assert "AAAAX" in index and "BBBBX" in index
        assert "ZZZZX" not in index  # excluded funds never render
        # Sorted by gap descending: BBBBX (90) before AAAAX (40)
        assert index.index("BBBBX") < index.index("AAAAX")
        assert (out / "funds" / "AAAAX.html").exists()
        assert (out / "style.css").exists()

    def test_fund_page_contains_provenance_and_disclaimer(self, tmp_path: Path) -> None:
        qdir = tmp_path / "2026-Q3"
        self._write_snapshot(qdir, "AAAAX", 40.0, notes=["AAAAX: fallback used"])
        out = tmp_path / "site"
        build_site(qdir, out)
        page = (out / "funds" / "AAAAX.html").read_text()
        assert "Chain of custody" in page
        assert "fallback used" in page
        assert "not investment advice" in page.lower()
        assert "Autopsy report No. 001" in page

    def test_build_site_escapes_html(self, tmp_path: Path) -> None:
        qdir = tmp_path / "2026-Q3"
        qdir.mkdir(parents=True)
        analysis = _fake_analysis("AAAAX", 40.0)
        analysis["name"] = "<script>alert(1)</script>"
        snap = {
            "quarter": "2026-Q3", "ticker": "AAAAX",
            "provenance": _ok_report("AAAAX").to_dict(),
            "analysis": analysis,
        }
        (qdir / "AAAAX.json").write_text(json.dumps(snap))
        out = tmp_path / "site"
        build_site(qdir, out)
        page = (out / "funds" / "AAAAX.html").read_text()
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;" in page


class TestDoctorReport:
    def test_verdicts(self) -> None:
        ok = _ok_report("AAAAX")
        assert ok.completed
        assert "COMPLETE" in ok.verdict

        caveat = _ok_report("AAAAX", notes=["note"])
        assert "CAVEATS" in caveat.verdict

        failed = _failed_report("ZZZZX")
        assert not failed.completed
        assert "EXCLUDED" in failed.verdict
        assert "resolve" in failed.verdict

    def test_to_dict_round_trip(self) -> None:
        d = _ok_report("AAAAX", notes=["n1"]).to_dict()
        assert d["ticker"] == "AAAAX"
        assert len(d["stages"]) == 4
        assert d["quality_notes"] == ["n1"]
