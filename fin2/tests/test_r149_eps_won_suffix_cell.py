"""R149(2026-09-20) 회귀 테스트 — 셀이 스스로 원 단위를 밝힌 `'2,564원'` 표기를
`parse_amount()` 가 못 읽어 **EPS 행이 통째로 결측**되던 결함.

금융지주 손익계산서는 표 전체를 `(단위: 백만원)` 으로 선언하면서 주당이익 행만 원
단위로 인쇄한다 — 그 행 셀이 `'2,564원'` 으로 와서 숫자로 파싱되지 않았고, EPS 경로와
본류 양쪽이 "금액 0개"로 보고 행을 버렸다. 실측: 신한지주 20220516002487(2022Q1)
[별도] `기본 및 희석주당이익` 2,564원 · [연결] `기본주당순이익` 2,552원(캠페인
원문전체대조 이슈#16). 전사 스코프 324건/19개사.

핵심은 **표의 배수를 이 셀에 적용하지 않는 것**이다 — 누르지 않으면 2,564 × 10⁶
이라는 날조가 된다.

실행: pytest fin2/tests/test_r149_eps_won_suffix_cell.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.report_lines import extract_report_lines      # noqa: E402
from parser.common.amount_normalizer import parse_amount        # noqa: E402

_SHINHAN_2022Q1 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00382199_신한지주/quarter/2022/20220516002487.xml"
)


def test_cell_declaring_its_own_won_unit_ignores_table_multiplier():
    """'2,564원' = 2,564원. 표가 백만원 선언이어도 이 셀엔 배수를 적용하지 않는다."""
    assert parse_amount("2,564원", 1) == 2564
    assert parse_amount("2,564원", 1_000_000) == 2564      # ★배수 무시
    assert parse_amount("2,552 원", 1_000_000) == 2552     # 숫자와 '원' 사이 공백 서식
    assert parse_amount("(2,564)원", 1) == -2564           # 괄호 음수 표기 유지


def test_multiplier_bearing_suffix_is_not_silently_stripped():
    """'천원'·'백만원' 접미사는 배수를 품고 있어 떼면 1000배 오류가 된다 — 실측 표본에
    데이터칸 사례가 0건이라 처리하지 않는다(종전 동작 유지)."""
    assert parse_amount("1,234천원", 1) is None
    assert parse_amount("1,234백만원", 1) is None


def test_plain_numbers_still_take_the_table_multiplier():
    """접미사 없는 셀은 종전대로 표 배수를 받는다(회귀 가드)."""
    assert parse_amount("1,406,564", 1_000_000) == 1_406_564_000_000


def test_shinhan_2022q1_eps_rows_recovered():
    """결측됐던 EPS 행이 원문값 그대로 복원된다(별도·연결 양쪽)."""
    if not _SHINHAN_2022Q1.exists():
        return
    lines = extract_report_lines(
        _SHINHAN_2022Q1, rcept_no="20220516002487", corp_code="00382199",
        report_fiscal_year=2022, report_fiscal_period="Q1",
    )
    eps = [l for l in lines if "주당" in (l.label_raw or "")]
    assert eps, "EPS 행이 여전히 결측"

    def current(basis: str, label_part: str) -> list[int]:
        return [l.value_won for l in eps
                if l.basis == basis and label_part in l.label_raw and l.col_index == 0]

    # [별도] 기본 및 희석주당이익 = 2,564원 (제22기 1분기)
    assert current("separate", "기본 및 희석주당이익") == [2564]
    # [연결] 기본주당순이익 / 희석주당순이익 = 2,552원
    assert current("consolidated", "기본주당순이익") == [2552]
    assert current("consolidated", "희석주당순이익") == [2552]

    # 전기 동기(제21기 1분기)도 원문대로.
    prior = {(l.basis, l.label_raw): l.value_won for l in eps if l.col_index == 1}
    assert prior[("separate", "기본 및 희석주당이익")] == 2428
    assert prior[("consolidated", "(1) 기본주당순이익")] == 2173

    # ★본류가 같은 행을 한 번 더 담아 ×10⁶ 유령행을 만들지 않는다(R144 가 밟은 지뢰).
    assert all(abs(l.value_won) < 1_000_000 for l in eps), \
        [(l.label_raw, l.value_won) for l in eps if abs(l.value_won) >= 1_000_000]
