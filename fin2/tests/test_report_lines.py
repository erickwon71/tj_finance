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
# 표시통화 문구)뿐이다. ★특수건설(20151116001903)·포시에스(20171114002836)·
# 팬엔터테인먼트(20181114002948)는 애초 **별개 결함**(제목+데이터 병합 표/제목 자체 없는
# 표라 BS/IS 분류 자체가 실패)이라 이 회귀에서 제외했으나, R4-2(아래)로 해결됐다 —
# docs/plans/merged_title_data_table_r4-2_2026-08-05.md.
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


# ── R67(2026-09-03): nearest_section_default_unit — 합성 XML(파일 비의존) ──────
# docs/plans/std_v3_kgaap_interim_consolidated_stale_annual_reprint_design_2026-09-02.md §12.

# 데이터표 판정(`table_has_amount_rows`)은 콤마금액 행이 **2개 이상** 있어야 한다
# (실측 사고 방지 — text.py `_table_has_data_rows` docstring 참고) — 아래 합성표는
# 전부 행 2개·콤마 3자리(예: "1,000")로 이 조건을 만족시킨다.

def test_nearest_section_default_unit_finds_other_table_same_section():
    """로컬선언 공란인 표라도, 같은 SECTION-2 안 **다른** 표에 선언이 있으면 그걸 쓴다
    (요약재무정보 문서전체 폴백보다 우선) — 00240857 실측의 최소 재현."""
    from lxml import etree
    from fin2.extract.text import nearest_section_default_unit
    xml = (
        "<DOCUMENT><BODY>"
        "<SECTION-2><TITLE>1. 요약재무정보</TITLE>"
        "<TABLE><TBODY><TR><TD>매출액</TD><TD>10,859,787</TD></TR>"
        "<TR><TD>영업이익</TD><TD>1,234,567</TD></TR></TBODY></TABLE>"
        "<P>(단위 :천원 )</P>"
        "</SECTION-2>"
        "<SECTION-2><TITLE>4. 재무제표</TITLE>"
        "<TABLE ID='target'><TBODY><TR><TD>매출액</TD><TD>10,859,787,838</TD></TR>"
        "<TR><TD>영업이익</TD><TD>1,234,567,890</TD></TR></TBODY></TABLE>"
        "<P>(단위 : 원)</P>"
        "<TABLE><TBODY><TR><TD>현금및현금성자산</TD><TD>1,000</TD></TR>"
        "<TR><TD>재고자산</TD><TD>2,000</TD></TR></TBODY></TABLE>"
        "</SECTION-2>"
        "</BODY></DOCUMENT>"
    )
    root = etree.fromstring(xml)
    target = root.find(".//TABLE[@ID='target']")
    unit, decl = nearest_section_default_unit(target, {})
    assert unit == 1, (unit, decl)
    assert "원" in (decl or "")


def test_nearest_section_default_unit_ignores_other_sections():
    """다른 SECTION-2(예: 요약재무정보)의 선언은 안 쓴다 — 반드시 자기 섹션만."""
    from lxml import etree
    from fin2.extract.text import nearest_section_default_unit
    xml = (
        "<DOCUMENT><BODY>"
        "<SECTION-2><TITLE>1. 요약재무정보</TITLE>"
        "<TABLE><TBODY><TR><TD>매출액</TD><TD>10,859,787</TD></TR>"
        "<TR><TD>영업이익</TD><TD>1,234,567</TD></TR></TBODY></TABLE>"
        "<P>(단위 :천원 )</P>"
        "</SECTION-2>"
        "<SECTION-2><TITLE>4. 재무제표</TITLE>"
        "<TABLE ID='target'><TBODY><TR><TD>매출액</TD><TD>10,859,787,838</TD></TR>"
        "<TR><TD>영업이익</TD><TD>1,234,567,890</TD></TR></TBODY></TABLE>"
        "</SECTION-2>"
        "</BODY></DOCUMENT>"
    )
    root = etree.fromstring(xml)
    target = root.find(".//TABLE[@ID='target']")
    assert nearest_section_default_unit(target, {}) == (None, None)


def test_nearest_section_default_unit_cache_reused_per_section():
    """같은 SECTION-2 안 여러 표가 캐시(dict)를 공유 — 두 번째 호출은 재스캔 없이 캐시 히트."""
    from lxml import etree
    from fin2.extract.text import nearest_section_default_unit
    xml = (
        "<DOCUMENT><BODY>"
        "<SECTION-2><TITLE>4. 재무제표</TITLE>"
        "<TABLE ID='a'><TBODY><TR><TD>매출액</TD><TD>1,000</TD></TR>"
        "<TR><TD>영업이익</TD><TD>2,000</TD></TR></TBODY></TABLE>"
        "<P>(단위 : 원)</P>"
        "<TABLE ID='b'><TBODY><TR><TD>영업이익</TD><TD>3,000</TD></TR>"
        "<TR><TD>당기순이익</TD><TD>4,000</TD></TR></TBODY></TABLE>"
        "</SECTION-2>"
        "</BODY></DOCUMENT>"
    )
    root = etree.fromstring(xml)
    cache: dict = {}
    a, b = root.find(".//TABLE[@ID='a']"), root.find(".//TABLE[@ID='b']")
    r1 = nearest_section_default_unit(a, cache)
    assert len(cache) == 1
    r2 = nearest_section_default_unit(b, cache)
    assert len(cache) == 1  # 같은 섹션 → 재사용, 새 항목 안 늘어남
    assert r1 == r2 == (1, "(단위 : 원)")


def test_previously_gap_filings_now_load_with_doc_default_source():
    """08-05 재로드에서 0행이던 4건이 이제 문서레벨 폴백 소스로 채워진다.

    ★R67(2026-09-03, design doc §12) — 인카금융서비스만 `unit_source`가
    'doc_default'→**'section_def'**로 바뀐다(값은 무변경, 둘 다 unit=1/원).
    원인: 이 문서는 "4. 재무제표" SECTION-2 **자신 안에** 다른 표의 로컬
    "(단위: 원)" 선언이 이미 있다(`nearest_section_default_unit()`이 이제
    `document_default_unit()`의 "요약재무정보" 문서전체 폴백보다 먼저 찾음) —
    이엘피×2·윙스풋은 그런 표가 자기 섹션 안에 없어 그대로 'doc_default' 유지
    (회귀 아님, 표본 4건 전부 원문대조로 확인됨).
    """
    targets = [
        (_ELP_A, "20160330001530", "00374020", 2015, "FY", "doc_default"),
        (_ELP_B, "20160513002038", "00374020", 2015, "FY", "doc_default"),
        (_WINGSFOOT, "20210517000207", "01405585", 2021, "Q1", "doc_default"),
        (_INCA, "20170516000038", "01013694", 2017, "Q1", "section_def"),
    ]
    for path, rcept, corp, fy, period, expected_source in targets:
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
        assert all(l.unit_source == expected_source for l in body), (
            rcept, {l.unit_source for l in body})
        assert all(l.value_won is not None for l in body)


