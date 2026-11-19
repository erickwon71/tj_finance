"""R347 order_backlog layout regression tests (grid literals copied from biz_section_tables, DB-free).

Rollforward-in-columns tables (기초잔고 | 신규 | 기납품 | 기말잔고) used to leak the opening and
new-order columns into `category` and shift the amounts. These grids are the printed rows.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.order_backlog import (  # noqa: E402
    LAYOUT_CUMULATIVE, LAYOUT_ROLLFORWARD, _aggregate_if_detail, map_order_table,
)

# HD현대마린엔진(00406046) FY2025 20260316001327 table_ord=28 — 수량/금액 sub-columns,
# recognition printed negative.
_HD_MARINE = [
    ["품목", "수주일자", "납기", "기초수주잔액", "기초수주잔액", "신규증감", "신규증감", "기납품액", "기납품액", "수주잔고", "수주잔고"],
    ["품목", "수주일자", "납기", "수량", "금액", "수량", "금액", "수량", "금액", "수량", "금액"],
    ["선박엔진", "'25.12.31까지", "-", "-", "689,570", "-", "621,029", "-", "-300,624", "-", "1,009,975"],
    ["엔진부품", "'25.12.31까지", "-", "-", "49,416", "-", "113,665", "-", "-84,158", "-", "78,923"],
    ["합 계", "합 계", "합 계", "-", "738,986", "-", "734,694", "-", "-384,782", "-", "1,088,898"],
]

# 20240313001778 — opening column next to 수주총액: 수주총액 is the period's new orders.
_CARRY_TOTAL = [
    ["품목", "수주일자", "납기", "전기이월누계", "수주총액", "기납품액", "수주잔고"],
    ["건설사 특판", "제51기", "2023.01.01~", "360,387", "260,300", "298,189", "322,498"],
    ["합 계", "합 계", "합 계", "360,387", "260,300", "298,189", "322,498"],
]

# 20240327000933 — 기초공사계약잔액 also contains "계약잔액"; it must be the opening, not the backlog.
_CONSTRUCTION_RF = [
    ["구분", "발주처", "공사명", "기초공사계약잔액", "증감액", "당기공사수익", "기말공사계약잔액"],
    ["토목", "국가철도공단", "중앙선 도담~영천", "939", "857", "977", "819"],
    ["토목", "수자원공사", "송산그린시티조성공사", "12,302", "2,019", "3,439", "10,882"],
]

# 20240313001646 — cumulative table with 매출액 (cumulative recognition) and spaced date headers.
_CUMULATIVE = [
    ["구분", "발주처 명칭", "계약명칭", "계약시작일", "계약종료일", "최종도급액", "매출액", "수주잔고"],
    ["국내", "넥스트레인 주식회사", "신안산선 복선전철", "2019년 2월", "2025년 4월", "1,510,909", "519,811", "991,098"],
]

# 20250317000850 — cumulative table with 수량/금액 sub-columns; quantity must not become the amount.
_QTY_AMOUNT = [
    ["사업부문", "품목", "수주", "납기", "수주총액", "수주총액", "기납품액", "기납품액", "수주잔고", "수주잔고"],
    ["사업부문", "품목", "수주", "납기", "수량", "금액", "수량", "금액", "수량", "금액"],
    ["합성사", "원사", "2024.12.31", "수시", "67,480", "559,105", "60,000", "500,000", "7,480", "59,105"],
]


def test_hd_marine_rollforward_columns_not_in_category():
    rows = map_order_table(_HD_MARINE, default_unit="백만원")
    by = {r.category: r for r in rows}
    assert set(by) == {"선박엔진", "엔진부품", "합 계"}, by.keys()
    r = by["선박엔진"]
    assert r.layout == LAYOUT_ROLLFORWARD
    assert (r.opening_backlog, r.new_orders, r.completed, r.backlog_amt) == (689570, 621029, 300624, 1009975)
    assert r.contract_total is None
    assert r.opening_backlog + r.new_orders - r.completed == r.backlog_amt


def test_opening_column_turns_total_into_new_orders():
    r = map_order_table(_CARRY_TOTAL)[0]
    assert r.category == "건설사 특판"
    assert r.layout == LAYOUT_ROLLFORWARD
    assert (r.opening_backlog, r.new_orders, r.completed, r.backlog_amt) == (360387, 260300, 298189, 322498)
    assert r.contract_total is None


def test_opening_contract_balance_is_not_backlog():
    rows = map_order_table(_CONSTRUCTION_RF)
    r = rows[0]
    assert r.category == "토목 국가철도공단 중앙선 도담~영천", r.category
    assert (r.opening_backlog, r.new_orders, r.completed, r.backlog_amt) == (939, 857, 977, 819)


def test_cumulative_table_keeps_contract_total():
    r = map_order_table(_CUMULATIVE)[0]
    assert r.layout == LAYOUT_CUMULATIVE
    assert r.category == "국내 넥스트레인 주식회사 신안산선 복선전철", r.category
    assert (r.contract_total, r.completed, r.backlog_amt) == (1510909, 519811, 991098)
    assert r.new_orders is None and r.opening_backlog is None


def test_quantity_subcolumns_are_not_amounts():
    r = map_order_table(_QTY_AMOUNT)[0]
    assert (r.contract_total, r.completed, r.backlog_amt) == (559105, 500000, 59105)


def test_aggregate_carries_new_fields():
    rows = map_order_table(_CONSTRUCTION_RF) * 6  # 12 rows -> detail aggregation
    agg = _aggregate_if_detail(rows)
    assert len(agg) == 1
    a = agg[0]
    assert a.layout == LAYOUT_ROLLFORWARD
    assert a.opening_backlog == 6 * (939 + 12302)
    assert a.backlog_amt == 6 * (819 + 10882)


# 01344336 FY2025 20260319001402 — merged "수량금액" sub-header is the amount column.
_MERGED_QTY_AMOUNT_HEADER = [
    ["품목", "수주일자", "납기", "수주총액", "기납품액", "수주잔고"],
    ["품목", "수주일자", "납기", "금액", "수량금액", "수량금액"],
    ["DeepMatcher 플랫폼 서비스", "2024-12-19", "2026-05-31", "400", "150", "250"],
]
# 20260408000011 — numbers only in the 수량 columns, 금액 "-": no amount is printed.
_QTY_ONLY_NUMBERS = [
    ["품목", "수주일자", "기간", "수주총액", "수주총액", "기납품액", "기납품액", "수주잔고", "수주잔고"],
    ["품목", "수주일자", "기간", "수량", "금액", "수량", "금액", "수량", "금액"],
    ["ESS CAN", "2025.06.25", "5년", "16,939,893", "-", "-", "-", "16,939,893", "-"],
]


def test_merged_quantity_amount_header_is_amount():
    r = map_order_table(_MERGED_QTY_AMOUNT_HEADER)[0]
    assert (r.contract_total, r.completed, r.backlog_amt) == (400, 150, 250)


def test_quantity_only_numbers_are_not_amounts():
    rows = map_order_table(_QTY_ONLY_NUMBERS)
    assert all(r.backlog_amt in (None, 0) and r.contract_total is None for r in rows), rows


# 삼성중공업 FY2019 20200330004469 — only "수량" columns are printed; they hold the amounts.
_QTY_LABEL_ONLY = [
    ["품목", "수주일자", "납기", "수주총액", "기납품액", "수주잔고"],
    ["품목", "수주일자", "납기", "수량", "수량", "수량"],
    ["조선 및 플랜트", "~ 2019.12.31", "-", "446,670", "305,319", "141,351"],
]
# 대우조선 FY2010 20170511004364 — "이월계약잔액" is the ending balance.
_CARRIED_ENDING = [
    ["구분", "기초계약잔액", "신규수주액", "기타증감액(*1)", "당기누적수익계상(*2)", "이월계약잔액"],
    ["조선", "19,175,969", "4,962,765", "(268,765)", "(8,155,197)", "15,714,772"],
]


def test_quantity_label_only_table_reads_amounts():
    r = map_order_table(_QTY_LABEL_ONLY)[0]
    assert (r.contract_total, r.completed, r.backlog_amt) == (446670, 305319, 141351)


def test_carried_forward_balance_is_ending():
    r = map_order_table(_CARRIED_ENDING)[0]
    assert r.layout == LAYOUT_ROLLFORWARD
    assert (r.opening_backlog, r.new_orders, r.completed, r.backlog_amt) == (
        19175969, 4962765 - 268765, 8155197, 15714772)
    assert r.opening_backlog + r.new_orders - r.completed == r.backlog_amt


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
