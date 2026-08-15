"""Phase 2 sub-investigation: enumerate every distinct '매출원가'-containing label that
AccountMapper currently drops (confidence < 0.88 or account_code startswith 'unknown.')
within the Phase 2 population (same 39-corp/883-row identity-validated rows as
scripts/probe_cogs_phase2_2026-08-15.py), and check global fuzzy-collision risk for each
candidate alias addition — same rigor as Phase 0 §Result 4 ('상품 및 제품매출원가').

For each candidate label, report:
  - how many (corp, row) occurrences in the Phase 2 population
  - the mapper's CURRENT result (unknown/low-conf)
  - whether adding it as an is.cogs alias would fuzzy-collide with any OTHER existing
    canonical's alias set (checked via mapper.map() on the label with a hypothetical
    higher weight — approximated by checking is there any non-is.cogs canonical this
    label's normalized form is already close to, using the mapper's own fuzzy path)

No DB writes, no code changes. Usage: python scripts/probe_cogs_unmapped_labels_2026-08-15.py
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
COGS_MARKER = "매출원가"


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
        unmapped = Counter()          # normalized label -> occurrence count
        unmapped_corps = {}           # normalized label -> set of corps
        raw_forms = {}                # normalized label -> set of raw label forms seen

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
            if not (n_missing == 0 and child_sum == pval):
                continue
            for lbl, v in children:
                if COGS_MARKER not in lbl:
                    continue
                r = mapper.map(lbl, fs_section="is")
                if r.confidence >= 0.88 and not r.account_code.startswith("unknown."):
                    continue   # already correctly mapped, not our concern here
                nlbl = norm_label(lbl)
                unmapped[nlbl] += 1
                unmapped_corps.setdefault(nlbl, set()).add(corp)
                raw_forms.setdefault(nlbl, set()).add(lbl)

        print(f"distinct unmapped normalized COGS labels = {len(unmapped)}")
        for nlbl, n in unmapped.most_common():
            corps = sorted(unmapped_corps[nlbl])
            forms = sorted(raw_forms[nlbl])
            r = mapper.map(nlbl, fs_section="is")
            print(f"\n  {nlbl!r} — occurrences={n}, corps={len(corps)}: {corps}")
            print(f"    raw forms seen: {forms}")
            print(f"    mapper.map({nlbl!r}) -> {r.account_code} stage={r.stage} conf={r.confidence}")

        # global fuzzy-collision check: for each candidate normalized label, see what the
        # mapper WOULD say if is.cogs alias weren't added — i.e. what's its best current
        # non-unknown guess (if any) across ALL fs sections, to catch any near-miss to a
        # DIFFERENT canonical that a blanket is.cogs alias could shadow/conflict with.
        print("\n=== cross-canonical collision scan (does this text look like it could mean something else?) ===")
        for nlbl in unmapped:
            for fs in ("is", "bs", "cf"):
                r = mapper.map(nlbl, fs_section=fs)
                if r.confidence > 0 and not r.account_code.startswith("unknown."):
                    print(f"  {nlbl!r} fs={fs} -> {r.account_code} stage={r.stage} conf={r.confidence}")

    print("\n=== DONE (read-only, no writes) ===")


if __name__ == "__main__":
    main()
