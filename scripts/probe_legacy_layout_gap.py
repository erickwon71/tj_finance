"""계층2 적재 공백 filing 의 **원문 섹션 구조**를 계측한다 (구형 레이아웃 규명).

배경 — 2026-08-04 감사에서 2015+ 계층2 진짜 공백 189건 중 ~109건이
"구형 레이아웃 미지원"으로 분류됐다. 재무제표가 `XI. 재무제표 등` 아래 있어
`_detect_body_statement_tables` 가 후보 섹션(`2.연결재무제표`/`4.재무제표`)을
못 찾는다는 가설이다.

이 스크립트는 가설을 **실측으로 확정**한다(R9: 휴리스틱 대신 실제 코드 경로 계측):
  · 문서의 SECTION-* TITLE 을 전부 덤프
  · `assign_tables_to_dart_sections` 가 실제로 귀속시킨 표 수
  · `_detect_body_statement_tables` 가 실제로 반환한 본문표 수
  · 문서 전체 TABLE 수(경계 앵커 `<TABLE[\\s>]` 로 원문 카운트 — 2026-08-04 계측버그 재발 방지)

사용:
    python scripts/probe_legacy_layout_gap.py               # 요약
    python scripts/probe_legacy_layout_gap.py --detail 20   # 앞 20건 TITLE 덤프
    python scripts/probe_legacy_layout_gap.py --rcept 20160330000123   # 단건 정밀
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (
    assign_tables_to_dart_sections, classify_dart_section,
    normalize_dart_section_title,
)
from fin2.extract.text import _detect_body_statement_tables, _detect_fin_type

# 2026-08-04 §4 와 같은 정의: report_lines 가 통째로 비어 있는 (기업·연도·기간·종류).
# download-only 백로그(2026-07-10 이후 제출)는 제외 — 아직 파싱을 안 돌린 것뿐이다.
SQL_GAP = """
WITH grp AS (
  SELECT f.corp_code, f.corp_name, f.fiscal_year, f.fiscal_period, f.report_type,
         f.rcept_no, f.filed_at,
         count(*) FILTER (
             WHERE EXISTS (SELECT 1 FROM report_lines r WHERE r.rcept_no = f.rcept_no)
         ) OVER (PARTITION BY f.corp_code, f.fiscal_year, f.fiscal_period, f.report_type)
             AS n_loaded,
         max(f.filed_at)
             OVER (PARTITION BY f.corp_code, f.fiscal_year, f.fiscal_period, f.report_type)
             AS last_filed
  FROM filings f
  WHERE f.fiscal_year >= 2015
)
SELECT corp_code, corp_name, fiscal_year, fiscal_period, report_type, rcept_no, filed_at
FROM grp
WHERE n_loaded = 0 AND last_filed <= DATE '2026-07-10'
ORDER BY corp_name, fiscal_year, fiscal_period
"""

# 원문 표 수 — 경계를 앵커한다. `b"<TABLE"` 은 `<TABLE-GROUP>` 까지 세어 원문 표 수를
# 부풀린다(2026-08-04 세션에서 실제로 틀린 계측).
_RAW_TABLE_RE = re.compile(rb"<TABLE[\s>]", re.I)


def _load(rcept_no: str, file_path: str | None):
    if not file_path or not Path(file_path).exists():
        return None, None
    raw = Path(file_path).read_bytes()
    return _parse_xml_file(Path(file_path)), raw


def _section_titles(root) -> list[str]:
    """문서 순서상 SECTION-* 의 TITLE 원문."""
    out = []
    for el in root.iter():
        tag = el.tag.upper() if isinstance(el.tag, str) else ""
        if not tag.startswith("SECTION"):
            continue
        t = el.find("TITLE")
        if t is not None:
            out.append(" ".join("".join(t.itertext()).split()))
    return out


def probe_one(rcept_no: str, file_path: str | None) -> dict:
    root, raw = _load(rcept_no, file_path)
    if root is None:
        return {"rcept_no": rcept_no, "status": "no_file"}

    titles = _section_titles(root)
    assigned = assign_tables_to_dart_sections(root)
    groups = _detect_body_statement_tables(root, _detect_fin_type(root), include_sce=True)
    n_raw_tables = len(_RAW_TABLE_RE.findall(raw))

    return {
        "rcept_no": rcept_no,
        "status": "ok",
        "titles": titles,
        "classified": [t for t in titles if classify_dart_section(t)],
        "assigned": {k: len(v) for k, v in assigned.items()},
        "body_groups": {k: len(v) for k, v in groups.items()},
        "n_raw_tables": n_raw_tables,
        "n_parsed_tables": len(root.findall(".//TABLE")),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", type=int, default=0, help="앞 N건 TITLE 덤프")
    ap.add_argument("--rcept", help="단건 정밀 진단")
    args = ap.parse_args()

    with get_session() as s:
        tasks = {r[0]: r[1] for r in s.execute(text(
            "SELECT rcept_no, file_path FROM download_tasks")).fetchall()}
        if args.rcept:
            rows = s.execute(text("""
                SELECT corp_code, corp_name, fiscal_year, fiscal_period, report_type,
                       rcept_no, filed_at
                  FROM filings WHERE rcept_no = :r
            """), {"r": args.rcept}).fetchall()
        else:
            rows = s.execute(text(SQL_GAP)).fetchall()

    print(f"대상 filing {len(rows)}건\n")

    buckets: Counter = Counter()
    detail_shown = 0
    legacy_examples: list[tuple] = []

    for corp_code, corp_name, fy, fp, rt, rcept, filed in rows:
        r = probe_one(rcept, tasks.get(rcept))
        if r["status"] == "no_file":
            buckets["원문 없음"] += 1
            continue

        has_body_section = any(
            classify_dart_section(t) in ("연결재무제표", "재무제표") for t in r["titles"])
        n_body = sum(r["body_groups"].values())

        if n_body > 0:
            bucket = "본문표 검출됨(다른 원인)"
        elif has_body_section:
            bucket = "본문섹션 있음 · 표 분류 실패"
        elif r["n_raw_tables"] == 0:
            bucket = "원문에 표 없음"
        else:
            bucket = "★본문섹션 없음(구형 레이아웃 후보)"
            legacy_examples.append((corp_name, fy, fp, rcept, r))
        buckets[bucket] += 1

        if args.rcept or (args.detail and detail_shown < args.detail
                          and bucket.startswith("★")):
            detail_shown += 1
            print(f"── {corp_name} {fy}{fp} {rt} {rcept} [{bucket}]")
            print(f"   원문표={r['n_raw_tables']} 파싱표={r['n_parsed_tables']} "
                  f"귀속={r['assigned']} 본문그룹={r['body_groups']}")
            for t in r["titles"][:40]:
                mark = "✔" if classify_dart_section(t) else " "
                print(f"   {mark} {t[:90]}  → norm={normalize_dart_section_title(t)[:50]}")
            print()

    print("=== 분류 ===")
    for k, v in buckets.most_common():
        print(f"  {v:5d}  {k}")

    if legacy_examples and not args.rcept:
        print("\n=== 구형 레이아웃 후보의 TITLE 빈도(상위 30) ===")
        c: Counter = Counter()
        for _, _, _, _, r in legacy_examples:
            for t in r["titles"]:
                c[normalize_dart_section_title(t)] += 1
        for k, v in c.most_common(30):
            print(f"  {v:5d}  {k[:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
