"""
item 4 진단 — Track B 섹션 탐지가 금융사 보고서에서 왜 0행인지 추적.

detect_sections / find_section_tables / extract_rows 를 단계별로 찍는다.

    PYTHONPATH=. .venv_tj_finance/bin/python scripts/diag_trackb_sections.py <xml_path>
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import detect_sections, find_section_tables, detect_unit_from_section
from parser.xml.table_extractor import extract_rows


def main() -> None:
    path = Path(sys.argv[1])
    root = _parse_xml_file(path)
    if root is None:
        print("파싱 실패")
        return

    sections = detect_sections(root)
    print("detect_sections 결과:")
    for code, elem in sections.items():
        found = elem is not None
        title = "".join(elem.itertext()).strip()[:40] if found else "-"
        print(f"  {code:6} found={found}  {title}")

    for code, elem in sections.items():
        if elem is None:
            continue
        tables = find_section_tables(elem)
        unit = detect_unit_from_section(elem)
        print(f"\n[{code}] find_section_tables={len(tables)} unit={unit}")
        for ti, table in enumerate(tables[:2]):
            trs = table.findall(".//TR")
            print(f"  table#{ti}: {len(trs)} TR")
            rows = extract_rows(table, multiplier=unit, num_cols=3)
            n_named = sum(1 for r in rows if r.account_name)
            print(f"    extract_rows={len(rows)} (named={n_named})")
            for r in rows[:6]:
                print(f"      acct={r.account_name!r:30} amts={r.amounts}")


if __name__ == "__main__":
    main()
