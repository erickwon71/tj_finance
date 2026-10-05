#!/usr/bin/env python
"""정기보고서 비재무 섹션 표 카탈로그 (READ-ONLY) — API→문서 전환 Phase 0.

docs/plans/api_to_document_migration_plan_2026-10-05.md §2·§3.

DART 원문은 표준 서식 표를 `<TABLE-GROUP ACLASS="DIVIDEND">` 처럼 서식 코드로 감싼다.
표제 문자열은 시대마다 흔들리지만(배당에관한사항 / 배당에관한사항등 / 가.최근5사업연도의…)
서식 코드는 안정적이라 계층2 의 1차 키로 쓴다. 이 도구는 연도별 표본에서
  · 서식 코드별 출현 필링 수(연도 구간별)와 대표 섹션 표제·헤더 행
  · 대상 섹션 안에 있는데 서식 코드가 **없는** 표(표제 폴백이 필요한 경우)
를 센다.

Usage
-----
    python scripts/audit_doc_section_catalog.py --per-year 40 --workers 4 --sd-mirror \
        --out docs/qa/doc_section_catalog_2026-10-05.md
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from collector.storage_guard import BACKUP_ROOT, SYMLINK as _RAW_REPORT_SYMLINK
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import normalize_dart_section_title, table_direct_rows
from parser.xml.table_extractor import _get_cells

# Section-title keywords of the migration targets (title fallback when no ACLASS).
TARGET_KEYWORDS = ("배당", "주주", "임원", "직원", "타법인출자", "자기주식", "주식의총수")

_SAMPLE_SQL = """
    SELECT rcept_no, fiscal_year, file_path FROM (
        SELECT f.rcept_no, f.fiscal_year, d.file_path,
               row_number() OVER (PARTITION BY f.fiscal_year ORDER BY md5(f.rcept_no)) AS rn
        FROM filings f JOIN download_tasks d USING (rcept_no)
        WHERE f.report_type = :rt AND d.status = 'completed' AND d.file_type = 'xml'
          AND d.file_path IS NOT NULL
    ) x WHERE rn <= :n ORDER BY fiscal_year, rcept_no
