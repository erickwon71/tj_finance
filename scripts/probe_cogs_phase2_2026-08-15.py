"""Phase 2 investigation (read-only) for
docs/plans/is_sga_cogs_holding_co_label_mismap_plan_2026-08-15.md Phase 2 (`is.cogs`).

Scope = the same 46-corp population Phase 0/1 validated for is.sga (`_SGA_SUBLINE_OVERRIDE_KEYS`
in fin2/layer3/combine.py). For each (corp, rcept, basis) row where the §1 '영업비용' P-line
holds (COGS+SGA children, identity confirmed), enumerate the COGS-marker children precisely
(label contains '매출원가', NOT the broader '원가' substring — that broad marker false-
positived on '임대사업원가' during Phase 0/1, see combine.py comment on 00163673 FY2010),
map each via AccountMapper, and compare the child-label count/mapping-stage/DB is.cogs value
to classify each row into:
  - single_clean:   exactly 1 COGS child, maps to is.cogs (any stage) — DB should already be correct.
  - multi_needs_sum: >=2 COGS children, at least one maps to unknown/is.cogs at conf=0 for the
                      currently-adopted single value — additive-override candidate (R17 pattern).
  - multi_conflict:  >=2 COGS children, more than one already maps to is.cogs distinctly (fuzzy or
                      otherwise) — _resolve() conflict/collision, needs individual inspection.
  - other:           doesn't fit the above (0 children, mapping anomalies) — flag for manual look.

No DB writes. Usage: python scripts/probe_cogs_phase2_2026-08-15.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session, init_db
from parser.common.amount_normalizer import normalize_account_name
from parser.common.account_mapper import get_mapper
from fin2.layer3.industry_profiles import norm as norm_label

SGA_MARKERS = ("판매비와관리비", "판매비및관리비", "판매비와 관리비", "판매비 및 관리비")
COGS_MARKER = "매출원가"   # precise marker (NOT the broad '원가' substring — see R20 comment)


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
    mapper = get_mapper()
    with get_session() as s:
        parents = find_parent_rows(s)
        rows_out = []
        for (pid, corp, rcept, basis, tseq, prow, pdepth, plabel, pval, fy, fp) in parents:
            if pval is None:
                continue
            children = direct_children(s, corp, rcept, basis, tseq, prow, pdepth)
            if not children:
                continue
            labels = [c[0] for c in children]
            has_cogs_precise = any(COGS_MARKER in lbl for lbl in labels)
            has_sga = any(any(m in lbl for m in SGA_MARKERS) for lbl in labels)
            if not (has_cogs_precise and has_sga):
                continue
            child_sum = sum(v for _, v in children if v is not None)
            n_missing = sum(1 for _, v in children if v is None)
            identity_ok = (n_missing == 0 and child_sum == pval)
            if not identity_ok:
                continue
            cogs_children = [(lbl, v) for lbl, v in children if COGS_MARKER in lbl]
            mapped = []
            for lbl, v in cogs_children:
                r = mapper.map(lbl, fs_section="is")
                mapped.append((lbl, v, r.account_code, r.stage, r.confidence))
            rows_out.append({
                "corp": corp, "rcept": rcept, "basis": basis, "fy": fy, "fp": fp,
                "cogs_children": mapped,
            })

        corps = sorted({r["corp"] for r in rows_out})
        print(f"rows={len(rows_out)} corps={len(corps)}")

        # classify per-row
        single_clean, multi_needs_sum, multi_conflict, other = [], [], [], []
        for r in rows_out:
            n = len(r["cogs_children"])
            if n == 1:
                single_clean.append(r)
                continue
            is_cogs_hits = [m for m in r["cogs_children"] if m[2] == "is.cogs"]
            unknown_hits = [m for m in r["cogs_children"] if m[2] != "is.cogs"]
            if len(is_cogs_hits) <= 1 and unknown_hits:
                multi_needs_sum.append(r)
            elif len(is_cogs_hits) >= 2:
                multi_conflict.append(r)
            else:
                other.append(r)

        print(f"\nsingle_clean(1개 COGS서브라인) = {len(single_clean)} rows, "
              f"{len({r['corp'] for r in single_clean})} corps")
        print(f"multi_needs_sum(>=2, 합산 필요 후보) = {len(multi_needs_sum)} rows, "
              f"{len({r['corp'] for r in multi_needs_sum})} corps")
        print(f"multi_conflict(>=2, 이미 여러개 is.cogs 매핑=충돌) = {len(multi_conflict)} rows, "
              f"{len({r['corp'] for r in multi_conflict})} corps")
        print(f"other(분류 애매, 수동확인) = {len(other)} rows, "
              f"{len({r['corp'] for r in other})} corps")

        def summarize(bucket, name, limit=60):
            print(f"\n=== {name} sample (corp/period/children) ===")
            seen_corp_period = set()
            shown = 0
            for r in bucket:
                key = (r["corp"], r["fy"], r["fp"])
                if key in seen_corp_period:
                    continue
                seen_corp_period.add(key)
                print(f"  {r['corp']} {r['fy']}{r['fp']} {r['basis']} children={r['cogs_children']}")
                shown += 1
                if shown >= limit:
                    break

        summarize(multi_needs_sum, "multi_needs_sum")
        summarize(multi_conflict, "multi_conflict")
        summarize(other, "other")

        # unique (corp,fy,fp) label-set signature per bucket (to see if labels are stable per corp)
        print("\n=== multi_needs_sum: distinct corp -> label-set signatures ===")
        sig_by_corp = {}
        for r in multi_needs_sum:
            sig = tuple(sorted(norm_label(lbl) for lbl, *_ in r["cogs_children"]))
            sig_by_corp.setdefault(r["corp"], set()).add(sig)
        for corp, sigs in sig_by_corp.items():
            print(f"  {corp}: {sigs}")

        print("\n=== multi_conflict: distinct corp -> label-set signatures ===")
        sig_by_corp2 = {}
        for r in multi_conflict:
            sig = tuple(sorted(norm_label(lbl) for lbl, *_ in r["cogs_children"]))
            sig_by_corp2.setdefault(r["corp"], set()).add(sig)
        for corp, sigs in sig_by_corp2.items():
            print(f"  {corp}: {sigs}")

        # cross-check current std_v3 cogs value vs the correct sum, for multi_needs_sum/conflict rows
        print("\n=== DB is.cogs vs correct-sum mismatch (multi_needs_sum + multi_conflict) ===")
        checked = 0
        mismatches = 0
        for r in (multi_needs_sum + multi_conflict):
            key = (r["corp"], r["fy"], r["fp"], r["basis"])
            if key in locals().get("_seen", set()):
                continue
            correct_sum = sum(v for _, v, *_ in r["cogs_children"] if v is not None)
            db_row = s.execute(text("""
                SELECT cogs FROM std_financials_v3
                WHERE corp_code=:c AND fiscal_year=:y AND fiscal_period=:p AND statement_type=:b
            """), {"c": r["corp"], "y": r["fy"], "p": r["fp"], "b": r["basis"]}).fetchone()
            checked += 1
            db_val = db_row[0] if db_row else None
            if db_val != correct_sum:
                mismatches += 1
                if mismatches <= 40:
                    print(f"  {r['corp']} {r['fy']}{r['fp']} {r['basis']} db_cogs={db_val} "
                          f"correct_sum={correct_sum} children={r['cogs_children']}")
        print(f"\nchecked={checked} mismatches={mismatches}")

    print("\n=== DONE (read-only, no writes) ===")


if __name__ == "__main__":
    main()
