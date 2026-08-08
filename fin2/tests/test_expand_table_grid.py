"""
`parser/xml/table_extractor.py::expand_table_grid` 회귀 테스트 (합성 XML, DB/NAS 비의존).

R11(`docs/PARSING_RULES.md`)이 등재한 "표의 논리적 열 = 헤더·본문을 관통하는 하나의
occupied-grid" 규칙의 구현 유틸(계획 `docs/plans/note_span_fix_plan_2026-08-07.md` Phase 2,
T2.2). 여기서 검증하는 두 표 구조는 실제 결함이 확정된 원문 사례를 그대로 축소한 것 —
`docs/qa/handoff_note_lines_span_misattribution_2026-08-07.md` §8-2/§8-1 참고.

실행: python -m fin2.tests.test_expand_table_grid  또는  pytest fin2/tests/
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree  # noqa: E402

from parser.xml.table_extractor import expand_table_grid  # noqa: E402


def _parse(xml: str):
    table = etree.fromstring(xml)
    return expand_table_grid(table)


# ---------------------------------------------------------------------------
# 텔코웨어 20240814002630 축소판 — ROWSPAN 이어짐 (handoff §8-2)
#   원문 헤더 : <TD COLSPAN=2>구 분</TD> <TD>당반기말</TD> <TD>전기말</TD>
#   원문 행1  : <TD ROWSPAN=6>유동</TD> <TD>단기대여금</TD> <TD>398,691</TD> <TD>328,996</TD>
#   원문 행2  :                          <TD>미수수익</TD>   <TD>442,190</TD> <TD>470,100</TD>
# 결함: 현재 파이프라인은 행2 의 물리적 셀(미수수익·442,190·470,100)을 항상 "라벨+나머지"로
# 가정해 442,190 을 라벨열(구분)에, 470,100 을 '당반기말'열에 저장한다(원문상 전기말 값인데).
# ---------------------------------------------------------------------------
_TELCOWARE_XML = """<TABLE>
<TR><TD COLSPAN="2">구 분</TD><TD>당반기말</TD><TD>전기말</TD></TR>
<TR><TD ROWSPAN="6">유동</TD><TD>단기대여금</TD><TD>398,691</TD><TD>328,996</TD></TR>
<TR><TD>미수수익</TD><TD>442,190</TD><TD>470,100</TD></TR>
</TABLE>"""


def test_rowspan_continuation_shifts_true_grid_col():
    """ROWSPAN 이어짐 행(미수수익)은 진짜 grid_col 이 1칸 밀린 자리에서 시작한다."""
    rows = _parse(_TELCOWARE_XML)
    assert len(rows) == 3

    header, row1, row2 = rows
    # 헤더: 구분(COLSPAN=2, col0~1) | 당반기말(col2) | 전기말(col3)
    assert [c.grid_col for c in header] == [0, 2, 3]
    assert header[0].text == "구 분" and header[0].colspan == 2
    assert header[1].text == "당반기말"
    assert header[2].text == "전기말"

    # 행1(유동, ROWSPAN=6): 물리 셀 4개가 전부 있어 grid_col 이 물리 위치와 그대로 일치한다.
    assert [(c.text, c.grid_col, c.inherited) for c in row1] == [
        ("유동", 0, False),
        ("단기대여금", 1, False),
        ("398,691", 2, False),
        ("328,996", 3, False),
    ]

    # 행2(미수수익): col0 은 행1 의 ROWSPAN 이 이어받는다(inherited=True) → 이 행 자신의
    # 물리 셀은 grid_col **1** 부터 시작한다. 이게 R11 이 고치려는 밀림의 정체다.
    assert [(c.text, c.grid_col, c.inherited) for c in row2] == [
        ("유동", 0, True),           # 상속(물리 셀 아님)
        ("미수수익", 1, False),
        ("442,190", 2, False),       # 진짜 '당반기말' 열(header col2)
        ("470,100", 3, False),       # 진짜 '전기말' 열(header col3)
    ]
    # 현재(버그) 파이프라인은 물리 위치만 보고 442,190 을 라벨열, 470,100 을 '당반기말'에
    # 저장한다(offset=1 기준) — 진짜 열은 위 grid_col 이 보여주듯 2·3(당반기말·전기말)이다.
    amount_true_cols = [c.grid_col for c in row2 if c.text in ("442,190", "470,100")]
    assert amount_true_cols == [2, 3]


# ---------------------------------------------------------------------------
# 풍강 20150429000186 축소판 — COLSPAN'd 라벨 (handoff §1-2)
#   원문 헤더 5열: 차입금종류 | 차입처 | 이자율(%) | 당반기말 | 전기말
#   "합계" 행: <TD COLSPAN=3>합계</TD> <TD>금액A</TD> <TD>금액B</TD>
# ---------------------------------------------------------------------------
_PUNGGANG_XML = """<TABLE>
<TR><TD>차입금종류</TD><TD>차입처</TD><TD>이자율(%)</TD><TD>당반기말</TD><TD>전기말</TD></TR>
<TR><TD COLSPAN="3">합계</TD><TD>6,713,681</TD><TD>6,000,000</TD></TR>
</TABLE>"""


def test_colspan_label_row_reserves_full_width():
    """COLSPAN=3 라벨 행("합계")도 뒤따르는 금액 2개가 진짜 열(col3·col4)에 놓인다."""
    rows = _parse(_PUNGGANG_XML)
    header, total_row = rows
    assert [c.grid_col for c in header] == [0, 1, 2, 3, 4]

    assert [(c.text, c.grid_col, c.colspan, c.inherited) for c in total_row] == [
        ("합계", 0, 3, False),
        ("6,713,681", 3, 1, False),
        ("6,000,000", 4, 1, False),
    ]
    # 현재(버그) 파이프라인은 "라벨 1개 + 나머지"로 가정해 6,713,681 을 물리 위치 1
    # (offset=1 이면 col_label '차입처')에 놓는다 — 진짜 열은 3(당반기말)이다.
    assert total_row[1].grid_col == 3


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
