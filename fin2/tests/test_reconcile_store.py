"""`fin2/extract/reconcile_store.py` 순수 로직(`build_recon_candidate_rows`) 단위 테스트.

★ `persist_unresolved()`(실제 session.execute/upsert)는 여기서 테스트하지 않는다 —
`fin2/tests/test_curated_key_scan.py` 와 동일 관례(DB 의존 write-path 는 pytest
스위트가 아니라 수동 스모크로 1회 검증, 결과를 대화/문서에 남긴다).

실행: python -m fin2.tests.test_reconcile_store
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.reconcile import Confidence, ReconcileResult  # noqa: E402
from fin2.extract.reconcile_store import build_recon_candidate_rows  # noqa: E402
from fin2.extract.xbrl import ExtractedFact  # noqa: E402


def _fact(canon, basis, amount):
    return ExtractedFact(
        corp_code="00000000", rcept_no="r1", report_fiscal_year=2001,
        report_fiscal_period="H1", acode=canon.split(".")[-1], basis=basis,
        context_fiscal_year=2001, col_index=0, period_kind="instant",
        period_type="H1", is_cumulative=False, extra_dims=None,
        is_dimensional=False, adecimal=0, amount_won=amount,
        source_format="test", source_ref=None, acontext_raw=None,
        context_parsed=False, canonical_account=canon,
    )


def _unresolved_result(basis="separate", html_amt=150, pdf_amt=190):
    html_facts = [
        _fact("bs.total_assets", basis, 300),
        _fact("bs.total_liabilities", basis, 100),
        _fact("bs.total_equity", basis, html_amt),
    ]
    pdf_facts = [
        _fact("bs.total_assets", basis, 300),
        _fact("bs.total_liabilities", basis, 100),
        _fact("bs.total_equity", basis, pdf_amt),
    ]
    return ReconcileResult(
        corp_code="00000000", rcept_no="r1", basis=basis, decision="unresolved",
        html_confidence=Confidence.T3_AMBIGUOUS, pdf_confidence=Confidence.T3_AMBIGUOUS,
        html_facts=html_facts, pdf_facts=pdf_facts,
        reason="HTML·PDF 둘 다 T1 아님(애매함) — 자동 채택 안 함, 사람 확인 대기",
    )


def _html_decided_result(basis="separate"):
    facts = [
        _fact("bs.total_assets", basis, 300),
        _fact("bs.total_liabilities", basis, 100),
        _fact("bs.total_equity", basis, 200),
    ]
    return ReconcileResult(
        corp_code="00000000", rcept_no="r1", basis=basis, decision="html",
        html_confidence=Confidence.T1_CONFIDENT, pdf_confidence=None,
        html_facts=facts, pdf_facts=None,
        reason="HTML T1(항등식 성립) — PDF 시도 안 함",
    )


def test_only_unresolved_results_produce_rows():
    results = [_html_decided_result("separate"), _unresolved_result("consolidated")]
    rows = build_recon_candidate_rows(
        results, corp_code="00000000", rcept_no="r1",
        report_fiscal_year=2001, report_fiscal_period="H1",
    )
    assert len(rows) == 1
    assert rows[0]["basis"] == "consolidated"
    assert rows[0]["decision"] == "unresolved"


def test_no_unresolved_results_produces_empty_list():
    results = [_html_decided_result("separate")]
    rows = build_recon_candidate_rows(
        results, corp_code="00000000", rcept_no="r1",
        report_fiscal_year=2001, report_fiscal_period="H1",
    )
    assert rows == []


def test_row_carries_both_candidate_totals_for_human_review():
    results = [_unresolved_result("separate", html_amt=150, pdf_amt=190)]
    rows = build_recon_candidate_rows(
        results, corp_code="00000000", rcept_no="r1",
        report_fiscal_year=2001, report_fiscal_period="H1",
    )
    row = rows[0]
    assert row["html_values"]["bs.total_equity"] == 150
    assert row["pdf_values"]["bs.total_equity"] == 190
    assert row["html_confidence"] == "T3"
    assert row["pdf_confidence"] == "T3"


def test_pdf_not_attempted_keeps_pdf_values_none_distinct_from_empty():
    """T1 이라 PDF 를 아예 안 부른 경우와, PDF 를 불렀는데 완전공백(T2)인 경우를
    구분해야 한다 — `pdf_facts=None`(미시도)이면 `pdf_values`도 None, `pdf_facts=[]`
    (시도했지만 0건)이면 `pdf_values`는 {전부 None}인 dict(리뷰 화면에서 다르게
    보여야 함). unresolved 로만 적재되므로 T1(미시도)은 이 경로를 안 타지만, T3
    양쪽 다 애매한데 어느 한쪽이 fetch 실패로 빈 리스트가 된 경우를 검증한다."""
    result = ReconcileResult(
        corp_code="00000000", rcept_no="r1", basis="separate", decision="unresolved",
        html_confidence=Confidence.T3_AMBIGUOUS, pdf_confidence=Confidence.T2_EMPTY,
        html_facts=[_fact("bs.total_assets", "separate", 300),
                    _fact("bs.total_liabilities", "separate", 100),
                    _fact("bs.total_equity", "separate", 150)],
        pdf_facts=[],
        reason="test",
    )
    rows = build_recon_candidate_rows(
        [result], corp_code="00000000", rcept_no="r1",
        report_fiscal_year=2001, report_fiscal_period="H1",
    )
    row = rows[0]
    assert row["pdf_values"] == {
        "bs.total_assets": None, "bs.total_liabilities": None, "bs.total_equity": None,
    }
    assert row["html_values"]["bs.total_assets"] == 300


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