# ── R67(2026-09-03): 같은 SECTION-2 내 다른 표 단위선언 우선 참조 ──────────────
# docs/plans/std_v3_kgaap_interim_consolidated_stale_annual_reprint_design_2026-09-02.md §12.
# `document_default_unit()`("요약재무정보" 표 — 압축표기라 배수는 그 표 자신에게만 정당,
# 다른 표의 원자릿수 인쇄와 같은 배수를 공유한다는 보장이 없음)로 가기 **전에**, 로컬선언이
# 공란인 표 자신이 속한 SECTION-2("재무제표" 등) 안의 **다른** 표 선언을 먼저 찾는다
# (`nearest_section_default_unit`) — 원자릿수 인쇄 관행을 공유할 가능성이 훨씬 높다.
_BIOSMART_H1 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00240857_바이오스마트/half/2005/20050816000383.xml"
)
_BIOSMART_Q3 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00240857_바이오스마트/quarter/2005/20051115000359.xml"
)
_KYUNGDONG_Q3 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00101549_경동제약/quarter/2003/20031114000457.xml"
)


def test_r67_section_default_fixes_1000x_inflation():
    """00240857(바이오스마트) 2005H1/Q3 손익계산서 — 로컬선언 공란인 "매출액"이
    예전엔 "요약재무정보"(천원, 그 표 자신에겐 정당) 배수를 잘못 물려받아 ×1000
    부풀려졌다. 같은 "4. 재무제표" 섹션 뒤쪽엔 "(단위 : 원)" 선언이 이미 15회+
    있다 — 이제 그쪽을 먼저 찾아 원문과 정확히 일치하는 값을 낸다(원문/DB
    직접대조로 확정된 값, design doc §12.1).
    """
    if not _BIOSMART_H1.exists() or not _BIOSMART_Q3.exists():
        return
    h1_lines = extract_report_lines(
        _BIOSMART_H1, rcept_no="20050816000383", corp_code="00240857",
        report_fiscal_year=2005, report_fiscal_period="H1",
    )
    q3_lines = extract_report_lines(
        _BIOSMART_Q3, rcept_no="20051115000359", corp_code="00240857",
        report_fiscal_year=2005, report_fiscal_period="Q3",
    )
    h1_rev = next(l for l in h1_lines if l.statement == "IS" and l.basis == "separate"
                  and l.label_raw == "매출액" and l.col_index == 0)
    q3_rev = next(l for l in q3_lines if l.statement == "IS" and l.basis == "separate"
                  and l.label_raw == "매출액" and l.col_index == 0)
    assert h1_rev.value_won == 10_859_787_838, h1_rev.value_won
    assert h1_rev.unit_source == "section_def"
    assert h1_rev.adecimal == 0
    assert q3_rev.value_won == 14_378_192_970, q3_rev.value_won
    assert q3_rev.unit_source == "section_def"


def test_r67_section_default_fixes_1e6x_inflation_cf():
    """00101549(경동제약) 2003Q3 현금흐름표 — 로컬선언 공란인 CF 세부계정이
    예전엔 "요약재무정보"(백만원) 배수를 잘못 물려받아 ×1,000,000 부풀려졌다.
    다른 회사·다른 statement(CF)로 같은 메커니즘 재현(design doc §12.1 표본2).
    """
    if not _KYUNGDONG_Q3.exists():
        return
    lines = extract_report_lines(
        _KYUNGDONG_Q3, rcept_no="20031114000457", corp_code="00101549",
        report_fiscal_year=2003, report_fiscal_period="Q3",
    )
    ni = next(l for l in lines if l.statement == "CF" and l.basis == "separate"
              and "당" in l.label_raw and "순" in l.label_raw and "이" in l.label_raw
              and l.col_index == 0)
    assert ni.unit_source == "section_def"
    assert ni.adecimal == 0
    # 원 단위 그대로(수백억 아님) — 부풀려졌다면 10^6배 커졌을 것.
    assert abs(ni.value_won) < 100_000_000_000


def test_r67_no_local_declaration_anywhere_falls_through_to_doc_default():
    """R67 폴백은 **추가만** — 같은 SECTION-2 안에 정말 아무 선언도 없으면(이엘피·
    윙스풋처럼) 예전 그대로 `document_default_unit()`까지 간다(회귀 없음)."""
    if not _ELP_A.exists():
        return
    lines = extract_report_lines(
        _ELP_A, rcept_no="20160330001530", corp_code="00374020",
        report_fiscal_year=2015, report_fiscal_period="FY",
    )
    body = [l for l in lines if l.statement in ("BS", "IS", "SCE", "CF")
            and l.section_path != "주당손익"]
    assert body and all(l.unit_source == "doc_default" for l in body)


# ── R4-2: 제목+데이터 병합 표 / 제목 자체 없는 표 (2026-08-05) ──────────────
# docs/plans/merged_title_data_table_r4-2_2026-08-05.md. 위 R4-1 로도 못 고치던 특수건설·
# 팬엔터테인먼트(제목이 표 자신의 첫 행에 병합)·포시에스(BS 는 제목 자체가 없음, 위치+
# 계정명 규칙)를 해결한다.
_TUKGUN = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00186939_특수건설/quarter/2015/20151116001903.xml"
)
_PANENT = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00397191_팬엔터테인먼트/quarter/2018/20181114002948.xml"
)
_FORCS = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00939942_포시에스/quarter/2018/20171114002836.xml"
)


def test_owned_merged_title_reads_bare_title_row():
    """표 자신의 첫 행이 재무제표명 하나뿐이면 statement 코드를 반환한다(특수건설 패턴)."""
    from lxml import etree
    from fin2.extract.statement_titles import owned_merged_title

    xml = (
        "<TABLE><TBODY>"
        "<TR><TD COLSPAN='6'>재무상태표</TD></TR>"
        "<TR><TD>계정명</TD><TD>금액</TD></TR>"
        "<TR><TD>유동자산</TD><TD>95,539,541,976</TD></TR>"
        "</TBODY></TABLE>"
    )
    tbl = etree.fromstring(xml)
    assert owned_merged_title(tbl) == "BS"


def test_owned_merged_title_none_when_first_row_is_data():
    """첫 행이 재무제표명이 아니면(정상 표) None — 광범위 오검출 방지의 핵심 가드."""
    from lxml import etree
    from fin2.extract.statement_titles import owned_merged_title

    xml = "<TABLE><TBODY><TR><TD>계정명</TD><TD>금액</TD></TR></TBODY></TABLE>"
    tbl = etree.fromstring(xml)
    assert owned_merged_title(tbl) is None


def test_merged_table_local_unit_finds_inline_declaration():
    """병합표 안, 헤더행 이전 메타행의 '(단위 : 원)' 을 찾는다(특수건설·팬엔터 패턴)."""
    from lxml import etree
    from fin2.extract.text import merged_table_local_unit

    xml = (
        "<TABLE><TBODY>"
        "<TR><TD COLSPAN='6'>재무상태표</TD></TR>"
        "<TR><TD>회사명 : (주)특수건설</TD><TD>(단위 : 원)</TD></TR>"
        "<TR><TD>계정명</TD><TD>금액</TD></TR>"
        "<TR><TD>유동자산</TD><TD>95,539,541,976</TD></TR>"
        "</TBODY></TABLE>"
    )
    tbl = etree.fromstring(xml)
    assert merged_table_local_unit(tbl) == 1


