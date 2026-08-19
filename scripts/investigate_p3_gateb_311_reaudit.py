"""P3-1 재감사 후속 조사 — '400일 이내 정정인데 reconcile 이 안 고른' 311건 원인 분류.

statement_source.lineage 에서 chosen=false 이면서 is_final=true, 그리고 (filed_at -
earliest_filed_at) <= 400일 인 후보를 골라, fin2.reconcile.select_source() 를 그 후보군에
직접 재실행해서 왜 그 후보가 안 뽑혔는지(anchor 없음 / is_amendment=False / 더 완전한
경쟁 후보에 밀림 / 기타) 를 실측으로 분류한다.

용법: .venv/bin/python scripts/investigate_p3_gateb_311_reaudit.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text

from fin2.reconcile import select_source, _STATEMENTS

eng = create_engine("postgresql://localhost/tj_finance")

with eng.connect() as c:
    rows = c.execute(text("""
        WITH cand AS (
          SELECT ss.corp_code, ss.fiscal_year, ss.fiscal_period, ss.basis, ss.statement,
                 ss.source_rcept_no, ss.lineage,
                 jsonb_array_elements(ss.lineage) AS c
          FROM statement_source ss
        ),
        parsed AS (
          SELECT corp_code, fiscal_year, fiscal_period, basis, statement, source_rcept_no, lineage,
                 (c->>'rcept') AS rcept,
                 (c->>'chosen')::boolean AS chosen,
                 (c->>'filed_at')::date AS filed_at,
                 (c->>'is_amendment')::boolean AS is_amendment,
                 (c->>'line_count')::int AS line_count
          FROM cand
        ),
        keyed AS (
          SELECT *,
                 min(filed_at) OVER (PARTITION BY corp_code, fiscal_year, fiscal_period, basis,
                                      statement, source_rcept_no) AS earliest_filed_at
          FROM parsed
        ),
        withfinal AS (
          SELECT k.*, f.is_final
          FROM keyed k
          JOIN filings f ON f.rcept_no = k.rcept
        )
        SELECT DISTINCT corp_code, fiscal_year, fiscal_period, basis, statement, source_rcept_no,
               lineage
        FROM withfinal
        WHERE chosen = false AND is_final = true
          AND (filed_at - earliest_filed_at) <= 400
    """)).fetchall()

print(f"대상 statement_source 행: {len(rows)}건")

reasons = Counter()
examples: dict[str, list] = {}

for r in rows:
    stmt = r.statement
    prefix, anchor = _STATEMENTS[stmt]
    lineage = r.lineage  # list of dicts

    candidates = [
        (
            d["rcept"],
            frozenset(),  # placeholder, filled below per-candidate from fact_v2 if needed
            None,
            d["is_amendment"],
        )
        for d in lineage
    ]

    # lineage 에 실제 canonical 라인 집합이 없으므로(line_count 만 기록) anchor 보유 여부는
    # fact_v2 에서 다시 조회해야 한다.
    rcepts = [d["rcept"] for d in lineage]
    with eng.connect() as c2:
        line_rows = c2.execute(text("""
            SELECT rcept_no, canonical_account
            FROM fact_v2
            WHERE corp_code=:corp AND rcept_no = ANY(:rcepts)
              AND col_index=0 AND NOT is_dimensional AND canonical_account IS NOT NULL
              AND basis=:basis
        """), {"corp": r.corp_code, "rcepts": rcepts, "basis": r.basis}).fetchall()

    lines_by_rcept: dict[str, set] = {}
    for lr in line_rows:
        ca = lr.canonical_account
        if not ca.startswith(prefix):
            continue
        lines_by_rcept.setdefault(lr.rcept_no, set()).add(ca)

    real_candidates = []
    filed_at_by_rcept = {d["rcept"]: d["filed_at"] for d in lineage}
    from datetime import date
    for d in lineage:
        rc = d["rcept"]
        lines = lines_by_rcept.get(rc, set())
        fa = filed_at_by_rcept[rc]
        fa_date = date.fromisoformat(fa) if fa else None
        real_candidates.append((rc, lines, fa_date, bool(d["is_amendment"])))

    best = select_source(real_candidates, anchor)
    is_final_rcept = r.source_rcept_no  # NOTE: this is the CHOSEN one, not is_final; find is_final separately

    # is_final rcept = the one flagged is_final=true among lineage — re-derive via DB
    with eng.connect() as c3:
        final_rcept_row = c3.execute(text("""
            SELECT rcept_no FROM filings WHERE rcept_no = ANY(:rcepts) AND is_final = true
        """), {"rcepts": rcepts}).fetchone()
    final_rcept = final_rcept_row[0] if final_rcept_row else None

    if final_rcept is None:
        reasons["NO_IS_FINAL_IN_CANDIDATES(불가능,점검)"] += 1
        continue

    if best[0] == final_rcept:
        reasons["재실행하면_실제로_is_final이_이김(불일치_이미_해소됨_또는_레이스)"] += 1
        continue

    final_cand = next(cnd for cnd in real_candidates if cnd[0] == final_rcept)
    best_cand = best

    fc_lines, fc_fa, fc_amend = final_cand[1], final_cand[2], final_cand[3]
    bc_lines, bc_fa, bc_amend = best_cand[1], best_cand[2], best_cand[3]

    has_anchor_fc = anchor in fc_lines
    has_anchor_bc = anchor in bc_lines

    if not has_anchor_fc:
        reason = "A_is_final후보에_anchor라인없음(해당statement비정정)"
    elif not fc_amend:
        reason = "B_is_final후보가_is_amendment=False(첨부정정등)"
    elif has_anchor_bc and bc_amend and len(bc_lines) > len(fc_lines):
        reason = "C_더_완전한_경쟁_기재정정에_밀림(둘다_적시정정,라인수로_역전)"
    else:
        reason = "D_기타(수동확인필요)"

    reasons[reason] += 1
    examples.setdefault(reason, [])
    if len(examples[reason]) < 3:
        examples[reason].append(
            f"{r.corp_code} {r.fiscal_year}{r.fiscal_period} {r.basis}/{stmt}: "
            f"is_final={final_rcept}(lines={len(fc_lines)},amend={fc_amend}) vs "
            f"chosen={best_cand[0]}(lines={len(bc_lines)},amend={bc_amend})"
        )

print("\n=== 분류 결과 ===")
for reason, n in reasons.most_common():
    print(f"{reason}: {n}건")
    for ex in examples.get(reason, []):
        print(f"    예: {ex}")
