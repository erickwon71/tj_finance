"""계층3 — 배당(dividend_facts) 을 원문 '주요배당지표' 표에서 만든다 (API→문서 전환 Phase 1).

docs/plans/api_to_document_migration_plan_2026-10-05.md. 입력은 계층2 `doc_section_tables`
(aclass='DIVIDEND') 뿐이다(R1, 원문 파일 직접 접근 없음).

DART alotMatter API 의 응답은 이 표를 행 그대로 옮긴 것이다(se = 0열 항목명, stock_knd = 1열
주식종류, 병합이면 '-', thstrm = 당기 열). 그래서 API 판의 피벗 규칙
(구 `collector/dart_periodic._map_dividend`, 2026-10-05 삭제)을 원문 격자에 그대로 적용한다 — 컬럼 의미·단위
(배당총액 백만원, 비율 %) 모두 같다. 항목명은 공백을 지우고 비교한다(원문 표기 흔들림 흡수).

필링 선택: 같은 (corp, FY) 의 필링을 최신(is_final)→최초 순으로 보며 배당 표가 실제로 있는
첫 필링. 첨부정정은 본문이 없어 표가 없으므로 자연히 원본으로 내려간다(계층3
`select_canonical_rcepts` 의 statement 별 체인 규칙과 같은 원리).
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import text

from fin2.layer3.doc_common import parse_int as _num, parse_pct as _pct

_WS = re.compile(r"\s+")

# normalized label -> (column, stock kind or None for any, parser)
_FIELDS = {
    ("현금배당금총액(백만원)", None): "total_dividend_amount",
    ("(연결)현금배당성향(%)", None): "payout_ratio",
    ("현금배당수익률(%)", "보통주"): "dividend_yield_common",
    ("주당현금배당금(원)", "보통주"): "dps_common",
    ("주당현금배당금(원)", "우선주"): "dps_pref",
    ("주당주식배당(주)", "보통주"): "stock_dividend_ratio",
}
_INT_COLS = frozenset({"total_dividend_amount", "dps_common", "dps_pref"})


def _norm(s: Optional[str]) -> str:
    return _WS.sub("", s or "")


def _current_col(grid: list[list[Optional[str]]]) -> Optional[int]:
    """Column whose header reads '당기' (the filing's own year). None if absent — no guess."""
    for row in grid[:3]:
        for i, c in enumerate(row):
            if _norm(c) == "당기":
                return i
    return None


def map_dividend_grid(grid: list[list[Optional[str]]]) -> Optional[dict]:
    """주요배당지표 격자 → dividend_facts 값 컬럼 dict. 당기 열을 못 찾으면 None."""
    cur = _current_col(grid)
    if cur is None:
        return None
    out: dict = {}
    for row in grid:
        if len(row) <= cur:
            continue
        label = _norm(row[0])
        knd_raw = _norm(row[1]) if len(row) > 1 else ""
        knd = "-" if knd_raw in ("", label) else knd_raw
        for (want_label, want_knd), col in _FIELDS.items():
            if label != want_label or (want_knd is not None and knd != want_knd):
                continue
            if col in out:
                continue  # first matching row wins (API parity: rows are unique per se/knd)
            out[col] = _num(row[cur]) if col in _INT_COLS else _pct(row[cur])
    return out


_DIVIDEND_TABLES_SQL = text("""
    SELECT d.rcept_no, d.grid
    FROM doc_section_tables d
    WHERE d.rcept_no = ANY(:rcepts) AND d.aclass = 'DIVIDEND'
    ORDER BY d.rcept_no, d.n_rows DESC, d.table_ord
""")

_FY_FILINGS_SQL = text("""
    SELECT corp_code, fiscal_year, rcept_no FROM filings
    WHERE corp_code = ANY(:corps) AND fiscal_period = 'FY' AND report_type = 'annual'
      AND fiscal_year >= :fy_min
    ORDER BY corp_code, fiscal_year, is_final DESC, filed_at DESC NULLS LAST, rcept_no DESC
""")


def build_dividend_rows(session, corps: list[str], fy_min: int = 2015) -> list[dict]:
    """(corp, FY) → dividend_facts 행(dict). 배당 표가 있는 필링이 없으면 행을 만들지 않는다."""
    chains: dict[tuple[str, int], list[str]] = {}
    for c, y, r in session.execute(_FY_FILINGS_SQL, {"corps": corps, "fy_min": fy_min}):
        chains.setdefault((c, y), []).append(r)
    all_rcepts = [r for rs in chains.values() for r in rs]
    grids: dict[str, list] = {}
    for rcept, grid in session.execute(_DIVIDEND_TABLES_SQL, {"rcepts": all_rcepts}):
        grids.setdefault(rcept, grid)          # largest DIVIDEND table of the filing
    rows = []
    for (corp, fy), chain in chains.items():
        rcept = next((r for r in chain if r in grids), None)
        if rcept is None:
            continue
        vals = map_dividend_grid(grids[rcept])
        if vals is None:
            continue
        rows.append({"corp_code": corp, "fiscal_year": fy, "rcept_no": rcept, **vals,
                     # provenance: the source grid replaces the API response kept in `raw`
                     "raw": {"source": "doc_section_tables", "aclass": "DIVIDEND",
                             "rcept_no": rcept, "grid": grids[rcept]}})
    return rows

