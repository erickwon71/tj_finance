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


# ── 제목표/데이터표 분리 서식 (2026-07-23, docs/qa/layer2_split_table_gap) ──────────
# 재무제표명('연 결 재 무 상 태 표')이 데이터 없는 별도 표로 떨어지고 숫자·단위는 다음
# 데이터표에 있는 서식(보험/증권 + 일반사 특정연도, 로더 done 중 2.9%가 이 탓에 0행이었다).
# _detect_body_statement_tables 의 전방연결이 없으면 이 파일은 0행이 된다.
_HK = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00103176_흥국화재/annual/2015/20160330003906.xml"
)


def _hk_lines():
    return extract_report_lines(
        _HK, rcept_no="20160330003906", corp_code="00103176",
        report_fiscal_year=2015, report_fiscal_period="FY",
    )


def test_split_title_data_table_extracted():
    """제목표/데이터표 분리 서식이 0행이 아니라 BS/IS/CF/SCE 를 전부 전사한다."""
    if not _HK.exists():
        return
    lines = _hk_lines()
    stmts = {(l.statement, l.basis) for l in lines}
    for want in (("BS", "consolidated"), ("IS", "consolidated"), ("CF", "consolidated"),
                 ("BS", "separate"), ("IS", "separate")):
        assert want in stmts, (want, sorted(stmts))


def test_split_table_values_match_source():
    """전방연결로 붙인 데이터표의 값이 원문(=std_v2 산출)과 일치한다."""
    if not _HK.exists():
        return
    lines = _hk_lines()
    def col0(stmt, basis, needle):
        for l in lines:
            if (l.statement == stmt and l.basis == basis and l.col_index == 0
                    and l.value_won is not None and needle in (l.label_raw or "").replace(" ", "")):
                return l.value_won
        return None
    # 단위(백만원)가 데이터표에 선언 → declared_unit 이 전방연결로 따라온다.
    assert col0("BS", "consolidated", "자산총계") == 8_987_851_000_000
    assert col0("BS", "consolidated", "자본총계") == 442_022_000_000
    assert col0("IS", "consolidated", "영업수익") == 4_235_585_000_000
    assert col0("IS", "consolidated", "당기순이익") == 19_653_000_000


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


# ── 문서 전체 기본 단위 (2026-08-05, ★사용자 결정) ──────────────────────────
# '재무제표_직접작성' 수기입력 서식은 본문(BS/IS/SCE/CF) 표에 단위를 재선언하지 않는
# 경우가 있다 — 08-04/08-05 잔여공백 24건 재분해 중 발견(핸드오프
# handoff_delisting_filepath_and_gap_recheck_2026-08-05.md §5 "표잡힘(현대)-적재만안됨").
# 근거는 magnitude 추론이 아니라 문서 안 텍스트 선언(요약재무정보 표 단위·회계정책 주석의
# 표시통화 문구)뿐이다. 특수건설(20151116001903)은 **별개 결함**(제목+데이터 병합 표라
# BS/IS 분류 자체가 실패)이라 이 회귀 대상에서 제외 — docs/PARSING_RULES.md 부록C 참고.
_ELP_A = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00374020_이엘피/annual/2015/20160330001530.xml"
)
_ELP_B = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00374020_이엘피/annual/2015/20160513002038.xml"
)
_WINGSFOOT = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/01405585_윙스풋/quarter/2021/20210517000207.xml"
)
_INCA = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/01013694_인카금융서비스/quarter/2017/20170516000038.xml"
)


def test_doc_default_unit_from_summary_section():
    """요약재무정보 표의 '(단위 : 원)' 선언을 문서 기본값으로 찾는다(이엘피 실측)."""
    if not _ELP_A.exists():
        return
    from parser.xml.dart_xml_parser import _parse_xml_file
    from fin2.extract.text import document_default_unit
    root = _parse_xml_file(_ELP_A)
    unit, decl = document_default_unit(root)
    assert unit == 1, (unit, decl)
    assert "원" in (decl or "")


