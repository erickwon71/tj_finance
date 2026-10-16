"""R243 — a current-period header such as "제78기 당반기" keeps its quarter/half suffix in period_key.

Before the fix the key was cut to the bare ordinal ("제78기"), so R115
(`drop_mismatched_granularity_columns`) removed the current column as an annual reference column
and the prior-period column was stored as the current one (period_misassign).
"""
import pytest
from lxml import etree

from parser.xml.table_extractor import (
    _PERIOD_KEY_RE,
    drop_mismatched_granularity_columns,
    parse_header_columns,
)


@pytest.mark.parametrize("text, expected", [
    ("제78기 당반기", "제78기 당반기"),
    ("제21기(당)1분기", "제21기(당)1분기"),
    ("제14(당)기 분기", "제14(당)기 분기"),
    ("제13(전)기 1분기", "제13(전)기 1분기"),
    ("제23기(당)기 반기", "제23기(당)기 반기"),
    ("제77기 반기(전반기)", "제77기 반기"),
    ("제 21(당) 1분기", "제 21(당) 1분기"),
])
def test_period_key_keeps_quarter_or_half_suffix(text, expected):
    assert _PERIOD_KEY_RE.search(text).group(0) == expected


@pytest.mark.parametrize("text, expected", [
    ("제77기(전기)", "제77기"), ("제76기(전전기)", "제76기"), ("제40기", "제40기"), ("제14(당)기", "제14(당)기"),
])
def test_bare_annual_ordinals_stay_bare(text, expected):
    assert _PERIOD_KEY_RE.search(text).group(0) == expected


def _table(headers):
    ths = "".join(f"<TH>{h}</TH>" for h in headers)
    n = len(headers) - 1
    tds = "".join("<TD>1</TD>" for _ in range(n))
    return etree.fromstring(
        f"<TABLE><THEAD><TR>{ths}</TR></THEAD><TBODY><TR><TD>매출액</TD>{tds}</TR></TBODY></TABLE>")


def test_half_report_keeps_current_half_column():
    cols = parse_header_columns(_table(["과목", "제78기 당반기", "제77기 반기(전반기)", "제77기(전기)", "제76기(전전기)"]))
    kept = drop_mismatched_granularity_columns(cols, "H1")
    assert [(c.position, c.period_rank) for c in kept if not c.is_note] == [(0, 0), (1, 1)]


def test_first_quarter_keeps_current_quarter_column():
    cols = parse_header_columns(_table(["과목", "제14(당)기 분기", "제13(전)기 1분기"]))
    kept = drop_mismatched_granularity_columns(cols, "Q1")
    assert [(c.position, c.period_rank) for c in kept if not c.is_note] == [(0, 0), (1, 1)]


def test_bare_current_column_next_to_suffixed_prior_is_kept():
    # R243-c: current column printed "제 10 기" (3개월/누적 in a sub row), prior "제 9 기 1분기".
    cols = parse_header_columns(_table(["과목", "제 10 기", "제 9 기 1분기", "제 9 기", "제 8 기"]))
    kept = drop_mismatched_granularity_columns(cols, "Q1")
    assert [(c.position, c.period_rank) for c in kept if not c.is_note] == [(0, 0), (1, 1)]


def test_bare_prior_year_column_before_suffixed_current_is_still_dropped():
    # first-fiscal-year layout: "제 1 기" (full year) printed before "제 2 기 반기" (current)
    cols = parse_header_columns(_table(["과목", "제 1 기", "제 2 기 반기"]))
    kept = drop_mismatched_granularity_columns(cols, "H1")
    assert [(c.position, c.period_rank) for c in kept if not c.is_note] == [(1, 0)]
