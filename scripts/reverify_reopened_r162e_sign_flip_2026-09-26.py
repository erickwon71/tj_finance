"""One-time cleanup: re-verify every 'reopened' R162-e sign_flip issue against a fresh machine
comparison (the same check `machine_pass.recheck_slot()` uses for 'fixed' issues) and close the
ones whose finding no longer appears — they were already resolved by a reload, but nothing ever
re-checks 'reopened' issues (recheck_slot only scans status='fixed'), so they were stuck forever.

This is a read-verify-then-write pass, admin role (bypasses the verify-role restriction on
reopened->closed, same as any other admin data-quality fix). Genuinely still-wrong issues are
left untouched for the fix side to batch.

Context: docs/qa/handoff_2026-09-26_full_automation.md follow-up (sign_flip batching, 2026-09-26).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text  # noqa: E402

from fin2.verification import machine_compare as mc  # noqa: E402
from fin2.verification.machine_pass import _issue_key, _source_path, sign_issues  # noqa: E402
from fin2.verification.ops import engine, transition  # noqa: E402

with engine.connect() as conn:
    rows = [dict(r) for r in conn.execute(text("""
        SELECT issue_id, rcept_no, basis, account_label, column_label
        FROM verification.issues
        WHERE status = 'reopened' AND error_type = 'sign_flip' AND rule_id = 'R162-e'
    """)).mappings()]

by_rcept: dict[str, list[dict]] = {}
for r in rows:
    by_rcept.setdefault(r["rcept_no"], []).append(r)

print(f"대상 이슈 {len(rows)}건 / 필링 {len(by_rcept)}건")

to_close: list[int] = []
to_keep = 0
no_path = 0
t0 = time.time()
with engine.connect() as conn:
    for n, (rcept, items) in enumerate(by_rcept.items(), 1):
        path = _source_path(conn, rcept)
        if path is None:
            no_path += len(items)
            continue
        res = mc.compare_filing(conn, rcept, path)
        still = {_issue_key(x) for x in sign_issues(res)}
        for i in items:
            if _issue_key(i) in still:
                to_keep += 1
            else:
                to_close.append(i["issue_id"])
        if n % 500 == 0:
            print(f"  {n}/{len(by_rcept)} 필링 ({time.time()-t0:.0f}s)")

print(f"\n재검증 완료 ({time.time()-t0:.0f}s): 이미 해소돼 close 대상 {len(to_close)}건 · "
      f"여전히 불일치(그대로 둠) {to_keep}건 · 원문경로 없음 {no_path}건")

if "--apply" not in sys.argv:
    print("\n--apply 없이 실행됨: 실제 close는 하지 않았다.")
    sys.exit(0)

closed = 0
for iid in to_close:
    transition(iid, "closed",
               f"[admin 재검증 2026-09-26] machine_compare 재실행 결과 이 셀의 sign_omitted 발견이 "
               f"더 이상 나오지 않음(재적재로 이미 해소됨) — recheck_slot이 reopened 이슈는 재검사하지 "
               f"않아 방치돼 있던 건")
    closed += 1
    if closed % 500 == 0:
        print(f"  close {closed}/{len(to_close)}")
print(f"\nclose 완료: {closed}건")
