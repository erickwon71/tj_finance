"""Close issues that are out of the verification campaign's scope (user decision 2026-10-10:
the campaign checks layer-2 faithfulness only — source arithmetic and sign defects of the print are
layer-3 backlog, scripts/r0_2_migration/layer3_backlog.py).

Closed (open / reopened only; issues inside a fix batch are left alone):
  - every source_defect (a record of the print's own arithmetic, DB = print);
  - sign_flip whose db_value equals the printed source string (DB = print; the "flip" is a layer-3
    correction). sign_flip with DB != print is a real layer-2 error and stays.

Usage (cwd = repo root, DATABASE_URL = admin):
  python scripts/r0_2_migration/close_out_of_scope.py            # dry run
  python scripts/r0_2_migration/close_out_of_scope.py --apply
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from decimal import Decimal

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "scripts", "r0_2_migration"))

from close_d3_issues import UNIT, printed_number  # noqa: E402

EVIDENCE = ("[범위 밖, 사용자 결정 2026-10-10] 검증 캠페인 = 계층2 충실도만. {what} "
            "계층3 보정 후보로 모은다(scripts/r0_2_migration/layer3_backlog.py).")
SQL = """
SELECT issue_id, error_type, status, db_value, source_value_raw, source_unit
FROM verification.issues
WHERE status IN ('open', 'reopened') AND fix_batch_id IS NULL
  AND error_type IN ('source_defect', 'sign_flip')
ORDER BY issue_id"""


def main():
    apply = "--apply" in sys.argv
    from sqlalchemy import text
    from collector.db import engine
    with engine.connect() as conn:
        rows = conn.execute(text(SQL)).mappings().fetchall()
    tally, close = Counter(), []
    for r in rows:
        if r["error_type"] == "source_defect":
            close.append((r["issue_id"], EVIDENCE.format(what="원문 산수 불일치·괄호 누락 추정 기록(DB = 원문).")))
            tally["close source_defect"] += 1
            continue
        p = printed_number(r["source_value_raw"])
        unit = UNIT.get(r["source_unit"] or "원")
        if p is not None and unit and r["db_value"] is not None and Decimal(r["db_value"]) == p * unit:
            close.append((r["issue_id"], EVIDENCE.format(what="sign_flip 이지만 DB = 원문 인쇄값(부호 보정은 계층3).")))
            tally["close sign_flip (DB = print)"] += 1
        else:
            tally["keep sign_flip (DB != print)"] += 1
    print(dict(tally))
    if not apply:
        return
    from fin2.verification import ops
    for i, (iid, ev) in enumerate(close, 1):
        ops.transition(iid, "closed", ev)
        if i % 5000 == 0:
            print(i, flush=True)
    print("closed", len(close))


if __name__ == "__main__":
    main()
