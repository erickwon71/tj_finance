"""
item 4 진단 — EXTRACT_EMPTY(추출 0행) 모집단 정밀 분해.

Gate A 가 REVIEW/EXTRACT_EMPTY 로 표시한 완료 다운로드를 XML/PDF·연도·기업으로 분해.
2015+ XML-추출0 의 실제 corp 목록(금융 우세 여부)을 확인한다. 읽기 전용.

    PYTHONPATH=. .venv_tj_finance/bin/python scripts/diag_extract_empty.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from collector.db import get_session


def main() -> None:
    with get_session() as session:
        rows = session.execute(text("""
            SELECT dt.rcept_no, dt.file_path,
                   f.corp_code, c.corp_name, c.market,
                   f.fiscal_year, f.fiscal_period, f.report_type
            FROM download_tasks dt
            JOIN filings f ON f.rcept_no = dt.rcept_no
            LEFT JOIN corporations c ON c.corp_code = f.corp_code
            WHERE dt.gate_a_status = 'REVIEW'
              AND dt.gate_a_reason = 'EXTRACT_EMPTY'
              AND f.is_final = TRUE
        """)).fetchall()

    print(f"총 EXTRACT_EMPTY filing: {len(rows):,}")

    by_ext = Counter()
    xml_by_year = Counter()
    xml_2015_corp = Counter()
    xml_2015_rows = []
    for r in rows:
        ext = Path(r.file_path).suffix.lower() if r.file_path else "?"
        by_ext[ext] += 1
        if ext == ".xml":
            xml_by_year[r.fiscal_year] += 1
            if (r.fiscal_year or 0) >= 2015:
                xml_2015_corp[(r.corp_code, r.corp_name)] += 1
                xml_2015_rows.append(r)

    print("\n[확장자별]")
    for ext, n in by_ext.most_common():
        print(f"  {ext:6} {n:,}")

    print("\n[XML 연도별 추출0]")
    for yr in sorted(xml_by_year, reverse=True):
        if (yr or 0) >= 2010:
            print(f"  {yr}: {xml_by_year[yr]:,}")

    print(f"\n[2015+ XML 추출0 기업 상위 25] (총 {len(xml_2015_rows):,} filing / {len(xml_2015_corp):,} corp)")
    for (cc, nm), n in xml_2015_corp.most_common(25):
        print(f"  {nm or '?':24} ({cc})  {n}")

    print("\n[2015+ XML 추출0 표본 8건 — 경로]")
    for r in xml_2015_rows[:8]:
        print(f"  {r.corp_name or '?':20} {r.fiscal_year} {r.fiscal_period:3} {r.report_type:8} {r.file_path}")


if __name__ == "__main__":
    main()
