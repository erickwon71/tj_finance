"""
R144 회귀 테스트 — 계층2 원문대조 캠페인 fail 20건의 근본원인 3종.

① EPS 이중 전사(단위 오귀속 유령행)
   `_emit_eps_lines`(행 인라인 단위=원)와 본류 `_emit_section_lines`(표 단위를 이미
   곱한 값)가 **서로 다른 스케일**로 각자 `_looks_like_eps_amounts()`를 부르는 바람에,
   백만원 선언 표에서 같은 EPS 행이 두 경로로 전부 전사됐다 — 정상(원) 1쌍 + 단위=
   백만원으로 라벨된 ×10⁶ 유령 1쌍. 실측: 삼성생명 17개 필링(2019Q3~2023H1) 연결·별도.

② EPS 열 밀림(당기 공란 시 전기 값이 당기로 둔갑)
   `_emit_eps_lines`의 FY 분기가 `present`(None 제거 압축)를 썼다. 당기 셀이 공란인
   행에서 열이 왼쪽으로 밀렸다. 실측: 삼성물산 20160330002954·20170331003913 연결IS
   '중단사업 주당이익'(원문 당기=공란/전기=3,418/전전기=470).

③ 셀 안에서 줄바꿈으로 쪼개진 숫자
   원문 XML 이 한 금액을 TD 안에서 개행으로 끊어 담는 경우('22,270,03\\n9'), 공백
   제거가 개행을 빼먹어 "숫자 아님"으로 판정돼 **행이 통째로 사라지거나** 뒤 열이
   당기 열로 밀렸다. 실측: 삼성생명 20210517001864 연결 BS/CF/IS 5행, 20220516002463
   연결 SCE 6값.

실행: pytest fin2/tests/test_report_lines_r144_eps_dup_and_cell_linebreak.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree  # noqa: E402

from fin2.extract.report_lines import _emit_section_lines  # noqa: E402
from parser.common.amount_normalizer import parse_amount  # noqa: E402
from parser.xml.table_extractor import extract_rows  # noqa: E402

_RCEPT = "TESTR144-000000001"
_MILLION = 1_000_000


def _fy_table(rows: list[list[str]]) -> etree._Element:
    """FY 3열(당기/전기/전전기) 표. rows[i] = [라벨, 당기, 전기, 전전기]."""
    trs = "".join(
        "<TR>" + "".join(f"<TD>{c}</TD>" for c in row) + "</TR>" for row in rows)
    return etree.fromstring(f"<TABLE>{trs}</TABLE>")


def _run_fy(table, *, unit: int = _MILLION):
    decl = "(단위 : 백만원)" if unit == _MILLION else "(단위 : 원)"
    lines: list = []
    _emit_section_lines(
        "IS_C", [(table, unit, decl)],
        emit=lines.append, corp_code="TESTCORP", rcept_no=_RCEPT,
        report_fiscal_year=2020, report_fiscal_period="FY",
    )
    return lines


# ── ① EPS 이중 전사 ────────────────────────────────────────────────────
def test_eps_row_is_emitted_once_in_million_unit_table():
    """백만원 선언 표의 EPS 행은 **EPS 경로 1번만** 전사된다.

    실측 재현(삼성생명 20210310001045 연결IS 기본주당이익 7,049원): 수정 전에는
    `eps/`(7,049원)와 `IS_C/`(7,049,000,000원=×10⁶ 유령) 두 행이 같이 나왔다."""
    table = _fy_table([
        ["Ⅰ.영업수익", "34,534,340", "31,804,022", "32,240,885"],
        ["XIII.지배기업소유지분에대한 주당이익(단위: 원)", "", "", ""],
        ["기본주당이익", "7,049", "5,443", "9,268"],
    ])

    lines = _run_fy(table)

    eps = [l for l in lines if l.label_raw == "기본주당이익"]
    assert len(eps) == 3, [(l.source_ref, l.value_won) for l in eps]
    assert all(l.source_ref.startswith("eps/") for l in eps), \
        [l.source_ref for l in eps]
    assert {l.col_index: l.value_won for l in eps} == {0: 7_049, 1: 5_443, 2: 9_268}
    # 표 단위(백만원)를 물려받은 유령행이 없어야 한다.
    assert not [l for l in lines if l.label_raw == "기본주당이익" and l.adecimal == -6]


def test_eps_section_header_without_unit_declaration_still_dedups():
    """EPS 섹션 헤더가 **단위 선언을 안 달아도** 그 아래 행은 본류에서 빠진다.

    실측(00149947 20240814004158): 헤더가 `주당손익 (주32)` 뿐이라 '(단위: 원)' 증거가
    없고, 그래서 1차 수정에서 유령행이 그대로 남았다. 금액 없는 '주당' 행 = 그 표의
    EPS 섹션 헤더라는 **구조 신호**를 증거로 같이 인정한다."""
    table = _fy_table([
        ["Ⅰ.영업수익", "34,534,340", "31,804,022", "32,240,885"],
        ["주당손익 (주32)", "", "", ""],
        ["보통주 기본주당순손익", "1,163", "1,216", "1,102"],
    ])

    lines = _run_fy(table)

    eps = [l for l in lines if l.label_raw == "보통주 기본주당순손익"]
    assert eps, "EPS 행이 사라졌다"
    assert all(l.source_ref.startswith("eps/") for l in eps), [l.source_ref for l in eps]
    assert not [l for l in eps if l.adecimal == -6], "백만원 유령 중복행이 남았다"
    assert {l.col_index: l.value_won for l in eps} == {0: 1_163, 1: 1_216, 2: 1_102}


def test_non_eps_row_with_judang_substring_is_not_lost_from_main_path():
    """★이번 수정의 안전장치 — 원 단위 **선언이 없는** 백만원 표에서는 '주당' 부분문자열
    행을 본류에서 빼지 않는다.

    '지배주주당기순이익' = 지배+주주+당기순이익 — 우연히 '주당'이 생긴 총액 행이다(R27).
    백만원 표에서는 금액 크기로 진짜 EPS 와 구분할 수 없어서, 선언 증거 없이 본류에서
    빼면 이 총액이 통째로 사라진다. (EPS 경로가 이 행을 같이 담는 R27 잔여 중복은 이번
    수정 범위 밖 — 기존 동작 그대로 두고, **유실만** 막는다.)"""
    table = _fy_table([
        ["지배주주당기순이익", "1,088,065", "977,391", "1,265,766"],
    ])

    lines = _run_fy(table)

    main = [l for l in lines if l.label_raw == "지배주주당기순이익"
            and l.source_ref.startswith("IS_C/")]
    assert main, "NI귀속 총액이 본류에서 사라졌다"
    # 표 단위(백만원)가 적용된 총액이어야 한다.
    assert main[0].value_won == 1_088_065 * _MILLION


# ── ② EPS 열 밀림 ──────────────────────────────────────────────────────
def test_eps_blank_current_column_does_not_shift_prior_year_value():
    """당기 셀이 공란이면 **공란으로 남긴다** — 전기 값을 당기로 당기지 않는다.

    실측 재현(삼성물산 20160330002954 연결IS '중단사업 주당이익'): 원문 제52기(당기)=
    공란, 제51기(전기)=3,418, 제50기(전전기)=470. 수정 전엔 당기=3,418/전기=470 로
    한 칸씩 밀려 저장됐다. 그 표는 원(₩) 단위 선언이라 unit=1 로 재현한다."""
    table = _fy_table([
        ["주당손익", "", "", ""],
        ["기본주당순이익", "20,636", "4,284", "422"],
        ["중단사업 주당이익", "", "3,418", "470"],
    ])

    lines = _run_fy(table, unit=1)

    eps = {l.col_index: l.value_won for l in lines
           if l.label_raw == "중단사업 주당이익"}
    assert eps == {1: 3_418, 2: 470}, eps
    assert 0 not in eps, "당기(공란)에 값이 날조됐다"


def test_eps_uses_header_grid_when_available_for_interim_cumulative():
    """④ 반기 표에서 EPS 도 본류와 **같은 R88 헤더 그리드**로 누적열을 고른다.

    실측 재현(삼성생명 20230814002621 연결IS '1. 기본주당이익'): 헤더는 논리 4열
    [3개월|누적|3개월|누적]인데 데이터 행은 값마다 빈칸이 끼어 8칸이라, 헤더 위치로 만든
    `cum_map` 을 데이터 위치에 그대로 대면 한 칸씩 어긋나 **당3개월(1,489)이 당기**로,
    당기누적(5,425)이 전기로 담겼다. 당기=5,425 / 전기=3,512 여야 한다."""
    header = ("<THEAD>"
              "<TR><TD></TD><TD COLSPAN='4'>제 68(당)기 반기</TD>"
              "<TD COLSPAN='4'>제 67(전)기 반기</TD></TR>"
              "<TR><TD></TD><TD COLSPAN='2'>3 개 월</TD><TD COLSPAN='2'>누  적</TD>"
              "<TD COLSPAN='2'>3 개 월</TD><TD COLSPAN='2'>누  적</TD></TR>"
              "</THEAD>")
    body = ("<TR><TD>XIII.지배기업지분 주당이익(단위: 원)</TD>"
            + "<TD></TD>" * 8 + "</TR>"
            "<TR><TD>1. 기본주당이익</TD>"
            "<TD></TD><TD>1,489</TD><TD></TD><TD>5,425</TD>"
            "<TD></TD><TD>2,018</TD><TD></TD><TD>3,512</TD></TR>")
    table = etree.fromstring(f"<TABLE>{header}<TBODY>{body}</TBODY></TABLE>")

    lines: list = []
    _emit_section_lines(
        "IS_C", [(table, _MILLION, "(단위 : 백만원)")],
        emit=lines.append, corp_code="TESTCORP", rcept_no=_RCEPT,
        report_fiscal_year=2023, report_fiscal_period="H1",
    )

    eps = {l.col_index: l.value_won for l in lines
           if l.label_raw == "1. 기본주당이익"}
    assert eps == {0: 5_425, 1: 3_512}, eps


def test_eps_short_row_does_not_crash_header_grid_selection():
    """그리드 폭보다 **물리 셀이 모자란** EPS 행에서 터지지 않는다.

    `select_by_header_columns()` 는 `amounts[c.position]` 으로 바로 인덱싱하므로
    호출자가 그리드 폭까지 패딩해줘야 한다(본류는 `extract_rows(num_cols=…)` 가 해준다).
    실측: 20040330001459·20040601000173 에서 `IndexError: list index out of range`."""
    header = ("<THEAD><TR><TD></TD><TD>제 1(당)기</TD><TD>제 2(전)기</TD>"
              "<TD>제 3(전전)기</TD></TR></THEAD>")
    # EPS 행의 금액 셀이 1개뿐 — 헤더 그리드는 3열.
    body = ("<TR><TD>기본주당이익 (단위 : 원)</TD><TD>1,234</TD></TR>")
    table = etree.fromstring(f"<TABLE>{header}<TBODY>{body}</TBODY></TABLE>")

    lines: list = []
    _emit_section_lines(
        "IS_C", [(table, _MILLION, "(단위 : 백만원)")],
        emit=lines.append, corp_code="TESTCORP", rcept_no=_RCEPT,
        report_fiscal_year=2020, report_fiscal_period="FY",
    )

    eps = {l.col_index: l.value_won for l in lines
           if l.label_raw.startswith("기본주당이익")}
    assert eps == {0: 1_234}, eps


# ── ③ 셀 안 줄바꿈으로 쪼개진 숫자 ─────────────────────────────────────
def test_parse_amount_joins_number_split_by_linebreak():
    """개행은 나머지 공백과 같이 취급한다 — 한 숫자가 개행으로 쪼개진 원문 실측 패턴."""
    assert parse_amount("22,270,03\n9") == 22_270_039
    assert parse_amount("1,264,18\n1") == 1_264_181
    assert parse_amount("(102,6\n41\n)") == -102_641
    assert parse_amount("44,75\n4") == 44_754
    assert parse_amount("41,91\n2") == 41_912


def test_parse_amount_still_rejects_two_distinct_numbers_in_one_cell():
    """R1 가드 유지 — 서로 다른 **온전한** 숫자 둘이 한 셀에 있으면 결측(개행 구분 포함)."""
    assert parse_amount("723,570,750 723,570,751") is None
    assert parse_amount("723,570,750\n723,570,751") is None
    # 같은 값이 반복된 셀은 종전대로 하나로 취한다.
    assert parse_amount("723,570,750\n723,570,750") == 723_570_750


def test_linebreak_number_cell_is_not_dropped_from_amount_cells():
    """개행이 낀 금액 셀이 `amount_cells` 에서 빠지면 뒤 열이 당기 열로 밀린다.

    실측 재현(삼성생명 20210517001864 연결BS 'Ⅳ.기타금융부채'): 원문
    ['22,270,03\\n9', '21,335,183', '20,377,319'] — 수정 전엔 첫 칸이 통째로 빠져
    전기 값 21,335,183 이 당기 자리로 들어갔다."""
    table = _fy_table([
        ["Ⅳ.기타금융부채", "22,270,03\n9", "21,335,183", "20,377,319"],
    ])

    rows = extract_rows(table, multiplier=_MILLION, num_cols=3,
                        direct_only=True, skip_junk=False)

    assert len(rows) == 1, rows
    assert rows[0].amounts == [22_270_039 * _MILLION,
                               21_335_183 * _MILLION,
                               20_377_319 * _MILLION], rows[0].amounts
