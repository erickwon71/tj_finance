#!/usr/bin/env python
"""API→문서 전환 검증 (READ-ONLY) — 원문판(계층3 doc_* 매퍼) vs API 판 테이블, 전 도메인.

docs/plans/api_to_document_migration_plan_2026-10-05.md §4. API 는 정답이 아니다 — 불일치는
표본을 원문 대조로 판정한다. 비교 단위:
  · (corp, FY) 그룹의 행 **다중집합**(값 튜플) — 그룹 완전일치율
  · 행 단위 재현율(API 행 중 원문판에 같은 튜플이 있는 비율)·정밀도
문자열은 공백 제거, 비율은 소수 2자리로 맞춘다. 값이 전부 NULL 인 행(API 의 '변동 없음' 자리표시)은
양쪽에서 뺀다.

    python scripts/compare_doc_vs_api_2026-10-05.py                  # 전 도메인
    python scripts/compare_doc_vs_api_2026-10-05.py --only dividend_facts --samples 15
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.layer3 import (doc_dividend, doc_investments, doc_pay, doc_people, doc_shareholders,
                         doc_treasury)
from fin2.layer3.doc_common import norm, norm_date

# table -> value columns compared
SPECS = {
    "dividend_facts": ("dps_common", "dps_pref", "total_dividend_amount", "payout_ratio",
                       "dividend_yield_common", "stock_dividend_ratio"),
    "major_shareholders": ("name", "stock_kind", "shares_begin", "pct_begin", "shares_end",
                           "pct_end"),
    "shareholder_changes": ("change_on", "holder_name", "shares", "pct"),
    "retail_ownership": ("holder_count", "holder_total_count", "holder_rate_pct", "held_shares",
                         "total_shares", "held_rate_pct"),
    "employee_stats": ("division", "sex", "regular_count", "contract_count", "total_count",
                       "annual_salary_total", "avg_salary"),
    "executives": ("name", "gender", "position"),
    "exec_pay_summary": ("total_exec_count", "total_pay_amount", "avg_pay_per_person"),
    "exec_pay_individual": ("person_name", "total_pay_amount"),
    "other_investments": ("investee_name", "first_acquired_amount", "begin_qty", "begin_pct",
                          "begin_book_value", "end_qty", "end_pct", "end_book_value",
                          "investee_total_assets", "investee_net_income"),
    "treasury_activity": ("stock_kind", "qty_begin", "qty_acquired", "qty_disposed",
                          "qty_incinerated", "qty_end"),
}


def _v(x):
    if isinstance(x, str):
        return norm(x)
    if isinstance(x, float):
        return round(x, 2)
    return x


_DATE_COLS = frozenset({"change_on", "first_acquired_date"})


def _tuple(row, cols):
    return tuple(_v(norm_date(row.get(c)) if c in _DATE_COLS else row.get(c)) for c in cols)


def _doc_rows(session, table: str, corps: list[str]) -> list[dict]:
    if table == "dividend_facts":
        return doc_dividend.build_dividend_rows(session, corps)
    if table in ("major_shareholders", "shareholder_changes", "retail_ownership"):
        return doc_shareholders.build_rows(session, corps)[table]
    if table in ("executives", "employee_stats"):
        return doc_people.build_rows(session, corps)[table]
    if table in ("exec_pay_summary", "exec_pay_individual"):
        return doc_pay.build_rows(session, corps)[table]
    if table == "other_investments":
        return doc_investments.build_rows(session, corps)
    if table == "treasury_activity":
        return doc_treasury.build_rows(session, corps)
    raise KeyError(table)


def compare(session, table: str, samples: int) -> None:
    cols = SPECS[table]
    api_rows = [dict(r) for r in session.execute(text(
        f"SELECT * FROM {table} WHERE fiscal_year BETWEEN 2015 AND 2025")).mappings()]
    corps = sorted({r["corp_code"] for r in api_rows})
    doc_rows = []
    for i in range(0, len(corps), 200):
        doc_rows += [r for r in _doc_rows(session, table, corps[i:i + 200])
                     if r["fiscal_year"] <= 2025]

    def groups(rows):
        g = defaultdict(Counter)
        for r in rows:
            t = _tuple(r, cols)
            if all(x is None or x == "" for x in t):
                continue
            g[(r["corp_code"], r["fiscal_year"])][t] += 1
        return g

    ga, gd = groups(api_rows), groups(doc_rows)
    both = set(ga) & set(gd)
    exact = sum(1 for k in both if ga[k] == gd[k])
    api_n = sum(sum(c.values()) for k, c in ga.items() if k in both)
    doc_n = sum(sum(c.values()) for k, c in gd.items() if k in both)
    hit = sum(sum((ga[k] & gd[k]).values()) for k in both)
    print(f"\n=== {table}")
    print(f"groups API {len(ga):,} · doc {len(gd):,} · both {len(both):,} · "
          f"API-only {len(set(ga) - set(gd)):,} · doc-only {len(set(gd) - set(ga)):,}")
    if both:
        print(f"group exact {exact:,}/{len(both):,} = {100 * exact / len(both):.2f}% · "
              f"row recall {100 * hit / max(api_n, 1):.2f}% · row precision "
              f"{100 * hit / max(doc_n, 1):.2f}%")
    # per-column mismatch for single-row groups (where rows align 1:1)
    col_diff = Counter()
    shown = 0
    for k in sorted(both):
        if ga[k] == gd[k]:
            continue
        a_only, d_only = ga[k] - gd[k], gd[k] - ga[k]
        if len(a_only) == 1 and len(d_only) == 1:
            ta, td = next(iter(a_only)), next(iter(d_only))
            for c, x, y in zip(cols, ta, td):
                if x != y:
                    col_diff[c] += 1
        if shown < samples:
            shown += 1
            print(f"  {k}: API-only {list(a_only.items())[:2]} | doc-only {list(d_only.items())[:2]}")
    if col_diff:
        print("  1:1 column mismatches:", dict(col_diff))
    print("  API-only group samples:", sorted(set(ga) - set(gd))[:samples])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--samples", type=int, default=6)
    args = ap.parse_args()
    with get_session() as s:
        for t in ([args.only] if args.only else SPECS):
            compare(s, t, args.samples)
    return 0


if __name__ == "__main__":
    sys.exit(main())
