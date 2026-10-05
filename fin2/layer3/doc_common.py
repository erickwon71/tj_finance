"""계층3 문서 섹션 매퍼 공통 도구 (API→문서 전환, docs/plans/api_to_document_migration_plan_2026-10-05.md).

입력은 계층2 `doc_section_tables` 뿐이다(R1).
  · `pick_filing_grids`  — (corp, FY) 마다 서식 코드 표가 있는 정본 필링 하나와 그 격자들
  · `split_header`/`header_paths` — 전개 격자의 머리행과 열별 머리 경로
  · `parse_int`/`parse_pct` — API 판 파서와 같은 계약(쉼표 제거, '-'·빈칸 → None, 그 외 실패 → None)
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import text

_WS = re.compile(r"\s+")

Grid = list[list[Optional[str]]]


def norm(s: Optional[str]) -> str:
    return _WS.sub("", s or "")


def parse_int(v: Optional[str]) -> Optional[int]:
    # Whitespace inside a number is layout, not content: '3,388,\n417' (삼양식품 2024 BSH_SPCL
    # 계 행) — same family as PARSING_RULES R150 (space after a thousands comma).
    v = norm(v)
    if not v or v == "-":
        return None
    try:
        return int(v.replace(",", ""))
    except ValueError:
        return None


def parse_pct(v: Optional[str]) -> Optional[float]:
    v = norm(v)
    if not v or v == "-":
        return None
    try:
        return float(v.replace(",", "").replace("%", ""))
    except ValueError:
        return None


def text_or_none(v: Optional[str], n: int) -> Optional[str]:
    v = (v or "").strip()
    return v[:n] if v else None


def _has_number(row) -> bool:
    return any(parse_pct(c) is not None for c in row[1:])


def split_header(grid: Grid) -> tuple[Grid, Grid]:
    """Split an expanded grid into (header rows, body rows).

    Standard-form tables usually put a row-spanning label in column 0 of every header row, so
    the header is the leading run of rows whose column 0 equals row 0's. When that run is a
    single row (EMPLOYEE: '직원' over '사업부문'), the header is instead the leading run of rows
    without any numeric cell (capped at 5).
    """
    if not grid:
        return [], []
    key = norm(grid[0][0] if grid[0] else "")
    n = 0
    while n < len(grid) and grid[n] and norm(grid[n][0]) == key:
        n += 1
    if n <= 1:
        m = 0
        while m < min(len(grid), 5) and not _has_number(grid[m]):
            m += 1
        n = max(n, m)
    return grid[:n], grid[n:]


_UNIT_RE = re.compile(r"단위[:：]?\(?(백만원|천원|원|억원)")
_UNIT_MULT = {"원": 1, "천원": 1_000, "백만원": 1_000_000, "억원": 100_000_000}


def money_unit(grids: list[Grid]) -> Optional[int]:
    """Won multiplier declared in the group's caption ('(단위 : 천원, 주, %)' → 1000).
    None when no money unit is declared — callers must not guess."""
    for g in grids:
        if len(g) > 2:
            continue                      # only caption-sized tables
        for row in g:
            for c in row:
                m = _UNIT_RE.search(norm(c))
                if m:
                    return _UNIT_MULT[m.group(1)]
    return None


_QTY_RE = re.compile(r"(천주|백만주|만주)")
_QTY_MULT = {"천주": 1_000, "만주": 10_000, "백만주": 1_000_000}


def qty_unit(grids: list[Grid]) -> int:
    """Share-count multiplier declared in the group's caption ('(단위 : 백만원, 천주, %)' → 1000).
    Defaults to 1 (주) — share counts are declared in 천주 only by exception."""
    for g in grids:
        if len(g) > 2:
            continue
        for row in g:
            for cell in row:
                t = norm(cell)
                if "단위" in t:
                    m = _QTY_RE.search(t)
                    if m:
                        return _QTY_MULT[m.group(1)]
    return 1


_TENURE_RE = re.compile(r"^(?:(\d+)년)?(?:(\d+)개월)?$")


def parse_years(v: Optional[str]) -> Optional[float]:
    """Average tenure: '6.4' / '6년 5개월' / '5개월' → years (2 decimals). Else None."""
    x = parse_pct(v)
    if x is not None:
        return x
    m = _TENURE_RE.match(norm(v))
    if not m or not any(m.groups()):
        return None
    return round(int(m.group(1) or 0) + int(m.group(2) or 0) / 12, 2)


def header_paths(header: Grid) -> list[tuple[str, ...]]:
    """Per column: normalized header texts top→bottom with consecutive duplicates collapsed."""
    width = max((len(r) for r in header), default=0)
    out = []
    for c in range(width):
        path: list[str] = []
        for r in header:
            t = norm(r[c]) if c < len(r) else ""
            if t and (not path or path[-1] != t):
                path.append(t)
        out.append(tuple(path))
    return out


def find_col(paths: list[tuple[str, ...]], *needles: str, leaf: Optional[str] = None,
             nth: int = 0) -> Optional[int]:
    """Index of the nth column whose header path contains every needle (substring match) and,
    if given, whose bottom header cell contains `leaf`. Use `leaf` for the measure: an upper
    banner like '소유주식수 및 지분율' contains both measures' names."""
    hits = [i for i, p in enumerate(paths)
            if p and all(any(n in seg for seg in p) for n in needles)
            and (leaf is None or leaf in p[-1])]
    return hits[nth] if len(hits) > nth else None


