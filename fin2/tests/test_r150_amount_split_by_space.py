"""R150(2026-09-20) 회귀 테스트 — 천단위 콤마 **바로 뒤**에서 공백으로 쪼개진 금액
(`'4,244, 863'`)을 못 읽어 재무상태표 행이 통째로 유실되던 결함.

`parse_amount()` 의 R1 가드는 "한 셀에 온전한 숫자가 둘 이상이면 어느 것이 그 셀
값인지 원문이 말하지 않으므로 결측"으로 처리한다(날조 방지). 그런데 `'4,244,'` 는
온전한 숫자가 아니라 **조각**이다 — 콤마로 끝나기 때문이다. R1 이 이걸 두 값으로 보고
None 을 돌려줘서, BS 는 당기만 적재하므로 그 행이 사라졌다.

실측: 신한지주 20150515002196 [연결] 재무상태표 — `'Ⅸ.무형자산'` 4,244,863(백만원,
= 4.24조)과 `'XIV.기타자산'` 18,245,860(= 18.2조) 두 행이 통째로 결측이었다. 적재된
라벨이 `Ⅷ.유형자산` 다음 `Ⅹ.관계기업에 대한 투자자산` 으로 건너뛴 것이 증거다.
`fin2/audit/row_coverage.py`(행 단위 결측 탐지기)가 잡아낸 첫 실제 결함.

실행: pytest fin2/tests/test_r150_amount_split_by_space.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.report_lines import extract_report_lines      # noqa: E402
from parser.common.amount_normalizer import parse_amount        # noqa: E402

_SHINHAN_2015Q1 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00382199_신한지주/quarter/2015/20150515002196.xml"
)


def test_number_split_right_after_a_thousands_comma_is_rejoined():
    """콤마로 끝나는 토큰은 조각이므로 이어붙인다."""
    assert parse_amount("4,244, 863", 1) == 4_244_863
    assert parse_amount("18,245, 860", 1) == 18_245_860
    assert parse_amount("12, 345", 1) == 12_345
    assert parse_amount("1,234, 567, 890", 1) == 1_234_567_890


def test_two_whole_numbers_in_one_cell_are_still_missing():
    """★R1 가드는 그대로 살아 있어야 한다 — 콤마로 끝나지 않는 **온전한 숫자 둘**은
    어느 것이 그 셀 값인지 원문이 말하지 않으므로 결측이다(짐작 금지)."""
    assert parse_amount("1,234 5,678", 1) is None
    assert parse_amount("- -", 1) is None


def test_note_reference_lists_are_not_fabricated_into_amounts():
    """★가장 위험한 오작동 — 주석번호 목록 `'4, 27, 30'` 을 42,730 으로 날조하면 안 된다.

    실측: 한국금융지주 20150515002047 [연결] BS 는 주석 열에 `'4, 27, 30'`·`'15, 30'`
    처럼 번호를 쉼표로 나열한다(스코프 스캔에서 25칸 발견). 3자리 그룹이 아니라
    이어붙이지 않고, 기존 R1 가드(온전한 숫자 둘 이상 → 결측)가 받는다.
    """
    assert parse_amount("4, 27, 30", 1) is None
    assert parse_amount("5, 27, 30", 1) is None
    assert parse_amount("15, 30", 1) is None


def test_rejoin_does_not_swallow_non_numeric_tails():
    """뒤 토큰이 숫자가 아니면 이어붙이지 않는다(기간 표기 등)."""
    assert parse_amount("4,244, 개월", 1) is None
    assert parse_amount("4,244, abc", 1) is None


def test_rejoin_still_respects_the_digit_count_sanity_guard():
    """이어붙여서 자릿수가 폭발하는 것(두 금액이 실제로 이어붙은 경우)은 여전히 결측 —
    R2 의 `_AMOUNT_SANE_MAX` 가드가 그대로 작동해야 날조를 막는다."""
    assert parse_amount("316,305268, 96147,344", 1) is None


def test_shinhan_2015q1_balance_sheet_rows_recovered():
    """결측됐던 [연결] 무형자산·기타자산 행이 원문값 그대로 복원된다."""
    if not _SHINHAN_2015Q1.exists():
        return
    lines = extract_report_lines(
        _SHINHAN_2015Q1, rcept_no="20150515002196", corp_code="00382199",
        report_fiscal_year=2015, report_fiscal_period="Q1")
    got = {(l.basis, l.label_raw): l.value_won
           for l in lines if l.statement == "BS" and l.col_index == 0}
    # 표 단위 선언이 백만원이므로 원 단위로는 ×10⁶.
    assert got[("consolidated", "Ⅸ.무형자산")] == 4_244_863_000_000
    assert got[("consolidated", "XIV.기타자산")] == 18_245_860_000_000
    # 원문 라벨 순서대로 이웃 행이 그대로 남아 있는지(가산적 수정인지) 확인.
    assert got[("consolidated", "Ⅷ.유형자산")] == 3_114_557_000_000
