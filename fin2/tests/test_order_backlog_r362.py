"""R362: business combination / disposal columns of an order rollforward go to scope_change."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.order_backlog import (  # noqa: E402
    LAYOUT_ROLLFORWARD, _aggregate_if_detail, _col_kind, _join_wrapped_number, is_prior_period_row,
    map_order_table)

# HD현대중공업 FY2025 20260320000859 table_ord=20 (HD현대미포 merger in the year).
_HHI_2025 = [
    ["품목", "수주일자", "납기", "기초수주잔액", "기초수주잔액", "사업결합", "사업결합", "신규증감", "신규증감",
     "기납품액", "기납품액", "기말수주잔고", "기말수주잔고"],
    ["품목", "수주일자", "납기", "수량", "금액", "수량", "금액", "수량", "금액", "수량", "금액", "수량", "금액"],
    ["조       선", "'25.12.31일까지", "-", "-", "33,937,341", "-", "11,376,357", "-", "11,500,524", "-",
     "(12,463,097)", "-", "44,351,125"],
    ["해양플랜트", "'25.12.31일까지", "-", "-", "3,629,748", "-", "-", "-", "54,367", "-", "(1,239,028)",
     "-", "2,445,087"],
    ["합 계", "합 계", "합 계", "-", "46,931,768", "-", "11,376,357", "-", "15,656,980", "-", "(17,580,633)",
     "-", "56,384,472"],
]
# 동원시스템즈 FY2018 20190329000207 table_ord=8.
_DONGWON_2018 = [
    ["내    역", "기초공사 계약잔액", "신규계약 및계약변경액", "공사(분양)수익계상액", "종속기업처분으로 제거",
     "기말공사 계약잔액"],
    ["도급공사", "541,286,219", "87,560,892", "49,920,406", "(578,926,705)", "-"],
    ["합    계", "544,284,616", "87,560,892", "48,707,880", "(583,137,628)", "-"],
]


def test_scope_keywords():
    assert _col_kind("사업결합 금액") == "scope"
    assert _col_kind("종속기업처분으로 제거") == "scope"
    assert _col_kind("신규증감 금액") == "new"


def test_hhi_business_combination_not_in_category_or_new_orders():
    rows = map_order_table(_HHI_2025)
    by = {r.category: r for r in rows}
    assert set(by) == {"조       선", "해양플랜트", "합 계"}, list(by)
    r = by["조       선"]
    assert r.layout == LAYOUT_ROLLFORWARD
    assert (r.opening_backlog, r.scope_change, r.new_orders, r.completed, r.backlog_amt) == (
        33937341, 11376357, 11500524, 12463097, 44351125)
    assert r.opening_backlog + r.new_orders + r.scope_change - r.completed == r.backlog_amt
    assert by["해양플랜트"].scope_change is None  # "-" is not a number
    t = by["합 계"]
    assert t.opening_backlog + t.new_orders + t.scope_change - t.completed == t.backlog_amt


def test_dongwon_disposal_keeps_printed_sign():
    rows = map_order_table(_DONGWON_2018)
    assert [r.category for r in rows] == ["도급공사", "합    계"]
    r = rows[0]
    assert (r.opening_backlog, r.new_orders, r.completed, r.scope_change, r.backlog_amt) == (
        541286219, 87560892, 49920406, -578926705, 0)


def test_aggregate_sums_scope_change():
    one = map_order_table(_HHI_2025)[0]
    agg = _aggregate_if_detail([one] * 11)
    assert agg[0].scope_change == 11376357 * 11


# 동원시스템즈 FY2018 table_ord=11 — the prior-period table printed after the current one.
_DONGWON_2018_PRIOR = [
    ["내    역", "기초공사 계약잔액", "신규계약 및계약변경액", "공사(분양)수익계상액", "기말공사 계약잔액"],
    ["도급공사", "384,766,830", "393,639,016", "(237,119,627)", "541,286,219"],
]


def test_prior_period_table_does_not_overwrite_current():
    cur = map_order_table(_DONGWON_2018)[0].__dict__
    prior = map_order_table(_DONGWON_2018_PRIOR)[0].__dict__
    assert is_prior_period_row(prior, cur)
    assert not is_prior_period_row(cur, prior)
    # same values (amendment reprint) are not a prior period
    assert not is_prior_period_row(dict(cur), cur)
    # cumulative tables have no opening balance — never judged
    assert not is_prior_period_row({**prior, "layout": "cumulative"}, cur)


# R363 — 디와이피엔에프 FY2023 20240403001366 table_ord=3 and 현대무벡스 2024 Q1 20240516001786 table_ord=9.
_DYPNF_2023 = [
    ["(단위: 천원)"] * 5,
    ["구      분", "기초 공사계약잔액", "증감액(*1)", "공사수익", "기말 공사계약잔액"],
    ["국내공사", "70,113,936", "384,361,375", "(102,523,650)", "351,951,66\n1"],
]
_MOVEX_2024Q1 = [
    ["품목", "수주일자", "수주총액", "기납품액", "수주잔고"],
    ["품목", "수주일자", "금액", "금액", "금액"],
    ["물류자동화", "2024.03.31. 까지", "3\n\n79\n,584\n,983", "41,790,084", "337\n,794\n,899"],
    ["IT서비스", "2024.03.31. 까지", "20,770,841", "5,502,052", "15,268,789"],
]


def test_wrapped_number_join_is_strict():
    assert _join_wrapped_number("351,951,66\n1") == "351,951,661"
    assert _join_wrapped_number("(1,234,56\n7)") == "(1,234,567)"
    assert _join_wrapped_number("1,000 2,000") == "1,000 2,000"  # two printed numbers
    assert _join_wrapped_number("12 345") == "12 345"  # no thousands grouping
    assert _join_wrapped_number("1,234,567") == "1,234,567"


def test_wrapped_cells_read_whole_number():
    r = map_order_table(_DYPNF_2023)[0]
    assert r.backlog_amt == 351951661
    assert r.opening_backlog + r.new_orders - r.completed == r.backlog_amt
    rows = {x.category: x for x in map_order_table(_MOVEX_2024Q1)}
    m = rows["물류자동화"]
    assert (m.contract_total, m.completed, m.backlog_amt) == (379584983, 41790084, 337794899)


# R364 — 파인텍 FY2016 20170330000725 table_ord=14, 두산에너빌리티 FY2014 "수주잔고증감액".
_FINETEK_2016 = [
    ["구 분", "기초잔액", "연결범위의 변동", "계약잔액 변경", "기납품액", "수주잔고"],
    ["당기", "-", "9,936,860", "71,295,625", "64,286,540", "16,945,945"],
]


def test_balance_change_header_is_period_change():
    assert _col_kind("계약잔액 변경") == "new"
    assert _col_kind("수주잔고증감액") == "new"
    assert _col_kind("기말수주잔고") == "backlog"
    assert _col_kind("기초공사 계약잔액") == "opening"
    r = map_order_table(_FINETEK_2016)[0]
    assert (r.scope_change, r.new_orders, r.completed, r.backlog_amt) == (9936860, 71295625, 64286540, 16945945)
    assert r.new_orders + r.scope_change - r.completed == r.backlog_amt


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
