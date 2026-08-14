"""Phase 3-2(R19 검증) — BS 항등식(자산=부채+자본) 전수 재검사.

`docs/plans/note_ref_guard_body_statement_fix_plan_2026-08-14.md` Phase 3-2. R19 백필
(report_lines 185,067건 전수 재추출) 후, 재추출된 report_lines 전체(1999~) 대상으로
자산총계=부채총계+자본총계 항등식이 성립하는지 검사한다. 읽기 전용(DB 미기록).

패턴은 `scripts/verify_pre2015_pilot_identity.py::check_identity()`를 pilot 26개사 한정에서
DB 전체로 확장한 것.

usage:
  .venv/bin/python scripts/probe_bs_identity_post_r19_2026-08-15.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session


def check_identity(session) -> None:
    sql = text("""
        WITH bs AS (
            SELECT rl.rcept_no, rl.basis, rl.col_index,
                   MAX(CASE WHEN rl.label_raw ~ '^자산\\s*총\\s*계$' THEN rl.value_won END) AS assets,
                   MAX(CASE WHEN rl.label_raw ~ '^부채\\s*총\\s*계$' THEN rl.value_won END) AS liabs,
                   MAX(CASE WHEN rl.label_raw ~ '^자본\\s*총\\s*계$' THEN rl.value_won END) AS equity
            FROM report_lines rl
            WHERE rl.statement = 'BS'
            GROUP BY rl.rcept_no, rl.basis, rl.col_index
        )
        SELECT rcept_no, basis, col_index, assets, liabs, equity,
               (assets - (liabs + equity)) AS diff
        FROM bs
        WHERE assets IS NOT NULL AND liabs IS NOT NULL AND equity IS NOT NULL
    """)
    rows = session.execute(sql).fetchall()
    print(f"=== BS 항등식(자산=부채+자본) 전수 재검사 ===")
    print(f"검사 대상(자산/부채/자본 총계 3종 다 있는 rcept×basis×col) = {len(rows)}")
    ok = [r for r in rows if abs(r.diff) < 2]
    bad = [r for r in rows if abs(r.diff) >= 2]
    print(f"항등식 성립(오차<2원) = {len(ok)} ({100*len(ok)/max(len(rows),1):.2f}%)")
    print(f"항등식 위반 = {len(bad)} ({100*len(bad)/max(len(rows),1):.2f}%)")
    for r in bad[:30]:
        print(f"  {r.rcept_no} {r.basis} col{r.col_index}: 자산={r.assets:,} "
              f"부채+자본={(r.liabs or 0)+(r.equity or 0):,} diff={r.diff:,}")
    if len(bad) > 30:
        print(f"  ... 외 {len(bad)-30}건")


def main() -> None:
    with get_session() as session:
        check_identity(session)


if __name__ == "__main__":
    main()
