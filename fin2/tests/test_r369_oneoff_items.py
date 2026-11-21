"""R369 (tj_asset request #7): one-off non-operating items — labels, note tables, body-first."""
from types import SimpleNamespace as NS

import pytest

from fin2.layer3.note_oneoff import oneoff_from_body_rows, oneoff_from_note_rows
from parser.common.note_labels import (
    DEBT_FORGIVENESS_GAIN, DISPOSAL_GAIN, DISPOSAL_LOSS, IMPAIRMENT_LOSS, IMPAIRMENT_REVERSAL,
    classify_oneoff_label,
)
from parser.common.note_topics import OTHER_INCOME_EXPENSE, map_topic


@pytest.mark.parametrize("label,want", [
    ("유형자산감액손실환입", IMPAIRMENT_REVERSAL),      # HD현대마린엔진 2025 FY (720억)
    ("유형자산손상차손환입", IMPAIRMENT_REVERSAL),
    ("매각예정자산손상차손", IMPAIRMENT_LOSS),
    ("종속기업투자주식손상차손", IMPAIRMENT_LOSS),
    ("영업권손상차손", IMPAIRMENT_LOSS),
    ("기타비용>유형자산처분손실", DISPOSAL_LOSS),     # parent group name is not part of the item
    ("무형자산처분손실", DISPOSAL_LOSS),
    ("유형자산처분이익", DISPOSAL_GAIN),
    ("관계기업투자처분이익", DISPOSAL_GAIN),
    ("채무면제이익", DEBT_FORGIVENESS_GAIN),
    # excluded: recurring costs, financial assets, net labels, balances
    ("기타의대손상각비", None),
    ("대손충당금환입", None),
    ("재고자산평가손실", None),
    ("금융자산처분이익", None),
    ("매출채권처분손실", None),
    ("기타수익>투자자산처분이익", None),               # plain 투자자산 may be financial
    ("손상차손(환입)", None),                           # net label cannot be split
    ("처분이익(손실)", None),
    ("무형자산손상차손누계액", None),
    ("유형자산감가상각비", None),
])
def test_label(label, want):
    assert classify_oneoff_label(label) == want


def test_bare_disposal_needs_non_financial_context():
    assert classify_oneoff_label("처분이익") == DISPOSAL_GAIN                    # 기타수익 note
    assert classify_oneoff_label("처분이익", fin_note=True) is None              # 금융수익 note
    assert classify_oneoff_label("처분이익", strict=True) is None                # body income statement
    assert classify_oneoff_label("유형자산처분이익", strict=True) == DISPOSAL_GAIN


def test_topic():
    assert map_topic("25. 기타수익 및 기타비용 (연결)") == OTHER_INCOME_EXPENSE
    assert map_topic("26. 금융수익 및 금융비용") == OTHER_INCOME_EXPENSE
    assert map_topic("12. 유형자산 (연결)") != OTHER_INCOME_EXPENSE


def _row(section, seq, order, label, value, col=0, col_label="공시금액"):
    return NS(section_path=section, table_seq=seq, row_order=order, col_index=col,
              col_label=col_label, label_raw=label, value_won=value)


SEC = "25. 기타수익 및 기타비용 (연결)"


def test_note_current_table_wins_and_sums_within_table():
    rows = [
        # current-year table (449) then prior-year sibling (452) — only the current one counts
        _row(SEC, 449, 0, "기타수익", 78_880_726_000),
        _row(SEC, 449, 1, "유형자산처분이익", 6_868_074_000),
        _row(SEC, 449, 2, "투자부동산처분이익", 0),
        _row(SEC, 449, 3, "유형자산감액손실환입", 71_963_577_000),
        _row(SEC, 449, 4, "기타비용", 2_629_264_000),
        _row(SEC, 449, 5, "유형자산처분손실", 851_801_000),
        _row(SEC, 449, 6, "무형자산처분손실", 3_000),
        _row(SEC, 449, 7, "무형자산손상차손", 0),
        _row(SEC, 449, 8, "기타의대손상각비", 106_694_000),
        _row(SEC, 452, 0, "기타수익", 4_447_283_000),
        _row(SEC, 452, 1, "유형자산처분이익", 1_090_121_000),
        _row(SEC, 452, 2, "투자부동산처분이익", 2_434_723_000),
        _row(SEC, 452, 3, "유형자산감액손실환입", 0),
        _row(SEC, 452, 5, "유형자산처분손실", 58_553_000),
        _row(SEC, 452, 7, "무형자산손상차손", 3_986_000),
    ]
    got = oneoff_from_note_rows(rows, "FY")
    assert got[IMPAIRMENT_REVERSAL] == 71_963_577_000
    assert got[DISPOSAL_GAIN] == 6_868_074_000
    assert got[DISPOSAL_LOSS] == 851_804_000
    assert got[IMPAIRMENT_LOSS] == 0                       # printed as 0 stays 0
    assert DEBT_FORGIVENESS_GAIN not in got                 # not named -> no value (not 0)


def test_financial_note_skips_unnamed_disposal():
    rows = [_row("26. 금융수익 및 금융비용", 457, 0, "처분이익", 5),
            _row("26. 금융수익 및 금융비용", 457, 1, "이자수익", 7)]
    assert oneoff_from_note_rows(rows, "FY") == {}


def _body(label, value, stmt="IS", cum=True):
    return {"statement": stmt, "basis": "consolidated", "label_raw": label,
            "value_won": value, "is_cumulative": cum}


def test_body_lines_strict_and_interim_cumulative_only():
    merged = [_body("유형자산처분이익", 10), _body("유형자산처분이익", 3, cum=False),
              _body("처분이익", 99), _body("유형자산손상차손", -20), _body("유형자산처분이익", 7, stmt="BS")]
    assert oneoff_from_body_rows(merged, "consolidated", "Q3") == {
        DISPOSAL_GAIN: 10, IMPAIRMENT_LOSS: 20}
    assert oneoff_from_body_rows(merged, "separate", "FY") == {}
