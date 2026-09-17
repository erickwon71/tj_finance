"""Track C(PDF) 파서 단위 테스트 — 텍스트-리전 파싱(앵커·단위·컬럼·매핑).

실행: python -m fin2.tests.test_pdf
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.pdf import (  # noqa: E402
    parse_number, _find_anchors, _iter_data_lines, facts_from_text,
    _looks_multiline_bilingual, _iter_data_lines_multiline,
    _table_has_anchor_labels, _iter_data_lines_from_table_rows,
    _parse_single_line, _looks_like_real_amount, _parse_pdf_table_header,
    _lines_disagree_with_header,
)

# 모던 보고서 모사: 연결 BS(천원) + 연결 IS(천원, interim 3개월·누적) + 별도 BS.
_MODERN = """2. 연결재무제표
2-1. 연결 재무상태표
연결 재무상태표
제 50 기 1분기말 2026.03.31 현재
(단위 : 천원)
자산
유동자산 32,208,963 30,705,420
자산총계 56,659,594 53,953,669
부채총계 39,219,529 37,000,000
자본총계 17,440,065 16,953,669
2-2. 연결 손익계산서
연결 손익계산서
제 50 기 2026.01.01 ~ 2026.03.31
(단위 : 천원)
3개월 누적 3개월 누적
매출 5,000,000 5,000,000 4,800,000 4,800,000
영업이익 600,000 600,000 500,000 500,000
당기순이익 500,000 500,000 400,000 400,000
4. 재무제표
재무상태표
제 50 기 1분기말 2026.03.31 현재
(단위 : 천원)
자산총계 26,535,096 25,000,000
부채총계 17,268,806 16,000,000
자본총계 9,266,290 9,000,000
"""


def _facts():
    return facts_from_text(_MODERN, corp_code="00000000", rcept_no="r",
                           report_fiscal_year=2026, report_fiscal_period="Q1")


# ★2026-09-06 — 1999~2002년대 "3줄 이중언어" BS 레이아웃 모사(설계문서
# docs/plans/pdf_multiline_bilingual_layout_2026-09-06.md §원문레이아웃상세, 00163691
# 실측 기반). 한글라벨줄 / 숫자단독줄(열보존) / 영문번역줄이 항목마다 반복된다.
# 항등식(자산=부채+자본)이 두 기간 모두 성립하도록 값을 골랐다: 당기(col0)
# 1,367,881,896,679 = 600,000,000,000 + 767,881,896,679, 전기(col1)도 동일 항등식.
_LEGACY_MULTILINE = """대차대조표
제 30 기 2001.12.31 현재
(단위 : 원)
Ⅰ. 유동자산
(971,735,843,010) (851,037,426,728)
(Current Assets)
(1)당좌자산
931,031,052,669 (814,763,588,627)
(Quick Assets)
1. 현금및현금 등가물 (주석 2, 3)
436,850,563,946 232,352,148,393
(Cash and Cash Equivalents)
2. 단기금융상품
- 100,000,000
(Short-term Financial Instruments)
전자공시시스템 dart.fss.or.kr Page 66
자산
(Assets)
자산총계
1,367,881,896,679 1,065,801,015,121
(Total Assets)
부채총계
600,000,000,000 500,000,000,000
(Total Liabilities)
자본총계
767,881,896,679 565,801,015,121
(Total Equity)
"""


def test_parse_number():
    assert parse_number("1,234,567") == 1234567
    assert parse_number("(1,234)") == -1234
    assert parse_number("△500") == -500
    assert parse_number("") is None
    assert parse_number("주5,6") == 56  # 숫자만 — 라벨 분리는 호출측 책임


def test_anchors_detected_with_basis_and_unit():
    ancs = _find_anchors(_MODERN)
    kinds = [(a.statement, a.basis, a.unit) for a in ancs]
    assert ("BS", "consolidated", 1000) in kinds
    assert ("IS", "consolidated", 1000) in kinds
    assert ("BS", "separate", 1000) in kinds


def test_anchor_period_mark_accepts_hyphenated_subperiod():
    # 00102432 rcept 20000512000074 실측: "제 34-1 분기"(정정회차 포함 표기) — 기존
    # `제\s*\d+\s*기` 는 숫자 뒤 "-1"에서 끊겨 기간마커를 못 찾고, 그러면 `_find_anchors()`
    # 가 이 statement 제목을 목차/주석 언급으로 오판해 앵커 자체가 안 잡혔다.
    text = (
        "대 차 대 조 표\n"
        "제 34-1 분기 2000. 03. 31 현재\n"
        "자산총계 237,213,104,850\n"
        "부채총계 139,574,641,275\n"
        "자본총계 97,638,463,575\n"
    )
    ancs = _find_anchors(text)
    kinds = [(a.statement, a.basis) for a in ancs]
    assert ("BS", "separate") in kinds


def test_anchor_period_mark_accepts_parenthetical_current_prior_remark():
    # 00115694 rcept 20010214000346 실측: "제19(당)기"/"제18(전)기"(당기/전기 표시를
    # 괄호로 숫자와 "기" 사이에 끼워넣은 표기) — 위 하이픈 케이스와 마찬가지로 옛
    # regex는 숫자 바로 뒤에 "기"가 와야 해서 이것도 놓쳤다.
    text = (
        "대 차 대 조 표\n"
        "제19(당)기 분기 2000년 12월 31일 현재\n"
        "제18(전)기 분기 1999년 12월 31일 현재\n"
        "자 산 316,770,277,742 575,308,504,584\n"
    )
    ancs = _find_anchors(text)
    kinds = [(a.statement, a.basis) for a in ancs]
    assert ("BS", "separate") in kinds


def test_bs_unit_scaling_and_identity():
    facts = _facts()
    def won(canon, basis):
        m = [f.amount_won for f in facts if f.canonical_account == canon and f.basis == basis]
        return m[0] if m else None
    # 천원 → 원(×1000)
    assert won("bs.total_assets", "consolidated") == 56_659_594_000
    # 회계 항등식: 자산 = 부채 + 자본
    assert won("bs.total_assets", "consolidated") == \
        won("bs.total_liabilities", "consolidated") + won("bs.total_equity", "consolidated")
    # 별도도 추출
    assert won("bs.total_assets", "separate") == 26_535_096_000


def test_interim_cumulative_column_selected():
    # interim IS '3개월 누적' 2단 → 누적(2번째) 컬럼 채택. 여기선 3개월==누적이라 값 동일하나
    # 컬럼 인덱스 선택 로직이 첫 전기 컬럼(4,800,000)으로 새지 않는지 검증.
    facts = _facts()
    rev = [f.amount_won for f in facts if f.canonical_account == "is.revenue"]
    assert 5_000_000_000 in rev


def test_unmapped_label_stored_with_null_canon_not_skipped():
    # ★R137(2026-09-18) — 계정지도 미매핑 라벨은 canonical_account=None 으로만 남고
    # (섹션은 anc.statement 로 이미 확정돼 있으므로) facts 리스트에서 통째로 빠지지
    # 않는다(구 동작: continue 로 드롭 → report_lines 에 영영 안 실림).
    facts = facts_from_text(
        "재무상태표\n제 1 기 2020.12.31 현재\n(단위 : 원)\n"
        "자산총계 100\n부채총계 60\n자본총계 40\n알수없는계정 999\n",
        corp_code="c", rcept_no="r", report_fiscal_year=2020, report_fiscal_period="FY")
    canons = {f.canonical_account for f in facts}
    assert "bs.total_assets" in canons
    assert not any(c and c.startswith("unknown") for c in canons)
    unmapped = [f for f in facts if f.acode == "알수없는계정"]
    assert len(unmapped) == 1
    assert unmapped[0].canonical_account is None
    assert unmapped[0].statement == "BS"
    assert unmapped[0].amount_won == 999


def test_ascii_roman_numeral_subtotal_header_not_negative():
    # R74 트랙② 재조사(2026-09-06, 00198697 일진디스플 2000Q1 실측) — 같은 문서 안에서도
    # pdfplumber가 로마숫자를 "Ⅴ."(유니코드)와 "I."/"II."/"III."/"IV."(라틴 문자)로
    # 섞어 뽑아낸다. 라틴 로마숫자 헤더 + 단일 괄호값(=바로 아래 유일한 세부항목의 합계
    # 미리보기)이 괄호=음수로 오판정되면 안 된다.
    region = (
        "I. 자본금 (22,083,500,000)\n"
        "보통주자본금 22,083,500,000\n"
        "Ⅴ. 연결조정대 36,629,675,373\n"
    )
    lines = dict(_iter_data_lines(region))
    assert lines["I. 자본금"] == [22_083_500_000]
    assert lines["보통주자본금"] == [22_083_500_000]


# ★2026-09-06 — 00101488(rcept 20010814000979) 원문 dry-run 중 설계문서에 없던 3줄
# 레이아웃 변종 3개를 추가로 발견(3줄이 항상 엄격히 라벨/숫자/영문 순으로 분리돼
# 있지는 않다): ①"총계"류는 라벨+짧은영문+숫자가 전부 한 줄에 붙어 나옴, ②긴 영문
# 번역은 두 줄로 줄바꿈되며 진짜 숫자가 그 첫 영문줄 끝에 섞여 나옴, ③순수 섹션헤더가
# pdfplumber 오독으로 "0" 짜리 가짜 숫자줄을 달고 나옴(밑줄/구분선 추정).
_LEGACY_MULTILINE_2 = """대차대조표
제 29 기 반기 2001. 6. 30 현재
(단위 : 원)
자 산
(Assets)
Ⅰ. 유 동 자 산
72,229,874,575
(Current Assets)
4. 해 외 시 장 개척 준비금
(Appropriated Retained Earnings 622,000,000
for Overseas Market Development)
자 산 총 계 (Total Assets) 120,860,966,620
부 채
0
(Liabilities)
Ⅰ. 유 동 부 채
40,386,280,399
(Current Liabilities)
부 채 총 계
45,679,024,634
(Total Liabilities)
"""


def test_multiline_grand_total_label_glued_with_gloss_and_number():
    # "자 산 총 계 (Total Assets) 120,860,966,620" — 라벨+짧은영문+숫자가 한 줄에 붙음.
    # 영문 대역어를 떼지 않으면 account_mapper 가 "자산총계 (Total Assets)"를 못 알아봐
    # 헤드라인 항목이 통째로 결측된다(원문 대조로 발견).
    lines = dict(_iter_data_lines_multiline(_LEGACY_MULTILINE_2))
    assert lines["자 산 총 계"] == [120_860_966_620]
    assert "자 산 총 계 (Total Assets)" not in lines


def test_multiline_wrapped_english_embedded_number_column_preserved():
    # 긴 영문 번역이 두 줄로 줄바꿈되며 진짜 숫자가 첫 영문줄 끝에 붙어 나옴
    # ("(Appropriated Retained Earnings 622,000,000"). 앞쪽 영문 단어 토큰이 대시처럼
    # 결측 자리를 만들면(None) 뒤 실측값이 col0 이 아닌 다른 열로 밀린다 — 잡음은
    # 자리를 만들지 않고 버려야 col0 에 실제 값이 그대로 남는다.
    lines = dict(_iter_data_lines_multiline(_LEGACY_MULTILINE_2))
    assert lines["4. 해 외 시 장 개척 준비금"] == [622_000_000]


def test_multiline_all_zero_section_header_dropped():
    # "부 채\n0\n(Liabilities)" — pdfplumber 가 밑줄/구분선을 "0"으로 오독한 것으로
    # 추정되는 가짜 숫자줄. 실측 원문에서 이 라벨이 account_mapper 에 매핑되면
    # 진짜 "부채총계" 값과 경합하는 가짜 0원 후보가 생긴다 — 결측과 동일하게 스킵.
    lines = dict(_iter_data_lines_multiline(_LEGACY_MULTILINE_2))
    assert "부 채" not in lines


def test_multiline_gate_detects_3line_layout_only():
    # 3줄 레이아웃 리전만 게이트가 켜져야 한다 — 기존 정상(단일줄) 필링은 무영향.
    assert _looks_multiline_bilingual(_LEGACY_MULTILINE) is True
    modern_bs_region = _MODERN[:_MODERN.index("2-2. 연결 손익계산서")]
    assert _looks_multiline_bilingual(modern_bs_region) is False


def test_multiline_header_row_multivalue_parens_stripped():
    # "Ⅰ. 유동자산"은 두 값 모두 괄호(들쭉날쭉 아님), "(1)당좌자산"은 첫 값만 괄호 없음 —
    # 헤더 행이므로 실측대로 둘 다 양수(소계 미리보기, 진짜 음수 아님)로 풀려야 한다.
    lines = dict(_iter_data_lines_multiline(_LEGACY_MULTILINE))
    assert lines["Ⅰ. 유동자산"] == [971_735_843_010, 851_037_426_728]
    assert lines["(1)당좌자산"] == [931_031_052_669, 814_763_588_627]


def test_multiline_note_ref_label_paired_with_number_line():
    # 라벨줄에 붙은 각주참조("(주석 2, 3)")의 작은 숫자가 실제 데이터로 오인되지 않고,
    # 바로 다음 숫자단독줄과 정상 페어링돼야 한다(진짜 leaf 항목 — 헤더 아님, 괄호=음수 유지).
    lines = dict(_iter_data_lines_multiline(_LEGACY_MULTILINE))
    label = "1. 현금및현금 등가물 (주석 2, 3)"
    assert lines[label] == [436_850_563_946, 232_352_148_393]


def test_multiline_dash_placeholder_preserves_column_position():
    # "- 100,000,000" — col0(당기) 결측을 대시로, col1(전기)만 값. 왼쪽으로 채우면 안 되므로
    # col0 자리는 None으로 그대로 남아야 한다(값이 100,000,000으로 새면 컬럼압축 버그 재발).
    lines = dict(_iter_data_lines_multiline(_LEGACY_MULTILINE))
    assert lines["2. 단기금융상품"] == [None, 100_000_000]


def test_multiline_footer_noise_and_pure_section_header_skipped():
    lines = dict(_iter_data_lines_multiline(_LEGACY_MULTILINE))
    assert not any("전자공시시스템" in label for label in lines)
    assert "자산" not in lines  # 순수 섹션헤더(숫자줄 없음, "자산\n(Assets)") — 데이터 아님


def test_multiline_bs_end_to_end_identity():
    # facts_from_text 전체 경로 — 단위 원(×1) 스케일링 + 회계항등식(자산=부채+자본), 두 기간 모두.
    facts = facts_from_text(_LEGACY_MULTILINE, corp_code="00163691", rcept_no="r2001",
                            report_fiscal_year=2001, report_fiscal_period="FY")
    total_assets = [f.amount_won for f in facts if f.canonical_account == "bs.total_assets"]
    total_liab = [f.amount_won for f in facts if f.canonical_account == "bs.total_liabilities"]
    total_equity = [f.amount_won for f in facts if f.canonical_account == "bs.total_equity"]
    assert total_assets == [1_367_881_896_679]  # col0(당기)만 채택 — 단일 fact
    assert total_assets[0] == total_liab[0] + total_equity[0]


# 00116268 동성제약 rcept 20010813000395 실측 재현(단순화) — "자 산 총\n계"처럼 라벨이
# 숫자를 사이에 두고 줄바꿈돼 텍스트 스트림만으론 "자산총계" 문자열 자체가 안 잡힌다
# (_region_has_anchor_labels 가 이런 리전은 실측상 전부 거부 — BS 전체가 통째로 유실).
_WRAPPED_LABEL_TEXT = """대 차 대 조 표
제 45 기 반기 2001. 06. 30 현재
(단위 : 원)
자
산
Ⅰ.유동자산 300 200
자 산 총
300 200
계
부
채
Ⅰ.유동부채 100 80
부 채 총
100 80
계
자
본
Ⅰ.자본금 200 120
자 본 총
200 120
계
"""


class _FakePage:
    def __init__(self, rows: list[list[str]]):
        self._rows = rows

    def extract_tables(self):
        return [self._rows]


class _FakePdf:
    def __init__(self, pages: list[_FakePage]):
        self.pages = pages


# pdfplumber extract_tables() 가 실측(00116268)에서 실제로 돌려주는 모양 그대로 —
# 라벨 조각이 줄바꿈째로 한 셀에 합쳐지고, 같은 행에 숫자가 붙는다.
_WRAPPED_LABEL_TABLE_ROWS = [
    ["Ⅰ.유동자산", "300", "200"],
    ["자 산 총\n계", "300", "200"],
    ["Ⅰ.유동부채", "100", "80"],
    ["부 채 총\n계", "100", "80"],
    ["Ⅰ.자본금", "200", "120"],
    ["자 본 총\n계", "200", "120"],
]


def test_table_has_anchor_labels_reconstructs_wrapped_cell():
    assert _table_has_anchor_labels(_WRAPPED_LABEL_TABLE_ROWS, "BS")
    assert not _table_has_anchor_labels([["Ⅰ.유동자산", "300"]], "BS")


def test_iter_data_lines_from_table_rows_yields_full_reconstructed_label():
    lines = dict(_iter_data_lines_from_table_rows(_WRAPPED_LABEL_TABLE_ROWS))
    assert lines["자 산 총 계"] == [300, 200]
    assert lines["부 채 총 계"] == [100, 80]
    assert lines["자 본 총 계"] == [200, 120]


def test_table_fallback_recovers_wrapped_grand_totals_end_to_end():
    # pdf/page_bounds 없이(기존 텍스트 전용 경로)는 이 레이아웃에서 BS가 통째로
    # 결측이어야 한다 — 그래야 아래 표-폴백이 실제로 필요했다는 게 증명된다.
    facts_no_table = facts_from_text(
        _WRAPPED_LABEL_TEXT, corp_code="00116268", rcept_no="r2001",
        report_fiscal_year=2001, report_fiscal_period="H1")
    assert not any(f.canonical_account == "bs.total_assets" for f in facts_no_table)

    fake_pdf = _FakePdf([_FakePage(_WRAPPED_LABEL_TABLE_ROWS)])
    facts = facts_from_text(
        _WRAPPED_LABEL_TEXT, corp_code="00116268", rcept_no="r2001",
        report_fiscal_year=2001, report_fiscal_period="H1",
        pdf=fake_pdf, page_bounds=[(0, len(_WRAPPED_LABEL_TEXT))])

    def won(canon):
        m = [f.amount_won for f in facts if f.canonical_account == canon]
        return m[0] if m else None

    assert won("bs.total_assets") == 300
    assert won("bs.total_liabilities") == 100
    assert won("bs.total_equity") == 200
    assert won("bs.total_assets") == won("bs.total_liabilities") + won("bs.total_equity")


# ── 헤더 구조 우선 파싱 (2026-09-12, `docs/plans/pdf_header_aware_table_parsing_
#   redesign_2026-09-12.md`) — 솔트웨어 20220802000208 실측 회귀 ────────────────

from fin2.extract.pdf import (  # noqa: E402
    _looks_like_real_amount, _parse_pdf_table_header, _lines_disagree_with_header,
    extract_pdf_facts,
)


def test_looks_like_real_amount_accepts_proper_thousands_grouping():
    assert _looks_like_real_amount("2,351,294,869")
    assert _looks_like_real_amount("148")          # 콤마 없음 — 그대로 금액
    assert _looks_like_real_amount("(2,351,294,869)")
    assert _looks_like_real_amount("-2,351,294,869")


def test_looks_like_real_amount_rejects_note_ref_lists():
    """★거짓양성 회귀 — 솔트웨어 실측: "4,5,6"/"4,5,7,18" 같은 주석번호 나열은
    콤마 있는 숫자토큰 형태가 금액과 같아 보이지만, 자릿수 그룹이 불규칙(1~2자리)
    하다는 점으로 구분된다."""
    assert not _looks_like_real_amount("4,5,6")
    assert not _looks_like_real_amount("4,5,7,18")


# ── R136(2026-09-18) — 콤마 없는 단독 주석번호(has_note_col) ─────────────────
# 배경: `_looks_like_real_amount`는 콤마 없는 토큰을 항상 "진짜 금액"으로 본다
# (위 테스트가 이미 그 계약을 확정하고 있다: "148" 등). 그래서 라벨 바로 다음이
# 콤마 없는 단독 주석번호("14"/"9"/"10"/"11")인 행은 이 함수만으로는 못 거른다
# — 솔트웨어 20220802000208 원문대조로 실측(사용자 확인, 2026-09-17~18). XML
# 경로(`table_extractor.py` R19/R65)와 동형으로, "이 표가 주석열을 쓴다"고 이미
# 확인됐을 때만(`has_note_col`) 라벨 바로 다음 자리에 한해 콤마 없는 단독 숫자도
# 주석번호로 처리한다.

def test_parse_single_line_note_col_strips_bare_note_number():
    """실측 4건 재현 — 이연법인세부채/보통주자본금/주식발행초과금/미처분이익잉여금."""
    cases = [
        ("이연법인세부채    14    42,726,070    30,649,401",
         "이연법인세부채", [42726070, 30649401]),
        ("보통주자본금    9    648,200,000    648,200,000",
         "보통주자본금", [648200000, 648200000]),
        ("주식발행초과금    10    11,764,905,920    11,764,905,920",
         "주식발행초과금", [11764905920, 11764905920]),
        ("미처분이익잉여금    11    11,495,730    35,676,617",
         "미처분이익잉여금", [11495730, 35676617]),
    ]
    for line, label, nums in cases:
        assert _parse_single_line(line, has_note_col=True) == (label, nums)


def test_parse_single_line_note_col_false_keeps_old_broken_behavior():
    """has_note_col 기본값(False)은 회귀 없음 — 기존 호출자(테스트 포함) 그대로.
    이 "틀린" 결과 자체가 버그의 재현이며, 위 테스트가 고쳐진 동작을 확인한다."""
    label, nums = _parse_single_line("이연법인세부채    14    42,726,070    30,649,401")
    assert label == "이연법인세부채"
    assert nums == [14, 42726070, 30649401]


def test_parse_single_line_note_col_does_not_double_filter_comma_note_refs():
    """콤마 다중참조("4,5,8,16,17")는 has_note_col 값과 무관하게 이미
    `_looks_like_real_amount`가 걸러낸다 — 새 분기가 이를 중복 처리해 값까지
    같이 날리지 않는지 확인."""
    line = "전환사채    4,5,8,16,17    2,282,142,575    2,260,831,260"
    assert (_parse_single_line(line, has_note_col=True)
            == _parse_single_line(line, has_note_col=False)
            == ("전환사채", [2282142575, 2260831260]))


def test_parse_single_line_note_col_true_still_parses_normal_row_unaffected():
    """주석 컬럼이 없는(주석번호 자체가 없는) 정상 행은 has_note_col=True 여도
    그대로 파싱된다 — 새 분기가 라벨 바로 다음 자리를 무조건 지우는 게 아님을 확인."""
    line = "자산총계    14,954,294,161    14,939,210,092"
    assert (_parse_single_line(line, has_note_col=True)
            == ("자산총계", [14954294161, 14939210092]))


def test_iter_data_lines_end_to_end_with_has_note_col():
    """region 단위 종단 확인 — 솔트웨어 BS 표를 축약 재현."""
    region = (
        "재 무 상 태 표\n"
        "과 목 주석 제 4(당)반기말 제 3(전)기말\n"
        " I. 유동자산\n"
        "이연법인세부채    14    42,726,070    30,649,401\n"
        "전환사채    4,5,8,16,17    2,282,142,575    2,260,831,260\n"
    )
    lines = dict(_iter_data_lines(region, has_note_col=True))
    assert lines["이연법인세부채"] == [42726070, 30649401]
    assert lines["전환사채"] == [2282142575, 2260831260]


def test_parse_pdf_table_header_reads_period_columns():
    region = ("재 무 상 태 표\n제 4(당)반기말: 2022년 06월 30일 현재\n"
              "제 3(전)기말 : 2021년 12월 31일 현재\n미래에셋대우 (단위:원)\n"
              "과 목 주석 제 4(당)반기말 제 3(전)기말\n자 산\n")
    header = _parse_pdf_table_header(region)
    assert header is not None
    assert header.n_period_cols == 2
    assert header.has_note_col is True


def test_parse_pdf_table_header_none_when_no_multi_period_line():
    """단일 기간마커줄(제목 앵커 확인용)만 있고 진짜 컬럼헤더가 없으면 None —
    지어내지 않는다(R6)."""
    region = "손익계산서\n제 28 기 2020.01.01 ~ 2020.12.31\n(단위 : 원)\n매출 100\n"
    assert _parse_pdf_table_header(region) is None


def test_lines_disagree_with_header_flags_note_ref_contamination():
    from fin2.extract.pdf import PdfTableHeader
    header = PdfTableHeader(has_note_col=True, n_period_cols=2, period_labels=["a", "b"])
    ok_lines = [("유동자산", [100, 90])]
    bad_lines = [("현금및현금성자산", [456, 100, 90])]  # 주석번호가 안 걸러진 경우 흉내
    assert not _lines_disagree_with_header(ok_lines, header)
    assert _lines_disagree_with_header(bad_lines, header)


def test_half_year_report_title_now_anchors_correctly():
    """★거짓양성 회귀 — 솔트웨어 실측: "제4(당)반기"("반"이 "기" 앞에 낌)는 예전
    `_PERIOD_MARK_RE`로 앵커 확정을 못 받았다. 이 갭 때문에 포괄손익계산서·현금흐름표
    앵커가 아예 안 잡혀, BS 리전이 다음 anchor 없이 문서 끝까지 뻗어나가 다른 표까지
    섞였다. 반기보고서 title 뒤에 오는 "제N(당)반기" 형태가 이제 정상 앵커로 잡히는지
    직접 확인."""
    text = (
        "재무상태표\n제 4(당)반기말: 2022년 06월 30일 현재\n제 3(전)기말 : 2021년"
        " 12월 31일 현재\n(단위:원)\n"
        "과 목 제 4(당)반기말 제 3(전)기말\n"
        "자산총계 14,954,294,161 14,939,210,092\n"
        "부채총계 2,363,475,864 2,324,210,908\n"
        "자본총계 12,590,818,297 12,614,999,184\n"
        "현금흐름표\n제4(당)반기 : 2022년 01월 01일부터 2022년 06월 30일까지\n(단위:원)\n"
        "영업활동으로인한현금흐름 52,636,847 40,000,000\n"
        "투자활동으로인한현금흐름 1 1\n재무활동으로인한현금흐름 1 1\n"
    )
    facts = facts_from_text(
        text, corp_code="01390399", rcept_no="r2022h1",
        report_fiscal_year=2022, report_fiscal_period="H1")
    # ★R137(2026-09-18) — canonical_account 는 매핑 실패 시 None 일 수 있으므로(저장은
    # 막지 않음), 소속 재무제표 판정은 anchor 가 직접 채운 .statement 로 확인한다.
    stmts = {f.statement for f in facts}
    assert "CF" in stmts, "현금흐름표 앵커가 안 잡혀 CF 사실이 하나도 없음(회귀)"
    bs_labels = {f.acode for f in facts if f.statement == "BS"}
    assert "영업활동으로인한현금흐름" not in bs_labels, (
        "CF 앵커 부재로 BS 리전이 CF 까지 삼켜 오염됐다(회귀)")


def test_parse_pdf_table_header_doubles_for_3month_cumulative_subheader():
    """★2026-09-12(솔트웨어 IS 실측, 사용자 질문 "손익계산서는 왜 누락되었나?"로 발견) —
    기간마커줄엔 기간당 1번("제4(당) 반기")만 찍히지만 바로 아래 서브헤더줄에서
    "3개월/누적" 둘로 갈라진다. 이걸 배로 세지 않으면 실제 4컬럼 데이터줄이 헤더선언
    (2컬럼)보다 많다고 오판돼 R93 최종필터가 정상 IS 데이터를 통째로 버린다."""
    region = (
        "포 괄 손 익 계 산 서\n제4(당)반기 : ...\n제3(전)반기 : ...\n(단위:원)\n"
        "제4(당) 반기 제3(전) 반기\n과 목 주 석\n3개월 누적 3개월 누적\n"
        "I. 영업수익 - - - -\n"
    )
    header = _parse_pdf_table_header(region)
    assert header is not None
    assert header.n_period_cols == 4, "3개월/누적 서브헤더로 실제 컬럼수가 배가돼야 함"


def test_parse_pdf_table_header_no_doubling_without_subheader():
    """3개월/누적 서브헤더가 없는 보통 CF 헤더는 그대로 2컬럼 — 위 배가 로직이
    무관한 표에 오발동하지 않는지 회귀."""
    region = (
        "현 금 흐 름 표\n제4(당)반기 : ...\n제3(전)반기 : ...\n(단위:원)\n"
        "과 목 주 석 제4(당)반기 제3(전)반기\n"
        "I. 영업활동으로 인한 현금흐름 (52,636,847) (8,122,944)\n"
    )
    header = _parse_pdf_table_header(region)
    assert header is not None
    assert header.n_period_cols == 2


def test_anchor_labels_accept_loss_wording_for_is():
    """★2026-09-12(사용자 지시 "BS/IS/CF 무조건 3개 다 있어야 하는데 없는 경우
    조사해봐"로 발견) — 적자 회사(영업손실/당기순손실 워딩)의 진짜 IS 본문표가
    흑자전용 화이트리스트 때문에 게이트를 못 넘어 통째로 스킵되던 회귀."""
    from fin2.extract.pdf import _region_has_anchor_labels
    loss_region = (
        "I. 영업수익 - - - -\n"
        "III. 영업손실 (17,022,570) (68,052,797)\n"
        "VIII. 당기순손실 18,178,691 (24,180,887)\n"
    )
    assert _region_has_anchor_labels(loss_region, "IS"), (
        "영업손실/당기순손실만 있어도 IS 앵커 라벨 게이트를 통과해야 함")


def test_parse_numline_tokens_strips_parens_only_for_bs():
    """★2026-09-12(솔트웨어 IS/CF 실측) — 로마숫자 헤더행 "괄호=미리보기(양수)" 관례는
    pre-2015 K-GAAP BS 전용이다. IS/CF 의 로마숫자 라벨(Ⅲ.영업손실, Ⅰ.영업활동으로
    인한 현금흐름)에 같은 관례를 적용하면 진짜 음수(적자/현금유출)의 부호가 사라진다
    — statement 를 명시하지 않으면(기존 BS 전용 호출부 하위호환) 계속 벗기고,
    IS/CF 로 명시하면 괄호를 진짜 음수로 파싱해야 한다."""
    from fin2.extract.pdf import _parse_numline_tokens
    assert _parse_numline_tokens("III. 영업손실", ["(68,052,797)"], "BS") == [68052797]
    assert _parse_numline_tokens("III. 영업손실", ["(68,052,797)"], "IS") == [-68052797]
    assert _parse_numline_tokens("I. 영업활동으로 인한 현금흐름", ["(52,636,847)"], "CF") == [-52636847]
    # 기존 BS 전용 호출부(기본값)는 그대로 벗겨야 함(하위호환, 회귀 없음).
    assert _parse_numline_tokens("I. 유동자산", ["(45,700,051)"]) == [45700051]


def test_saltware_real_pdf_end_to_end():
    """실제 사고 파일 종단 확인(파일 없으면 스킵). 별도 BS 17행이 내부 정합
    (자산총계=부채총계+자본총계)하고, CF 항목이 더는 BS 로 안 새는지 확인.

    ★2026-09-12 후속(사용자 "손익계산서는 왜 누락되었나?" 질문으로 발견) — 이 회사는
    적자(영업손실/당기순손실)라 IS 는 원래 완전히 0행이었다(3개 원인: ①헤더 서브컬럼
    "3개월/누적" 미인식으로 헤더선언 컬럼수 과소산정, ②`_ANCHOR_LABELS["IS"]`가 흑자
    워딩만 있어 게이트 미통과, ③격자폴백에서 BS 전용 "로마숫자헤더=괄호는 미리보기(양수)"
    관례가 IS 로마숫자 손실계정에도 적용돼 부호소실). 세 개 다 고친 뒤 IS 7행 + 올바른
    부호(적자는 음수)까지 확인 — 그냥 "행이 있다"만 보면 부호소실 회귀를 못 잡는다."""
    path = Path("/private/tmp/claude-501/-Users-taejin-Project-tj-finance/"
                "1077c697-af9a-4a13-ba1c-ef1de6f6e281/scratchpad/"
                "saltware_20220802000208.pdf")
    if not path.exists():
        return
    facts = extract_pdf_facts(
        path, corp_code="01390399", rcept_no="20220802000208",
        report_fiscal_year=2022, report_fiscal_period="H1")
    bs = {f.canonical_account: f.amount_won for f in facts
          if f.canonical_account.startswith("bs.") and f.basis == "separate"}
    assert bs.get("bs.total_assets") == bs.get("bs.total_liabilities", 0) + bs.get(
        "bs.total_equity", 0)
    cf_labels = {f.acode for f in facts if f.canonical_account.startswith("cf.")}
    assert "기초의현금및현금성자산" in cf_labels, "CF 앵커가 잡혀 별도 basis 로 나와야 함"

    is_sep = {f.canonical_account: f.amount_won for f in facts
              if f.canonical_account and f.canonical_account.startswith("is.")
              and f.basis == "separate"}
    assert is_sep.get("is.operating_income") == -68_052_797, "적자 영업손실이 음수로 저장돼야 함"
    assert is_sep.get("is.net_income") == -24_180_887, "당기순손실이 음수로 저장돼야 함"
    # EBT 항등식(누적 6개월): 영업손실 + 금융수익 - 금융원가 = 세전손실
    assert is_sep["is.operating_income"] + is_sep["is.finance_income"] - \
        is_sep["is.finance_cost"] == is_sep["is.ebt"]

    cf_sep = {f.acode: f.amount_won for f in facts
              if f.canonical_account and f.canonical_account.startswith("cf.")
              and f.basis == "separate"}
    # ★같은 부호소실 버그가 CF 의 로마숫자 라벨("Ⅰ.영업활동으로 인한 현금흐름")에도 걸려
    # 있었다 — IS 를 고치며 같이 드러난 latent 버그, CF 항등식으로 회귀 고정.
    assert cf_sep.get("영업활동으로인한현금흐름") == -52_636_847
    assert cf_sep["기초의현금및현금성자산"] + cf_sep["현금의증가"] == \
        cf_sep["반기말의현금및현금성자산"]


# ★R137(2026-09-18, 솔트웨어 CF separate 실측) — 문서에서 가장 마지막 앵커(다음 앵커가
# 없어 리전이 `len(text)`까지 뻗어나가는 경우)가 그 뒤 주석(note) 섹션 전체를 통째로
# 삼키는 결함. 계정지도 매핑 실패 게이트가 이 노이즈를 우연히 걸러주던 게 없어지면서
# (R137 canon/storage 분리) 노출됐다.
_CF_WITH_TRAILING_NOTES = """현금흐름표
제 1 기 2020.01.01 ~ 2020.12.31
(단위 : 원)
영업활동으로 인한 현금흐름 100,000,000
투자활동으로 인한 현금흐름 -50,000,000
재무활동으로 인한 현금흐름 -20,000,000
별첨 주석은 본 재무제표의 일부입니다.
재무제표 주석
1. 일반사항
주주명 주식수 지분율
기타 6,182,000 95.37
합 계 6,482,000 100.0
"""


def test_header_note_column_detected_with_letter_spaced_label():
    # ★R137(2026-09-18, 솔트웨어 CF separate "나"/"다" 세부항목 실측) — 헤더가
    # "주 석"처럼 자간공백을 넣어 렌더링돼도 has_note_col=True 로 잡혀야 한다
    # (구 정규식은 "주석"이 붙어있어야만 매치해 이 변형을 놓쳤다).
    header = _parse_pdf_table_header(
        "과 목 주 석 제4(당)반기 제3(전)반기\n"
        "I. 영업활동으로 인한 현금흐름 (52,636,847) (8,122,944)\n")
    assert header is not None
    assert header.has_note_col is True


def test_last_anchor_region_clamped_at_notes_section_boundary():
    facts = facts_from_text(
        _CF_WITH_TRAILING_NOTES, corp_code="c", rcept_no="r",
        report_fiscal_year=2020, report_fiscal_period="FY")
    labels = {f.acode for f in facts}
    assert "기타" not in labels
    assert "합계" not in labels
    assert any("영업활동" in lab for lab in labels)


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
