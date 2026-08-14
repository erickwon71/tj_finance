"""Read-only diagnostic (재실행 가능) — reproduce report_lines extraction for
Hanjin Heavy Industries Holdings (00163673), separate IS, rcept 20250814001174,
to show why 'Ⅰ.영업수익' col_index=0 ends up as 629 (should be 9,097).

Root cause: `parser/xml/table_extractor.py::_split_label_amounts()`'s note-reference-number
guard mistakes a comma-less 1~3 digit first-period amount ("654") for a footnote reference
and drops it, shifting every later amount left by one column.
See docs/qa/gate_b_revenue_bugB_note_ref_guard_root_cause_2026-08-14.md.

No DB writes, no source changes.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fin2.extract.report_lines import extract_report_lines, _detect_body_statement_tables, _detect_fin_type
from fin2.extract.text import _interim_cumulative_cols
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.table_extractor import extract_rows, _get_cells, _split_label_amounts
from parser.xml.section_detector import table_direct_rows

FILE = "/Users/taejin/Project/tj_finance/raw_report/KOSPI/00163673_한진중공업홀딩스/half/2025/20250814001174.xml"


def main():
    root = _parse_xml_file(Path(FILE))
    fin_type = _detect_fin_type(root)
    print("fin_type:", fin_type)

    groups = _detect_body_statement_tables(root, fin_type, include_sce=True)
    print("groups keys:", list(groups.keys()))

    for code, tws in groups.items():
        if not code.startswith("IS"):
            continue
        print(f"\n=== {code}: {len(tws)} tables ===")
        for i, (t, u, _) in enumerate(tws):
            cum_map = _interim_cumulative_cols(t)
            n_rows = len(t.findall(".//TR"))
            print(f"  table[{i}] rows={n_rows} unit={u} cum_map={cum_map}")

    print("\n=== raw extract_rows on IS_S table[0] ===")
    tws = groups["IS_S"]
    t0, u0, _ = tws[0]
    cum_map0 = _interim_cumulative_cols(t0)
    n_cols0 = max(cum_map0) + 1 if cum_map0 else 3
    rows0 = list(extract_rows(t0, multiplier=u0, num_cols=n_cols0, direct_only=True, skip_junk=False))
    for r in rows0:
        print("account_name:", repr(r.account_name), "amounts:", r.amounts)

    print("\n=== raw TR cell inspection (root cause) ===")
    for tr in table_direct_rows(t0):
        cells = _get_cells(tr)
        if cells and "영업수익" in cells[0]:
            print("cells:", cells)
            label, amt = _split_label_amounts(cells)
            print("label:", repr(label), "amount_cells:", amt, " ← '654' dropped here")

    print("\n=== full extract_report_lines (what actually gets stored) ===")
    lines = extract_report_lines(
        FILE, rcept_no="20250814001174", corp_code="00163673",
        report_fiscal_year=2025, report_fiscal_period="H1",
    )
    for l in lines:
        if l.statement == "IS" and l.basis == "separate" and "영업수익" in (l.label_raw or ""):
            print(l.table_seq, l.col_index, l.value_won, l.label_raw, l.is_cumulative, l.context_fiscal_year)


if __name__ == "__main__":
    main()
