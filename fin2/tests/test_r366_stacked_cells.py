"""R366: stacked amount cells (one value per item per line) make no row; wrapped numbers are joined."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from collector.biz_metrics import _map_row  # noqa: E402
from fin2.extract.biz_section import is_stacked_amount_cell, join_wrapped_number  # noqa: E402


def test_stacked_cell_detection():
    assert is_stacked_amount_cell("167,334\n23,018")            # 금강공업 FY2015 (after R246 re-read)
    assert is_stacked_amount_cell("14,884\n-\n14,884")          # 내수 | 수출 | 계 with an empty line
    assert not is_stacked_amount_cell("102,759,182\n(72,210)")  # amount + bracketed note
    assert not is_stacked_amount_cell("(18,3\n99)")             # one wrapped number
    assert not is_stacked_amount_cell("1,\n918")
    assert not is_stacked_amount_cell("-\n-")
    assert not is_stacked_amount_cell("1,234")


def test_wrapped_number_join():
    assert join_wrapped_number("1,\n918") == "1,918"            # SOOP 2020 반기 sales 기타
    assert join_wrapped_number("(18,3\n99)") == "(18,399)"      # 더라미 2020 1분기 중단손익
    assert join_wrapped_number("1,000 2,000") == "1,000 2,000"


# 금강공업 FY2019 20200330003571 sales table: each cell stacks 내수 / 수출 / 계.
_KUMKANG_SALES = [
    ["구 분", "품목", "매출유형", "제41기 연간", "제40기 연간", "제39기 연간"],
    ["구 분", "품목", "매출유형", "금 액", "금 액", "금 액"],
    ["제 품", "강  관", "내  수수  출계", "89,661\n18,076\n107,737", "82,446\n8,281\n90,727",
     "92,808\n10,791\n103,599"],
    ["제 품", "가설재", "내  수수  출계", "14,884\n-\n14,884", "3,600\n-\n3,600", "6,807\n-\n6,807"],
]
# SOOP 2020 반기 20200814002165: "1,\n918" is 1,918.
_SOOP_SALES = [
    ["매출구분", "매출구분", "제25기 반기(2020년)", "제25기 반기(2020년)"],
    ["매출구분", "매출구분", "매출액", "매출비중"],
    ["3", "멀티플랫폼", "2,924", "3.4%"],
    ["4", "기타", "1,\n918", "1.5%"],
]


def test_sales_mapper_skips_stacked_rows_and_joins_wrapped():
    assert _map_row("sales", "sales", "", _KUMKANG_SALES, 2019) == []
    rows = _map_row("sales", "sales", "", _SOOP_SALES, 2020)
    assert {r["item"] or r["segment"]: r["value"] for r in rows}["기타"] == 1918


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
