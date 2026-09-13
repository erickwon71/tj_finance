"""Track C(HTML 웹뷰어) 파서 단위 테스트 — TOC 파싱·레이아웃 2종·값 추출.

두 레이아웃 fixture(_KD_STYLE_BS/_DONGSUNG_STYLE_BS)는 KD(00111218 rcept
20010814000291)·동성제약(00116268 rcept 20010813000395) 실측 HTML 구조를
그대로 축약한 것 — 총계 3개(자산/부채/자본)는 두 필링 모두 이미 원문대조로
확정된 실제 값(docs/plans/pdf_track_c_parser_robustness_2026-09-06.md
§4-보강/R78)이라, 항등식(자산=부채+자본) 성립까지 확인하면 파서가 실제
필링에서도 같은 값을 재현할 근거가 된다.

실행: python -m fin2.tests.test_html_viewer
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.html_viewer import (  # noqa: E402
    parse_toc_tree, find_statement_nodes, facts_from_sections,
)

# ── 레이아웃 A(거대-셀형, KD류) ──────────────────────────────────────────────
_KD_STYLE_BS = """
<P class='section-3'>가. 대차대조표</P>
<P class='table-group'>대 차 대 조 표</P>
<TABLE class='nb' width='600'>
<TBODY>
<TR><TD align='CENTER'>제 28 기 반기 2001.06.30 현재</TD></TR>
<TR><TD align='RIGHT'>(단위 :천원)</TD></TR>
</TBODY>
</TABLE>
<TABLE border='1' width='638'>
<THEAD>
<TR><TH>과목</TH><TH>제 28 기 반기</TH><TH>제 27 기 반기</TH></TR>
</THEAD>
<TBODY>
<TR>
  <TD width='200' valign='TOP'>Ⅰ.유동자산<BR/>자산총계<BR/>Ⅰ.유동부채<BR/>부채총계<BR/>Ⅰ.자본금<BR/>자본총계<BR/>부채와자본총계</TD>
  <TD width='110' align='RIGHT'>14,903,038<BR/>24,164,567<BR/>13,007,264<BR/>14,826,827<BR/>2,900,000<BR/>9,337,740<BR/>24,164,567</TD>
  <TD width='110' align='RIGHT'>10,298,683<BR/>18,132,563<BR/>9,264,281<BR/>11,245,086<BR/>2,000,000<BR/>6,887,477<BR/>18,132,563</TD>
</TR>
</TBODY>
</TABLE>
"""

# ── 레이아웃 B(행별-TR형, 동성제약류) ────────────────────────────────────────
# 실측(동성제약)과 동일하게 헤더 colspan 쌍마다 앞쪽은 빈 플레이스홀더, 실제
# 값은 뒤쪽 컬럼에 온다 — col0 판정이 "첫 비어있지 않은 셀"이어야 함을 검증.
_DONGSUNG_STYLE_BS = """
<P class='section-3'>가. 대차대조표</P>
<TABLE class='nb' width='600'>
<TBODY>
<TR><TD align='RIGHT'>(단위 : 원)</TD></TR>
</TBODY>
</TABLE>
<TABLE border='1' width='1110'>
<THEAD>
<TR>
  <TH rowspan='2'>과목</TH>
  <TH colspan='2'>제 45 반기</TH>
  <TH colspan='2'>제 44 반기</TH>
</TR>
<TR>
  <TH colspan='2'>금액</TH>
  <TH colspan='2'><BR/><BR/></TH>
</TR>
</THEAD>
<TBODY>
<TR>
  <TD valign='TOP'>자산총계</TD>
  <TD align='RIGHT'><BR/><BR/></TD>
  <TD align='RIGHT'>107,638,242,656&nbsp;</TD>
  <TD align='RIGHT'><BR/><BR/></TD>
  <TD align='RIGHT'>112,172,222,762</TD>
</TR>
<TR>
  <TD valign='TOP'>부채총계</TD>
  <TD align='RIGHT'><BR/><BR/></TD>
  <TD align='RIGHT'>61,277,762,838&nbsp;</TD>
  <TD align='RIGHT'><BR/><BR/></TD>
  <TD align='RIGHT'>67,408,436,903</TD>
