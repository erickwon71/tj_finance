"""R230 (2026-10-10): a note table whose header is [period > function] (매출원가 / 판관비 /
합계) — the current period's total column, not its first column."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fin2.layer3.note_da import _note_da_canonicals_from_rows  # noqa: E402
from parser.common.note_labels import AMORTIZATION, DEPRECIATION  # noqa: E402


class R:
    def __init__(self, label, ci, col_label, value, seq=40, row=0,
                 section="비용의 성격별 분류"):
        self.section_path, self.table_seq, self.row_order = section, seq, row
        self.col_index, self.col_label, self.label_raw, self.value_won = ci, col_label, label, value


def _nature_q3():
    """00110431 2015Q3 [기재정정] 20151209000350 연결 — 비용의 성격별 분류(천원 → 원)."""
    heads = ["(단위:천원)>3개월>매출원가", "(단위:천원)>3개월>판매비와 관리비", "(단위:천원)>3개월>성격별 비용",
             "(단위:천원)>누적>매출원가", "(단위:천원)>누적>판매비와 관리비", "(단위:천원)>누적>성격별 비용"]
    dep = [126810000, 106823000, 233633000, 343401000, 378414000, 721815000]
    amo = [0, 359671000, 359671000, None, 1076024000, 1076024000]
    rows = [R("감가상각비", i, h, v, row=6) for i, (h, v) in enumerate(zip(heads, dep))]
    rows += [R("무형자산상각비", i, h, v, row=7) for i, (h, v) in enumerate(zip(heads, amo)) if v is not None]
    return rows


def test_interim_cumulative_total_column():
    got = _note_da_canonicals_from_rows(_nature_q3(), "Q3")
    assert got.get(DEPRECIATION) == 721815000 and got.get(AMORTIZATION) == 1076024000


def test_fy_period_then_function_header():
    heads = ["(단위:원)>당기>매출원가", "(단위:원)>당기>판매비와관리비", "(단위:원)>당기>합계",
             "(단위:원)>전기>매출원가", "(단위:원)>전기>판매비와관리비", "(단위:원)>전기>합계"]
    vals = [10, 20, 30, 1, 2, 3]
    rows = [R("감가상각비", i, h, v) for i, (h, v) in enumerate(zip(heads, vals))]
    assert _note_da_canonicals_from_rows(rows, "FY").get(DEPRECIATION) == 30


def test_no_total_column_keeps_the_first_column():
    heads = ["(단위:원)>누적>매출원가", "(단위:원)>누적>판매비와관리비"]
    rows = [R("감가상각비", i, h, v) for i, (h, v) in enumerate(zip(heads, [10, 20]))]
    assert _note_da_canonicals_from_rows(rows, "H1").get(DEPRECIATION) == 10


def test_three_month_column_under_a_cumulative_header():
    """00126487 2021Q3 20211115001068 별도 비용의 성격별 분류."""
    heads = ["당누적3분기>3개월", "당누적3분기>누적", "전누적3분기>3개월", "전누적3분기>누적"]
    vals = [46095000, 7812531000, 5132383000, 16035954000]
    rows = [R("감가상각비, 사용권자산상각비 및 무형자산상각비", i, h, v, seq=146)
            for i, (h, v) in enumerate(zip(heads, vals))]
    got = _note_da_canonicals_from_rows(rows, "Q3")
    assert sum(got.values()) == 7812531000


def test_spaced_period_words():
    """'누 적' / '당 분 기' / '전 분 기' (00217743 20151116000973, 00178790 20251114000638)."""
    heads = ["(단위 : 원)>판매비와관리비>3개월", "(단위 : 원)>판매비와관리비>누 적",
             "(단위 : 원)>성격별 비용>3개월", "(단위 : 원)>성격별 비용>누 적"]
    rows = [R("감가상각비와 기타상각비", i, h, v, seq=38)
            for i, (h, v) in enumerate(zip(heads, [35805417, 70878459, 255068034, 508789124]))]
    assert sum(_note_da_canonicals_from_rows(rows, "H1").values()) == 508789124
    heads = ["당 분 기>3개월", "당 분 기>누 적", "전 분 기>3개월", "전 분 기>누적"]
    rows = [R("감가상각비", i, h, v, seq=88)
            for i, (h, v) in enumerate(zip(heads, [1453324000, 3571006000, 1238135000, 3852310000]))]
    assert _note_da_canonicals_from_rows(rows, "Q3").get(DEPRECIATION) == 3571006000


def test_plain_period_columns_unchanged():
    rows = [R("감가상각비", 0, "(단위:원)>당기", 100), R("감가상각비", 1, "(단위:원)>전기", 90)]
    assert _note_da_canonicals_from_rows(rows, "FY").get(DEPRECIATION) == 100
    rows = [R("감가상각비", 0, "(단위:원)>3개월", 40), R("감가상각비", 1, "(단위:원)>누적", 100)]
    assert _note_da_canonicals_from_rows(rows, "H1").get(DEPRECIATION) == 100