def test_titleless_bs_start_position_rule():
    """제목 없이 곧바로 '과목' 헤더로 시작 + 첫 계정명 '자산' → BS 시작 신호(포시에스 패턴).

    ★ROWSPAN 함정: "과목" 헤더 셀이 ROWSPAN=2 라 다음 행 첫 TD 가 날짜값으로 밀린다 —
    그 날짜를 계정명으로 오인하지 않고 건너뛰어 진짜 첫 계정명("자산")까지 가야 한다.
    """
    from lxml import etree
    from fin2.extract.statement_titles import titleless_bs_start

    xml = (
        "<TABLE><TBODY>"
        "<TR><TD ROWSPAN='2'>과 목</TD><TD>당기말</TD><TD>전기말</TD></TR>"
        "<TR><TD>2017-09-30</TD><TD>2017-06-30</TD></TR>"
        "<TR><TD>자산</TD><TD></TD><TD></TD></TR>"
        "<TR><TD>유동자산</TD><TD>12,459,539,381</TD><TD>13,954,627,977</TD></TR>"
        "</TBODY></TABLE>"
    )
    tbl = etree.fromstring(xml)
    assert titleless_bs_start(tbl) is True


def test_titleless_bs_start_false_for_income_statement():
    """제목 없이 '과목' 으로 시작해도 첫 계정명이 '자산'이 아니면(예 매출) BS 신호 아님."""
    from lxml import etree
    from fin2.extract.statement_titles import titleless_bs_start

    xml = (
        "<TABLE><TBODY>"
        "<TR><TD>과목</TD><TD>당기</TD></TR>"
        "<TR><TD>매출액</TD><TD>2,637,279,464</TD></TR>"
        "</TBODY></TABLE>"
    )
    tbl = etree.fromstring(xml)
    assert titleless_bs_start(tbl) is False


def test_r4_2_merged_and_titleless_filings_fully_loaded():
    """특수건설·팬엔터(병합표)·포시에스(위치+계정명 BS)가 이제 BS/IS 전 섹션을 적재한다.

    원문 대조(2026-08-05): 특수건설 유동자산 95,539,541,976·매출액 109,300,142,706,
    포시에스 자산총계 44,370,779,689, 팬엔터 부채자본총계 62,471,323,149.
    """
    targets = [
        (_TUKGUN, "20151116001903", "00186939", 2015, "Q3",
         [("BS", "separate", "유동자산", 95_539_541_976),
          ("IS", "separate", "매출액", 109_300_142_706)]),
        (_PANENT, "20181114002948", "00397191", 2018, "Q3",
         [("BS", "consolidated", "부채자본총계", 62_471_323_149),
          ("BS", "separate", "부채자본총계", 62_471_323_149)]),
        (_FORCS, "20171114002836", "00939942", 2017, "Q3",
         [("BS", "consolidated", "자  산  총  계", 44_370_779_689),
          ("BS", "separate", "자  산  총  계", 44_370_779_689)]),
    ]
    for path, rcept, corp, fy, period, checks in targets:
        if not path.exists():
            continue
        lines = extract_report_lines(
            path, rcept_no=rcept, corp_code=corp,
            report_fiscal_year=fy, report_fiscal_period=period,
        )
        assert lines, f"{rcept} 여전히 0행"
        for stmt, basis, label, expect in checks:
            hits = [l for l in lines if l.statement == stmt and l.basis == basis
                    and l.col_index == 0 and l.label_raw.strip() == label.strip()]
            assert any(l.value_won == expect for l in hits), (
                rcept, stmt, basis, label, [l.value_won for l in hits])


# ── R4-2 §3: 헤더 재등장으로 병합된 복수 재무제표 (2026-08-07) ──────────────
# `_split_headed_multi_statement_table` — 섹션 안 물리적 TABLE 이 1개뿐인데 그 표 안에서
# BS 데이터 뒤에 헤더행("과 목"+기간)이 다시 나타나며 IS 가 이어붙은 서식(이노시뮬레이션 패턴).
# `owned_merged_title`(표가 여럿이어야 함)도 `titleless_bs_start`(첫 계정명이 정확히 '자산'
# 이어야 함, 이 표는 '유동자산'으로 시작)도 안 걸리는 세 번째 폴백.
_INNOSIM_2018 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00965318_이노시뮬레이션/annual/2018/20190405000147.xml"
)
_INNOSIM_2019 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00965318_이노시뮬레이션/annual/2019/20200330004128.xml"
)


def test_split_headed_multi_statement_table_bs_then_is():
    """헤더행 재등장으로 BS→IS 두 구간이 이어붙은 표를 BS/IS 로 정확히 분리한다."""
    from lxml import etree
    from fin2.extract.text import _split_headed_multi_statement_table

    xml = (
        "<TABLE><TBODY>"
        "<TR><TD>과   목</TD><TD>당기</TD><TD>전기</TD></TR>"
        "<TR><TD>Ⅰ.유동자산</TD><TD>14,985,801,573</TD><TD>16,135,644,358</TD></TR>"
        "<TR><TD>자산총계</TD><TD>29,825,708,825</TD><TD>21,599,508,385</TD></TR>"
        "<TR><TD>부채총계</TD><TD>19,803,372,402</TD><TD>8,976,306,526</TD></TR>"
        "<TR><TD>자본총계</TD><TD>10,022,336,423</TD><TD>12,623,201,859</TD></TR>"
        "<TR><TD>과   목</TD><TD>당기</TD><TD>전기</TD></TR>"
        "<TR><TD>매출액</TD><TD>15,307,775,916</TD><TD>29,622,802,160</TD></TR>"
        "<TR><TD>영업이익(영업손실)</TD><TD>(6,609,440,874)</TD><TD>2,430,632,717</TD></TR>"
        "</TBODY></TABLE>"
    )
    tbl = etree.fromstring(xml)
    result = _split_headed_multi_statement_table(tbl)
    assert result is not None
    stmts = [s for s, _ in result]
    assert stmts == ["BS", "IS"]


def test_split_headed_multi_statement_table_none_for_single_header():
    """헤더행이 한 번뿐인 정상 표는 재등장이 없으므로 None(이 폴백의 대상이 아님)."""
    from lxml import etree
    from fin2.extract.text import _split_headed_multi_statement_table

    xml = (
        "<TABLE><TBODY>"
        "<TR><TD>과목</TD><TD>당기</TD></TR>"
        "<TR><TD>Ⅰ.유동자산</TD><TD>12,459,539,381</TD></TR>"
        "<TR><TD>자산총계</TD><TD>95,539,541,976</TD></TR>"
        "</TBODY></TABLE>"
    )
    tbl = etree.fromstring(xml)
    assert _split_headed_multi_statement_table(tbl) is None


