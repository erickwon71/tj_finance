"""R354 - sales period header '25(당)기' / '25기 3분기' is a header, not a data row (이지케어텍 00490090)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.sales_section import SalesTable, _is_sales_period_cell, map_sales_table  # noqa: E402


def test_period_cells():
    for c in ("25(당)기", "25 (당) 기", "25기 3분기", "25기 반기", "56기 반기", "제58(당)기"):
        assert _is_sales_period_cell(c), c
    for c in ("1,999", "25", "3,089"):
        assert not _is_sales_period_cell(c), c


def test_ezcaretech_fy2025_dang_gi_header():
    # 20250618000187 FY2025 (백만원): total 72,642 = IS consolidated revenue 72,641.5M
    grid = [["사업부문", "매출유형", "품  목", "품  목", "25(당)기", "24기", "23기"],
            ["클라우드 (Cloud)", "용역", "클라우드 서비스 수익", "합 계", "5,468", "7,157", "8,365"],
            ["합     계", "합     계", "합     계", "합     계", "72,642", "67,943", "73,187"]]
    rows = map_sales_table(SalesTable(narrative="(단위 : 백만원)", grid=grid), 2025)
    got = {(r.value, r.period_year, r.period_label) for r in rows}
    assert (72642.0, 2025, "제25기") in got and (73187.0, 2023, "제23기") in got
    assert all(r.value not in (25.0, 24.0, 23.0) for r in rows)


def test_interim_suffix_header_row_not_read_as_values():
    # 대한항공 2017 H1: '56기 반기' used to make the header row data (values 56/55/54, unit '기')
    grid = [["구 분", "56기 반기", "55기", "54기"],
            ["총매출액", "5,492,648", "10,995,413", "10,628,613"]]
    rows = map_sales_table(SalesTable(narrative="(단위 : 백만원)", grid=grid), 2017)
    assert [(r.value, r.period_year) for r in rows] == [
        (5492648.0, 2017), (10995413.0, 2016), (10628613.0, 2015)]
