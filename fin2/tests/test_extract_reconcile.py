"""HTML↔PDF 신뢰도 조정(T1/T2/T3) 단위 테스트 — 순수 함수, DB/HTTP 미의존.

대상: `fin2/extract/reconcile.py`. ★파일명 주의 — `fin2/reconcile.py`(기재정정
select_source 우선순위, 완전히 다른 모듈)를 테스트하는 기존 `test_reconcile.py`와
basename 충돌이 나서 `test_extract_reconcile.py`로 분리했다(2026-09-07, 원래
Write 로 새 파일을 만들며 기존 파일을 덮어썼던 걸 커밋 직전에 발견해 복구).

실행: python -m fin2.tests.test_extract_reconcile
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest.mock import patch  # noqa: E402

import fin2.extract.reconcile as reconcile_mod  # noqa: E402
from fin2.extract.reconcile import (  # noqa: E402
    Confidence, classify_confidence, reconcile_basis, reconcile,
)
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


def _bs_facts(basis, a, l, e):
    facts = []
    if a is not None:
        facts.append(_fact("bs.total_assets", basis, a))
    if l is not None:
        facts.append(_fact("bs.total_liabilities", basis, l))
    if e is not None:
        facts.append(_fact("bs.total_equity", basis, e))
    return facts


# ── classify_confidence ──────────────────────────────────────────────────

def test_separate_identity_holds_is_t1():
    facts = _bs_facts("separate", 300, 100, 200)
    assert classify_confidence(facts, "separate") == Confidence.T1_CONFIDENT


def test_separate_identity_fails_is_t3():
    facts = _bs_facts("separate", 300, 100, 150)  # 100+150 != 300
    assert classify_confidence(facts, "separate") == Confidence.T3_AMBIGUOUS


def test_empty_facts_is_t2():
    assert classify_confidence([], "separate") == Confidence.T2_EMPTY


def test_partial_facts_is_t3():
    facts = _bs_facts("separate", 300, None, 200)  # 부채총계 없음
    assert classify_confidence(facts, "separate") == Confidence.T3_AMBIGUOUS


def test_consolidated_never_promoted_to_t1_even_if_identity_holds():
    """제일기획 연결류(§8-4/§8-8) — 3자분할(외부주주지분) 가능성 때문에
    연결은 항등식이 성립해도 보수적으로 T1 승격 안 함(설계 결정 그대로)."""
    facts = _bs_facts("consolidated", 300, 100, 200)
    assert classify_confidence(facts, "consolidated") == Confidence.T3_AMBIGUOUS


# ── reconcile_basis ───────────────────────────────────────────────────────

def test_t1_html_never_calls_pdf():
    calls = []

    def get_pdf_facts():
        calls.append(1)
        return []

    html_facts = _bs_facts("separate", 300, 100, 200)
    result = reconcile_basis("separate", html_facts, get_pdf_facts,
                              corp_code="00000000", rcept_no="r1")
    assert result.decision == "html"
    assert result.pdf_confidence is None
    assert calls == []  # PDF 아예 안 불림


def test_t2_html_falls_back_to_pdf_when_pdf_has_data():
    pdf_facts = _bs_facts("separate", 300, 100, 200)
    result = reconcile_basis("separate", [], lambda: pdf_facts,
                              corp_code="00000000", rcept_no="r1")
    assert result.decision == "pdf"
    assert result.pdf_confidence == Confidence.T1_CONFIDENT


def test_t2_html_and_t3_pdf_stays_unresolved_not_auto_adopted():
    """실측 발견(2026-09-07, 93건 백필 직후 독립 재검증 — 일성건설·일진디스플)
    — HTML 이 완전공백(T2)이어도 PDF 가 항등식을 스스로 증명 못 하면(T3, 부분
    값 또는 불일치) 자동 채택 안 함. HTML 이 아무것도 못 찾은 이상 교차검증
    상대가 없어 PDF 의 "확신 없음"을 봐줄 근거가 없다(원래 버그: "완전공백만
    아니면" 채택하던 걸 "T1 이어야만" 채택으로 강화)."""
    pdf_facts = _bs_facts("separate", 300, 100, 150)  # 항등식 불성립(T3)
    result = reconcile_basis("separate", [], lambda: pdf_facts,
                              corp_code="00000000", rcept_no="r1")
    assert result.decision == "unresolved"
    assert result.pdf_confidence == Confidence.T3_AMBIGUOUS


def test_t2_html_and_t2_pdf_stays_unresolved():
    result = reconcile_basis("separate", [], lambda: [],
                              corp_code="00000000", rcept_no="r1")
    assert result.decision == "unresolved"


def test_pdf_facts_in_result_are_filtered_to_this_basis_not_leaked_from_other():
    """실측 발견(2026-09-07, reconcile_store 스모크테스트, KD 00111218) —
    `get_pdf_facts()`는 문서 전체(별도+연결 섞인) 리스트를 캐시로 반환하는데,
    ReconcileResult.pdf_facts 에 그대로(basis 로 안 거른 채) 저장하면 별도
    basis 의 값이 연결 basis 결과의 pdf_facts 로 새어 들어간다(classify_
    confidence 는 내부에서 자체로 걸러서 등급판정 자체는 안 틀렸지만, pdf_facts
    필드를 그대로 쓰는 소비자는 오염된 값을 받는다). html_facts 와 대칭이
    맞아야 한다 — 둘 다 basis 로 걸러진 채로 ReconcileResult 에 담겨야 한다."""
    mixed_pdf_facts = (
        _bs_facts("consolidated", 999, 111, 888) +   # 별도 조회인데 섞여 들어온 연결 값(오염원)
        _bs_facts("separate", 300, 100, 200)         # 진짜 별도 값(항등식 성립, T1)
    )
    result = reconcile_basis("separate", [], lambda: mixed_pdf_facts,
                              corp_code="00000000", rcept_no="r1")
    assert result.pdf_confidence == Confidence.T1_CONFIDENT
    assert {f.basis for f in result.pdf_facts} == {"separate"}
    assert {f.amount_won for f in result.pdf_facts} == {300, 100, 200}


def test_t3_html_t1_pdf_picks_pdf_when_overlap_agrees():
    """제일기획 연결류의 반대 상황(HTML 이 애매, PDF 가 확신) + 교차검증(§8-11)
    통과 — HTML 이 부분적으로 찾은 자산·부채총계가 PDF 값과 정확히 일치하고
    (자본총계는 HTML 이 못 찾음, 그래서 T3), 겹치는 항목에 충돌이 없으니 PDF
    채택."""
    html_facts = _bs_facts("separate", 300, 100, None)  # 자본총계는 못 찾음(2/3, T3)
    pdf_facts = _bs_facts("separate", 300, 100, 200)     # 항등식 성립(T1)
    result = reconcile_basis("separate", html_facts, lambda: pdf_facts,
                              corp_code="00000000", rcept_no="r1")
    assert result.decision == "pdf"


def test_t3_html_t1_pdf_stays_unresolved_when_overlap_conflicts():
    """§8-11 — PDF T1("항등식 성립")은 필요조건일 뿐 충분조건이 아니다: 라벨-값이
    뒤바뀌어도(swap-bug) 우연히 셈이 맞을 수 있다(KD swap-bug 패턴 실증). HTML이
    찾은 자본총계(150)와 PDF가 찾은 자본총계(200)가 서로 다르면 — 둘 다 자산·
    부채총계는 일치하는데 자본총계만 어긋나면 — PDF의 "확신"을 못 믿고 자동
    채택 안 함(사람 확인 대기)."""
    html_facts = _bs_facts("separate", 300, 100, 150)  # 항등식 불성립(T3)
    pdf_facts = _bs_facts("separate", 300, 100, 200)   # 항등식 성립(T1)이지만 equity 가 HTML과 충돌
    result = reconcile_basis("separate", html_facts, lambda: pdf_facts,
                              corp_code="00000000", rcept_no="r1")
    assert result.decision == "unresolved"
    assert "불일치" in result.reason


def test_t3_html_t3_pdf_stays_unresolved_not_auto_picked():
    """둘 다 애매하면 어느 쪽도 자동 채택 안 함 — 결측이 오염보다 낫다."""
    html_facts = _bs_facts("separate", 300, 100, 150)
    pdf_facts = _bs_facts("separate", 300, 100, 190)
    result = reconcile_basis("separate", html_facts, lambda: pdf_facts,
                              corp_code="00000000", rcept_no="r1")
    assert result.decision == "unresolved"
    assert result.html_facts and result.pdf_facts  # 둘 다 후보로 남아있음(사람 확인용)


# ── reconcile() — basis 목록을 TOC에서 뽑는지(html_facts에서 뽑으면 안 됨) ──

_FAKE_TOC = """
var node1 = {};
node1['text'] = "3. 재무제표";
node1['eleId'] = "1";
node1['offset'] = "0";
node1['length'] = "10";
node1['dtd'] = "dart2.dtd";
node1['dcmNo'] = "1";
var node1 = {};
node1['text'] = "4. 연결재무제표";
node1['eleId'] = "2";
node1['offset'] = "0";
node1['length'] = "10";
node1['dtd'] = "dart2.dtd";
node1['dcmNo'] = "1";
"""


class _FakeScraper:
    def fetch_toc_page(self, rcept_no):
        return _FAKE_TOC

    def fetch_pdf_bytes(self, rcept_no):
        return b"%PDF-fake"


def test_reconcile_checks_consolidated_even_if_html_found_zero_facts_there():
    """실측 발견(일성건설 00146232) — TOC엔 "4. 연결재무제표" 노드가 있는데
    (연결재무제표가 실제로 존재) 원인B(§8-5) 때문에 그 표의 세부항목까지
    전부 0건이 되면, basis 자체를 html_facts 에서 뽑는 예전 방식은 "연결"이
    아예 사라져 reconcile 대상에서 빠졌다(PDF 폴백 기회를 놓침). TOC 노드
    유무로 판정해야 consolidated 도 빠지지 않는다."""
    html_facts_separate_only = [
        ExtractedFact(
            corp_code="c", rcept_no="r", report_fiscal_year=1999,
            report_fiscal_period="FY", acode="매출채권", basis="separate",
            context_fiscal_year=1999, col_index=0, period_kind="instant",
            period_type="FY", is_cumulative=False, extra_dims=None,
            is_dimensional=False, adecimal=0, amount_won=100,
            source_format="html", source_ref=None, acontext_raw=None,
            context_parsed=False, canonical_account="bs.trade_receivables",
        ),
    ]
    with patch.object(reconcile_mod, "extract_html_facts", return_value=html_facts_separate_only), \
         patch.object(reconcile_mod, "extract_pdf_facts", return_value=[]):
        results = reconcile(_FakeScraper(), "r", corp_code="c",
                             report_fiscal_year=1999, report_fiscal_period="FY")
    bases = {r.basis for r in results}
    assert bases == {"separate", "consolidated"}


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
