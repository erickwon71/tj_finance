"""구형 레이아웃 백필 **결과를 DB에서** 확인한다 (로그 신뢰 금지 — 실제 적재 확인).

`load_report_lines.py --redo-empty` 실행 후, 구형 레이아웃 문서가 정말로 채워졌는지와
잔여 공백의 정체를 DB 기준으로 본다.

사용:
    python scripts/verify_legacy_backfill_result.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (
    SEC_CONSOL_FS, SEC_SEP_FS, SEC_LEGACY_FS,
    assign_tables_to_dart_sections, normalize_dart_section_title,
)
from fin2.extract.text import _detect_body_statement_tables, _detect_fin_type

# 2015+ 전체에서 구형 레이아웃 문서를 다시 찾는다(공백이 메워졌으므로 SQL_GAP 으로는 못 찾는다).
SQL_2015 = """
SELECT f.corp_code, f.corp_name, f.fiscal_year, f.fiscal_period, f.rcept_no,
       d.file_path,
       (SELECT count(*) FROM report_lines r WHERE r.rcept_no = f.rcept_no) AS n_lines
  FROM filings f JOIN download_tasks d ON d.rcept_no = f.rcept_no
 WHERE f.fiscal_year BETWEEN 2015 AND 2019
   AND d.status = 'completed'
"""

# 잔여 공백(원 정의 그대로)
SQL_GAP_NOW = """
WITH grp AS (
  SELECT f.corp_code, f.corp_name, f.fiscal_year, f.fiscal_period, f.report_type,
         f.rcept_no,
         count(*) FILTER (
             WHERE EXISTS (SELECT 1 FROM report_lines r WHERE r.rcept_no = f.rcept_no)
         ) OVER (PARTITION BY f.corp_code, f.fiscal_year, f.fiscal_period, f.report_type)
             AS n_loaded,
         max(f.filed_at)
             OVER (PARTITION BY f.corp_code, f.fiscal_year, f.fiscal_period, f.report_type)
             AS last_filed
  FROM filings f WHERE f.fiscal_year >= 2015
)
SELECT corp_code, corp_name, fiscal_year, fiscal_period, report_type, rcept_no
FROM grp WHERE n_loaded = 0 AND last_filed <= DATE '2026-07-10'
"""


def main() -> int:
    with get_session() as s:
        rows = s.execute(text(SQL_2015)).fetchall()
        gap = s.execute(text(SQL_GAP_NOW)).fetchall()
        tasks = {r[0]: r[1] for r in s.execute(text(
            "SELECT rcept_no, file_path FROM download_tasks")).fetchall()}

    legacy_loaded = legacy_empty = 0
    total_lines = 0
    empties: list[tuple] = []

    for corp_code, corp_name, fy, fp, rcept, fpth, n_lines in rows:
        if not fpth or not Path(fpth).exists():
            continue
        root = _parse_xml_file(Path(fpth))
        if root is None:
            continue
        sec = assign_tables_to_dart_sections(root)
        if sec.get(SEC_CONSOL_FS) or sec.get(SEC_SEP_FS):
            continue                                   # 현대 서식 — 대상 아님
        titles = {normalize_dart_section_title("".join(t.itertext()))
                  for t in root.iter("TITLE")}
        if SEC_LEGACY_FS not in titles:
            continue                                   # C군(섹션 없음) — 대상 아님
        if n_lines > 0:
            legacy_loaded += 1
            total_lines += n_lines
        else:
            legacy_empty += 1
            empties.append((corp_name, fy, fp, rcept))

    print("=== 구형 레이아웃(`XI. 재무제표 등` 보유) 문서의 DB 적재 상태 ===")
    print(f"  적재됨 : {legacy_loaded}건 · report_lines {total_lines:,}행 "
          f"(문서당 평균 {total_lines // max(legacy_loaded, 1)}행)")
    print(f"  0행    : {legacy_empty}건")
    for e in empties[:10]:
        print(f"     {e}")

    print(f"\n=== 2015+ 잔여 공백(기간 그룹 기준) : {len(gap)}건 ===")
    kinds: Counter = Counter()
    for corp_code, corp_name, fy, fp, rt, rcept in gap:
        fpth = tasks.get(rcept)
        if not fpth or not Path(fpth).exists():
            kinds["원문 없음"] += 1
            continue
        root = _parse_xml_file(Path(fpth))
        if root is None:
            kinds["XML 파싱 실패"] += 1
            continue
        groups = _detect_body_statement_tables(root, _detect_fin_type(root), include_sce=True)
        if groups:
            kinds["표는 잡히는데 미적재(재파싱 대기)"] += 1
        else:
            sec = assign_tables_to_dart_sections(root)
            if sec.get(SEC_CONSOL_FS) or sec.get(SEC_SEP_FS):
                kinds["본문섹션 있음 · 표 분류 실패"] += 1
            else:
                kinds["본문섹션 없음(구형 C군 등)"] += 1
    for k, v in kinds.most_common():
        print(f"  {v:4d}  {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
