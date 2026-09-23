"""R166(2026-09-23) regression test — the second physical row of a ROWSPAN label
had its values dropped entirely.

DART renders a long SCE row label by giving the label `<TE>` a ROWSPAN=2 and
putting the figures on the SECOND physical row. That row has no label cell of
its own, so `_grid_body_rows` took `physical[0]` (the first AMOUNT cell) as the
label, found it empty, and hit `if not label: continue` — discarding the row
and every value on it.

Found by camp_run on SK이노베이션 20240320000950 [연결] SCE (campaign issue #34),
who confirmed by screenshot + computed style that the screen matches the XML
(only the label cell is 65px = two rows tall; every other cell is a normal
32px single row). So this is a real source layout, not a render mismatch.

The three year sections in that filing are NOT the same shape, which is why the
fix only fills EMPTY columns of the preceding logical row:

    2022 / 2023   label row entirely empty, all values on the second row,
                  and that row closes its own identity      -> merge is right
    2021          label row already self-complete
                  (20,388,640 + 17,913 = 20,406,553) and the second row holds
                  only 자본합계 = 20,599,397, which closes nothing
                  -> identity unknown, must NOT be pushed in (R6)

Run: pytest fin2/tests/test_r166_rowspan_continuation_row.py
"""
from __future__ import annotations

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
    """A minimal SCE table: one header row, then a ROWSPAN=2 label with values
    split over two physical rows. `None` means an empty cell."""
    head = "".join("<TE>%s</TE>" % c for c in _COLS)

    def cells(vals):
        return "".join("<TE>%s</TE>" % ("" if v is None else v) for v in vals)

    # ★A real data row must come first: `_grid_header_split` ends the header at
    #   the first row containing numbers, so a value-less label row placed
    #   directly after the header would be swallowed INTO the header and the
    #   continuation would have no preceding logical row to merge into. In the
    #   real filing these sections sit mid-table, after 기초자본 etc.
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


def test_values_on_the_second_physical_row_are_not_dropped():
    """★핵심 — 라벨행이 비고 값이 둘째 행에 있는 서식(2022·2023 구간 모양)."""
    tbl = _table([None] * 6,
                 [None, None, "(48,279,660)", "(48,279,660)",
                  "(4,822,811)", "(53,102,471)"])
    rows = _rows(tbl)
    assert len(rows) == 2, [r.account_name for r in rows]
    got = [a for a in rows[1].amounts if a is not None]
    assert -48_279_660 in got and -53_102_471 in got, got
    assert rows[1].account_name.startswith("기타포괄손익"), rows[1].account_name


def test_second_row_never_overwrites_a_value_the_label_row_already_had():
    """★2021 구간 — 라벨행이 이미 자기완결이면 둘째 행 값을 밀어넣지 않는다.

    그 값(20,599,397)은 어떤 항등식도 닫지 않아 정체를 알 수 없다. 짐작으로
    채우지 않는 것이 옳다(R6) — 여기서 통과하면 오염 경로가 열린 것이다.
    """
    tbl = _table([None, "914,716", "19,473,924", "20,388,640", "17,913",
                  "20,406,553"],
                 [None] * 5 + ["20,599,397"])
    rows = _rows(tbl)
    assert len(rows) == 2
    got = [a for a in rows[1].amounts if a is not None]
    assert 20_406_553 in got, got
    assert 20_599_397 not in got, "정체 불명 값이 주입됐다 — 오염(R6 위반)"


def test_label_is_kept_from_the_rowspan_origin():
    """병합된 행이 새 행으로 쪼개지지 않는다 — 같은 라벨 행이 둘이 되면 열
    롤포워드 항등식(R162·R165)이 깨진다."""
    tbl = _table([None] * 6,
                 [None, "1,000", None, "1,000", None, "1,000"])
    rows = _rows(tbl)
    assert len(rows) == 2, [r.account_name for r in rows]
    assert rows[1].account_name.startswith("기타포괄손익")


_SK = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00631518_SK이노베이션/annual/2023/20240320000950.xml"
)


def test_sk_innovation_2023fy_sections_recovered_and_identities_close():
    """실측 필링 — 2022·2023 구간이 복구되고 세 구간 모두 항등식이 닫힌다.

    2021 구간의 20,599,397 은 **복구되지 않는 것이 정답**이다.
    """
    if not _SK.exists():
        return
    lines = extract_report_lines(
        _SK, rcept_no="20240320000950", corp_code="00631518",
        report_fiscal_year=2023, report_fiscal_period="FY")
    sce = [l for l in lines if l.statement == "SCE"
           and l.basis == "consolidated"
           and "기타포괄손익-공정가치" in (l.label_raw or "")]
    assert sce

    by_row: dict = {}
    for l in sce:
        by_row.setdefault(l.row_order, {})[
            (l.col_label or "").split(">")[-1].strip()] = l.value_won

    closed = 0
    for cols in by_row.values():
        own = next((v for k, v in cols.items()
                    if "지배기업" in k and "합계" in k), None)
        nci = next((v for k, v in cols.items() if "비지배" in k), None)
        tot = next((v for k, v in cols.items()
                    if k.endswith("합계") and "지배기업" not in k), None)
        if None not in (own, nci, tot):
            assert own + nci == tot, (own, nci, tot)
            closed += 1
    assert closed == 3, "세 연차 구간이 모두 닫혀야 한다 — 실제 %d" % closed

    vals = {abs(l.value_won) for l in sce if l.value_won is not None}
    assert 53_102_471_000 in vals, "2022 구간 미복구(R166 회귀)"
    assert 28_607_200_000 in vals, "2023 구간 미복구(R166 회귀)"
    assert 20_599_397_000 not in vals, "정체 불명 값이 주입됐다(R6 위반)"
