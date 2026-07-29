"""로컬 원본 XML 에서 특정 라벨이 **어느 주석 아래에** 있는지 사람이 읽을 수 있게 출력.

DART 사이트가 점검 중일 때 다운로드된 원본으로 직접 확인하기 위한 도구.
정규화(sanitize) 전/후를 나란히 보여줘 "오귀속이 교정된 것인지"를 눈으로 확인할 수 있다.

Usage
-----
    python scripts/show_note_source.py --rcept 20250317001028 --label 차입금, 기준이자율
    python scripts/show_note_source.py --rcept 20250317001028 --label 장기차입금 --basis consolidated
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import extract_report_lines
import parser.xml.dart_xml_parser as dxp

PATH_SQL = text(
    "SELECT d.file_path, f.corp_code FROM download_tasks d JOIN filings f USING (rcept_no) "
    "WHERE d.rcept_no = :r AND d.file_type='xml' LIMIT 1"
)


def collect(path, rcept, corp, fy, per, sanitize: bool):
    orig = dxp.sanitize_dart_xml
    try:
        if not sanitize:
            dxp.sanitize_dart_xml = lambda b: b
        return list(extract_report_lines(path, rcept_no=rcept, corp_code=corp,
                                         report_fiscal_year=fy,
                                         report_fiscal_period=per,
                                         include_notes=True))
    finally:
        dxp.sanitize_dart_xml = orig


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rcept", required=True)
    ap.add_argument("--label", required=True, help="찾을 라벨(부분일치)")
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--period", default="FY")
    ap.add_argument("--basis", default=None)
    args = ap.parse_args()

    with get_session() as s:
        row = s.execute(PATH_SQL, {"r": args.rcept}).fetchone()
    if not row:
        print("파일 경로를 찾을 수 없다")
        return 1
    print(f"원본: {row.file_path}\n")

    for tag, san in (("정규화 전(기존 적재)", False), ("정규화 후(현재)", True)):
        rows = collect(row.file_path, args.rcept, row.corp_code,
                       args.year, args.period, san)
        hits = [
            r for r in rows
            if r.statement == "note" and args.label in (r.label_raw or "")
            and (args.basis is None or r.basis == args.basis)
        ]
        print(f"=== {tag} — '{args.label}' 포함 행 {len(hits)}개 ===")
        seen = set()
        for r in hits[:12]:
            key = (r.basis, r.section_path, r.label_raw, r.col_index)
            if key in seen:
                continue
            seen.add(key)
            val = f"{r.value_won:,}" if r.value_won is not None else "-"
            print(f"  [{r.basis[:4]}] 주석 <{r.section_path}>")
            print(f"        {r.label_raw[:46]:<46} c{r.col_index} = {val}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