def test_doc_default_unit_from_presentation_currency_note():
    """요약재무정보 표에 선언이 없으면 회계정책 주석의 '표시통화…원(KRW)' 문구로 찾는다.

    실측 문구(윙스풋 20210517000207) 그대로 합성 — 이 문서는 요약재무정보에도 단위가 있어
    ①경로가 먼저 잡히므로(정상 우선순위), ②경로 단독을 시험하려면 ①을 뺀 합성 문서가 필요.
    """
    from lxml import etree
    from fin2.extract.text import document_default_unit
    xml = (
        "<DOCUMENT><BODY>"
        "<SECTION-2><TITLE>1. 요약재무정보</TITLE><P>해당사항 없습니다.</P></SECTION-2>"
        "<P>재무제표는 회사의 기능통화이면서 표시통화인 \"원(KRW)\"으로 표시되고 있으며 "
        "별도로 언급하고 있는 사항을 제외하고는 \"원(KRW)\" 단위로 표시되고 있습니다.</P>"
        "</BODY></DOCUMENT>"
    )
    root = etree.fromstring(xml)
    unit, decl = document_default_unit(root)
    assert unit == 1, (unit, decl)
    assert "표시통화" in (decl or "")


def test_doc_default_unit_absent_returns_none():
    """텍스트 근거가 전혀 없는 합성 문서는 (None, None) — 추측하지 않는다."""
    from lxml import etree
    from fin2.extract.text import document_default_unit
    root = etree.fromstring("<DOCUMENT><BODY><P>해당사항 없습니다.</P></BODY></DOCUMENT>")
    assert document_default_unit(root) == (None, None)


def test_previously_gap_filings_now_load_with_doc_default_source():
    """08-05 재로드에서 0행이던 4건이 이제 unit_source='doc_default'로 채워진다."""
    targets = [
        (_ELP_A, "20160330001530", "00374020", 2015, "FY"),
        (_ELP_B, "20160513002038", "00374020", 2015, "FY"),
        (_WINGSFOOT, "20210517000207", "01405585", 2021, "Q1"),
        (_INCA, "20170516000038", "01013694", 2017, "Q1"),
    ]
    for path, rcept, corp, fy, period in targets:
        if not path.exists():
            continue
        lines = extract_report_lines(
            path, rcept_no=rcept, corp_code=corp,
            report_fiscal_year=fy, report_fiscal_period=period,
        )
        assert lines, f"{rcept} 여전히 0행"
        # 주당손익(EPS)행은 제외 — 그건 표 단위가 아니라 라벨 단위(원/주)라 별도 경로(늘 'declared').
        body = [l for l in lines if l.statement in ("BS", "IS", "SCE", "CF")
                and l.section_path != "주당손익"]
        assert body, f"{rcept} 본문 행 없음"
        assert all(l.unit_source == "doc_default" for l in body), (
            rcept, {l.unit_source for l in body})
        assert all(l.value_won is not None for l in body)


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
    # ★F1(2026-07-31): 주석은 이제 **비금액·단위미확정 표까지 전사**한다. 불변식이 바뀌었다 —
    #   "모든 행에 value_won 이 있다"가 아니라 **"값이 없으면 원문이 있다"**가 계약이다.
    #   (종전 계약은 단위를 선언한 표만 적재했으므로 항상 declared 였다.)
    money_src = {"declared", "col_money"}
    for l in notes:
        if l.value_won is not None:
            assert l.unit_source in money_src, (l.unit_source, l.label_raw)
            assert l.value_raw is None, "값이 있으면 원문은 중복이라 저장하지 않는다"
        else:
            assert l.unit_source in {"non_monetary", "undetermined", "undeclared"}, l.unit_source
            assert l.value_raw, f"단위 미확정 칸인데 원문이 없다: {l.label_raw}"
    assert any(l.value_won is not None for l in notes), "금액 주석 표가 하나도 전사되지 않음"
    # 종속기업 요약재무현황(천원 선언) 단위환산 검증: KG ETS 자산총계 = 767,614,120천원 → 원
    # ★로케이터 필드 변경(2026-07-26 주석 전사): section_path = **관장 번호 주석 제목**
    #   ('3. 연결재무제표 주석')이 되고, 표 직전 설명('…종속기업의 요약재무현황')은
    #   table_title 로 옮겼다(`_emit_note_lines` 주석 참고). 검증 의도(천원→원 환산)는 그대로.
    ets = [l for l in notes if "KG ETS" in l.label_raw
           and "요약재무현황" in (l.table_title or "") and l.col_index == 0]
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
