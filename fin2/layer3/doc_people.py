"""계층3 — 임원(executives) · 직원(employee_stats)을 원문 '임원 및 직원 등의 현황' 표에서 만든다
(API→문서 전환 Phase 3, docs/plans/api_to_document_migration_plan_2026-10-05.md).

  SH5_DRCT_STT  임원 현황 → executives
  EMPLOYEE      직원 현황 → employee_stats

API 판과 다른 점(원문 기준으로 고친 것):
  · executives.is_registered / is_fulltime — API 판은 'Y'/'N' 만 참으로 읽어 원문 값
    ('사내이사'·'미등기'·'상근'·'비상근')이 대부분 NULL/거짓이었다(삼양식품 2024 부회장 김정수:
    원문 '사내이사', API 판 is_registered=false). 원문 문자열로 판정한다.
  · employee_stats.avg_tenure_years — 원문 '6년 5개월' 을 6.42 로 읽는다(API 판은 NULL).
  · 금액은 캡션 단위(천원 등)를 곱해 원으로 적재한다(API 판과 같은 원 단위).
"""
from __future__ import annotations

from typing import Optional

from fin2.layer3.doc_common import (coalesce, find_col, header_paths, main_grid, money_unit, norm,
                                    parse_int, parse_years, pick_filing_grids, split_header,
                                    text_or_none)

_REGISTERED = ("사내이사", "사외이사", "기타비상무", "감사", "등기임원", "이사")


def _registered(v: Optional[str]) -> Optional[bool]:
    t = norm(v)
    if not t or t == "-":
        return None
    if "미등기" in t:
        return False
    return True if any(k in t for k in _REGISTERED) else None


def _fulltime(v: Optional[str]) -> Optional[bool]:
    t = norm(v)
    if t.startswith("비상근"):
        return False
    if t.startswith("상근"):
        return True
    return None


def _cell(row, c) -> Optional[str]:
    return row[c] if c is not None and c < len(row) else None


def map_executives(grid) -> list[dict]:
    header, body = split_header(grid)
    p = header_paths(header)
    cols = {k: find_col(p, n) for k, n in (
        ("name", "성명"), ("gender", "성별"), ("birth", "출생"), ("position", "직위"),
        ("reg", "등기"), ("ft", "상근"), ("resp", "담당업무"), ("career", "주요경력"),
        ("rel", "최대주주"), ("period", "재직기간"), ("end", "임기만료"))}
    if cols["name"] is None:
        return []
    out = []
    for row in body:
        g = lambda k: _cell(row, cols[k])  # noqa: E731
        name = text_or_none(g("name"), 50)
        if not name or name == "-":
            continue
        out.append({
            "name": name, "gender": text_or_none(g("gender"), 4),
            "birth_ym": text_or_none(g("birth"), 10), "position": text_or_none(g("position"), 150),
            "is_registered": _registered(g("reg")), "is_fulltime": _fulltime(g("ft")),
            "responsibility": text_or_none(g("resp"), 300),
            "main_career": text_or_none(g("career"), 500),
            "shareholder_rel": text_or_none(g("rel"), 100),
            "tenure_period": text_or_none(g("period"), 60),
            "tenure_end": text_or_none(g("end"), 20),
        })
    return out


# '전체' is NOT a total: single-division companies name their only division '전체' (with 남/여
# rows under it — 1,026 filings mapped to nothing before this was dropped from the set).
_TOTAL_DIVISIONS = frozenset({"합계", "계", "총계"})


def map_employees(grid, unit: Optional[int]) -> list[dict]:
    header, body = split_header(grid)
    p = header_paths(header)
    c_div = 0
    c_sex = find_col(p, "성별")
    c_reg = coalesce(find_col(p, "정함이없는", leaf="전체"), find_col(p, "정함이없는"),
                     find_col(p, "정규직"))
    c_con = coalesce(find_col(p, "기간제", leaf="전체"), find_col(p, "기간제"),
                     find_col(p, "계약직"))
    c_tot = coalesce(find_col(p, "직원수", leaf="합계"), find_col(p, leaf="합계"))
    c_ten = find_col(p, "근속")
    c_sal = find_col(p, "급여총")
    c_avg = coalesce(find_col(p, "1인평균"), find_col(p, "평균급여"))
    c_rm = find_col(p, "비고")
    out = []
    for row in body:
        div = text_or_none(_cell(row, c_div), 60)
        if not div or norm(div) in _TOTAL_DIVISIONS:
            continue
        if div == "-":
            div = None   # single-division companies print '-' (API stores NULL)
        sal, avg = parse_int(_cell(row, c_sal)), parse_int(_cell(row, c_avg))
        out.append({
            "division": div, "sex": text_or_none(_cell(row, c_sex), 4),
            "regular_count": parse_int(_cell(row, c_reg)),
            "contract_count": parse_int(_cell(row, c_con)),
            "total_count": parse_int(_cell(row, c_tot)),
            "avg_tenure_years": parse_years(_cell(row, c_ten)),
            "annual_salary_total": sal * unit if sal is not None and unit else None,
            "avg_salary": avg * unit if avg is not None and unit else None,
            "remark": text_or_none(_cell(row, c_rm), 200),
        })
    return out


def build_rows(session, corps: list[str], fy_min: int = 2015) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"executives": [], "employee_stats": []}
    for (corp, fy), (rcept, grids) in pick_filing_grids(session, corps, "SH5_DRCT_STT",
                                                        fy_min).items():
        for r in map_executives(main_grid(grids)):
            out["executives"].append({"corp_code": corp, "fiscal_year": fy, **r})
    for (corp, fy), (rcept, grids) in pick_filing_grids(session, corps, "EMPLOYEE",
                                                        fy_min).items():
        for r in map_employees(main_grid(grids), money_unit(grids)):
            out["employee_stats"].append({"corp_code": corp, "fiscal_year": fy,
                                          "rcept_no": rcept, **r})
    return out
