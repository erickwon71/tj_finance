"""계층3 — 타법인출자(other_investments)를 원문 '타법인출자 현황(상세)' 표에서 만든다
(API→문서 전환 Phase 5). 서식 코드 INV_PRT (DART otrCprInvstmntSttus 가 같은 표를 옮긴 것).

열은 3단 머리 경로로 찾는다(기초잔액/증가(감소)/기말잔액 × 수량/지분율/장부가액, 최근사업연도
재무현황 × 총자산/당기순손익). 금액은 캡션 단위(대개 천원)를 곱해 원으로 적재한다. API 판처럼
합계 행도 담는다(이름은 '합계' 로 정규화).
"""
from __future__ import annotations

from typing import Optional

from fin2.layer3.doc_common import (find_col, header_paths, main_grid, money_unit, norm,
                                    norm_date, parse_int, parse_pct, pick_filing_grids, qty_unit,
                                    split_header, text_or_none)

_TOTAL_NAMES = frozenset({"합계", "계", "총계"})
def _dash_none(v: Optional[str]) -> Optional[str]:
    return None if v == "-" else v


def _cell(row, c):
    return row[c] if c is not None and c < len(row) else None


def map_investments(grid, unit: Optional[int], qty: int = 1) -> list[dict]:
    header, body = split_header(grid)
    p = header_paths(header)
    c = {
        "name": find_col(p, "법인명"), "date": find_col(p, "최초취득일"),
        "purpose": find_col(p, "출자목적"), "first_amt": find_col(p, "최초취득금액"),
        "bq": find_col(p, "기초", leaf="수량"), "bp": find_col(p, "기초", leaf="지분율"),
        "bb": find_col(p, "기초", leaf="장부가액"),
        "eq": find_col(p, "기말", leaf="수량"), "ep": find_col(p, "기말", leaf="지분율"),
        "eb": find_col(p, "기말", leaf="장부가액"),
        "ta": find_col(p, "재무현황", leaf="총자산"), "ni": find_col(p, "재무현황", leaf="순손"),
    }
    if c["name"] is None or c["eb"] is None:
        return []

    def shares(row, k):
        x = parse_int(_cell(row, c[k]))
        return x * qty if x is not None else None

    def won(row, k):
        x = parse_int(_cell(row, c[k]))
        return x * unit if x is not None and unit else None

    out = []
    for row in body:
        name = text_or_none(_cell(row, c["name"]), 150)
        if not name or name == "-":
            continue
        if norm(name) in _TOTAL_NAMES:
            name = "합계"
        date = norm_date(_cell(row, c["date"]))
        out.append({
            "investee_name": name,
            "first_acquired_date": None if name == "합계" else date,
            "purpose": None if name == "합계" else _dash_none(text_or_none(_cell(row, c["purpose"]), 60)),
            "first_acquired_amount": won(row, "first_amt"),
            "begin_qty": shares(row, "bq"), "begin_pct": parse_pct(_cell(row, c["bp"])),
            "begin_book_value": won(row, "bb"),
            "end_qty": shares(row, "eq"), "end_pct": parse_pct(_cell(row, c["ep"])),
            "end_book_value": won(row, "eb"),
            "investee_total_assets": won(row, "ta"), "investee_net_income": won(row, "ni"),
        })
    return out


def build_rows(session, corps: list[str], fy_min: int = 2015) -> list[dict]:
    out = []
    for (corp, fy), (rcept, grids) in pick_filing_grids(session, corps, "INV_PRT", fy_min).items():
        for r in map_investments(main_grid(grids), money_unit(grids), qty_unit(grids)):
            out.append({"corp_code": corp, "fiscal_year": fy, "rcept_no": rcept, **r})
    return out
