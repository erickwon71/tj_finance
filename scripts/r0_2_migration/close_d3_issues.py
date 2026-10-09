"""R0-2 D3 (user decision 2026-10-10 morning): close the frozen R162-e sign_flip issues (동결 ①) and
the R165-type source_defect issues — after the migration layer 2 holds the printed value, which is
the answer for these cells; any restoration lives in layer3_cell_corrections.

Closed only when BOTH hold:
  1. the filing's reload outcome guarantees report_lines = printed extraction
     (done / already / full_done / nochange in the reload logs; drift filings are kept);
  2. for sign_flip: the issue's db_value equals its printed source string (DB = 원문).

Usage (cwd = repo root, DATABASE_URL = admin):
  python scripts/r0_2_migration/close_d3_issues.py <reload_all.jsonl>            # dry run
  python scripts/r0_2_migration/close_d3_issues.py <reload_all.jsonl> --apply
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from decimal import Decimal

sys.path.insert(0, os.getcwd())

PRINTED_OK = {"done", "already", "full_done", "nochange"}
UNIT = {"원": 1, "천원": 1_000, "백만원": 1_000_000}
EVIDENCE = ("[R0-2 이행 D3, 사용자 결정 2026-10-10] 계층2 = 원문 인쇄값으로 재적재 확인(reload {st}). "
            "{what} 부호·값 보정은 계층3(layer3_cell_corrections)에서만 한다.")

SQL = """
SELECT issue_id, rcept_no, error_type, status, db_value, source_value_raw, source_unit
FROM verification.issues
WHERE (error_type = 'sign_flip' AND rule_id = 'R162-e' AND created_at < '2026-09-26'
       AND status IN ('open', 'reopened'))
   OR (status IN ('open', 'reopened') AND (rule_id ILIKE '%R165%' OR evidence ILIKE '%R165%'))
ORDER BY issue_id"""


def printed_number(raw: str | None):
    """Printed amount string -> number in the printed unit; None if it is not one plain number."""
    if raw is None:
        return None
    t = raw.strip().replace(",", "").replace(" ", "")
    neg = t.startswith("(") and t.endswith(")") or t.startswith("△") or t.startswith("-") or t.startswith("▲")
    t = t.strip("()△▲-")
    if not re.fullmatch(r"\d+(\.\d+)?", t):
        return None
    v = Decimal(t)
    return -v if neg else v


def main():
    logs, apply = sys.argv[1], "--apply" in sys.argv
    status = {}
    for line in open(logs):
        d = json.loads(line)
        status[d["rcept"]] = d["status"].split(":")[0]
    from sqlalchemy import text
    from collector.db import engine
    with engine.connect() as conn:
        rows = conn.execute(text(SQL)).mappings().fetchall()
    tally, close = Counter(), []
    for r in rows:
        st = status.get(r["rcept_no"])
        if st not in PRINTED_OK:
            tally[f"keep: filing {st or 'not reloaded'}"] += 1
            continue
        if r["error_type"] == "sign_flip":
            p = printed_number(r["source_value_raw"])
            unit = UNIT.get(r["source_unit"] or "원")
            if p is None or unit is None or r["db_value"] is None or Decimal(r["db_value"]) != p * unit:
                tally["keep: db_value != printed"] += 1
                continue
            what = "동결 ① sign_flip(R162-e) — DB 는 인쇄 부호 그대로가 정답."
        else:
            what = "R165 유형 source_defect — 원문 산수 불일치는 사실 기록, 계층2 는 원문 그대로."
        close.append((r["issue_id"], EVIDENCE.format(st=st, what=what)))
        tally[f"close: {r['error_type']}"] += 1
    print(dict(tally))
    if not apply:
        return
    from fin2.verification import ops
    for i, (iid, ev) in enumerate(close, 1):
        ops.transition(iid, "closed", ev)
        if i % 1000 == 0:
            print(i, flush=True)
    print("closed", len(close))


if __name__ == "__main__":
    main()
