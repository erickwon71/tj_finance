"""`collector/pdf_lines_sync.py::recover_one()`/`facts_to_report_lines()` 단위
테스트(순수 로직, DB/HTTP 미의존 — `reconcile()`을 `unittest.mock.patch`로 대체).

배경(2026-09-07, 사용자 지시 "파이프라인 배선부터 진행해"): `recover_one()`이
PDF만 파싱하던 옛 방식에서 `fin2/extract/reconcile.py::reconcile()`(HTML→PDF
T1/T2/T3 조정)을 쓰도록 바뀌었다 — basis별 decision 이 "html"/"pdf"(자동
채택)인 facts 만 report_lines 에 담고, "unresolved"는 제외한다(호출자가
`report_recon_candidates` 리뷰 큐에 적재).

★`sync_pdf_recovery()`(DB write-path)는 이 프로젝트 관례대로(`fin2/audit/
curated_key_scan.py`/`fin2/extract/reconcile_store.py`와 동일) pytest 스위트가
아니라 수동 스모크로 검증한다.

실행: python fin2/tests/test_pdf_lines_sync.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import collector.pdf_lines_sync as pls  # noqa: E402
from collector.pdf_lines_sync import facts_to_report_lines, recover_one  # noqa: E402
from fin2.extract.reconcile import Confidence, ReconcileResult  # noqa: E402
from fin2.extract.xbrl import ExtractedFact  # noqa: E402


def _fact(canon, basis, amount, *, source_format="html"):
    return ExtractedFact(
        corp_code="00000000", rcept_no="r1", report_fiscal_year=2001,
        report_fiscal_period="H1", acode=canon.split(".")[-1], basis=basis,
        context_fiscal_year=2001, col_index=0, period_kind="instant",
        period_type="H1", is_cumulative=False, extra_dims=None,
        is_dimensional=False, adecimal=0, amount_won=amount,
        source_format=source_format, source_ref=None, acontext_raw=None,
        context_parsed=False, canonical_account=canon,
    )


def test_facts_to_report_lines_carries_source_format_as_unit_source():
    facts = [_fact("bs.total_assets", "separate", 300, source_format="html"),
             _fact("bs.total_liabilities", "separate", 100, source_format="pdf")]
    rows = facts_to_report_lines(facts)
    by_stmt = {r.label_raw: r for r in rows}
    assert rows[0].unit_source == "html"
    assert rows[1].unit_source == "pdf"


def test_facts_to_report_lines_skips_facts_without_canonical():
    f = _fact("bs.total_assets", "separate", 300)
    f_no_canon = ExtractedFact(**{**vars(f), "canonical_account": None})
    rows = facts_to_report_lines([f, f_no_canon])
    assert len(rows) == 1


def test_recover_one_only_includes_html_and_pdf_decisions_not_unresolved():
    """separate=html(T1) / consolidated=unresolved(T3/T3) 인 경우 —
    report_lines 에는 separate 만 실리고 consolidated 는 안 실려야 한다."""
    html_facts = [_fact("bs.total_assets", "separate", 300, source_format="html")]
    pdf_facts = [_fact("bs.total_equity", "consolidated", 999, source_format="pdf")]
    results = [
        ReconcileResult(
            corp_code="00000000", rcept_no="r1", basis="separate", decision="html",
            html_confidence=Confidence.T1_CONFIDENT, pdf_confidence=None,
            html_facts=html_facts, pdf_facts=None, reason="T1",
        ),
        ReconcileResult(
            corp_code="00000000", rcept_no="r1", basis="consolidated", decision="unresolved",
            html_confidence=Confidence.T3_AMBIGUOUS, pdf_confidence=Confidence.T3_AMBIGUOUS,
            html_facts=[], pdf_facts=pdf_facts, reason="T3/T3",
        ),
    ]
    with patch.object(pls, "reconcile", return_value=results):
        lines, returned_results = recover_one(
            scraper=object(), rcept_no="r1", corp_code="00000000",
            fiscal_year=2001, fiscal_period="H1")
    assert len(lines) == 1
    assert lines[0].basis == "separate"
    assert returned_results == results  # 호출자가 persist_unresolved() 에 그대로 넘길 수 있어야 함


def test_recover_one_uses_pdf_facts_when_decision_is_pdf():
    pdf_facts = [_fact("bs.total_assets", "separate", 300, source_format="pdf")]
    results = [
        ReconcileResult(
            corp_code="00000000", rcept_no="r1", basis="separate", decision="pdf",
            html_confidence=Confidence.T2_EMPTY, pdf_confidence=Confidence.T1_CONFIDENT,
            html_facts=[], pdf_facts=pdf_facts, reason="T2->pdf",
        ),
    ]
    with patch.object(pls, "reconcile", return_value=results):
        lines, _ = recover_one(
            scraper=object(), rcept_no="r1", corp_code="00000000",
            fiscal_year=2001, fiscal_period="H1")
    assert len(lines) == 1
    assert lines[0].unit_source == "pdf"


def test_recover_one_all_unresolved_returns_empty_lines_not_none():
    """전부 unresolved 면 report_lines 는 빈 리스트 — 호출자(sync_pdf_recovery)가
    `if lines:` 가드로 store_report_lines() 를 아예 안 부르게 하는 전제."""
    results = [
        ReconcileResult(
            corp_code="00000000", rcept_no="r1", basis="separate", decision="unresolved",
            html_confidence=Confidence.T2_EMPTY, pdf_confidence=Confidence.T2_EMPTY,
            html_facts=[], pdf_facts=[], reason="T2/T2",
        ),
    ]
    with patch.object(pls, "reconcile", return_value=results):
        lines, returned_results = recover_one(
            scraper=object(), rcept_no="r1", corp_code="00000000",
            fiscal_year=2001, fiscal_period="H1")
    assert lines == []
    assert returned_results == results


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {t.__name__}: {e}")
    print(f"\n{len(tests)} tests, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