def test_r4_2_headed_multi_statement_filings_fully_loaded():
    """이노시뮬레이션 2018FY·2019FY — 원문 대조(2026-08-07): 연결 자산총계·매출액 등."""
    targets = [
        (_INNOSIM_2018, "20190405000147", "00965318", 2018, "FY",
         [("BS", "consolidated", "자산총계", 29_825_708_825),
          ("BS", "consolidated", "부채총계", 19_803_372_402),
          ("BS", "consolidated", "자본총계", 10_022_336_423),
          ("IS", "consolidated", "매출액", 15_307_775_916),
          ("IS", "consolidated", "영업이익(영업손실)", -6_609_440_874),
          ("IS", "consolidated", "당기순이익(당기순손실)", -6_522_062_497)]),
        (_INNOSIM_2019, "20200330004128", "00965318", 2019, "FY",
         [("BS", "consolidated", "자산총계", 44_405_816_652),
          ("IS", "consolidated", "매출액", 19_408_742_657)]),
    ]
    for path, rcept, corp, fy, period, checks in targets:
        if not path.exists():
            continue
        lines = extract_report_lines(
            path, rcept_no=rcept, corp_code=corp,
            report_fiscal_year=fy, report_fiscal_period=period,
        )
        assert lines, f"{rcept} 여전히 0행"
        for stmt, basis, label, expect in checks:
            hits = [l for l in lines if l.statement == stmt and l.basis == basis
                    and l.col_index == 0 and l.label_raw.strip() == label.strip()]
            assert any(l.value_won == expect for l in hits), (
                rcept, stmt, basis, label, [l.value_won for l in hits])


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


# ── Gate B 버그①(cum_map col-misselect) 근본수정(옵션 A) 회귀 — 2026-08-24 ──
# `gateb_bugA_col_misselect_optionA_rootfix_plan_2026-08-24.md` §3-4/§3-5 최종설계.
# 두 실측 사례: (a) 주석컬럼이 있는 표(코리안리) — `_split_label_amounts()`의 빈
# 주석칸 소비 수정만으로 이미 정답이던 값이 안 깨지는지, (b) 주석컬럼이 없는 표
# (국일제지 00104573) — `preserve_col_positions=(cum_map is not None)`가 진짜
# 결측(당기3개월 미공시)을 더 이상 압축으로 지워버리지 않는지.

_KORIANRE_Q3 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00113191_코리안리/quarter/2021/20211115001569.xml"
)
_GUKIL_Q3 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00104573_국일제지/quarter/2025/20251113000801.xml"
)


def test_korianre_note_column_table_still_correct_after_rootfix():
    """코리안리(00113191) 2021Q3 IS — 라벨과 값 사이에 '주석' 컬럼이 구조적으로
    있는 표(다른 행에 콤마 다중참조 있어 table_has_note_column=True). 근본수정
    전에도 6-column pop 압축이 우연히 이 표를 올바르게 읽었다 — 근본수정(옵션 A)
    후에도 같은 정답이 나와야 한다(회귀 없음이 핵심, §3-4-1/3-4-2 반증 재발 방지)."""
    if not _KORIANRE_Q3.exists():
        return
    lines = extract_report_lines(
        _KORIANRE_Q3, rcept_no="20211115001569", corp_code="00113191",
        report_fiscal_year=2021, report_fiscal_period="Q3",
    )

    def _col0_col1(label):
        rows = [l for l in lines if l.statement == "IS" and l.basis == "consolidated"
                and l.label_raw == label]
        return {l.col_index: l.value_won for l in rows}

    assert _col0_col1("Ⅲ. 영업이익") == {0: 200_284_956_061, 1: 171_367_376_772}
    assert _col0_col1("Ⅵ. 법인세비용차감전순이익") == {0: 199_537_863_402, 1: 171_530_344_675}


def test_gukil_paper_no_note_column_table_corrected_by_rootfix():
    """국일제지(00104573) 2025Q3 IS — 주석 컬럼이 없는 표(table_has_note_column=
    False)에서 당기3개월 disclosure 미공시로 생긴 진짜 선행 None이, 근본수정
    (`preserve_col_positions=(cum_map is not None)`) 이후 압축으로 지워지지 않고
    cum_map 절대위치 인덱싱과 맞아떨어져 정답을 낸다. 값은
    `test_report_lines_inline_xbrl_overlay.py`의 오버레이 테스트와 동일 — 이쪽은
    오버레이(옵션 B) 없이 근본수정(옵션 A) 단독으로 같은 정답에 도달함을 확인한다."""
    if not _GUKIL_Q3.exists():
        return
    lines = extract_report_lines(
        _GUKIL_Q3, rcept_no="20251113000801", corp_code="00104573",
        report_fiscal_year=2025, report_fiscal_period="Q3",
    )
    row = next(l for l in lines if l.statement == "IS" and l.basis == "consolidated"
               and (l.col_index or 0) == 0 and l.label_raw == "법인세비용(수익)")
    assert row.value_won == -2_310_052_284


# ── R65(2026-09-02): 헤더 `<TH>주석</TH>` 기반 주석열 탐지 신규 회귀 ──
# `note_ref_multicol_compaction_value_corruption_design_2026-09-02.md` §5.1.
# 두 실측 사례 모두 "매 행이 주석을 하나씩만 인용"(콤마 다중참조가 표 전체에 0번)이라
# `_table_has_comma_note_column()`(R19)이 영원히 False로 남아 안전장치가 미발동 —
# 주석번호가 진짜 금액으로 오채택되고(00537337), col_index≥1 적재제외 규칙에 걸려
# 진짜 당기금액 자체가 DB에서 소실됐다(원문대조 확정, 메모리
# note-ref-multicol-compaction-value-corruption-2026-09-02 참고).

_ANCN_FY2011 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00537337_앤씨앤/annual/2011/20120329000506.xml"
)
_SJBEAUTY_FY2020 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00132202_선진뷰티사이언스/annual/2020/20210323001110.xml"
)


def test_ancn_2011_revenue_no_longer_lost_to_note_ref():
    """앤씨앤(00537337) 2011FY(K-GAAP→IFRS 전환기) — 수정 전에는 "Ⅰ. 매출액"
    col_index0=5원(주석번호 오채택)이고 진짜 당기금액(458억)은 DB에서 아예 소실됐다.
    헤더기반 탐지(R65) 후에는 col_index0 이 진짜 당기금액, col_index1 이 진짜
    전기금액이어야 한다(원문 XML 직접대조 확정값).

    ★2026-09-15 정정: label_raw 는 그 뒤 로마숫자 접두어("Ⅰ. ")가 라벨 정규화로
    빠져 "매출액"으로 바뀌었다(값 자체는 원래 검증대로 정확 — 라벨 문자열만 갱신)."""
    if not _ANCN_FY2011.exists():
        return
    lines = extract_report_lines(
        _ANCN_FY2011, rcept_no="20120329000506", corp_code="00537337",
        report_fiscal_year=2011, report_fiscal_period="FY",
    )
    rev = {l.col_index: l.value_won for l in lines
           if l.statement == "IS" and l.basis == "separate" and l.label_raw == "매출액"}
    assert rev == {0: 45_830_369_541, 1: 50_367_549_269}, rev


