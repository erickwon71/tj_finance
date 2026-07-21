"""
계층2 report_lines 추출기 회귀 테스트 (실측 파일, DB 비의존).

핵심 = **금융업 이중섹션 카나리아**(4계층 재설계의 동기).
KG케미칼 2023FY: 현금및현금성자산이 유동자산(288.7B) + 금융업자산(2.1B) 두 섹션에 존재.
평면 fact_v2 는 (acode, acontext) 충돌로 한쪽을 잃었으나, report_lines 는 section_path
(들여쓰기 tree)로 **두 라인 모두 보존·구분**하고 합이 CF 기말현금과 정확히 일치한다.

실행: python -m fin2.tests.test_report_lines
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.report_lines import extract_report_lines, _assign_section_paths  # noqa: E402
from parser.xml.table_extractor import RowData  # noqa: E402

_KG = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00101220_KG케미칼/annual/2023/20240321001911.xml"
)


def _kg_lines():
    return extract_report_lines(
        _KG, rcept_no="20240321001911", corp_code="00101220",
        report_fiscal_year=2023, report_fiscal_period="FY",
    )


def test_financial_dual_section_cash_both_lines_kept():
    """금융업 이중섹션 현금이 두 라인으로 보존되고 section_path 로 구분된다(합=CF 기말현금)."""
    if not _KG.exists():
        return
    lines = _kg_lines()
    cash = [l for l in lines if l.statement == "BS" and l.basis == "consolidated"
            and l.col_index == 0 and l.label_raw == "현금및현금성자산"]
    paths = {l.section_path: l.value_won for l in cash}
    assert paths.get("자산>유동자산") == 288_717_146_272, paths
    assert paths.get("자산>금융업자산") == 2_112_712_279, paths
    assert sum(paths.values()) == 290_829_858_551  # CF 기말현금과 정확 일치


def test_financial_dual_section_debt_distinguished():
    """단기차입금(유동부채)과 차입금(금융업부채)이 서로 다른 section_path 를 갖는다."""
    if not _KG.exists():
        return
    lines = _kg_lines()
    bs = [l for l in lines if l.statement == "BS" and l.basis == "consolidated" and l.col_index == 0]
    st = next(l for l in bs if l.label_raw == "단기차입금")
    fin = next(l for l in bs if l.label_raw == "차입금")
    assert st.section_path == "부채>유동부채", st.section_path
    assert fin.section_path == "부채>금융업부채", fin.section_path


def test_no_synthetic_top_no_doubling():
    """자산/부채/자본 top 을 주입하지 않는다 — 원문 top 행이 조상이라 접두가 겹치지 않는다."""
    if not _KG.exists():
        return
    lines = _kg_lines()
    assert not any(l.section_path and l.section_path.startswith("자산>자산") for l in lines)


def test_indent_stack_pure_structure():
    """section_path = 들여쓰기 조상 체인(순수 구조). 합성 RowData 로 로직만 검증(파일 무관)."""
    rows = [
        RowData("자산", [None], row_order=0, raw_indent=0),
        RowData("유동자산", [100], row_order=1, raw_indent=1),
        RowData("현금", [40], row_order=2, raw_indent=2),
        RowData("금융업자산", [10], row_order=3, raw_indent=1),
        RowData("현금", [3], row_order=4, raw_indent=2),
    ]
    paths = _assign_section_paths(rows, "BS")
    got = [paths[id(r)] for r in rows]
    assert got == [None, "자산", "자산>유동자산", "자산", "자산>금융업자산"], got


def test_labels_not_normalized():
    """label_raw 는 원문 그대로(정규화 없음) — 로마숫자·괄호 접두 보존."""
    if not _KG.exists():
        return
    lines = _kg_lines()
    # 큐로셀·리드코프 등은 'Ⅰ.' 접두를 쓰지만 KG 는 접두 없음 — 원문 그대로인지 라벨 유무로 검증
    labels = {l.label_raw for l in lines}
    assert "현금및현금성자산" in labels
    # 정규화가 걸렸다면 괄호가 사라졌을 '이익잉여금(결손금)' 이 원문 그대로 남아야
    assert any("(" in l for l in labels)


def test_notes_off_by_default():
    """include_notes=False(기본)면 note 라인이 없다(본문 먼저·주석 단계화)."""
    if not _KG.exists():
        return
    lines = _kg_lines()
    assert not any(l.statement == "note" for l in lines)


def test_notes_monetary_transcribed_positional():
    """include_notes=True: 화폐 주석 표가 전사되되 컬럼은 위치(연도 아님)·context_fy NULL."""
    if not _KG.exists():
        return
    lines = extract_report_lines(
        _KG, rcept_no="20240321001911", corp_code="00101220",
        report_fiscal_year=2023, report_fiscal_period="FY", include_notes=True,
    )
    notes = [l for l in lines if l.statement == "note"]
    assert notes, "화폐 주석 표가 하나도 전사되지 않음"
    # 연도 판단 금지: 주석 라인은 context_fiscal_year/period_kind 를 주장하지 않는다
    assert all(l.context_fiscal_year is None for l in notes)
    assert all(l.period_kind is None for l in notes)
    assert all(l.value_won is not None and l.unit_source == "declared" for l in notes)
    # 종속기업 요약재무현황(천원 선언) 단위환산 검증: KG ETS 자산총계 = 767,614,120천원 → 원
    ets = [l for l in notes if "KG ETS" in l.label_raw
           and "요약재무현황" in (l.section_path or "") and l.col_index == 0]
    assert any(l.value_won == 767_614_120_000 for l in ets), [l.value_won for l in ets]


def _run():
    if not _KG.exists():
        print(f"  - SKIP(파일 없음): {_KG}")
        # 파일 무관 테스트는 그래도 실행
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
