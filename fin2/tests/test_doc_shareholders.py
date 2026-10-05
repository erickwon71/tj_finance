"""API→문서 전환 Phase 2 — 주주 3종 매퍼 (fin2/layer3/doc_shareholders.py).
Grids are 삼양식품 2024 사업보고서(20250318001186) as stored by layer 2 (spans expanded)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.doc_shareholders import (map_major_shareholders, map_retail_ownership,
                                          map_shareholder_changes)

_BSH_SPCL = [
    ["성 명", "관 계", "주식의종류", "소유주식수 및 지분율", "소유주식수 및 지분율",
     "소유주식수 및 지분율", "소유주식수 및 지분율", "비고"],
    ["성 명", "관 계", "주식의종류", "기 초", "기 초", "기 말", "기 말", "비고"],
    ["성 명", "관 계", "주식의종류", "주식수", "지분율", "주식수", "지분율", "비고"],
    ["삼양라운드스퀘어(주)", "본인", "보통주", "2,630,587", "34.92", "2,630,587", "34.92", "사명변경"],
    ["전세경", "기타특수관계인", "보통주", "14,500", "0.19", "0", "0.00", "-"],
    ["계", "계", "보통주", "3,403,217", "45.18", "3,388,\n417", "44.98", "-"],
]


def test_major_shareholders_columns_by_header_leaf():
    rows = map_major_shareholders(_BSH_SPCL)
    assert rows[0] == {"name": "삼양라운드스퀘어(주)", "relation": "본인", "stock_kind": "보통주",
                       "shares_begin": 2630587, "pct_begin": 34.92, "shares_end": 2630587,
                       "pct_end": 34.92, "remark": "사명변경"}
    assert rows[1]["shares_end"] == 0 and rows[1]["pct_end"] == 0.0


def test_total_row_relation_null_and_linebreak_number():
    total = map_major_shareholders(_BSH_SPCL)[-1]
    assert total["relation"] is None
    assert total["shares_end"] == 3388417


def test_shareholder_changes():
    grid = [["변동일", "최대주주명", "소유주식수", "지분율", "변동원인", "비 고"],
            ["2022년 05월 10일", "삼양라운드스퀘어(주)", "2,630,587", "34.92", "합병에 따른 지분증가", "-"]]
    assert map_shareholder_changes(grid) == [{
        "change_on": "2022.05.10", "holder_name": "삼양라운드스퀘어(주)",
        "shares": 2630587, "pct": 34.92, "cause": "합병에 따른 지분증가"}]


def test_retail_ownership_two_ratio_columns():
    grid = [["구 분", "주주", "주주", "주주", "소유주식", "소유주식", "소유주식", "비 고"],
            ["구 분", "소액주주수", "전체주주수", "비율(%)", "소액주식수", "총발행주식수", "비율(%)", "비 고"],
            ["소액주주", "32,616", "32,630", "99.97", "3,408,786", "7,533,015", "45.26", "-"]]
    assert map_retail_ownership(grid) == {
        "holder_count": 32616, "holder_total_count": 32630, "holder_rate_pct": 99.97,
        "held_shares": 3408786, "total_shares": 7533015, "held_rate_pct": 45.26}


def test_retail_ownership_pre_2020_form():
    grid = [["구 분", "주주", "주주", "보유주식", "보유주식", "비 고"],
            ["구 분", "주주수", "비율", "주식수", "비율", "비 고"],
            ["소액주주", "8,673", "99.80", "2,490,005", "33.05", "-"]]
    assert map_retail_ownership(grid) == {
        "holder_count": 8673, "holder_total_count": None, "holder_rate_pct": 99.8,
        "held_shares": 2490005, "total_shares": None, "held_rate_pct": 33.05}
