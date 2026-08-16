"""
R28 follow-up track T3-1 -- source cross-check for 5 hand-picked samples.
(docs/plans/eps_r28_followup_tracks_design_2026-08-16.md §6 T3-1.)

For each sample, reproduces the same table/row the extractor used (via the same
routing report_lines.py uses: pre-2015 merged groups for FY<=2010, direct_only rows,
no skip_junk) and prints:
  - the table's declared unit multiplier + provenance text
  - the target row's raw_amounts (as printed in the source XML, BEFORE the unit
    multiplier) and amounts (AFTER the multiplier == what report_lines stores)
  - a few neighboring rows for context, to confirm the row really is the headline
    NI row (not some other row a '순이익'+'주당' substring match grabbed).

Read-only. No DB/source writes.

Usage:
  .venv/bin/python scripts/verify_t3_1_source_2026-08-16.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fin2.extract.report_lines import (                                    # noqa: E402
    _detect_body_statement_tables, _detect_pre2015_body_statement_tables_merged,
    _detect_fin_type, _PRE2015_ROUTING_MAX_FY, _emit_section_lines,
)
from fin2.extract.text import _interim_cumulative_cols, document_default_unit  # noqa: E402
from parser.xml.dart_xml_parser import _parse_xml_file                     # noqa: E402
from parser.xml.table_extractor import extract_rows                        # noqa: E402
from parser.xml.section_detector import table_direct_rows                  # noqa: E402
from fin2.extract.report_lines import _detect_period_layout                # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]

# (rcept, corp, fiscal_year, fiscal_period, basis, table_seq, target_row_order, note)
SAMPLES = [
    dict(rcept="20031229000074", corp="00298377", fy=2003, period="FY", basis="separate",
         table_seq=0, row_order=63,
         file=REPO_ROOT / "raw_report/KOSDAQ/00298377_아이씨디/annual/2003/20031229000074.xml"),
    dict(rcept="20030813000576", corp="00109286", fy=2003, period="H1", basis="separate",
         table_seq=0, row_order=68,
         file=REPO_ROOT / "raw_report/KOSPI/00109286_대동/half/2003/20030813000576.xml"),
    dict(rcept="20050314000303", corp="00113410", fy=2004, period="FY", basis="separate",
         table_seq=0, row_order=68,
         file=REPO_ROOT / "raw_report/KOSPI/00113410_CJ대한통운/annual/2004/20050314000303.xml"),
    dict(rcept="20060629000325", corp="00117601", fy=2006, period="FY", basis="separate",
         table_seq=0, row_order=78,
         file=REPO_ROOT / "raw_report/KOSPI/00117601_유안타증권/annual/2006/20060629000325.xml"),
    dict(rcept="20071113000425", corp="00350020", fy=2007, period="Q3", basis="consolidated",
         table_seq=0, row_order=88,
         file=REPO_ROOT / "raw_report/KOSDAQ/00350020_파인디앤씨/quarter/2007/20071113000425.xml"),
]

_GROUP_FOR_BASIS = {"separate": "IS_S", "consolidated": "IS_C"}


def resolve_groups(root, fy):
    fin_type = _detect_fin_type(root)
    if fy <= _PRE2015_ROUTING_MAX_FY:
        return _detect_pre2015_body_statement_tables_merged(root, fin_type)
    return _detect_body_statement_tables(root, fin_type, include_sce=True)


def main():
    for s in SAMPLES:
        print(f"\n{'=' * 90}")
        print(f"rcept={s['rcept']} corp={s['corp']} {s['fy']}{s['period']} basis={s['basis']} "
              f"table_seq={s['table_seq']} target_row_order={s['row_order']}")
        print(f"file={s['file']}")
        if not s['file'].exists():
            print("  !! FILE NOT FOUND")
            continue
        root = _parse_xml_file(s['file'])
        groups = resolve_groups(root, s['fy'])
        code = _GROUP_FOR_BASIS[s['basis']]
        tws = groups.get(code)
        if not tws:
            print(f"  !! group {code} not found. groups={list(groups.keys())}")
            continue

        # Reproduce report_lines.py's table ordering: doc-order dedup, then
        # data_tables = sorted by row count desc for the actual emission loop --
        # but table_seq is the DOC-ORDER index (doc_seq), not the size-sorted index.
        tables = [t for t, _, _ in tws]
        unit_of = {id(t): u for t, u, _ in tws}
        tables_deduped = list(dict.fromkeys(tables))
        doc_seq = {id(t): i for i, t in enumerate(tables_deduped)}

        target_table = None
        for t in tables_deduped:
            if doc_seq[id(t)] == s['table_seq']:
                target_table = t
                break
        if target_table is None:
            print(f"  !! table_seq {s['table_seq']} not found among "
                  f"{sorted(doc_seq.values())}")
            continue

        unit = unit_of[id(target_table)]
        unit_note = "declared"
        if unit is None:
            dd = document_default_unit(root)
            unit, unit_note = dd[0], f"doc_default({dd[1]!r})"
        print(f"  table unit multiplier applied = {unit}  ({unit_note})")

        interim_flow = "IS" in code and s['period'] in ("H1", "Q1", "Q3")
        cum_map = _interim_cumulative_cols(target_table) if interim_flow else None
        n_periods, multicol = (3, False) if cum_map is not None else _detect_period_layout(target_table)
        n_cols = max(cum_map) + 1 if cum_map else (8 if multicol else 3)
        print(f"  interim_flow={interim_flow}  cum_map={cum_map}  multicol={multicol}")
        rows = list(extract_rows(target_table, multiplier=unit, num_cols=n_cols,
                                  direct_only=True, skip_junk=False))
        print(f"  table has {len(rows)} extracted rows (row_order 0..{len(rows) - 1})")

        def col0_value(row):
            """Reproduce _emit_section_lines' pairs logic to find what col_index=0 (당기) is."""
            if cum_map is not None:
                pairs = [(off, row.amounts[pos]) for pos, off in cum_map.items()
                         if pos < len(row.amounts) and row.amounts[pos] is not None]
                if not pairs:
                    present = [a for a in row.amounts if a is not None]
                    pairs = list(enumerate(present))
            elif multicol:
                present = [a for a in row.amounts if a is not None]
                pairs = list(enumerate(present[:n_periods]))
            else:
                amts = row.amounts
                lead = 0
                while lead < len(amts) and amts[lead] is None:
                    lead += 1
                pairs = list(enumerate(amts[lead:]))
            d = dict(pairs)
            return d.get(0)

        lo = max(0, s['row_order'] - 2)
        hi = min(len(rows), s['row_order'] + 3)
        for row in rows[lo:hi]:
            marker = " <<< TARGET" if row.row_order == s['row_order'] else ""
            print(f"    [{row.row_order}] {row.account_name!r}{marker}")
            print(f"        amounts(after x{unit})={row.amounts}")
            print(f"        raw_amounts(as printed)={row.raw_amounts}")
            if row.row_order == s['row_order']:
                print(f"        --> emitted col_index=0 (당기) value = {col0_value(row):,}"
                      if col0_value(row) is not None else "        --> col_index=0 value = None")


if __name__ == "__main__":
    main()
