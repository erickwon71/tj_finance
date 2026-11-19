"""R348 sales mapper T7 guard regression tests (grid literals from biz_section_tables, DB-free)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.sales_section import SalesTable, map_sales_table  # noqa: E402

# 티앤엘(00608440) FY2025 20260318001498 table_ord=1 (first rows) — two-row header "2025년" / "(제28기)".
_TNL_2025 = [
    ["부문", "매출유형", "품목", "품목", "2025년", "2024년", "2023년"],
    ["부문", "매출유형", "품목", "품목", "(제28기)", "(제27기)", "(제26기)"],
    ["창상치료재", "제품", "하이드로콜로이드", "수출", "102,759,182 (72,210)", "111,510,231 (81,598)", "62,740,266 (47,970)"],
    ["창상치료재", "제품", "하이드로콜로이드", "내수", "20,813,997", "19,652,994", "14,050,800"],
]
_TNL_NARRATIVE = "* 수출품목의 가격은 해당년도 년평균환율을 적용하여 미달러로 환산하였습니다. (단위 : 천원, 천달러)"

# 20120330002876 — year-only second header row used to become a data row with values 2009 / 2010.
_YEAR_ROW = [
    ["업    체", "매 출 액", "매 출 액"],
    ["업    체", "2009", "2010"],
    ["ASE Korea", "3,845", "5,083"],
]


def test_two_row_year_header_table_is_read():
    rows = map_sales_table(SalesTable(narrative=_TNL_NARRATIVE, grid=_TNL_2025), 2025)
    assert rows, "table must not be dropped"
    y25 = [r for r in rows if r.period_year == 2025]
    # "102,759,182 (72,210)" (KRW with USD in parentheses) is not read — pre-existing, separate item.
    assert {r.value for r in y25} == {20813997}, y25
    assert all(r.unit for r in rows)


def test_year_header_row_is_not_a_data_row():
    rows = map_sales_table(SalesTable(narrative="", grid=_YEAR_ROW), 2010)
    assert {r.value for r in rows} == {3845, 5083}, rows
    assert {r.period_year for r in rows} == {2009, 2010}



# R349 ----------------------------------------------------------------------------------------
# 20260319000395 shape (amount / share pairs) and 오리온-type quantity / amount pairs.
_QTY_AMOUNT_PAIRS = [
    ["사업부문", "품목", "구분", "제9기", "제9기", "제8기", "제8기"],
    ["사업부문", "품목", "구분", "중 량", "금 액", "중 량", "금 액"],
    ["식품", "껌캔디", "수출", "2,617", "25,199", "2,534", "22,550"],
]
_SHARE_PAIRS = [
    ["부문", "품목", "제 49기", "제 49기", "제 48기", "제 48기"],
    ["부문", "품목", "금액", "비중", "금액", "비중"],
    ["염료", "한국", "258,259", "68.02", "254,509", "68.01"],
]
_AMOUNT_WITH_SHARE_IN_PARENS = [
    ["사업부문", "품 목", "매출액(비율)", "매출총이익(비율)", "비 고"],
    ["상품매출수입", "건설기계", "162,218", "32,297", ""],
]
_RELATIVE_PERIODS = [
    ["사업부문", "품목", "제58(당)기 매출액", "제57(전)기 매출액"],
    ["푸드", "내수", "994,112", "941,759"],
]
_DANGI_JEONGI = [
    ["구분", "당기", "전기", "전전기"],
    ["제품", "300", "200", "100"],
]


def test_quantity_columns_dropped_when_amount_present():
    rows = map_sales_table(SalesTable(narrative="(단위 : TON, 백만원)", grid=_QTY_AMOUNT_PAIRS), 2025)
    assert {r.value for r in rows} == {25199, 22550}, rows
    assert {r.unit for r in rows} == {"백만원"}
    assert {r.period_year for r in rows} == {2025, 2024}


def test_share_columns_dropped():
    rows = map_sales_table(SalesTable(narrative="", grid=_SHARE_PAIRS), 2025)
    assert {r.value for r in rows} == {258259, 254509}, rows


def test_amount_header_with_ratio_note_kept_profit_dropped():
    rows = map_sales_table(SalesTable(narrative="", grid=_AMOUNT_WITH_SHARE_IN_PARENS), 2011)
    assert {r.value for r in rows} == {162218}, rows


def test_period_with_dang_jeon_note():
    rows = map_sales_table(SalesTable(narrative="", grid=_RELATIVE_PERIODS), 2025)
    assert {(r.value, r.period_year) for r in rows} == {(994112, 2025), (941759, 2024)}, rows


def test_relative_period_headers():
    rows = map_sales_table(SalesTable(narrative="", grid=_DANGI_JEONGI), 2025)
    assert {(r.value, r.period_year) for r in rows} == {(300, 2025), (200, 2024), (100, 2023)}, rows


# R349 header variants seen in the 2025 FY zero-row filings (롯데케미칼, 삼익악기, 엠투엔, 풍산홀딩스,
# 테라사이언스).
_YEAR_SUFFIX = [
    ["사업구분", "품목", "2025년(당기)", "2024년(전기)"],
    ["기초화학", "에틸렌", "4,320,748", "5,454,901"],
]
_GI_NO_JE = [
    ["사업부문", "품목", "53기 연간", "52기 연간"],
    ["악기사업", "GP", "108,392", "112,560"],
]
_QUARTER_NEXT_TO_YEAR = [
    ["사업부문", "매출유형", "2025년", "2025년 4분기"],
    ["사업부문", "매출유형", "금액", "금액"],
    ["신동", "내수", "1,000", "300"],
]
_SPARSE_DASHES = [
    ["구  분", "당  기", "전  기"],
    ["구  분", "매출액", "매출액"],
    ["피팅사업부", "14,134,318", "17,272,994"],
    ["바이오사업부", "-", "-"],
    ["기타", "-", "-"],
]


def test_year_header_with_suffix_is_a_header():
    rows = map_sales_table(SalesTable(narrative="", grid=_YEAR_SUFFIX), 2025)
    assert {(r.value, r.period_year) for r in rows} == {(4320748, 2025), (5454901, 2024)}, rows


def test_gi_without_je_is_a_header():
    rows = map_sales_table(SalesTable(narrative="", grid=_GI_NO_JE), 2025)
    assert {(r.value, r.period_year) for r in rows} == {(108392, 2025), (112560, 2024)}, rows


def test_quarter_column_label_kept_apart():
    rows = map_sales_table(SalesTable(narrative="", grid=_QUARTER_NEXT_TO_YEAR), 2025)
    assert {(r.value, r.period_label) for r in rows} == {(1000, "2025년"), (300, "2025년 4분기")}, rows


def test_dash_cells_do_not_turn_amount_column_into_label():
    rows = map_sales_table(SalesTable(narrative="", grid=_SPARSE_DASHES), 2025)
    assert {(r.segment, r.value, r.period_year) for r in rows} == {
        ("피팅사업부", 14134318, 2025), ("피팅사업부", 17272994, 2024)}, rows


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok {name}")
            except AssertionError as e:
                failed += 1
                print(f"  FAIL {name}: {e}")
    sys.exit(1 if failed else 0)
