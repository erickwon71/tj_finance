"""Reload the 127 filings where repair_sce_sign_loss (current R162-e code, no changes) already
computes a fix for the still-open sign_flip finding — confirmed by direct re-run against
current report_lines (see memory sign-flip-r162e-residual-investigation-2026-09-26). No new
parser code; this is a plain re-trigger via the normal fix_batches/batch_reload path.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text  # noqa: E402

from fin2.verification import ops  # noqa: E402

rcepts = Path(__file__).with_name("sign_flip_r162e_would_fix_2026-09-26.txt").read_text().split()
print(f"대상 필링 {len(rcepts)}건")

with ops.engine.connect() as conn:
    issue_ids = [r[0] for r in conn.execute(text("""
        SELECT issue_id FROM verification.issues
        WHERE status = 'reopened' AND error_type = 'sign_flip' AND rule_id = 'R162-e'
          AND rcept_no = ANY(:r)"""), {"r": rcepts}).fetchall()]
print(f"대상 이슈 {len(issue_ids)}건")

b = ops.batch_new("sign_flip",
                  "R162-e 재실행 재적재(신규코드 없음) — 다른 배치의 재적재로 후보 셀 정리돼 지금은 "
                  "단일후보 판정 가능해진 127필링", issue_ids, rule_id="R162-e")
print("batch_new:", b)
batch_id = b["batch_id"]

res = ops.batch_reload(batch_id, use_sd=True)
print("batch_reload:", res)

res2 = ops.batch_mark_fixed(batch_id)
print(f"batch_mark_fixed: fixed={len(res2['fixed'])} not_fixed={len(res2['not_fixed'])}")
if res2["not_fixed"]:
    for iid, err in res2["not_fixed"][:20]:
        print("  not_fixed:", iid, err)

ops.batch_set(batch_id, status="done", note="R162-e 재트리거만, 코드변경 없음")
print("batch done")
