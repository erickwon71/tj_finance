"""R31(T22) 회귀 테스트 — `_NUMBER_PATTERN`이 괄호 없는 순수 하이픈 음수("-N")를
"숫자 아님"으로 오판해 셀을 통째로 드롭하던 결함.

`docs/plans/t22_hyphen_negative_gate_todo_2026-08-16.md` Phase 3, `docs/PARSING_RULES.md` R31.
T21("(-)N" 이중마커)의 자매결함 — T21과 반대 방향: `parse_amount`는 이미 순수 "-N"을 정상
음수 처리했다(`amount_normalizer.py`) — 게이트(`_NUMBER_PATTERN`)만의 결함이었다.

실행: python -m pytest fin2/tests/test_hyphen_negative_gate_r31.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.common.amount_normalizer import parse_amount  # noqa: E402
from parser.xml.table_extractor import _NUMBER_PATTERN, _split_label_amounts  # noqa: E402
import parser.xml.table_extractor as te  # noqa: E402
import fin2.extract.report_lines as rl  # noqa: E402


# ── 3-1. _NUMBER_PATTERN 자체 ────────────────────────────────────────────────

def test_number_pattern_accepts_bare_hyphen_negative():
    assert _NUMBER_PATTERN.match("-466274")
    assert _NUMBER_PATTERN.search("-466,274")


# ── 3-2. _split_label_amounts — 8칸 전부 보존(실측 20031114000665 그대로) ───────

def test_split_label_amounts_keeps_all_hyphen_negative_cells():
    """원문 실측(20031114000665, IS 'ⅩⅢ. 분기순이익…' 행) 금액 TD 8칸 — 수정 전엔
    '-466,274'·'-493,768' 두 칸이 통째로 드롭돼 6칸으로 줄었다(§1 근거)."""
    cells = ["라벨", "", "-466,274", "", "3,616,480", "", "-493,768", "", "4,278,634"]
    label, amounts = _split_label_amounts(cells)
    assert label == "라벨"
    assert amounts == ["", "-466,274", "", "3,616,480", "", "-493,768", "", "4,278,634"]
    assert len(amounts) == 8


# ── 3-3. parse_amount 부호 왕복 — T21과 달리 이쪽은 원래도 정상이었다 ────────────

def test_parse_amount_bare_hyphen_negative_roundtrip():
    assert parse_amount("-466,274") == -466274
    assert parse_amount("-466,274", multiplier=1000) == -466_274_000


# ── 3-4. 회귀 가드 — 기존 동작 불변 ───────────────────────────────────────────

def test_dash_alone_still_blank_marker():
    """대시 한 글자는 여전히 공란 취급(공란 마커 의미 보존, Phase 2-4)."""
    assert _NUMBER_PATTERN.match("-")
    label, amounts = _split_label_amounts(["라벨", "-", "1,234"])
    assert amounts == ["-", "1,234"]
    assert [parse_amount(a) for a in amounts] == [None, 1234]


def test_leading_dash_label_text_is_not_amount():
    """'- 유동자산'처럼 뒤에 숫자가 아닌 텍스트가 오면 여전히 금액 아님."""
    assert not _NUMBER_PATTERN.match("-유동자산")


def test_other_negative_forms_unaffected():
    """괄호음수 / (-)N / △ / ▲ / 양수 — 기존 동작 그대로."""
    assert _NUMBER_PATTERN.match("(1,234)")
    assert _NUMBER_PATTERN.match("(-)1,234")
    assert _NUMBER_PATTERN.match("△1,234")
    assert _NUMBER_PATTERN.match("▲1,234")
    assert _NUMBER_PATTERN.match("1,234")


# ── 3-5. 밀림 재현 — 실측 파일, 수정 전(원래 패턴)/후(현재 패턴) 산출을 같은 테스트에서
#    직접 비교한다. "전" 재현은 R31 이전 원본 `_NUMBER_PATTERN` 소스를 그대로 복사해 임시
#    monkeypatch — 실제 프로덕션 함수(`extract_report_lines`)를 그대로 태운다(합성 아님).
# ────────────────────────────────────────────────────────────────────────────

_PRE_R31_PATTERN_SRC = (
    r'^[\s\-\─\—\―]$|'
    r'^\([\d,]+\.?\d*\)$|'
    r'^\(-\)[\d,]+\.?\d*$|'
    r'^[\d,]+\.?\d*$|'
    r'^△[\d,]+\.?\d*$|'
    r'^▲[\d,]+\.?\d*$'
)
_PRE_R31_PATTERN = re.compile(_PRE_R31_PATTERN_SRC)

_XML = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00132725_SB성보/quarter/2003/20031114000665.xml"
)


def _extract(rcept="20031114000665", corp="00132725", fy=2003, period="Q3"):
    return rl.extract_report_lines(
        _XML, rcept_no=rcept, corp_code=corp,
        report_fiscal_year=fy, report_fiscal_period=period, include_notes=False)


def test_cum_map_misalignment_fixed_by_gate_widening():
    """★핵심 회귀 — 실측(20031114000665) IS 'ⅩⅢ. 분기순이익…' 행(당기순이익 컬럼).

    수정 전(R31 이전 패턴): 하이픈 음수 셀 2개가 드롭돼 배열이 밀리고, interim 2단헤더
    cum_map 이 헤더 위치 기준이라 어긋난 자리를 가리켜 **전기(42기) 누적값 4,278,634가
    당기(col_index=1) 자리로 오emit** — 진짜 당기 누적 -466,274 은 아예 안 나온다(결측이
    아니라 틀린 값이 조용히 나온다는 게 문제).
    수정 후(R31): 밀림이 없어 진짜 당기 -466,274 / 전기 3,616,480 이 각각 맞는 컬럼으로 나온다.
    """
    if not _XML.exists():
        return  # 실측 파일 없는 환경(SD카드 미마운트 등) — 스킵, DB 비의존 테스트는 위에서 이미 커버

    label_head = "ⅩⅢ"

    te._NUMBER_PATTERN = _PRE_R31_PATTERN  # 임시로 R31 이전 상태로 되돌림
    rl._NUMBER_PATTERN = _PRE_R31_PATTERN
    try:
        before = _extract()
    finally:
        te._NUMBER_PATTERN = _NUMBER_PATTERN  # 실제 소스(R31 반영본)로 복원
        rl._NUMBER_PATTERN = _NUMBER_PATTERN

    after = _extract()

    def col_map(lines):
        return {ln.col_index: ln.value_won for ln in lines
                if ln.statement == "IS" and ln.basis == "separate"
                and (ln.label_raw or "").startswith(label_head)}

    before_map = col_map(before)
    after_map = col_map(after)

    # 수정 전(R31 이전 NUMBER_PATTERN) — 오답: col0(당기)이 살아남지 못한다.
    # ★2026-08-24: `_split_label_amounts()`에 Gate B 버그① 근본수정(주석컬럼 빈칸도 항상
    # 소비, `gateb_bugA_col_misselect_optionA_rootfix_plan_2026-08-24.md` §3-4)이 들어가며
    # 이 "before" 재현값도 같이 바뀌었다 — 이 표에 주석컬럼이 있어(다른 행의 콤마 다중참조로
    # table_has_note_column=True) 그 수정이 R31 패치 여부와 무관하게 항상 적용되기 때문.
    # "before"는 R31 하나만 되돌린 가상 상태가 아니라 "R31 + 이 수정 둘 다 없던 상태"의
    # 근사가 아니라는 뜻 — 실제 회귀 방지 목적(당기 col0 값)은 아래 after_map 이 핵심이다.
    assert before_map == {0: 3616480000}, before_map
    # 수정 후 — 정답: 당기(col0)가 살아나고, 전기(col1)도 올바른 값으로 바로잡힌다.
    assert after_map == {0: -466274000, 1: 3616480000}, after_map
    # ★적재 영향 — col_index=0 만 DB 로 간다(_is_loadable).
    # 2026-08-24 이전엔 이 행이 DB에 전혀 없었다(T1 그룹A 잔여13건 중 하나, col0 자체가
    # 없어 결측으로 남음). 2026-08-24 노트컬럼 수정 이후의 "before"(R31만 되돌린 가상
    # 상태)는 col0 이 **존재하되 틀린 값**(3,616,480,000 — 실제로는 전기 값)으로 나온다 —
    # "결측"에서 "오염된 값"으로 실패 양상이 바뀐 것뿐, R31(당기 실값 -466,274,000 을
    # 되살리는 것)이 여전히 필요하다는 결론은 그대로다. 아래 after_map 이 핵심 회귀 가드.
    assert before_map[0] != -466274000
    assert after_map[0] == -466274000


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
