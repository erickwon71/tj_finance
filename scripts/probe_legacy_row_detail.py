"""대조에서 어긋난 라벨의 **원문 행 셀 배열**과 추출 결과를 나란히 본다.

`verify_legacy_against_source.py` 가 낸 불일치/거짓부재가 **진짜 결함인지, 대조기의 한계인지**
가르기 위한 도구다(R9 — 개별 사례를 원문까지 따라간다).

사용:
    python scripts/probe_legacy_row_detail.py --rcept 20141128001023 --label 기본주당이익
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import table_direct_rows
from parser.xml.table_extractor import _get_cells
from fin2.extract.report_lines import extract_report_lines
from fin2.extract.text import _detect_body_statement_tables, _detect_fin_type


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rcept", required=True)
    ap.add_argument("--label", required=True)
    args = ap.parse_args()

    with get_session() as s:
        row = s.execute(text("""
            SELECT f.corp_code, f.fiscal_year, f.fiscal_period, d.file_path
              FROM filings f JOIN download_tasks d ON d.rcept_no = f.rcept_no
             WHERE f.rcept_no = :r
        """), {"r": args.rcept}).fetchone()
    corp_code, fy, fp, fpth = row

    root = _parse_xml_file(Path(fpth))
    groups = _detect_body_statement_tables(root, _detect_fin_type(root), include_sce=True)

    key = re.sub(r"\s+", "", args.label)
    print("=== 원문 행 ===")
    for code, tables in groups.items():
        for ti, (tbl, unit, _kind) in enumerate(tables):
            for tr in table_direct_rows(tbl):
                cells = [c.strip() for c in _get_cells(tr)]
                if any(key in re.sub(r"\s+", "", c) for c in cells):
                    print(f"  [{code} 표{ti} unit={unit}] {cells}")

    print("\n=== 추출 행 ===")
    lines = extract_report_lines(fpth, rcept_no=args.rcept, corp_code=corp_code,
                                 report_fiscal_year=fy, report_fiscal_period=fp)
    for ln in lines:
        if key in re.sub(r"\s+", "", ln.label_raw or ""):
            print(f"  {ln.statement}/{ln.basis} col={ln.col_index} "
                  f"label={ln.label_raw!r} won={ln.value_won} raw={ln.value_raw!r} "
                  f"adec={ln.adecimal} unit_src={ln.unit_source} hint={ln.header_hint}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