def test_sjbeauty_2020_revenue_consolidated_and_separate_both_corrected():
    """선진뷰티사이언스(00132202) 2020FY(K-IFRS 정상표기 시대) — 수정 전에는 연결·별도
    양쪽 "Ⅰ. 매출액" 모두 주석번호(21/22)로 오채택됐다. R65 후에는 두 basis 모두
    올바른 당기·전기 금액이어야 한다(원문 XML 직접대조 확정값)."""
    if not _SJBEAUTY_FY2020.exists():
        return
    lines = extract_report_lines(
        _SJBEAUTY_FY2020, rcept_no="20210323001110", corp_code="00132202",
        report_fiscal_year=2020, report_fiscal_period="FY",
    )

    def _rev(basis):
        return {l.col_index: l.value_won for l in lines
                if l.statement == "IS" and l.basis == basis and l.label_raw == "Ⅰ. 매출액"}

    assert _rev("consolidated") == {0: 46_392_320_333, 1: 47_402_941_509}
    assert _rev("separate") == {0: 43_725_183_663, 1: 44_290_163_397}


_SOFTCEN_FY2022 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00204226_소프트센/annual/2022/20230323001157.xml"
)


def test_softcen_2022_sanemax_reject_no_longer_shifts_columns():
    """소프트센(00204226) 2022FY 연결BS — 원문이 "(단위 : 백만원)" 선언인데 실제로는
    이미 원 단위 숫자를 찍은 자기모순 필링(원문대조 확정, R73 (가+라) 그룹). 수정 전에는
    당기(제36기) "이익잉여금(결손금)" 17,293,933,213원이 ×10⁶ 스케일에서
    `_AMOUNT_SANE_MAX`(1경원) 가드에 걸려 None 이 됐고, 그 선두 None 을 (진짜 미공시로
    오인해) 절삭하는 바람에 전기(제35기) 값이 당기 열로, 전전기(제34기) 값이 전기 열로
    한 칸씩 밀려 들어갔다 — 원문에 없는 값이 특정 회계연도 것으로 둔갑하는 조용한
    오염(R3 자신의 "오염보다 결측을 택한다" 원칙 위반). 수정 후에는 거부된 당기 셀이
    그대로 결측(행 자체가 없음)으로 남고, 전기·전전기는 원래 자리(col_index 1·2)를
    지켜야 한다. (단위선언 자체의 교정은 별도 unit_override 트랙 — 여기서는 컬럼 밀림만
    검증한다.) 근거: docs/plans/report_lines_sanemax_reject_compaction_shift_design_2026-09-06.md
    """
    if not _SOFTCEN_FY2022.exists():
        return
    lines = extract_report_lines(
        _SOFTCEN_FY2022, rcept_no="20230323001157", corp_code="00204226",
        report_fiscal_year=2022, report_fiscal_period="FY",
    )

    def _by_col(label, basis="consolidated"):
        return {l.col_index: (l.context_fiscal_year, l.value_won) for l in lines
                if l.statement == "BS" and l.basis == basis and l.label_raw == label}

    re_col = _by_col("이익잉여금(결손금)")
    assert 0 not in re_col, f"거부된 당기 셀이 결측 대신 값으로 남음: {re_col}"
    assert re_col[1] == (2021, 6_570_137_526_000_000), re_col
    assert re_col[2] == (2020, -8_460_317_110_000_000), re_col

    nci_col = _by_col("비지배지분")
    assert 0 not in nci_col, f"거부된 당기 셀이 결측 대신 값으로 남음: {nci_col}"
    assert nci_col[1] == (2021, 8_058_575_267_000_000), nci_col
    assert nci_col[2] == (2020, 5_571_400_065_000_000), nci_col


_3S_FY2023Q3 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00378363_3S/quarter/2023/20230209000202.xml"
)


def test_3s_2023q3_sanemax_reject_cum_map_no_longer_wrong_column():
    """3S(00378363) 2023 Q3(FYE 3월, 회계상 2022.10~12 3분기) 연결IS — 원문
    "(단위:백만원)" 선언이 실제 자릿수와 안 맞는 자기모순 필링(원문 위 comment
    `fin2/extract/text.py::_emit_section` 근처에 이미 "3S(원문 (단위:백만원) 오기)"로
    기록돼 있던 바로 그 회사). 표는 [당기3개월|당기누적|전기3개월|전기누적] 2단
    헤더라 cum_map={1:0, 3:1}(누적컬럼만)이어야 정상인데, 당기누적·전기누적 둘 다
    ×10⁶ 스케일에서 `_AMOUNT_SANE_MAX` 에 걸려 거부되자, 수정 전에는 "누적컬럼이
    비면 존재값 아무거나 순서대로 채택"하는 폴백이 **전기 3개월**값(6,642,030,087)을
    주워 당기누적으로 둔갑시켰다(컬럼 밀림이 아니라 3개월값과 누적값이 뒤바뀌는 더
    위험한 변종). 수정 후에는 매출액 자체가 결측(행 없음)이어야 한다 — 엉뚱한 값보다
    결측이 안전하다는 R3/R74 원칙. 근거:
    docs/plans/report_lines_sanemax_reject_compaction_shift_design_2026-09-06.md
    """
    if not _3S_FY2023Q3.exists():
        return
    lines = extract_report_lines(
        _3S_FY2023Q3, rcept_no="20230209000202", corp_code="00378363",
        report_fiscal_year=2023, report_fiscal_period="Q3",
    )
    rev = [l for l in lines if l.statement == "IS" and l.basis == "consolidated"
           and l.label_raw == "매출액"]
    assert rev == [], f"거부된 누적값 대신 엉뚱한 값(전기 3개월)이 남음: {rev}"


_SAMSUNG_2019FY = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00126380_삼성전자/annual/2019/20200330003851.xml"
)
_HANWHA_2020FY = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00135917_한화손해보험/annual/2020/20210310000259.xml"
)
_SAMSUNG_2017Q1 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00126380_삼성전자/quarter/2017/20170515003806.xml"
)
_SAMSUNGLIFE_2016FY = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00126256_삼성생명/annual/2016/20170331005566.xml"
)


