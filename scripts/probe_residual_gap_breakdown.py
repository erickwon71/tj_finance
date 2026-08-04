"""잔여 공백 97건을 **원인별로 정확히** 가르고 대표 사례를 뽑는다.

앞선 설명이 'done 77 / 미등록 20' 이라는 **로더 원장 상태**와
'파싱 가능 여부' 라는 **다른 축**을 뒤섞었다. 두 축은 독립이다:

  · 로더 원장   : 로더가 이 보고서를 처리한 적이 있는가 (done / 미등록)
  · 감지기 결과 : 지금 감지기를 돌리면 본문표가 잡히는가 (잡힘 / 안 잡힘)

'미등록 & 잡힘' 은 **파싱 실패가 아니라 그냥 안 돌린 것**이고,
'done & 안 잡힘' 이라야 진짜 파싱 미지원이다.

사용:
    python scripts/probe_residual_gap_breakdown.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
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

SQL = """
WITH grp AS (
  SELECT f.corp_code, f.corp_name, f.fiscal_year, f.fiscal_period, f.report_type, f.rcept_no,
         count(*) FILTER (
           WHERE EXISTS (SELECT 1 FROM report_lines r WHERE r.rcept_no=f.rcept_no))
           OVER (PARTITION BY f.corp_code,f.fiscal_year,f.fiscal_period,f.report_type) AS n_loaded,
         max(f.filed_at)
           OVER (PARTITION BY f.corp_code,f.fiscal_year,f.fiscal_period,f.report_type) AS last_filed
    FROM filings f WHERE f.fiscal_year >= 2015
)
SELECT g.corp_name, g.fiscal_year, g.fiscal_period, g.rcept_no,
       p.status, d.file_path
  FROM grp g
  LEFT JOIN report_line_load_progress p ON p.rcept_no = g.rcept_no
  LEFT JOIN download_tasks d ON d.rcept_no = g.rcept_no
 WHERE g.n_loaded = 0 AND g.last_filed <= DATE '2026-07-10'
 ORDER BY g.corp_name, g.fiscal_year
"""

DART = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="


def main() -> int:
    with get_session() as s:
        rows = s.execute(text(SQL)).fetchall()

    buckets: dict[str, list] = defaultdict(list)

    for corp_name, fy, fp, rcept, status, fpth in rows:
        ledger = "done" if status == "done" else ("미등록" if status is None else status)

        if not fpth or not Path(fpth).exists():
            buckets[f"[{ledger}] 원문 파일 없음"].append((corp_name, fy, fp, rcept))
            continue
        root = _parse_xml_file(Path(fpth))
        if root is None:
            buckets[f"[{ledger}] XML 파싱 자체 실패"].append((corp_name, fy, fp, rcept))
            continue

        groups = _detect_body_statement_tables(root, _detect_fin_type(root), include_sce=True)
        n_tbl = sum(len(v) for v in groups.values())
        sec = assign_tables_to_dart_sections(root)
        modern = bool(sec.get(SEC_CONSOL_FS) or sec.get(SEC_SEP_FS))
        titles = {normalize_dart_section_title("".join(t.itertext()))
                  for t in root.iter("TITLE")}
        legacy = SEC_LEGACY_FS in titles

        if n_tbl > 0:
            layout = "현대서식" if modern else ("구형서식" if legacy else "기타서식")
            buckets[f"[{ledger}] ✅표 잡힘({layout}) — 파싱 문제 아님, 적재만 안 됨"].append(
                (corp_name, fy, fp, rcept))
        else:
            if modern:
                why = "본문섹션은 있는데 표 분류 실패"
            elif legacy:
                why = "구형섹션은 있는데 표 없음(XML 절단 등)"
            else:
                why = "본문·구형 섹션 둘 다 없음(다른 서식)"
            buckets[f"[{ledger}] ❌표 못 잡음 — {why}"].append((corp_name, fy, fp, rcept))

    print(f"=== 잔여 공백 {len(rows)}건 원인 분해 ===\n")
    for k in sorted(buckets, key=lambda x: -len(buckets[x])):
        v = buckets[k]
        print(f"{len(v):4d}건  {k}")
        # 대표 사례 = 그 군에서 서로 다른 기업 최대 3곳
        seen = set()
        for corp_name, fy, fp, rcept in v:
            if corp_name in seen:
                continue
            seen.add(corp_name)
            print(f"         · {corp_name} {fy}{fp}  {DART}{rcept}")
            if len(seen) >= 3:
                break
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
