"""P2-1 investigation: why do 두산밥캣 (20260814003597) and 아남전자 (20260811000654)
extract 0 report_lines rows from their xbrl_zip filings?

extract_report_lines_xbrl() never raises -- any failure is logged and yields [].
This script replicates its internals step by step (bypassing the swallowed
per-role try/except) so the exact point where candidates go to zero is visible.

Do not run with `python -c` (project convention) -- this file is the investigation
script called out in docs/plans/handoff_next_session_2026-08-19.md section 6.
"""
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fin2.extract.report_lines_xbrl import (  # noqa: E402
    _BASIS_AXIS_LOCAL,
    _BASIS_MEMBER_LOCAL,
    _basis_candidates,
    _extract_zip_members,
    _resolve_ifrs_namespace,
    _SUPPORTED_STATEMENTS,
)
from parser.xbrl_instance.instance_parser import QName, parse_instance  # noqa: E402
from parser.xbrl_instance.taxonomy_linkbase import parse_presentation  # noqa: E402
from parser.xbrl_instance.role_map import build_role_map, index_core_roles  # noqa: E402

CASES = [
    dict(
        label="두산밥캣 20260814003597",
        zip_path="/Users/taejin/Project/tj_finance/raw_report/KOSPI/01032486_두산밥캣/half/2026/20260814003597.zip",
        period_end_date=date(2026, 6, 30),
    ),
    dict(
        label="아남전자 20260811000654",
        zip_path="/Users/taejin/Project/tj_finance/raw_report/KOSPI/00138516_아남전자/half/2026/20260811000654.zip",
        period_end_date=date(2026, 6, 30),
    ),
]

for case in CASES:
    print(f"\n{'=' * 80}\n{case['label']}\n{'=' * 80}")
    zip_path = Path(case["zip_path"])
    period_end_date = case["period_end_date"]

    with tempfile.TemporaryDirectory(prefix="xbrl_inv_") as tmp:
        tmp_dir = Path(tmp)
        members = _extract_zip_members(zip_path, tmp_dir)
        instance = parse_instance(members.xbrl)
        pre_trees = parse_presentation(members.pre, instance.nsmap)
        core_roles = index_core_roles(
            build_role_map(members.xsd, needed_role_uris=set(pre_trees.keys()))
        )
        print(f"core_roles: {list(core_roles.keys())}")

        basis_axis_ns = _resolve_ifrs_namespace(instance.nsmap)
        print(f"basis_axis_ns: {basis_axis_ns}")
        if basis_axis_ns is None:
            continue
        basis_axis = QName(ns=basis_axis_ns, local=_BASIS_AXIS_LOCAL)

        facts_by_qname = {}
        for f in instance.facts:
            facts_by_qname.setdefault(f.qname, []).append(f)
        print(f"total facts: {len(instance.facts)}, distinct qnames: {len(facts_by_qname)}")

        # Context dims profile -- 0 dims means the filer never tagged the
        # consolidated/separate axis at all, which would make every
        # _basis_candidates() call return empty (len(ctx.dims) != 1 guard).
        dims_count_hist = Counter(len(c.dims) for c in instance.contexts.values())
        print(f"context dims-count histogram: {dict(dims_count_hist)}")
        axis_locals_seen = Counter()
        for c in instance.contexts.values():
            for d in c.dims:
                axis_locals_seen[d.axis.local] += 1
        print(f"axis locals seen across all contexts (top 10): {axis_locals_seen.most_common(10)}")

        for (statement, basis), role_info in core_roles.items():
            if statement not in _SUPPORTED_STATEMENTS:
                continue
            tree = pre_trees.get(role_info.role_uri)
            print(f"\n  ({statement}, {basis}): role_uri={role_info.role_uri}, "
                  f"tree_found={tree is not None}")
            if tree is None:
                continue
            basis_member = QName(ns=basis_axis_ns, local=_BASIS_MEMBER_LOCAL[basis])
            n_nodes = len(tree.nodes)
            n_with_facts = 0
            n_with_candidates = 0
            for loc_label, node in tree.nodes.items():
                fl = facts_by_qname.get(node.element, [])
                if fl:
                    n_with_facts += 1
                cand = _basis_candidates(node.element, facts_by_qname, instance.contexts,
                                          basis_axis, basis_member)
                if cand:
                    n_with_candidates += 1
            print(f"    nodes={n_nodes}, nodes_with_any_fact={n_with_facts}, "
                  f"nodes_with_basis_candidates={n_with_candidates}")

        # Deep dive: for the BS role, pick one concrete node and print the
        # actual dates its basis-filtered candidates carry, vs period_end_date.
        for (statement, basis), role_info in core_roles.items():
            if statement != "BS":
                continue
            tree = pre_trees.get(role_info.role_uri)
            basis_member = QName(ns=basis_axis_ns, local=_BASIS_MEMBER_LOCAL[basis])
            print(f"\n  -- BS/{basis} per-node date check (period_end_date={period_end_date}) --")
            shown = 0
            for loc_label, node in tree.nodes.items():
                cand = _basis_candidates(node.element, facts_by_qname, instance.contexts,
                                          basis_axis, basis_member)
                if not cand:
                    continue
                dates = sorted({c.instant if c.period_kind == "instant" else f"{c.start_date}~{c.end_date}"
                                 for _, c in cand})
                print(f"    {node.element.local}: {dates}")
                shown += 1
                if shown >= 5:
                    break

        # Full _emit_statement_lines call, no swallowing, to see the real count
        # and catch any exception verbatim.
        from fin2.extract.report_lines_xbrl import _emit_statement_lines, _emit_missing_totals
        print(f"\n  -- full _emit_statement_lines per (statement,basis) --")
        for (statement, basis), role_info in core_roles.items():
            if statement not in _SUPPORTED_STATEMENTS:
                continue
            tree = pre_trees.get(role_info.role_uri)
            if tree is None:
                continue
            basis_member = QName(ns=basis_axis_ns, local=_BASIS_MEMBER_LOCAL[basis])
            try:
                rows = _emit_statement_lines(
                    tree=tree, facts_by_qname=facts_by_qname, contexts=instance.contexts,
                    units=instance.units, labels={}, basis_axis=basis_axis,
                    basis_member=basis_member, statement=statement, basis=basis,
                    corp_code="X", rcept_no="X",
                    report_fiscal_year=2026, report_fiscal_period="H1",
                    period_end_date=period_end_date,
                )
                print(f"    ({statement},{basis}): {len(rows)} rows")
            except Exception as e:
                print(f"    ({statement},{basis}): EXCEPTION {type(e).__name__}: {e}")
        print(f"units count: {len(instance.units)}")
        sample_units = list(instance.units.items())[:3]
        print(f"sample units: {sample_units}")
        print(f"ALL units: {list(instance.units.keys())}")
        print(f"unit measures: {[(k, v.measure.local if v.measure else None) for k, v in instance.units.items()]}")