def test_samsung_2019fy_leading_blank_no_longer_shifted_to_current_period():
    """R86 — 삼성전자(00126380) 2019FY 별도 현금흐름표. IFRS9 전환으로 "장기매도가능
    금융자산의 처분/취득" 등은 전전기(2017, K-GAAP)에만 존재하고 당기/전기(2019/2018)는
    원문 자체가 진짜 공백([공란,공란,전전기값] 3열) — 수정 전에는 선두절삭이 이 공백을
    "파서 아티팩트"로 오인해 전전기값을 당기 열로 밀어 넣었다. 이 표는 주석참조 컬럼이
    없는(table_has_note_column=False) 순수 3열 비교표라, 수정 후에는 절삭 자체가 멈추고
    전전기값은 원래 자리(col_index=2)에 남아야 한다. docs/PARSING_RULES.md R86.
    """
    if not _SAMSUNG_2019FY.exists():
        return
    lines = extract_report_lines(
        _SAMSUNG_2019FY, rcept_no="20200330003851", corp_code="00126380",
        report_fiscal_year=2019, report_fiscal_period="FY")

    def _by_col(label):
        return {l.col_index: l.value_won for l in lines
                if l.statement == "CF" and l.basis == "separate" and l.label_raw == label}

    disposal = _by_col("장기매도가능금융자산의 처분")
    assert 0 not in disposal, f"당기 열에 전전기값이 밀려들어옴: {disposal}"
    assert disposal == {2: 98_265_000_000}, disposal

    acquisition = _by_col("장기매도가능금융자산의 취득")
    assert 0 not in acquisition, f"당기 열에 전전기값이 밀려들어옴: {acquisition}"
    assert acquisition == {2: -163_765_000_000}, acquisition

    # 선두 1칸만 공백인 행(전기값이 당기로 밀리던 사례)도 같이 확인.
    lt_acquire = _by_col("장기금융상품의 취득")
    assert 0 not in lt_acquire, f"당기 열에 전기값이 밀려들어옴: {lt_acquire}"
    assert lt_acquire == {1: -1_860_000_000_000, 2: -500_000_000_000}, lt_acquire

    # 선두가 공백이 아닌 행(당기값이 실제로 있는 행)은 무변경이어야 한다.
    lt_dispose = _by_col("장기금융상품의 처분")
    assert lt_dispose == {0: 1_400_000_000_000, 2: 1_700_000_000_000}, lt_dispose


def test_hanwha_2020fy_note_column_table_unchanged():
    """R86 회귀가드 — 한화손해보험(00135917) 2020FY 연결 IS 'VIII.당기순이익(손실)'.
    이 표는 주석참조 컬럼이 있는(table_has_note_column=True) 표라 R86 신규 조건이
    적용되지 않아야 한다 — classB(§5.1, 2026-08-29) 조사가 이미 이 표를 원 동기
    사례로 확인했고 R19 가 근본 해소했음을 검증한 값(수정 전/후 동일)."""
    if not _HANWHA_2020FY.exists():
        return
    lines = extract_report_lines(
        _HANWHA_2020FY, rcept_no="20210310000259", corp_code="00135917",
        report_fiscal_year=2020, report_fiscal_period="FY")

    ni = {l.col_index: l.value_won for l in lines
          if l.statement == "IS" and l.basis == "consolidated"
          and l.label_raw == "VIII. 당기순이익(손실)"}
    assert ni == {0: 48_250_117_187, 1: -69_073_849_554}, ni


def test_samsung_2017q1_four_column_cf_leading_blank_not_shifted():
    """R87(R86 후속) — 삼성전자(00126380) 2017Q1 별도·연결 현금흐름표.

    이 필링의 CF는 [당기1분기,전기1분기,전기(FY),전전기(FY)] 4열 구조(주석 X: `_interim_
    cumulative_cols()`가 3개월/누적 2단 헤더를 못 찾아 cum_map=None)라, R86이 고친
    `_emit_section_lines()`의 else 분기 이전에 `parser/xml/table_extractor.py::
    extract_rows()` 자신의 "6-column IS 형식 대응"(amount_cells≥4개 선두 None 절삭,
    R86과 별개 위치)이 먼저 작동해 R86의 가드가 보기도 전에 배열을 이미 밀어놨다 —
    "단기매도가능금융자산의 처분"(원문 [공란,전기1분기650,743,전기(FY)3,010,003,
    전전기(FY)2,143,384])의 전기1분기 값이 당기 열로 둔갑, "자기주식의 처분"(원문
    [공란,공란,공란,3,034]) 은 전전기(FY) 값이 당기 열로 3칸 밀려 둔갑했었다(사용자가
    원문대조로 발견). 이 표도 주석참조 컬럼이 없는(table_has_note_column=False) 순수
    기간열 표라, R86과 같은 근거로 `extract_rows()`의 이 절삭에도 같은 가드를 적용—
    수정 후에는 두 라벨 다 당기 열(col_index=0)이 없어야 한다(결측 유지)."""
    if not _SAMSUNG_2017Q1.exists():
        return
    lines = extract_report_lines(
        _SAMSUNG_2017Q1, rcept_no="20170515003806", corp_code="00126380",
        report_fiscal_year=2017, report_fiscal_period="Q1")

    def _by_col(label, basis):
        return {l.col_index: l.value_won for l in lines
                if l.statement == "CF" and l.basis == basis and l.label_raw == label}

    for basis in ("separate", "consolidated"):
        disposal = _by_col("단기매도가능금융자산의 처분", basis)
        assert 0 not in disposal, f"{basis}: 당기 열에 전기1분기값이 밀려들어옴: {disposal}"

        treasury = _by_col("자기주식의 처분", basis)
        assert 0 not in treasury, f"{basis}: 당기 열에 전전기(FY)값이 밀려들어옴: {treasury}"

    # 선두가 안 비어있는 행(연결, 당기값이 실제로 있음)은 무변경이어야 한다.
    lt_acquire_c = _by_col("단기매도가능금융자산의 취득", "consolidated")
    assert lt_acquire_c.get(0) == -544_463_000_000, lt_acquire_c


def test_samsunglife_multicol_paired_columns_unaffected_by_r86_r87():
    """R86/R87 후속 확인(2026-09-09, 코드 변경 없음) — 삼성생명(00126256) 2016
    사업보고서 연결 현금흐름표는 원문 금액셀 6개(2×n_periods)로 `multicol=True`
    분기를 탄다. 이 표는 기(期)마다 열이 2개(명세/소계 쌍)인 **정당한 구조적
    패딩**이라(소계행은 짝수쪽만·명세행은 홀수쪽만 채워짐), R86/R87의 `table_has_
    note_column` 가드를 여기 적용하면 오히려 정상값이 결측으로 사라진다 — 그래서
    의도적으로 적용하지 않는다. 이 테스트는 그 결론을 값으로 고정한다: 소계행
    ("Ⅰ.영업활동으로부터의 현금흐름")과 명세행("가.당기순이익") 둘 다 당기 열에
    원문 그대로의 실값이 있어야 한다(하나라도 결측이면 가드가 실수로 적용된 회귀)."""
    if not _SAMSUNGLIFE_2016FY.exists():
        return
    lines = extract_report_lines(
        _SAMSUNGLIFE_2016FY, rcept_no="20170331005566", corp_code="00126256",
        report_fiscal_year=2016, report_fiscal_period="FY")

    def _by_col(label):
        return {l.col_index: l.value_won for l in lines
                if l.statement == "CF" and l.basis == "consolidated" and l.label_raw == label}

    subtotal = _by_col("Ⅰ.영업활동으로부터의 현금흐름")
    assert subtotal.get(0) == 4_834_400_000_000, subtotal

    detail = _by_col("가. 당기순이익")
    assert detail.get(0) == 2_149_956_000_000, detail


