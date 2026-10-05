"""계층3 — 임원 보수(exec_pay_summary · exec_pay_individual · executives.compensation)를 원문
'임원의 보수 등' 표에서 만든다 (API→문서 전환 Phase 4).

  SUB_CMPT       보수지급금액(이사·감사 전체)          → exec_pay_summary      (API hmvAuditAllSttus)
  SUB_CMPK_HIGH  개인별 보수지급금액(5억 이상 상위 5인) → exec_pay_individual   (API indvdlByPay)
  SUB_CMPK       이사·감사의 개인별 보수현황           → executives.compensation (API hmvAuditIndvdlBySttus)
금액은 캡션 단위(대개 천원)를 곱해 원으로 적재한다(API 판과 같은 원 단위).
"""
from __future__ import annotations

from typing import Optional

from fin2.layer3.doc_common import (coalesce, find_col, header_paths, main_grid, money_unit,
                                    norm, parse_int, pick_filing_grids, split_header,
                                    text_or_none)


def _won(v: Optional[str], unit: Optional[int]) -> Optional[int]:
    x = parse_int(v)
    return x * unit if x is not None and unit else None


def _cell(row, c):
    return row[c] if c is not None and c < len(row) else None


def map_pay_summary(grid, unit: Optional[int]) -> Optional[dict]:
    header, body = split_header(grid)
    p = header_paths(header)
    c_n, c_tot = find_col(p, "인원"), find_col(p, "보수총액")
    c_avg, c_rm = find_col(p, "평균"), find_col(p, "비고")
    row = next((r for r in body if parse_int(_cell(r, c_n)) is not None
                or parse_int(_cell(r, c_tot)) is not None), None)
    if row is None or c_tot is None:
        return None
    rm = text_or_none(_cell(row, c_rm), 200)
    return {"total_exec_count": parse_int(_cell(row, c_n)),
            "total_pay_amount": _won(_cell(row, c_tot), unit),
            "avg_pay_per_person": _won(_cell(row, c_avg), unit),
            "remark": None if rm == "-" else rm}


_TOTAL_ROW = frozenset({"계", "합계", "총계"})


def map_pay_summary_from_breakdown(grid, unit: Optional[int]) -> Optional[dict]:
    """2015-form fallback: no SUB_CMPT table, the 전체 figure is the '계' row of the 구분별
    table (SUB_CMPP) — the API's hmvAuditAllSttus value for those years is exactly that row
    (강원에너지 2015: 8명 · 824 백만원)."""
    header, body = split_header(grid)
    total = next((r for r in body if r and norm(r[0]) in _TOTAL_ROW), None)
    if total is None:
        return None
    return map_pay_summary(_as_summary(header, total), unit)


def _as_summary(header, total_row):
    """Drop the 구분 column so the row has the SUB_CMPT shape (인원수·보수총액·평균·비고)."""
    return [r[1:] for r in header] + [total_row[1:]]


def map_pay_individuals(grid, unit: Optional[int]) -> list[dict]:
    header, body = split_header(grid)
    p = header_paths(header)
    c_nm, c_pos = coalesce(find_col(p, "이름"), find_col(p, "성명")), find_col(p, "직위")
    c_tot = find_col(p, "보수총액", nth=0)
    if c_nm is None or c_tot is None:
        return []
    out = []
    for row in body:
        name = text_or_none(_cell(row, c_nm), 50)
        if not name or name == "-":
            continue
        out.append({"person_name": name, "position": text_or_none(_cell(row, c_pos), 100),
                    "total_pay_amount": _won(_cell(row, c_tot), unit),
                    "pay_detail": {"header": [list(x) for x in p], "row": row}})
    return out


def build_rows(session, corps: list[str], fy_min: int = 2015) -> dict:
    out: dict = {"exec_pay_summary": [], "exec_pay_individual": [], "compensation": {}}
    summary = pick_filing_grids(session, corps, "SUB_CMPT", fy_min)
    for (corp, fy), (rcept, grids) in summary.items():
        r = map_pay_summary(main_grid(grids), money_unit(grids))
        if r:
            out["exec_pay_summary"].append({"corp_code": corp, "fiscal_year": fy,
                                            "rcept_no": rcept, **r})
    for (corp, fy), (rcept, grids) in pick_filing_grids(session, corps, "SUB_CMPP", fy_min).items():
        if (corp, fy) in summary:
            continue
        r = map_pay_summary_from_breakdown(main_grid(grids), money_unit(grids))
        if r:
            out["exec_pay_summary"].append({"corp_code": corp, "fiscal_year": fy,
                                            "rcept_no": rcept, **r})
    for (corp, fy), (rcept, grids) in pick_filing_grids(session, corps, "SUB_CMPK_HIGH",
                                                        fy_min).items():
        for r in map_pay_individuals(main_grid(grids), money_unit(grids)):
            out["exec_pay_individual"].append({"corp_code": corp, "fiscal_year": fy,
                                               "rcept_no": rcept, **r})
    # executives.compensation: name → amount from the 이사·감사 개인별 table
    for (corp, fy), (_rcept, grids) in pick_filing_grids(session, corps, "SUB_CMPK",
                                                         fy_min).items():
        for r in map_pay_individuals(main_grid(grids), money_unit(grids)):
            if r["total_pay_amount"] is not None:
                out["compensation"][(corp, fy, norm(r["person_name"]))] = r["total_pay_amount"]
    return out