</TR>
<TR>
  <TD valign='TOP'>자본총계</TD>
  <TD align='RIGHT'><BR/><BR/></TD>
  <TD align='RIGHT'>46,360,479,818&nbsp;</TD>
  <TD align='RIGHT'><BR/><BR/></TD>
  <TD align='RIGHT'>44,763,785,859</TD>
</TR>
</TBODY>
</TABLE>
"""

# ── 단일줄 이중언어 라벨(제일기획류) ─────────────────────────────────────────
# 실측(00148276 rcept 20010330001205, 2026-09-07 PDF결과 비교 중 발견) — 3줄
# 분리형(docs/plans/pdf_multiline_bilingual_layout_2026-09-06.md)과 다른 변형:
# 라벨이 "유동자산(Current Assets)"처럼 한 줄에 한글+영문 대역어가 같이 온다.
# `_strip_inline_english_gloss()` 없이는 account_mapper 가 못 알아봐 그
# basis/statement 전체가 통째로 빈손이 됐다(72행 파싱 성공 + 매핑 전부 실패).
_BILINGUAL_LABEL_BS = """
<P class='section-3'>가. 대차대조표</P>
<TABLE class='nb' width='600'>
<TBODY>
<TR><TD align='RIGHT'>(단위 : 원)</TD></TR>
</TBODY>
</TABLE>
<TABLE border='1' width='638'>
<THEAD>
<TR><TH>과목</TH><TH>당기</TH></TR>
</THEAD>
<TBODY>
<TR><TD>자산총계(Total Assets)</TD><TD align='RIGHT'>505,226,620,469</TD></TR>
<TR><TD>부채총계(Total Liabilities)</TD><TD align='RIGHT'>205,924,718,263</TD></TR>
<TR><TD>자본총계(Total Stockholders' Equity)</TD><TD align='RIGHT'>299,301,902,206</TD></TR>
</TBODY>
</TABLE>
"""

# ── 원인A: 당기 컬럼이 최좌측이 아님(제일기획류) ────────────────────────────
# 실측(00148276 rcept 20010814000859, 2026-09-07 fail19 비교 중 발견) — 헤더가
# "제28기/제27기/제26기"인데 앞 두 컬럼은 전부 진짜 대시("-")고 실제 값은
# 가장 오른쪽(제26기)에만 있다. "첫 비어있지 않은 셀=col0" 이었던 예전 로직은
# 첫 대시에서 멈춰 값을 통째로 놓쳤다 — "숫자로 파싱되는 첫 셀"까지 건너뛰어야
# 함을 검증.
_JEILGIHOEK_STYLE_BS = """
<P class='section-3'>가. 대차대조표</P>
<TABLE class='nb' width='600'>
<TBODY>
<TR><TD align='RIGHT'>(단위 : 원)</TD></TR>
</TBODY>
</TABLE>
<TABLE border='1' width='700'>
<THEAD>
<TR><TH>과목</TH><TH>제28기</TH><TH>제27기</TH><TH>제 26 기</TH></TR>
</THEAD>
<TBODY>
<TR><TD>자산총계</TD><TD align='RIGHT'>-</TD><TD align='RIGHT'>-</TD><TD align='RIGHT'>259,653,479,057</TD></TR>
<TR><TD>부채총계</TD><TD align='RIGHT'>-</TD><TD align='RIGHT'>-</TD><TD align='RIGHT'>217,161,013,022</TD></TR>
<TR><TD>자본총계</TD><TD align='RIGHT'>-</TD><TD align='RIGHT'>-</TD><TD align='RIGHT'>42,049,237,175</TD></TR>
</TBODY>
</TABLE>
"""

# ── DB증권류: 같은 표 안에서도 행마다 빈칸 위치가 다름(원인A 재발 방지) ────
# 실측(00115694 rcept 20010214000346) — 일반 항목행은 [값,빈칸,값,빈칸]인데
# 합계행만 [빈칸,값,빈칸,값]으로 밀린다(서식상 들여쓰기 차이로 추정). "표
# 전체에서 데이터 있는 첫 컬럼을 고정"하는 방식으로 고치면 이 표가 깨진다
# (일반 항목행 컬럼이 우선 뽑혀 col0으로 고정되고, 합계행은 그 컬럼이 항상
# 빈칸이라 못 뽑음) — 반드시 행마다 판정해야 함을 검증.
_DBSEC_MIXED_OFFSET_BS = """
<P class='section-3'>가. 대차대조표</P>
<TABLE class='nb' width='600'>
<TBODY>
<TR><TD align='RIGHT'>(단위 : 원)</TD></TR>
</TBODY>
</TABLE>
<TABLE border='1' width='700'>
<THEAD>
<TR><TH>과목</TH><TH colspan='2'>제19기 3/4분기</TH><TH colspan='2'>제18기 3/4분기</TH></TR>
</THEAD>
<TBODY>
<TR><TD>가.현금</TD><TD>2,765,845</TD><TD></TD><TD>10,021,231</TD><TD></TD></TR>
<TR><TD>자산총계</TD><TD></TD><TD>316,770,277,742</TD><TD></TD><TD>575,308,504,584</TD></TR>
<TR><TD>부채총계</TD><TD></TD><TD>168,222,750,184</TD><TD></TD><TD>500,000,000,000</TD></TR>
<TR><TD>자본총계</TD><TD></TD><TD>148,547,527,558</TD><TD></TD><TD>75,308,504,584</TD></TR>
</TBODY>
</TABLE>
"""

# ── 원인B(부분 대응): 그랜드토탈 라벨이 다음 섹션 머리글과 구분자 없이 붙음 ──
# 실측 축약(일성건설 00146232류 패턴) — 그랜드토탈이 바로 다음 섹션의
# 맨앞 bare 단어("부채"/"자본")와 구분자 없이 붙는다("자산총계부채",
# "부채총계자본"). `account_mapper.map()`은 이런 오염 라벨도 substring
# 포함만으로 fuzzy 매치해버리는 게 실측으로 확인됨("자산총계부채" →
# bs.total_assets, "부채총계자본" → bs.total_liabilities) — 값까지 우연히
# 파싱되면 조용히 틀린 숫자가 정답 canonical_account 에 실릴 위험이 있다.
# `_STRICT_TOTAL_LABELS` 가드가 이 두 오염 라벨은 거부하고, 오염 없는
# "자본총계"는 그대로 통과시키는지 검증.
_CONTAMINATED_TOTAL_LABEL_BS = """
<P class='section-3'>가. 대차대조표</P>
<TABLE class='nb' width='600'>
<TBODY>
<TR><TD align='RIGHT'>(단위 : 원)</TD></TR>
</TBODY>
</TABLE>
<TABLE border='1' width='700'>
<THEAD>
<TR><TH>과목</TH><TH>당기</TH></TR>
</THEAD>
<TBODY>
<TR>
  <TD>2.개발비<BR/>자산총계부채<BR/>1.매입채무<BR/>부채총계자본<BR/>1.자본금<BR/>자본총계<BR/></TD>
  <TD>200,000<BR/>999,999,999<BR/>888,888<BR/>777,777,777<BR/>666,666<BR/>51,787,901,214<BR/></TD>
</TR>
</TBODY>
</TABLE>
"""

_TOC_SAMPLE = """
var node1 = {};
node1['text'] = "3. 재무제표";
node1['eleId'] = "3126";
node1['offset'] = "334223";
node1['length'] = "25936";
node1['dtd'] = "dart2.dtd";
node1['dcmNo'] = "235764";
var node1 = {};
node1['text'] = "2. 재무제표 이용상의 유의점";
node1['eleId'] = "1995";
node1['offset'] = "210822";
node1['length'] = "481";
node1['dtd'] = "dart2.dtd";
node1['dcmNo'] = "234750";
var node1 = {};
node1['text'] = "4. 연결재무제표";
node1['eleId'] = "7317";
node1['offset'] = "850522";
node1['length'] = "25936";
node1['dtd'] = "dart2.dtd";
node1['dcmNo'] = "234750";
var node1 = {};
node1['text'] = "3. 연결재무제표에 대한 감사인의 감사의견 등";
node1['eleId'] = "8821";
node1['offset'] = "900000";
node1['length'] = "4987";
node1['dtd'] = "dart2.dtd";
node1['dcmNo'] = "234750";
"""


def _totals(facts):
    def won(canon):
        m = [f.amount_won for f in facts if f.canonical_account == canon]
        return m[0] if m else None
    return won("bs.total_assets"), won("bs.total_liabilities"), won("bs.total_equity")


def test_parse_toc_tree_extracts_all_node_fields():
    nodes = parse_toc_tree(_TOC_SAMPLE)
    assert len(nodes) == 4
    assert nodes[0].text == "3. 재무제표"
    assert nodes[0].ele_id == "3126"
    assert nodes[0].dcm_no == "235764"


def test_find_statement_nodes_excludes_유의점_and_감사의견():
    nodes = parse_toc_tree(_TOC_SAMPLE)
    fs = find_statement_nodes(nodes)
    texts = [n.text for n in fs]
    assert texts == ["3. 재무제표", "4. 연결재무제표"]


_TOC_NO_CONSOLIDATED = """
var node1 = {};
node1['text'] = "2. 연결재무제표";
node1['eleId'] = "1001";
node1['offset'] = "129317";
node1['length'] = "138";
node1['dtd'] = "dart3.dtd";
node1['dcmNo'] = "6383879";
var node1 = {};
node1['text'] = "3. 연결재무제표 주석";
node1['eleId'] = "1002";
node1['offset'] = "129459";
node1['length'] = "141";
node1['dtd'] = "dart3.dtd";
node1['dcmNo'] = "6383879";
var node1 = {};
node1['text'] = "4. 재무제표";
node1['eleId'] = "1003";
node1['offset'] = "129604";
node1['length'] = "29908";
node1['dtd'] = "dart3.dtd";
node1['dcmNo'] = "6383879";
var node1 = {};
node1['text'] = "5. 재무제표 주석";
node1['eleId'] = "1004";
node1['offset'] = "159516";
node1['length'] = "94998";
node1['dtd'] = "dart3.dtd";
node1['dcmNo'] = "6383879";
"""


def test_find_statement_nodes_excludes_placeholder_only_consolidated_section():
    """R98(2026-09-12) — TOC 는 연결이 없는 회사에도 "2.연결재무제표" 골격을 항상
    나열하지만, 실제 내용은 "해당사항이 없습니다" 류 한 줄뿐이라 length 가 극히 작다
    (실측: 자비스 01174038 정정본 20181114002329, "2.연결재무제표"=138B/"3.연결재무제표
    주석"=141B vs 실제 내용 있는 "4.재무제표"=29,908B — 3자리 vs 5자리 격차). 텍스트만
    보면 "연결재무제표" 노드가 있다고 착각해(`reconcile()`이 실제로 이렇게 오판) 존재하지도
    않는 연결 수치를 찾으려 든다 — length 로 placeholder 를 걸러야 한다."""
    nodes = parse_toc_tree(_TOC_NO_CONSOLIDATED)
    fs = find_statement_nodes(nodes)
    texts = [n.text for n in fs]
    assert texts == ["4. 재무제표", "5. 재무제표 주석"]


def test_find_statement_nodes_length_unparseable_falls_back_to_included():
    """length 필드가 파싱 불가면(빈 문자열 등) 판정 근거가 없으므로 기존대로 포함한다
    (R6 원칙 — 모르면 걸러내지 않는다)."""
    xml = _TOC_NO_CONSOLIDATED.replace('node1[\'length\'] = "138";', 'node1[\'length\'] = "";', 1)
    nodes = parse_toc_tree(xml)
    fs = find_statement_nodes(nodes)
    texts = [n.text for n in fs]
    assert "2. 연결재무제표" in texts


def test_giant_cell_layout_reconstructs_kd_grand_totals():
    facts = facts_from_sections(
        {"separate": _KD_STYLE_BS.encode("utf-8")},
        corp_code="00111218", rcept_no="20010814000291",
        report_fiscal_year=2001, report_fiscal_period="H1",
    )
    a, l, e = _totals(facts)
    assert (a, l, e) == (24_164_567_000, 14_826_827_000, 9_337_740_000)
    assert a == l + e


def test_row_layout_reconstructs_dongsung_grand_totals():
    facts = facts_from_sections(
        {"separate": _DONGSUNG_STYLE_BS.encode("utf-8")},
        corp_code="00116268", rcept_no="20010813000395",
        report_fiscal_year=2001, report_fiscal_period="H1",
    )
    a, l, e = _totals(facts)
    assert (a, l, e) == (107_638_242_656, 61_277_762_838, 46_360_479_818)
    assert a == l + e


def test_row_layout_skips_blank_placeholder_columns_not_second_period():
    """col0 은 "첫 비어있지 않은 셀"이어야지, 물리적 두 번째 TD(플레이스홀더)나
    세 번째 기간(제 44 반기) 값이 섞여 들어가면 안 된다."""
    facts = facts_from_sections(
        {"separate": _DONGSUNG_STYLE_BS.encode("utf-8")},
        corp_code="00116268", rcept_no="20010813000395",
        report_fiscal_year=2001, report_fiscal_period="H1",
    )
    a, _, _ = _totals(facts)
    assert a != 112_172_222_762  # 제 44 반기(다음 기간) 값이 아님


def test_bilingual_inline_label_gloss_is_stripped_before_mapping():
    """"자산총계(Total Assets)" 처럼 라벨에 붙은 영문 대역어를 못 떼면
    account_mapper 가 못 알아봐 facts 가 통째로 0건이 된다(제일기획 실측)."""
    facts = facts_from_sections(
        {"separate": _BILINGUAL_LABEL_BS.encode("utf-8")},
        corp_code="00148276", rcept_no="20010330001205",
        report_fiscal_year=2000, report_fiscal_period="FY",
    )
    a, l, e = _totals(facts)
    assert (a, l, e) == (505_226_620_469, 205_924_718_263, 299_301_902_206)
    assert a == l + e


def test_dash_columns_genuinely_missing_are_not_backfilled_from_older_period():
    """★2026-09-10 정정(header_first_parsing_expansion_design_2026-09-10.md §1) —
    이 테스트는 원래 "대시에서 멈추면 안 되고 오른쪽의 실제 값을 찾아야 한다"고
    주장하며 259,653,479,057을 **당기** 값으로 기대했다. DART 실 페이지를 직접
    재확인(rcpNo=20010814000859, 연결재무제표, 실제 연결대차대조표 THEAD="과목/
    제28기/제27기/제 26 기") 결과, 그 값은 "부채·외부주주지분 및 자본총계" 행의
    **제 26 기(전전기) 칸**에 있고 제28기(당기)·제27기(전기)는 그 표의 **모든
    행에서 진짜로 대시(미공시)** 였다 — 2001년 당시 연결재무제표를 당기/전기는
    작성하지 않고 참고용 과거 2개년만 실은 것으로 보인다. 즉 옛 "숫자로 파싱되는
    첫 셀=당기" 휴리스틱은 **전전기 값을 당기로 둔갑**시키고 있었다(R86/R87과
    같은 클래스의 결함, 이번 세션에 새로 발견·수정). 헤더그리드 경로는 이제
    이걸 정직하게 결측으로 남긴다(R3 원칙) — 아래 값-위치 폴백(THEAD를 못 읽는
    표에서만 여전히 남는 경로)과 달리, 진짜 당기가 없으면 없다고 말해야 한다."""
    facts = facts_from_sections(
        {"consolidated": _JEILGIHOEK_STYLE_BS.encode("utf-8")},
        corp_code="00148276", rcept_no="20010814000859",
        report_fiscal_year=2001, report_fiscal_period="H1",
    )
    a, l, e = _totals(facts)
    assert (a, l, e) == (None, None, None)  # 당기 진짜 결측 — 전전기 값으로 대체 안 함


def test_header_first_path_selects_true_current_column_not_first_parseable():
    """헤더그리드 경로가 실제로 작동함을 증명 — "숫자로 파싱되는 첫 셀"이 아니라
    헤더가 선언한 진짜 당기(제28기) 열을 고른다. 위 테스트와 짝을 이룬다:
    거기서는 당기가 진짜 결측이라 결측으로 남겨야 하고, 여기서는 당기에 값이
    있으면(설령 물리적으로 더 나중 열에 값이 하나 더 있어도) 헤더가 가리키는
    "제28기"(당기) 값을 정확히 골라야 한다."""
    xml = """
<P class='section-3'>가. 대차대조표</P>
<TABLE class='nb' width='600'>
<TBODY><TR><TD align='RIGHT'>(단위 : 원)</TD></TR></TBODY>
</TABLE>
<TABLE border='1' width='700'>
<THEAD>
<TR><TH>과목</TH><TH>제28기</TH><TH>제27기</TH><TH>제 26 기</TH></TR>
</THEAD>
<TBODY>
<TR><TD>자산총계</TD><TD align='RIGHT'>111,000,000</TD><TD align='RIGHT'>90,000,000</TD><TD align='RIGHT'>80,000,000</TD></TR>
<TR><TD>부채총계</TD><TD align='RIGHT'>61,000,000</TD><TD align='RIGHT'>50,000,000</TD><TD align='RIGHT'>40,000,000</TD></TR>
<TR><TD>자본총계</TD><TD align='RIGHT'>50,000,000</TD><TD align='RIGHT'>40,000,000</TD><TD align='RIGHT'>40,000,000</TD></TR>
</TBODY>
</TABLE>
"""
    facts = facts_from_sections(
        {"separate": xml.encode("utf-8")},
        corp_code="00148276", rcept_no="synthetic-current-column",
        report_fiscal_year=2001, report_fiscal_period="H1",
    )
    a, l, e = _totals(facts)
    assert (a, l, e) == (111_000_000, 61_000_000, 50_000_000)
    assert a == l + e


def test_header_first_path_prefers_cumulative_over_three_month():
    """모듈이 자인하던 갭(2026-09-10 이전 docstring: "interim IS/CF의 3개월 vs 누적
    구분을 이 모듈은 아직 안 한다") 해소 확인 — 2단 헤더(기간 + 3개월/누적)에서
    누적 값을 채택해야 한다(R85 원칙, XML과 동일)."""
    xml = """
<P class='section-3'>나. 손익계산서</P>
<TABLE class='nb' width='600'>
<TBODY><TR><TD align='RIGHT'>(단위 : 원)</TD></TR></TBODY>
</TABLE>
<TABLE border='1' width='700'>
<THEAD>
<TR><TH rowspan='2'>과목</TH><TH colspan='2'>제 28 기</TH></TR>
<TR><TH>3개월</TH><TH>누적</TH></TR>
</THEAD>
<TBODY>
<TR><TD>매출액</TD><TD align='RIGHT'>30,000,000</TD><TD align='RIGHT'>90,000,000</TD></TR>
</TBODY>
</TABLE>
"""
    facts = facts_from_sections(
        {"separate": xml.encode("utf-8")},
        corp_code="00148276", rcept_no="synthetic-cumulative",
        report_fiscal_year=2001, report_fiscal_period="Q3",
    )
    rev = [f.amount_won for f in facts if f.canonical_account == "is.revenue"]
    assert rev == [90_000_000]  # 누적(90,000,000) 채택 — 3개월(30,000,000) 아님


def test_row_offset_is_judged_per_row_not_per_table():
    """원인A를 "표 전체에서 데이터 있는 첫 컬럼 고정"으로 고치면 DB증권류가
    깨진다 — 같은 표 안에서도 일반 항목행/합계행의 빈칸 위치가 다르므로
    반드시 행마다 판정해야 한다."""
    facts = facts_from_sections(
        {"separate": _DBSEC_MIXED_OFFSET_BS.encode("utf-8")},
        corp_code="00115694", rcept_no="20010214000346",
        report_fiscal_year=2001, report_fiscal_period="Q3",
    )
    a, l, e = _totals(facts)
    assert (a, l, e) == (316_770_277_742, 168_222_750_184, 148_547_527_558)
    assert a == l + e


def test_strict_total_label_guard_rejects_contaminated_grand_totals():
    """레이아웃 A에서 그랜드토탈 라벨이 다음 섹션 머리글과 구분자 없이
    붙으면("자산총계부채") account_mapper 가 fuzzy 매치로 통과시켜버리는데
    (실측 확인), `_STRICT_TOTAL_LABELS` 가드가 그 오염된 자산총계·부채총계는
    거부하고 오염 없는 자본총계만 통과시켜야 한다 — 결측이 오염보다 낫다."""
    facts = facts_from_sections(
        {"separate": _CONTAMINATED_TOTAL_LABEL_BS.encode("utf-8")},
        corp_code="00146232", rcept_no="20000330000664",
        report_fiscal_year=1999, report_fiscal_period="FY",
    )
    a, l, e = _totals(facts)
    assert a is None  # "자산총계부채" — 오염, 거부돼야 함
    assert l is None  # "부채총계자본" — 오염, 거부돼야 함
    assert e == 51_787_901_214  # "자본총계" — 클린, 통과해야 함


def test_no_sections_returns_empty():
    assert facts_from_sections(
        {}, corp_code="x", rcept_no="y",
        report_fiscal_year=2001, report_fiscal_period="H1",
    ) == []


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
