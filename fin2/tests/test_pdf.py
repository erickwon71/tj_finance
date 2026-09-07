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


def test_unmapped_label_skipped():
    facts = facts_from_text(
        "재무상태표\n제 1 기 2020.12.31 현재\n(단위 : 원)\n"
        "자산총계 100\n부채총계 60\n자본총계 40\n알수없는계정 999\n",
        corp_code="c", rcept_no="r", report_fiscal_year=2020, report_fiscal_period="FY")
    canons = {f.canonical_account for f in facts}
    assert "bs.total_assets" in canons
    assert not any(c and c.startswith("unknown") for c in canons)


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
