"""R166(2026-09-23) regression test — the second physical row of a ROWSPAN label
had its values dropped entirely.

DART renders a long SCE row label by giving the label `<TE>` a ROWSPAN=2 and
putting figures on the SECOND physical row. That row has no label cell of its
own, so `_grid_body_rows` took `physical[0]` (the first AMOUNT cell) as the
label, found it empty, and hit `if not label: continue` — discarding the row and
every value on it.

Found by camp_run on SK이노베이션 20240320000950 (issue #34) and 한미반도체
20230814001921 (issue #35), who confirmed by screenshot + computed style that
the screen matches the XML (only the label cell is two rows tall). So this is a
real source layout, not a render mismatch.

## ★Design: emit a SEPARATE row, never merge

The first implementation assumed "one logical row split across two physical
rows" and filled the preceding row's empty (later also zero) columns. That
assumption is false. SK이노베이션 20260316000827 [별도] SCE:

    label row     기타자본구성요소 16,264,649 · 자본합계 16,264,649      -> closes
    continuation  이익잉여금 17,201,204 · 기타자본구성요소 (17,201,204)
                  · 자본합계 0                                        -> closes

Two DIFFERENT movements under one caption (a valuation gain, and an
이익잉여금<->기타자본 reclassification), each closing its own identity. Merging
them produced `17,201,204 + 16,264,649 = 33,465,853` against a 자본합계 of `0`
— a fabricated row. So the merge was dropped: what the source prints as two
rows is transcribed as two rows, with the continuation inheriting the ROWSPAN
label. Nothing is ever overwritten, so the change is purely additive.

Run: pytest fin2/tests/test_r166_rowspan_continuation_row.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree  # noqa: E402

from fin2.extract.report_lines import (  # noqa: E402
    _grid_body_rows, _grid_header_split, extract_report_lines,
)

_COLS = ("자본금", "이익잉여금", "기타자본구성요소",
         "지배기업의 소유주에게 귀속되는 지분 합계", "비지배지분", "자본 합계")


def _table(label_row_values, second_row_values) -> etree._Element:
    """One header row, a normal data row, then a ROWSPAN=2 label whose figures
    are split over two physical rows. `None` means an empty cell.

    ★The normal data row matters: `_grid_header_split` ends the header at the
    first row containing numbers, so a value-less label row placed directly
    after the header would be absorbed INTO the header.
    """
    head = "".join("<TE>%s</TE>" % c for c in _COLS)

    def cells(vals):
        return "".join("<TE>%s</TE>" % ("" if v is None else v) for v in vals)

    prior = cells(["1,000", "2,000", "3,000", "5,000", "6,000", "11,000"])
    return etree.fromstring((
        "<TABLE><TBODY>"
        "<TR><TE>과 목</TE>%s</TR>"
        "<TR><TE>2021.01.01 (기초자본)</TE>%s</TR>"
        '<TR><TE ROWSPAN="2">기타포괄손익-공정가치측정 금융자산 평가손익</TE>%s</TR>'
        "<TR>%s</TR>"
        "</TBODY></TABLE>" % (head, prior, cells(label_row_values),
                              cells(second_row_values))
    ).encode())


def _rows(tbl):
    grid_rows, n_header, offset, _width = _grid_header_split(tbl)
    return _grid_body_rows(tbl, grid_rows, n_header, offset,
                           multiplier=1, rcept_no="TEST",
                           allow_date_label=True, keep_header_rows=False)


def _vals(row):
    return [a for a in row.amounts if a is not None]


# ───────────────────────── the continuation row ─────────────────────────

def test_values_on_the_second_physical_row_are_not_dropped():
    """★핵심 — 둘째 물리행의 값이 더 이상 버려지지 않는다(이슈#34 2022·2023 모양)."""
    tbl = _table([None] * 6,
                 [None, None, "(48,279,660)", "(48,279,660)",
                  "(4,822,811)", "(53,102,471)"])
    rows = _rows(tbl)
    assert len(rows) == 3, [r.account_name for r in rows]
    got = _vals(rows[2])
    assert -48_279_660 in got and -53_102_471 in got, got


def test_continuation_inherits_the_rowspan_label():
    tbl = _table([None] * 6,
                 [None, "1,000", None, "1,000", None, "1,000"])
    rows = _rows(tbl)
    assert rows[-1].account_name.startswith("기타포괄손익"), rows[-1].account_name


def test_continuation_is_a_separate_row_and_never_overwrites():
    """★병합 금지 — 라벨행이 자기완결이면 그 값이 그대로 남고, 이어짐 행은 별도 행이다.

    병합했을 때 SK이노베이션 20260316000827 에서 날조된 행이 나왔다. 두 행을 각각
    전사하면 원문이 인쇄한 대로가 되고 덮어쓰기가 없다.
    """
    tbl = _table([None, "914,716", "19,473,924", "20,388,640", "17,913",
                  "20,406,553"],
                 [None] * 5 + ["20,599,397"])
    rows = _rows(tbl)
    assert len(rows) == 3, [r.account_name for r in rows]
    # 라벨행은 그대로다
    assert 20_406_553 in _vals(rows[1]), _vals(rows[1])
    assert 20_599_397 not in _vals(rows[1]), "직전 행이 덮어써졌다"
    # 이어짐 행은 자기 값만 갖는다
    assert _vals(rows[2]) == [20_599_397], _vals(rows[2])


def test_two_self_consistent_movements_stay_separate():
    """★SK이노베이션 20260316000827 모양 — 각각 항등식이 닫히는 두 변동.

    병합하면 `17,201,204 + 16,264,649 = 33,465,853` 인데 합계가 `0` 인 행이 된다.
    """
    tbl = _table([None, None, "16,264,649", "16,264,649", None, "16,264,649"],
                 [None, "17,201,204", "(17,201,204)", None, None, "0"])
    rows = _rows(tbl)
    assert len(rows) == 3
    assert 16_264_649 in _vals(rows[1])
    assert 17_201_204 in _vals(rows[2]) and -17_201_204 in _vals(rows[2])
    # 날조 확인: 두 변동이 한 행에 섞이지 않았다
    assert not (17_201_204 in _vals(rows[1]) and 16_264_649 in _vals(rows[1])
                and -17_201_204 not in _vals(rows[1])), "두 행이 병합돼 날조됨"


def test_all_zero_label_row_keeps_its_zeros():
    """라벨행이 전부 0 이어도 그 0 을 덮지 않는다(이슈#35 모양) — 값은 별도 행에."""
    tbl = _table(["0", "0", "0", "0", "0", "0"],
                 ["0", "5,464,171,128", "0", "5,464,171,128", "0",
                  "5,464,171,128"])
    rows = _rows(tbl)
    assert len(rows) == 3
    assert all(a in (0, None) for a in rows[1].amounts), rows[1].amounts
    assert _vals(rows[2]).count(5_464_171_128) == 3, _vals(rows[2])


def test_row_without_a_recoverable_label_is_still_dropped():
    """상속 라벨조차 없으면 종전대로 버린다 — 라벨 없는 행을 만들지 않는다."""
    tbl = etree.fromstring(
        "<TABLE><TBODY>"
        "<TR><TE>과 목</TE><TE>자본금</TE><TE>자본 합계</TE></TR>"
        "<TR><TE>2021.01.01 (기초자본)</TE><TE>1,000</TE><TE>1,000</TE></TR>"
        "<TR><TE></TE><TE>2,000</TE><TE>2,000</TE></TR>"
        "</TBODY></TABLE>".encode())
    rows = _rows(tbl)
    assert len(rows) == 1, [r.account_name for r in rows]


# ─────────────────────── real filings (issues #34/#35) ───────────────────────

_SK = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00631518_SK이노베이션/annual/2023/20240320000950.xml"
)
_HANMI = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00161383_한미반도체/half/2023/20230814001921.xml"
)
_SK2025 = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00631518_SK이노베이션/annual/2025/20260316000827.xml"
)


