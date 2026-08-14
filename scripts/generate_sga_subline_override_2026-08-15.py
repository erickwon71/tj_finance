"""Generate the (corp, fy, period) override key set for Phase 1 (`is.sga` stage-rank
shortcut fix), per docs/plans/is_sga_cogs_holding_co_label_mismap_plan_2026-08-15.md
Phase 1 (user-approved 2026-08-15, 46-corp scope = Phase 0's target_rows population).

Read-only. Reuses the exact classification logic from
scripts/probe_sga_cogs_holdco_phase0_2026-08-15.py (target_rows: COGS+SGA children,
identity holds) so the override population matches Phase 0 1:1. Additionally collects
the normalized SGA subline label(s) actually observed, to build the label frozenset
combine.py needs (rather than guessing which 판매비와관리비/판매비및관리비 variants exist).

Usage: python scripts/generate_sga_subline_override_2026-08-15.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session, init_db
from parser.common.amount_normalizer import normalize_account_name
from fin2.layer3.industry_profiles import norm as norm_label

COGS_MARKERS = ("매출원가", "원가")
SGA_MARKERS = ("판매비와관리비", "판매비및관리비", "판매비와 관리비", "판매비 및 관리비")


def find_parent_rows(session) -> list:
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
    with get_session() as s:
        parents = find_parent_rows(s)
        target_rows = []
        for (pid, corp, rcept, basis, tseq, prow, pdepth, plabel, pval, fy, fp) in parents:
            if pval is None:
                continue
            children = direct_children(s, corp, rcept, basis, tseq, prow, pdepth)
            if not children:
                continue
            labels = [c[0] for c in children]
            has_cogs = any(any(m in lbl for m in COGS_MARKERS) for lbl in labels)
            has_sga = any(any(m in lbl for m in SGA_MARKERS) for lbl in labels)
            if not (has_cogs and has_sga):
                continue
            child_sum = sum(v for _, v in children if v is not None)
            n_missing = sum(1 for _, v in children if v is None)
            identity_ok = (n_missing == 0 and child_sum == pval)
            if not identity_ok:
                continue
            sga_children = [(lbl, v) for lbl, v in children if any(m in lbl for m in SGA_MARKERS)]
            target_rows.append({
                "corp": corp, "rcept": rcept, "basis": basis, "fy": fy, "fp": fp,
                "sga_children": sga_children,
            })

        corps = sorted({r["corp"] for r in target_rows})
        print(f"target_rows={len(target_rows)} corps={len(corps)}")

        # normalized SGA subline labels actually observed (to size the frozenset in combine.py)
        norm_labels = Counter()
        for r in target_rows:
            for lbl, _ in r["sga_children"]:
                norm_labels[norm_label(lbl)] += 1
        print("\nnormalized SGA subline labels observed:")
        for lbl, n in norm_labels.most_common():
            print(f"  {lbl!r} x{n}")

        # rows where the SGA subline itself has >1 candidate (ambiguous — flag, don't silently pick)
        multi_sga = [r for r in target_rows if len(r["sga_children"]) > 1]
        print(f"\nrows with >1 SGA-marker child (ambiguous, needs review) = {len(multi_sga)}")
        for r in multi_sga[:20]:
            print(f"  {r['corp']} {r['rcept']} {r['basis']} {r['fy']}{r['fp']} sga_children={r['sga_children']}")

        # distinct (corp, fy, fp) override keys
        keys = sorted({(r["corp"], r["fy"], r["fp"]) for r in target_rows})
        print(f"\ndistinct (corp, fy, period) override keys = {len(keys)}")

        # check: does the same (corp, fy, fp) key ever appear in BOTH target_rows and would
        # collide with a DIFFERENT structure at another basis/rcept for the same key? (sanity)
        # -> not needed: basis is not part of the key (resolve() already scoped per-basis,
        #    per R17 precedent), and rcept differences within the same (corp,fy,fp) key would
        #    only arise from restated filings, which build_merged_lines() already collapses
        #    before _resolve() ever runs.

        print("\n_SGA_SUBLINE_OVERRIDE_KEYS = {")
        for corp, fy, fp in keys:
            print(f'    ("{corp}", {fy}, "{fp}"),')
        print("}")

    print("\n=== DONE (read-only, no writes) ===")


if __name__ == "__main__":
    main()
