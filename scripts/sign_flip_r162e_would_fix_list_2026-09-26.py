"""List (and optionally create+reload a fix batch for) the R162-e reopened sign_flip filings
where repair_sce_sign_loss, re-run against current report_lines, already computes a fix — no
new code, just a re-trigger (a later, unrelated reload changed a sibling cell that had been
blocking R162-e's single-candidate check). See memory
sign-flip-r162e-residual-investigation-2026-09-26 for the full breakdown.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text  # noqa: E402

from fin2.extract import sce_sign_repair as sr  # noqa: E402
from fin2.verification.machine_pass import _source_path, sign_issues  # noqa: E402
from fin2.verification import machine_compare as mc  # noqa: E402
from fin2.verification.ops import engine  # noqa: E402

COLS = ("statement", "basis", "label_raw", "col_index", "col_label", "row_order",
        "value_won", "table_seq")


def load_lines(conn, rcept):
    rows = conn.execute(text(f"""
        SELECT {", ".join(COLS)} FROM report_lines
        WHERE rcept_no = :r AND statement = 'SCE' ORDER BY basis, table_seq, row_order, col_index
    """), {"r": rcept}).mappings().all()
    return [SimpleNamespace(**dict(r)) for r in rows]


with engine.connect() as conn:
    rcepts = [r[0] for r in conn.execute(text("""
        SELECT DISTINCT rcept_no FROM verification.issues
        WHERE status = 'reopened' AND error_type = 'sign_flip' AND rule_id = 'R162-e'
    """)).fetchall()]

would_fix = []
with engine.connect() as conn:
    for n, rcept in enumerate(rcepts, 1):
        path = _source_path(conn, rcept)
        if path is None:
            continue
        res = mc.compare_filing(conn, rcept, path)
        if not sign_issues(res):
            continue
        lines = load_lines(conn, rcept)
        try:
            corrections = sr.repair_sce_sign_loss(lines)
        except Exception:
            continue
        if corrections:
            would_fix.append(rcept)
        if n % 1000 == 0:
            print(f"  {n}/{len(rcepts)}", file=sys.stderr)

print(f"재실행하면 고쳐지는 필링 {len(would_fix)}건")
out = Path(__file__).parent / "sign_flip_r162e_would_fix_2026-09-26.txt"
out.write_text("\n".join(would_fix), encoding="utf-8")
print(f"목록 저장: {out}")