# ── era 라우팅 역방향 폴백 (2026-09-12 설계) ────────────────────────────────
# docs/plans/era_routing_fallback_and_fiscal_year_correction_parsing_design_2026-09-12.md

def test_merge_missing_codes_fills_gaps_without_overwriting():
    """`_merge_missing_codes()` 순수 로직 — primary 가 채운 키는 그대로, 못 채운 키만 보충."""
    from fin2.extract.report_lines import _merge_missing_codes

    primary = {"BS_S": ["primary-bs"]}
    calls = []

    def fallback():
        calls.append(1)
        return {"BS_S": ["fallback-bs-should-be-ignored"], "IS_S": ["fallback-is"]}

    merged = _merge_missing_codes(primary, fallback)
    assert merged == {"BS_S": ["primary-bs"], "IS_S": ["fallback-is"]}
    assert calls == [1], "fallback_fn 은 정확히 한 번만 불려야 한다"


_JINWON_2022_CORRECTION_OF_2005FY = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00118521_진원생명과학/annual/2022/20220908000421.xml"
)


def test_misrouted_2011plus_falls_back_to_pre2015_detector():
    """★거짓양성 회귀 — 진원생명과학(00118521) 20220908000421(2026-09-12 실측).

    이 필링은 2022년에 접수된 [기재정정]이지만 실제 대상은 2005 회계연도(제30기, K-GAAP
    구서식)다. `report_nm`에 "(YYYY.MM)" 태그가 없어 수집 단계에서 fiscal_year 가 접수
    연도(2022)로 잘못 계산됐던 사고(입력측 수정은 `collector/filing_collector.py`
    `_fiscal_period_from_correction_section`, 이 테스트는 그 수정이 없어도 추출측
    폴백만으로 데이터가 살아나는지 확인 — 두 수정이 독립적으로 방어선이 되는지 검증).
    fiscal_year=2022(틀린 값)를 **그대로** 넘겨도, 2015+ 경로가 0행이면 pre-2015
    탐지기로 재시도해 실제 본문(별도 재무제표)을 복구해야 한다.
    """
    if not _JINWON_2022_CORRECTION_OF_2005FY.exists():
        return
    lines = extract_report_lines(
        _JINWON_2022_CORRECTION_OF_2005FY, rcept_no="20220908000421", corp_code="00118521",
        report_fiscal_year=2022, report_fiscal_period="FY")   # ★일부러 틀린 값
    assert len(lines) > 0, "역방향 폴백이 없으면 0행(보류)으로 끝난다 — 이게 실제 사고였다"
    bs_rows = [l for l in lines if l.statement == "BS" and l.basis == "separate"]
    assert bs_rows, "별도 대차대조표(구K-GAAP 명칭)가 폴백으로 복구돼야 한다"


_JEJU_BANK_2016_Q1 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00148832_제주은행/quarter/2016/20160516002967.xml"
)


def test_r118_jeju_bank_duplicate_period_label_typo_corrected():
    """R118(2026-09-14, 사용자 원문대조로 확정 — "별도는 정상인데 연결이 원문 오타") —
    제주은행 20160516002967 CF 연결 표 헤더가 "제57기 1분기"를 물리적으로 다른 두
    열에 완전히 동일한 텍스트로 중복 기재했다. 회계항등식(기초=전기말) 역산으로
    두 번째 열이 실제로는 "제56기 1분기"(전기)임을 확인, 이 rcept×CF×연결 조합에만
    한정한 예외 교정. 수정 전엔 두 값이 서로 달라 R6 판정불가로 행 전체 유실됐다."""
    if not _JEJU_BANK_2016_Q1.exists():
        return
    lines = extract_report_lines(
        _JEJU_BANK_2016_Q1, rcept_no="20160516002967", corp_code="00148832",
        report_fiscal_year=2016, report_fiscal_period="Q1")
    cf_c0 = [l for l in lines if l.statement == "CF" and l.basis == "consolidated"
             and (l.col_index or 0) == 0]
    ni = next((l for l in cf_c0 if l.label_raw == "Ⅰ. 영업활동으로 인한 현금흐름"), None)
    assert ni is not None, "R118 교정 실패 시 판정불가로 행 전체가 유실된다"
    assert ni.value_won == -48_817_000_000


_JEJU_BANK_2022_FY = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00148832_제주은행/annual/2022/20230314001271.xml"
)


def test_r118_jeju_bank_2022fy_triple_duplicate_period_label_typo_corrected():
    """R118 후속(2026-09-14, 사용자 확인 — "제주은행 보고서 단순 오타야") — 20230314001271
    CF 연결 표 헤더가 "제62기"(당기,정상)/"제62기"(전기, 원문에 제61기라고 썼어야 함)/
    "제61기"(전전기, 제60기라고 썼어야 함) 순으로 한 기수씩 밀려 중복·오기재됐다.
    회계항등식(기초=전기말) 역산으로 확정: 2번째 그룹 기초현금(302,547)이 3번째
    그룹 기말현금과 정확히 일치. 예외교정 없으면 rank 충돌로 3개 기간 전부
    R6 판정불가에 걸려 유실된다."""
    if not _JEJU_BANK_2022_FY.exists():
        return
    lines = extract_report_lines(
        _JEJU_BANK_2022_FY, rcept_no="20230314001271", corp_code="00148832",
        report_fiscal_year=2022, report_fiscal_period="FY")
    cf_c = [l for l in lines if l.statement == "CF" and l.basis == "consolidated"]
    by_rank = {}
    for l in cf_c:
        if l.label_raw == "Ⅰ. 영업활동으로 인한 현금흐름":
            by_rank[l.col_index] = l.value_won
    assert by_rank == {0: 114_388_000_000, 1: 137_050_000_000, 2: -120_627_000_000}, by_rank


_INNOSIMULATION_2019_FY = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00965318_이노시뮬레이션/annual/2019/20200330004128.xml"
)


def test_r118_innosimulation_2019fy_duplicate_period_label_typo_corrected():
    """R118 후속(2026-09-14, 사용자 확인 — "이노시뮬레이션은 단순 오타로 보여") —
    20200330004128 IS 별도 표 헤더가 "제19기(2018.01.01~2018.12.31)"를 완전히 동일
    하게 2번 반복한다. 같은 필링의 BS 별도는 정상(제20기/제19기/제18기, 중복 없음)
    이라, IS 만 position0을 "제20기"라고 썼어야 할 걸 "제19기"로 잘못 복사한 원문
    오타로 확정. 예외교정 없으면 rank 충돌로 3개 기간 전부 R6 판정불가에 걸려
    (기본주당이익 등 극소수 행만 남고) 본체가 유실된다."""
    if not _INNOSIMULATION_2019_FY.exists():
        return
    lines = extract_report_lines(
        _INNOSIMULATION_2019_FY, rcept_no="20200330004128", corp_code="00965318",
        report_fiscal_year=2019, report_fiscal_period="FY")
    is_sep = [l for l in lines if l.statement == "IS" and l.basis == "separate"]
    by_col = {}
    for l in is_sep:
        if l.label_raw == "매출액":
            by_col[l.col_index] = l.value_won
    assert by_col == {0: 14_779_266_111, 1: 14_512_073_752, 2: 29_076_802_160}, by_col


