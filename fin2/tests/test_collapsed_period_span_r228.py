"""R228 — a body-table header that puts ONE period over >=4 data columns.

B: split by the period tokens found in the table's own header or the title block above it.
A: no label evidence but the cells form two (detail|subtotal) period halves -> skip the table.
Otherwise the header is left alone."""
from __future__ import annotations

from lxml import etree

from parser.xml.table_extractor import (
    HeaderColumn, _period_tokens, resolve_collapsed_period_span,
)


def _cols(n: int, key: str = "제 22 기 반기") -> list[HeaderColumn]:
    return [HeaderColumn(position=i, period_key=key, period_rank=0) for i in range(n)]


def _table_xml(rows: list[list[str]], title_lines: list[str] | None = None) -> etree._Element:
    """Wrapper holding an optional title TABLE followed by the data TABLE; returns the data table."""
    parts = ["<BODY>"]
    if title_lines is not None:
        parts.append("<TABLE><TBODY>" + "".join(f"<TR><TD>{t}</TD></TR>" for t in title_lines) + "</TBODY></TABLE>")
    body = "".join("<TR>" + "".join(f"<TD>{c}</TD>" for c in r) + "</TR>" for r in rows)
    parts.append(f"<TABLE><TBODY>{body}</TBODY></TABLE></BODY>")
    root = etree.fromstring("".join(parts))
    return root.findall("TABLE")[-1]


PAIR_ROWS = [  # [label, cur detail, cur subtotal, prev detail, prev subtotal]
    ["a", "", "(433)", "", "(1,395)"], ["b", "3,146", "", "(19)", ""], ["c", "9,325", "", "4,927", ""],
    ["d", "-", "", "500", ""], ["e", "", "9,072", "", "160"], ["f", "699", "", "1,006", ""],
    ["g", "17,364", "", "10", ""],
]


def test_period_tokens_normalised_and_ordered():
    assert _period_tokens("제 22 기 반기 2020.01.01 부터 / 제 21 기 반기 2019.01.01") == ["제22기반기", "제21기반기"]
    assert _period_tokens("제22기(당)기 1분기 제22기(전)기 1분기") == ["제22기(당)기1분기", "제22기(전)기1분기"]


def test_b_split_by_title_block_periods():
    t = _table_xml(PAIR_ROWS, ["현금흐름표", "제 22 기 반기 2020.01.01 부터 2020.06.30 까지",
                               "제 21 기 반기 2019.01.01 부터 2019.06.30 까지", "(단위 : 원)"])
    cols, verdict = resolve_collapsed_period_span(t, _cols(4))
    assert verdict == "split"
    assert [(c.period_key, c.period_rank) for c in cols] == [
        ("제22기반기", 0), ("제22기반기", 0), ("제21기반기", 1), ("제21기반기", 1)]


def test_b_keeps_note_columns_untouched():
    t = _table_xml(PAIR_ROWS, ["제 22 기 반기", "제 21 기 반기"])
    cols = [HeaderColumn(position=0, period_key="주석", period_rank=-1, is_note=True)] + [
        HeaderColumn(position=i, period_key="제 22 기 반기", period_rank=0) for i in range(1, 5)]
    out, verdict = resolve_collapsed_period_span(t, cols)
    assert verdict == "split" and out[0].is_note and [c.period_rank for c in out[1:]] == [0, 0, 1, 1]


def test_a_skip_when_no_label_evidence_but_two_period_pairs():
    t = _table_xml(PAIR_ROWS, ["현금흐름표", "(단위 : 원)"])
    assert resolve_collapsed_period_span(t, _cols(4))[1] == "skip"


def test_normal_single_period_table_left_alone():
    # only the first half is filled -> not a two-period layout, no period evidence
    rows = [["a", "10", "", "", ""], ["b", "", "20", "", ""], ["c", "30", "", "", ""],
            ["d", "", "40", "", ""], ["e", "50", "", "", ""], ["f", "", "60", "", ""]]
    t = _table_xml(rows, ["재무상태표", "제 3 기 말"])
    cols, verdict = resolve_collapsed_period_span(t, _cols(4))
    assert verdict == "unchanged" and all(c.period_rank == 0 for c in cols)


def test_title_periods_not_divisible_is_not_split():
    t = _table_xml(PAIR_ROWS[:3], ["제 3 기", "제 2 기", "제 1 기"])   # 3 periods over 4 columns
    assert resolve_collapsed_period_span(t, _cols(4))[1] != "split"


def test_header_with_distinct_ranks_or_few_columns_unchanged():
    t = _table_xml(PAIR_ROWS, ["제 22 기 반기", "제 21 기 반기"])
    proper = [HeaderColumn(position=i, period_key="k", period_rank=i // 2) for i in range(4)]
    assert resolve_collapsed_period_span(t, proper)[1] == "unchanged"
    assert resolve_collapsed_period_span(t, _cols(2))[1] == "unchanged"
    assert resolve_collapsed_period_span(t, None) == (None, "unchanged")


def test_title_search_stops_at_a_big_previous_table():
    big = "".join(f"<TR><TD>제 9 기 말</TD></TR>" for _ in range(12))
    root = etree.fromstring(
        f"<BODY><TABLE><TBODY>{big}</TBODY></TABLE>"
        "<TABLE><TBODY><TR><TD>x</TD></TR></TBODY></TABLE></BODY>")
    second = root.findall("TABLE")[1]
    from parser.xml.table_extractor import _title_period_tokens
    assert _title_period_tokens(second) == []


def test_columns_already_split_by_subtype_are_not_collapsed():
    # first-period filing: [3개월 detail|sub | 누적 detail|sub] all share period_rank 0 but differ by subtype
    t = _table_xml(PAIR_ROWS, ["현금흐름표", "제 1 기 반기"])
    cols = [HeaderColumn(position=0, period_key="제1(당)기 반기", period_rank=0, subtype="three_month"),
            HeaderColumn(position=1, period_key="제1(당)기 반기", period_rank=0, subtype="three_month"),
            HeaderColumn(position=2, period_key="제1(당)기 반기", period_rank=0, subtype="cumulative"),
            HeaderColumn(position=3, period_key="제1(당)기 반기", period_rank=0, subtype="cumulative")]
    out, verdict = resolve_collapsed_period_span(t, cols)
    assert verdict == "unchanged" and out is cols


def test_repeated_subtype_blocks_are_split_by_title_periods():
    # 케이피항공산업 20200515000375: [3개월·누적 | 3개월·누적], both header labels typed as the same period
    t = _table_xml(PAIR_ROWS, ["손익계산서", "제 31 기 1분기", "제 30 기 1분기"])
    sub = ["three_month", "cumulative", "three_month", "cumulative"]
    cols = [HeaderColumn(position=i, period_key="제 30기 1분기", period_rank=0, subtype=sub[i]) for i in range(4)]
    out, verdict = resolve_collapsed_period_span(t, cols)
    assert verdict == "split"
    assert [(c.period_rank, c.subtype) for c in out] == [
        (0, "three_month"), (0, "cumulative"), (1, "three_month"), (1, "cumulative")]


def test_first_period_subtype_layout_still_untouched_even_with_two_title_periods():
    t = _table_xml(PAIR_ROWS, ["손익계산서", "제 1 기 반기", "제 0 기 반기"])
    sub = ["three_month", "three_month", "cumulative", "cumulative"]
    cols = [HeaderColumn(position=i, period_key="제1(당)기 반기", period_rank=0, subtype=sub[i]) for i in range(4)]
    assert resolve_collapsed_period_span(t, cols)[1] == "unchanged"