def _concept(col_label):
    return re.sub(r"\s+", "", (col_label or "").split(">")[-1])


def test_sk_innovation_2023fy_all_three_sections_recovered():
    """실측 이슈#34 — 세 연차 구간의 값이 전부 적재된다(원문 10셀)."""
    if not _SK.exists():
        return
    lines = extract_report_lines(
        _SK, rcept_no="20240320000950", corp_code="00631518",
        report_fiscal_year=2023, report_fiscal_period="FY")
    vals = {abs(l.value_won) for l in lines
            if l.statement == "SCE" and l.basis == "consolidated"
            and l.value_won is not None}
    for want in (53_102_471_000, 28_607_200_000, 20_599_397_000):
        assert want in vals, want


def test_hanmi_2023h1_treasury_gain_recovered():
    """실측 이슈#35 — 라벨행이 전부 0 인 서식."""
    if not _HANMI.exists():
        return
    lines = extract_report_lines(
        _HANMI, rcept_no="20230814001921", corp_code="00161383",
        report_fiscal_year=2023, report_fiscal_period="H1")
    for basis, expected in (("consolidated", 3), ("separate", 2)):
        n = len([l for l in lines if l.statement == "SCE" and l.basis == basis
                 and l.value_won == 5_464_171_128])
        assert n == expected, (basis, n, expected)


def test_sk_innovation_2025fy_separate_rows_each_close():
    """★실측 — 병합했을 때 날조된 행이 나오던 필링. 이제 각 행이 스스로 닫힌다."""
    if not _SK2025.exists():
        return
    lines = extract_report_lines(
        _SK2025, rcept_no="20260316000827", corp_code="00631518",
        report_fiscal_year=2025, report_fiscal_period="FY")
    rows: dict = {}
    for l in lines:
        if (l.statement == "SCE" and l.basis == "separate"
                and "기타포괄손익-공정가치" in (l.label_raw or "")):
            rows.setdefault(l.row_order, {})[_concept(l.col_label)] = l.value_won
    assert rows
    for ro, cols in rows.items():
        total = cols.get("자본합계")
        if total is None:
            continue
        comps = sum(v for k, v in cols.items()
                    if k not in ("자본합계", "기타불입자본합계") and v is not None)
        assert comps == total, (ro, comps, total)