_FY_FILINGS_SQL = text("""
    SELECT corp_code, fiscal_year, rcept_no FROM filings
    WHERE corp_code = ANY(:corps) AND fiscal_period = 'FY' AND report_type = 'annual'
      AND fiscal_year >= :fy_min
    ORDER BY corp_code, fiscal_year, is_final DESC, filed_at DESC NULLS LAST, rcept_no DESC
""")

_GRIDS_SQL = text("""
    SELECT rcept_no, group_ord, grid FROM doc_section_tables
    WHERE rcept_no = ANY(:rcepts) AND aclass = :aclass
    ORDER BY rcept_no, table_ord
""")


def pick_filing_grids(session, corps: list[str], aclass: str,
                      fy_min: int = 2015) -> dict[tuple[str, int], tuple[str, list[Grid]]]:
    """(corp, FY) → (rcept_no, [grids of `aclass` in document order]).

    The filing is the newest (is_final first) annual report of that FY that actually holds an
    `aclass` table — an attachment-only amendment has no body, so the chain falls back to the
    original (same principle as layer-3 `select_canonical_rcepts`). Caption tables (group_ord 0,
    one row) are kept; mappers skip them by shape.
    """
    chains: dict[tuple[str, int], list[str]] = {}
    for c, y, r in session.execute(_FY_FILINGS_SQL, {"corps": corps, "fy_min": fy_min}):
        chains.setdefault((c, y), []).append(r)
    rcepts = [r for rs in chains.values() for r in rs]
    grids: dict[str, list[Grid]] = {}
    for r, _g, grid in session.execute(_GRIDS_SQL, {"rcepts": rcepts, "aclass": aclass}):
        grids.setdefault(r, []).append(grid)
    out = {}
    for key, chain in chains.items():
        rcept = next((r for r in chain if r in grids), None)
        if rcept is not None:
            out[key] = (rcept, grids[rcept])
    return out


_DATE_RE = re.compile(r"^(\d{4})(?:년|[.\-/])(\d{1,2})(?:월|[.\-/])(\d{1,2})일?\.?$")


def norm_date(v: Optional[str]) -> Optional[str]:
    """'2021년 08월 25일' / '2021-08-25' / '2021.8.25' → '2021.08.25' (the API's own
    first_acquired_date form). Anything else is returned as stripped text; '-' → None."""
    t = text_or_none(v, 40)
    if t is None or t == "-":
        return None
    m = _DATE_RE.match(norm(t))
    return f"{m.group(1)}.{int(m.group(2)):02d}.{int(m.group(3)):02d}" if m else t


def coalesce(*vals):
    """First value that is not None — column index 0 is valid, so never chain with `or`."""
    return next((v for v in vals if v is not None), None)


def main_grid(grids: list[Grid]) -> Optional[Grid]:
    """The data table of a TABLE-GROUP: the one with the most rows (the first is usually a
    one-row 기준일/단위 caption)."""
    return max(grids, key=len) if grids else None
