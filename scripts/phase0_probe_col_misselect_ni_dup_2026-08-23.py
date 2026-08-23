"""Phase 0 verification probe for docs/plans/d_category_col_misselect_ni_label_dup_design_2026-08-23.md.

Calls extract_report_lines() directly on raw files (no production code
edits needed -- ReportLineRow already carries basis/depth/section_path/
col_index) to confirm, by actually running the code (not static analysis),
where each bug lives:

- Bug 1 (00104573 tax_expense col-misselect): run with a temporary debug
  print inside report_lines.py::_emit_section_lines (right before the
  `if "주당" in row.account_name` line) to dump row.amounts/cum_map, e.g.:
      if "법인세비용" in row.account_name:
          print("amounts=", row.amounts, "cum_map=", cum_map)
  Confirmed 2026-08-23: extract_rows()'s default preserve_col_positions=False
  drops the undisclosed leading CFY..Q cell instead of keeping a None
  placeholder, left-shifting row.amounts so cum_map={1:0, 3:1} lands on the
  wrong (PFY..Q) value. Root site: parser/xml/table_extractor.py::extract_rows()
  (see its preserve_col_positions docstring) -> corrupts cum_map consumption
  in fin2/extract/report_lines.py::_emit_section_lines() L498-503.

- Bug 2 (01497869 net_income/controlling_ni label dup): confirmed Layer 2
  (extract_report_lines) is NOT the culprit -- it correctly emits 3 distinct
  '계속영업손실' rows (depth=0/section_path=None = the true total;
  depth=2/section_path='...귀속>지배기업 소유주지분' and '...귀속>비지배지분'
  = the attributable sublines). The conflation must happen downstream in
  Layer 3 (fin2/layer3/combine.py) -- see scripts/phase0_probe_combine_2026-08-23.py
  for the (still unresolved) follow-up trace into combine.py itself.
"""
from fin2.extract.report_lines import extract_report_lines

TARGETS = [
    ("00104573", "20251113000801",
     "/Users/taejin/Project/tj_finance/raw_report/KOSDAQ/00104573_국일제지/quarter/2025/20251113000801.xml",
     2025, "Q3", "법인세비용"),
    ("01497869", "20250515002319",
     "/Users/taejin/Project/tj_finance/raw_report/KOSPI/01497869_티와이홀딩스/quarter/2025/20250515002319.xml",
     2025, "Q1", "계속영업손실"),
]

for corp, rcept, path, fy, fp, keyword in TARGETS:
    print(f"\n=== {corp} {rcept} fy{fy}{fp} ===")
    lines = extract_report_lines(path, rcept_no=rcept, corp_code=corp,
                                  report_fiscal_year=fy, report_fiscal_period=fp)
    for l in lines:
        if keyword in (l.label_raw or "") and l.statement == "IS" and (l.col_index or 0) == 0:
            print(f"  RESULT label={l.label_raw!r} basis={l.basis} depth={l.depth} "
                  f"section_path={l.section_path!r} node_role={l.node_role} "
                  f"value_won={l.value_won}")