_DOUBLE_U_GAMES_2015_FY = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/01010110_더블유게임즈/annual/2015/20160520000534.xml"
)


def test_r121_double_u_games_2015fy_consolidated_excluded():
    """R121(2026-09-14, 사용자 확인 — "더블유게임즈 해당 기간 3,4기는 연결대상이
    아니야... 삭제하고 연결비대상으로 표시해") — 20160520000534 문서의 "2. 연결
    재무제표" 섹션에 물리적으로 표가 있지만(유진로봇류 "완전공백 섹션"과 다름) 그
    값은 이 필링 당기(제4기)·전기(제3기)의 것이 아니라 제2기(2013) 시절 옛 자본변동
    표/EPS 수치뿐이다. 재배정할 근거가 없어(짐작 금지) 연결(_C) 섹션 자체를 배제한다
    — 별도(_S)는 무영향."""
    if not _DOUBLE_U_GAMES_2015_FY.exists():
        return
    lines = extract_report_lines(
        _DOUBLE_U_GAMES_2015_FY, rcept_no="20160520000534", corp_code="01010110",
        report_fiscal_year=2015, report_fiscal_period="FY")
    assert not any(l.basis == "consolidated" for l in lines), \
        "R121 배제 실패 시 제2기 시절 옛 데이터가 연결 basis 로 다시 새어든다"
    assert any(l.basis == "separate" and l.statement == "IS" for l in lines), \
        "별도는 무영향으로 정상 적재돼야 한다"


_HANWHA_INVESTMENT_2020_Q1 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00148610_한화투자증권/quarter/2020/20200515000970.xml"
)
_VQAI_2020_FY = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00980043_비큐AI/annual/2020/20210323000745.xml"
)


def test_r127_hanwha_investment_sce_data_no_longer_stored_as_cf():
    """R127(2026-09-15, header-fallback 잔여 14건 재조사로 발견) — 한화투자증권
    20200515000970 원문 자체가 "라. 연결현금흐름표"/"라. 현금흐름표" 캡션을 자본
    변동표(SCE) 데이터 표 바로 앞에 잘못 붙여놨다(진짜 CF 데이터는 그 뒤 별도
    무제목 표에 orphan 으로 남음). 표제만 보고 그대로 받아들이면 "2018.1.1(전전
    기초)" 같은 자본 롤포워드 행이 statement='CF' 로 오염된다(수정 전 실측 확인).
    표 내용(자본금/자본잉여금/이익잉여금 등 열이름)으로 걸러내 뒤에 있는 진짜
    현금흐름표 데이터를 대신 채택해야 한다."""
    if not _HANWHA_INVESTMENT_2020_Q1.exists():
        return
    lines = extract_report_lines(
        _HANWHA_INVESTMENT_2020_Q1, rcept_no="20200515000970", corp_code="00148610",
        report_fiscal_year=2020, report_fiscal_period="Q1")
    cf = [l for l in lines if l.statement == "CF"]
    assert cf, "R127 교정 실패 시 CF 전체가 유실될 수 있다"
    assert not any("기초" in l.label_raw and "자본" not in l.label_raw and l.label_raw.startswith("20")
                   for l in cf), "SCE 자본 롤포워드 라벨(예: 2018.1.1(전전기초))이 CF 에 새면 안 됨"
    ni = next((l for l in cf if l.basis == "consolidated"
               and l.label_raw == "I. 영업활동으로 인한 현금흐름" and l.col_index == 0), None)
    assert ni is not None, "진짜 현금흐름표 데이터가 채택돼야 한다"
    assert ni.value_won == 82_793_327_678


def test_r127_vqai_sce_data_no_longer_stored_as_cf():
    """R127(2026-09-15) — 비큐AI 20210323000745 도 동일 원문결함(별도 CF). 수정 전엔
    "2019.01.01(전기초)" 같은 자본변동표 행이 CF_separate 로 오염됐다."""
    if not _VQAI_2020_FY.exists():
        return
    lines = extract_report_lines(
        _VQAI_2020_FY, rcept_no="20210323000745", corp_code="00980043",
        report_fiscal_year=2020, report_fiscal_period="FY")
    cf_s = [l for l in lines if l.statement == "CF" and l.basis == "separate"]
    assert cf_s, "R127 교정 실패 시 CF_S 전체가 유실될 수 있다"
    assert not any("전기초" in l.label_raw or "전기말" in l.label_raw for l in cf_s), \
        "SCE 자본 롤포워드 라벨이 CF_S 에 새면 안 됨"
    ni = next((l for l in cf_s if "영업활동으로인한현금흐름" in l.label_raw.replace(" ", "")
               and l.col_index == 0), None)
    assert ni is not None, "진짜 현금흐름표 데이터가 채택돼야 한다"
    assert ni.value_won == -458_649_411


_HYUNDAICAR_SEC_2018_Q1 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00137997_현대차증권/quarter/2018/20180515002185.xml"
)


def test_r127b_hyundaicar_securities_footnote_misclassified_sce_no_longer_stored_as_is():
    """R127b(2026-09-15, R127 사각지대 후속발견) — 현대차증권 20180515002185 IS 연결.
    R127은 "제목+데이터 한 표"만 가드했는데, 여기는 "제목표/데이터표 분리 서식"의
    forward-scan 경로다: 각주 문장("...연결포괄손익계산서는...")이 title_text_owned
    에 의해 본문 제목처럼 오분류돼(단순 텍스트 포함 매칭) title-only 취급되면, 그
    다음 데이터표(SCE 자본변동표 요약, "지배주주지분/비지배지분/자본총계")가
    IS 데이터로 잘못 연결된다. 수정 전엔 "2017.01.01(전기초)(주1)" 같은 자본
    롤포워드 라벨이 statement='IS' 로 오염됐다(DB 직접대조로 확인)."""
    if not _HYUNDAICAR_SEC_2018_Q1.exists():
        return
    lines = extract_report_lines(
        _HYUNDAICAR_SEC_2018_Q1, rcept_no="20180515002185", corp_code="00137997",
        report_fiscal_year=2018, report_fiscal_period="Q1")
    is_c = [l for l in lines if l.statement == "IS" and l.basis == "consolidated"]
    assert is_c, "R127b 교정 실패 시 IS_C 전체가 유실될 수 있다"
    assert not any(l.label_raw.startswith("2017.01.01") for l in is_c), \
        "SCE 자본 롤포워드 라벨(전기초)이 IS 에 새면 안 됨"
    rev = next((l for l in is_c if l.label_raw == "I.영업수익" and l.col_index == 0), None)
    assert rev is not None, "진짜 포괄손익계산서 데이터가 채택돼야 한다"
    assert rev.value_won == 144_777_899_038


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
