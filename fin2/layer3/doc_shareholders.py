"""계층3 — 주주 3종(major_shareholders · shareholder_changes · retail_ownership)을 원문
'주주에 관한 사항' 표에서 만든다 (API→문서 전환 Phase 2).

서식 코드 → 테이블 (DART hyslrSttus / hyslrChgSttus / mrhlSttus API 가 같은 표를 옮긴 것):
  BSH_SPCL    최대주주 및 특수관계인의 주식소유 현황 → major_shareholders
  BSH_CHA     최대주주 변동현황                     → shareholder_changes
  SH4_PRE_STT 소액주주 현황                         → retail_ownership
열은 위치가 아니라 머리 경로(헤더 텍스트)로 찾는다(`doc_common.find_col`). 숫자 파싱은 API 판과
같은 계약이다.
"""
from __future__ import annotations

from typing import Optional

from fin2.layer3.doc_common import (coalesce, find_col, header_paths, main_grid, norm,
                                    norm_date, parse_int, parse_pct, pick_filing_grids,
                                    split_header, text_or_none)


def map_major_shareholders(grid) -> list[dict]:
    header, body = split_header(grid)
    p = header_paths(header)
    c_name, c_rel, c_knd = find_col(p, "성명"), find_col(p, "관계"), find_col(p, "종류")
    c_sb, c_pb = find_col(p, "기초", leaf="주식수"), find_col(p, "기초", leaf="지분율")
    c_se, c_pe = find_col(p, "기말", leaf="주식수"), find_col(p, "기말", leaf="지분율")
    c_rm = find_col(p, "비고")
    if None in (c_name, c_sb, c_se):
        return []

    def cell(row, c) -> Optional[str]:
        return row[c] if c is not None and c < len(row) else None

    out = []
    for row in body:
        name = text_or_none(cell(row, c_name), 100)
        if not name:
            continue
        rel = text_or_none(cell(row, c_rel), 50)
        if rel is not None and norm(rel) == norm(name):
            rel = None   # '계' row: the name cell spans the relation column
        out.append({
            "name": name, "relation": rel,
            "stock_kind": text_or_none(cell(row, c_knd), 20),
            "shares_begin": parse_int(cell(row, c_sb)), "pct_begin": parse_pct(cell(row, c_pb)),
            "shares_end": parse_int(cell(row, c_se)), "pct_end": parse_pct(cell(row, c_pe)),
            "remark": text_or_none(cell(row, c_rm), 200),
        })
    return out


def map_shareholder_changes(grid) -> list[dict]:
    header, body = split_header(grid)
    p = header_paths(header)
    c_on, c_nm = find_col(p, "변동일"), find_col(p, "최대주주")
    c_sh, c_pct = find_col(p, "주식수"), find_col(p, "지분율")
    c_cause = find_col(p, "변동원인")
    if None in (c_on, c_nm):
        return []
    out = []
    for row in body:
        g = lambda c: row[c] if c is not None and c < len(row) else None  # noqa: E731
        on = norm_date(g(c_on))
        if not on:
            continue
        out.append({"change_on": on[:20], "holder_name": text_or_none(g(c_nm), 100),
                    "shares": parse_int(g(c_sh)), "pct": parse_pct(g(c_pct)),
                    "cause": text_or_none(g(c_cause), 200)})
    return out


def map_retail_ownership(grid) -> Optional[dict]:
    header, body = split_header(grid)
    p = header_paths(header)
    # 2020+ form: 소액주주수/전체주주수/비율/소액주식수/총발행주식수/비율.
    # pre-2020 form (삼양식품 2015~2019): 주주>주주수·비율, 보유주식>주식수·비율 (no totals).
    cols = {
        "holder_count": coalesce(find_col(p, "소액주주수"), find_col(p, "주주", leaf="주주수")),
        "holder_total_count": find_col(p, "전체주주수"),
        "holder_rate_pct": find_col(p, leaf="비율", nth=0),
        "held_shares": coalesce(find_col(p, "소액주식수"), find_col(p, "소액", "주식수"),
                                find_col(p, "보유주식", leaf="주식수")),
        "total_shares": coalesce(find_col(p, "총발행주식수"), find_col(p, "발행주식")),
        "held_rate_pct": find_col(p, leaf="비율", nth=1),
    }
    row = next((r for r in body if "소액" in norm(r[0])), None)
    if row is None or cols["holder_count"] is None:
        return None
    out = {}
    for k, c in cols.items():
        v = row[c] if c is not None and c < len(row) else None
        out[k] = parse_pct(v) if k.endswith("_pct") else parse_int(v)
    return out


def build_rows(session, corps: list[str], fy_min: int = 2015) -> dict[str, list[dict]]:
    """→ {'major_shareholders': [...], 'shareholder_changes': [...], 'retail_ownership': [...]}"""
    out: dict[str, list[dict]] = {"major_shareholders": [], "shareholder_changes": [],
                                  "retail_ownership": []}
    specs = (("BSH_SPCL", "major_shareholders", map_major_shareholders),
             ("BSH_CHA", "shareholder_changes", map_shareholder_changes),
             ("SH4_PRE_STT", "retail_ownership", map_retail_ownership))
    for aclass, table, mapper in specs:
        for (corp, fy), (rcept, grids) in pick_filing_grids(session, corps, aclass, fy_min).items():
            mapped = mapper(main_grid(grids))
            if not mapped:
                continue
            for r in (mapped if isinstance(mapped, list) else [mapped]):
                out[table].append({"corp_code": corp, "fiscal_year": fy, "rcept_no": rcept, **r})
    return out
