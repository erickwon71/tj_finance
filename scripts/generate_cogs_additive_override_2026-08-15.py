"""Generate the (corp, fy, period, basis) -> tuple[normalized_label,...] override table
for Phase 2 (`is.cogs` additive fix), per
docs/plans/is_sga_cogs_holding_co_label_mismap_plan_2026-08-15.md Phase 2.

Population = the same '영업비용' P-line identity-validated rows as
scripts/probe_cogs_phase2_2026-08-15.py, narrowed to only the (corp,fy,period,basis) keys
that actually NEED a fix (single_mapped rows are already correct via the existing alias
table — excluded to keep the curated set minimal/auditable, matching R16/R17/R20 style).

Design note (why this is a combine.py raw-label override, NOT a general alias addition):
scripts/probe_cogs_alias_global_risk_2026-08-15.py found that 2 of the 5 unmapped COGS
sub-line labels ('상품및제품매출원가'/'임대매출원가_임대수익원가') co-occur with an EXACT
'매출원가' TOTAL sibling in OTHER companies' filings (64/162 and 514/548 combos respectively)
— the exact conflict pattern account_maps/is_accounts.py already documents removing
'제품매출원가'/'상품매출원가' aliases for (2026-07-18). Adding them as general aliases would
reintroduce that regression elsewhere. Keeping the fix scoped to curated (corp,fy,period,
basis) keys, computed from raw label text (not via AccountMapper), avoids that blast radius
entirely — this generator produces exactly that curated key set.

Consistency check performed separately (not re-run here): for all 70 (corp,fy,period,basis)
keys spanning >1 rcept_no (i.e., amended/restated), the COGS-children label-set signature
was IDENTICAL across every rcept_no (0 inconsistent) — confirms picking any one representative
rcept_no's structure per key is safe/representative of what build_merged_lines() will see at
combine() runtime (amendments patch values, not this line-item structure, for this population).

No DB writes. Usage: python scripts/generate_cogs_additive_override_2026-08-15.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session, init_db
from parser.common.amount_normalizer import normalize_account_name
from parser.common.account_mapper import get_mapper
from fin2.layer3.industry_profiles import norm as norm_label

SGA_MARKERS = ("판매비와관리비", "판매비및관리비", "판매비와 관리비", "판매비 및 관리비")
COGS_MARKER = "매출원가"


def find_parent_rows(session):
    rows = session.execute(text("""
        SELECT id, corp_code, rcept_no, basis, table_seq, row_order, depth, label_raw, value_won,
               report_fiscal_year, report_fiscal_period
        FROM report_lines
        WHERE statement = 'IS' AND col_index = 0 AND node_role = 'P'
          AND label_raw LIKE '%영업비용%'
    """)).fetchall()
    return [r for r in rows if normalize_account_name(r[7]) == "영업비용"]


def direct_children(session, corp, rcept, basis, tseq, prow, pdepth):
    siblings = session.execute(text("""
        SELECT row_order, depth, label_raw, value_won
        FROM report_lines
        WHERE corp_code = :c AND rcept_no = :r AND basis = :b AND statement = 'IS'
          AND table_seq = :t AND col_index = 0 AND row_order > :ro
        ORDER BY row_order
    """), {"c": corp, "r": rcept, "b": basis, "t": tseq, "ro": prow}).fetchall()
    children = []
    for ro, depth, label, val in siblings:
        if depth is None or pdepth is None or depth <= pdepth:
            break
        if depth == pdepth + 1:
            children.append((label, val))
    return children


def main():
    init_db()
    mapper = get_mapper()
    with get_session() as s:
        parents = find_parent_rows(s)
        by_key = {}   # (corp,fy,fp,basis) -> normalized cogs-label tuple (last rcept wins, verified consistent)
        for (pid, corp, rcept, basis, tseq, prow, pdepth, plabel, pval, fy, fp) in parents:
            if pval is None:
                continue
            children = direct_children(s, corp, rcept, basis, tseq, prow, pdepth)
            if not children:
                continue
            labels = [c[0] for c in children]
            has_cogs = any(COGS_MARKER in lbl for lbl in labels)
            has_sga = any(any(m in lbl for m in SGA_MARKERS) for lbl in labels)
            if not (has_cogs and has_sga):
                continue
            child_sum = sum(v for _, v in children if v is not None)
            n_missing = sum(1 for _, v in children if v is None)
            if not (n_missing == 0 and child_sum == pval):
                continue
            cogs_children = [lbl for lbl, v in children if COGS_MARKER in lbl]
            key = (corp, fy, fp, basis)
            by_key[key] = tuple(sorted({norm_label(lbl) for lbl in cogs_children}))

        # need-fix filter: exclude keys where the single label already maps cleanly
        # (already correct via existing alias table, no override needed)
        override = {}
        for key, labels in by_key.items():
            if len(labels) == 1:
                r = mapper.map(labels[0], fs_section="is")
                if r.confidence >= 0.88 and r.account_code == "is.cogs":
                    continue   # single_mapped — already correct, skip
            override[key] = labels

        print(f"total keys={len(by_key)}, override (needs fix)={len(override)}")
        corps = sorted({k[0] for k in override})
        print(f"corps needing is.cogs fix = {len(corps)}: {corps}")

        print("\n_COGS_ADDITIVE_OVERRIDE = {")
        for key in sorted(override):
            corp, fy, fp, basis = key
            labels = override[key]
            print(f'    ("{corp}", {fy}, "{fp}", "{basis}"): {labels!r},')
        print("}")

    print("\n=== DONE (read-only, no writes) ===")


if __name__ == "__main__":
    main()