"""


def _era(fy: int) -> str:
    if fy < 2005:
        return "1999-2004"
    if fy < 2010:
        return "2005-2009"
    if fy < 2015:
        return "2010-2014"
    if fy < 2020:
        return "2015-2019"
    return "2020+"


def _header(table) -> str:
    rows = table_direct_rows(table)
    if not rows:
        return ""
    return " | ".join(str(c).strip()[:10] for c in _get_cells(rows[0]))[:120]


def scan(path: str) -> dict:
    """Return {'groups': [(aclass, section, header)], 'orphans': [(section, header)]}."""
    root = _parse_xml_file(path)
    groups, orphans = [], []
    cur = None
    in_group: set[int] = set()
    for el in root.iter():
        tag = el.tag.upper() if isinstance(el.tag, str) else ""
        if tag.startswith("SECTION"):
            te = el.find("TITLE")
            if te is not None:
                cur = normalize_dart_section_title("".join(te.itertext()))
        elif tag == "TABLE-GROUP":
            ac = el.get("ACLASS") or "(none)"
            tables = [t for t in el.iter() if isinstance(t.tag, str) and t.tag.upper() == "TABLE"]
            for t in tables:
                in_group.add(id(t))
            if ac.startswith("{XBRL}"):
                continue
            # first table is often the 기준일/단위 caption → keep the largest table's header
            main = max(tables, key=lambda t: len(table_direct_rows(t)), default=None)
            groups.append((ac, cur, _header(main) if main is not None else ""))
        elif tag == "TABLE" and id(el) not in in_group and cur \
                and any(k in cur for k in TARGET_KEYWORDS):
            if len(table_direct_rows(el)) >= 2:
                orphans.append((cur, _header(el)))
    return {"groups": groups, "orphans": orphans}


def _work(args) -> tuple:
    rcept, fy, path, use_sd = args
    p = Path(path)
    if use_sd:
        p = BACKUP_ROOT / p.relative_to(_RAW_REPORT_SYMLINK)
    try:
        return rcept, fy, scan(str(p)), None
    except Exception as exc:  # noqa: BLE001
        return rcept, fy, None, f"{type(exc).__name__}: {exc}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-type", default="annual")
    ap.add_argument("--per-year", type=int, default=40)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--sd-mirror", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()

    with get_session() as s:
        rows = s.execute(text(_SAMPLE_SQL), {"rt": args.report_type, "n": args.per_year}).fetchall()
    jobs = [(r.rcept_no, r.fiscal_year, r.file_path, args.sd_mirror) for r in rows]

    files_by_era = Counter()
    ac_era = defaultdict(Counter)          # aclass -> era -> filings
    ac_sections = defaultdict(Counter)     # aclass -> section title
    ac_headers = defaultdict(Counter)      # aclass -> header
    orphan_era = defaultdict(Counter)      # section -> era -> filings
    orphan_headers = defaultdict(Counter)
    errors = []
    with Pool(args.workers) as pool:
        for rcept, fy, res, err in pool.imap_unordered(_work, jobs, chunksize=4):
            if err:
                errors.append((rcept, err))
                continue
            era = _era(fy)
            files_by_era[era] += 1
            for ac in {g[0] for g in res["groups"]}:
                ac_era[ac][era] += 1
            for ac, sec, hdr in res["groups"]:
                ac_sections[ac][sec or "(섹션 없음)"] += 1
                ac_headers[ac][hdr] += 1
            for sec in {o[0] for o in res["orphans"]}:
                orphan_era[sec][era] += 1
            for sec, hdr in res["orphans"]:
                orphan_headers[sec][hdr] += 1

    eras = ["1999-2004", "2005-2009", "2010-2014", "2015-2019", "2020+"]
    out = [f"# 비재무 섹션 표 카탈로그 — {args.report_type}, 연도당 {args.per_year}건 표본",
           "", "필링 수(연도 구간): " + " · ".join(f"{e} {files_by_era[e]}" for e in eras),
           f"오류 {len(errors)}건", "",
           "## 1. 서식 코드(TABLE-GROUP ACLASS)별 출현 필링 비율", "",
           "| ACLASS | " + " | ".join(eras) + " | 대표 섹션 | 대표 헤더 |",
           "|---|" + "---|" * len(eras) + "---|---|"]
    for ac in sorted(ac_era, key=lambda a: -sum(ac_era[a].values())):
        cells = [f"{ac_era[ac][e] / files_by_era[e]:.0%}" if files_by_era[e] else "-" for e in eras]
        sec = ac_sections[ac].most_common(1)[0][0]
        hdr = ac_headers[ac].most_common(1)[0][0].replace("|", "/")
        out.append(f"| `{ac}` | " + " | ".join(cells) + f" | {sec} | {hdr} |")
    out += ["", "## 2. 대상 섹션 안의 서식 코드 없는 표(표제 폴백 후보)", "",
            "| 섹션 표제 | " + " | ".join(eras) + " | 대표 헤더 |",
            "|---|" + "---|" * len(eras) + "---|"]
    for sec in sorted(orphan_era, key=lambda s: -sum(orphan_era[s].values())):
        cells = [f"{orphan_era[sec][e] / files_by_era[e]:.0%}" if files_by_era[e] else "-" for e in eras]
        hdr = orphan_headers[sec].most_common(1)[0][0].replace("|", "/")
        out.append(f"| {sec} | " + " | ".join(cells) + f" | {hdr} |")
    if errors:
        out += ["", "## 오류", ""] + [f"- {r}: {e}" for r, e in errors[:30]]
    text_out = "\n".join(out) + "\n"
    if args.out:
        Path(args.out).write_text(text_out, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
