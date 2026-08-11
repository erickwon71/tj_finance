"""`parse_amount` 부호 판정 회귀 테스트 (합성 셀텍스트, DB 비의존).

배경 — pre-2015 파일럿 백필(2026-08-10) BS 항등식(자산=부채+자본) 검증 중 발견: 일부
K-GAAP filer(실측 KG케미칼 2003~2008 반기/분기)는 음수를 표준 괄호랩("(1,234)")이 아니라
**"(-)1,234"**(괄호+명시 마이너스 이중접두) 로 표기한다. 이 형태를 `parse_amount` 가
못 읽고 `None`(파싱실패)을 반환하면, 호출측(`fin2/extract/report_lines.py::
_emit_section_lines`)의 컬럼압축 로직("앞쪽 None = 과거 미보고 기간"가정)이 오작동해
**전기 값이 당기 열로 밀려 들어간다** — 결측이 아니라 틀린 값이 조용히 DB 에 들어가는
쪽이라 결측보다 나쁘다. 연도 무관 공용 코드(`parser/common/amount_normalizer.py`)의
사각지대라 2015+ 에도 이론상 영향권.

실행: python -m pytest fin2/tests/test_amount_normalizer_parse.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.common.amount_normalizer import parse_amount  # noqa: E402
from parser.xml.table_extractor import _NUMBER_PATTERN, _split_label_amounts  # noqa: E402


def test_paren_dash_prefix_is_negative():
    """★핵심 회귀 — '(-)N' 이중접두를 음수로 정확히 읽는다(원인 규명된 실측 표기)."""
    assert parse_amount("(-)6,940,244,498") == -6_940_244_498
    assert parse_amount("(-)1,234") == -1234


def test_paren_dash_prefix_with_unit_multiplier():
    assert parse_amount("(-)1,234", multiplier=1000) == -1_234_000


def test_standard_paren_wrap_still_negative():
    """기존 표준 괄호랩("(N)")은 그대로 유지된다(회귀 없음)."""
    assert parse_amount("(1,234)") == -1234


def test_leading_minus_still_negative():
    assert parse_amount("-1,234") == -1234


def test_circled_dash_marks_still_negative():
    assert parse_amount("△1,234") == -1234
    assert parse_amount("▲1,234") == -1234


def test_positive_unaffected():
    assert parse_amount("1,234") == 1234
    assert parse_amount("6,940,244,498") == 6_940_244_498


def test_blank_and_unparseable_still_none():
    assert parse_amount("") is None
    assert parse_amount("-") is None
    assert parse_amount(None) is None


# ── table_extractor 쪽 게이트 — parse_amount 만 고치면 부족했던 이유 ───────────
# `_split_label_amounts`(표 한 행을 [라벨, 금액셀…]로 분리)는 `_NUMBER_PATTERN`으로 "이 셀이
# 금액인가"를 먼저 판정하고, 통과 못 하면 `parse_amount`까지 가지도 못한 채 그냥 버려진다
# (amount_cells 에 안 들어감 → 그 열 자체가 없는 셈이 돼 뒤 열이 앞으로 당겨짐). "(-)N" 은
# 이 게이트에서도 넓혀야 실제로 값이 산다 — parse_amount 만 고치고 여기를 안 고치면 회귀
# 테스트는 통과해도 실제 표 추출 경로에선 여전히 셀이 사라진다(2026-08-10 파일럿 재검증 중
# 발견 — parse_amount 만 고친 1차 수정으로는 DB 값이 그대로였다).

def test_number_pattern_accepts_paren_dash_prefix():
    assert _NUMBER_PATTERN.match("(-)6940244498")


def test_split_label_amounts_keeps_paren_dash_cell():
    cells = ["자본총계", "(-)6,940,244,498", "1,718,661,826", "4,658,998,809"]
    label, amounts = _split_label_amounts(cells)
    assert label == "자본총계"
    assert amounts == ["(-)6,940,244,498", "1,718,661,826", "4,658,998,809"]
    assert [parse_amount(a) for a in amounts] == [-6_940_244_498, 1_718_661_826, 4_658_998_809]
