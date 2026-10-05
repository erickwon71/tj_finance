"""API→문서 전환 Phase 1 — dividend_facts from the '주요배당지표' grid (fin2/layer3/doc_dividend.py)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.doc_dividend import map_dividend_grid

# 삼양식품 2024 사업보고서(20250318001186) DIVIDEND table, as stored by layer 2 (spans expanded).
_SAMYANG_2024 = [
    ["구   분", "주식의 종류", "당기", "전기", "전전기"],
    ["구   분", "주식의 종류", "제64기", "제63기", "제62기"],
    ["주당액면가액(원)", "주당액면가액(원)", "5,000", "5,000", "5,000"],
    ["(연결)당기순이익(백만원)", "(연결)당기순이익(백만원)", "271,256", "126,591", "80,271"],
    ["현금배당금총액(백만원)", "현금배당금총액(백만원)", "24,612", "15,662", "10,456"],
    ["주식배당금총액(백만원)", "주식배당금총액(백만원)", "-", "-", "-"],
    ["(연결)현금배당성향(%)", "(연결)현금배당성향(%)", "9.10", "12.40", "13.00"],
    ["현금배당수익률(%)", "보통주", "0.40", "0.90", "1.10"],
    ["현금배당수익률(%)", "우선주", "-", "-", "-"],
    ["주식배당수익률(%)", "보통주", "-", "-", "-"],
    ["주당 현금배당금(원)", "보통주", "3,300", "2,100", "1,400"],
    ["주당 현금배당금(원)", "우선주", "-", "-", "-"],
    ["주당 주식배당(주)", "보통주", "-", "-", "-"],
]


def test_samyang_2024_matches_api_values():
    assert map_dividend_grid(_SAMYANG_2024) == {
        "total_dividend_amount": 24612, "payout_ratio": 9.1,
        "dividend_yield_common": 0.4, "dps_common": 3300, "dps_pref": None,
        "stock_dividend_ratio": None,
    }


def test_label_whitespace_variants_match():
    grid = [["구분", "종류", "당 기"], ["주당현금배당금 (원)", "보통주", "1,000"]]
    assert map_dividend_grid(grid)["dps_common"] == 1000


def test_no_current_column_header_means_no_row():
    grid = [["구분", "종류", "제64기"], ["주당 현금배당금(원)", "보통주", "1,000"]]
    assert map_dividend_grid(grid) is None


def test_unparseable_cell_is_none_not_guessed():
    grid = [["구분", "종류", "당기"], ["주당 현금배당금(원)", "보통주", "1,000(*)"]]
    assert map_dividend_grid(grid)["dps_common"] is None
