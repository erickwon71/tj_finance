"""Targeted layer-2 re-load for specific corps / corp-years / filings.

Each filing is re-extracted and stored through the R0-2 path the daily collector and the
verification queue use (`fin2.verification.ops._reload_rcept`): printed rows (body + notes),
table meta and the layer-3 corrections (`layer3_cell_corrections`) in one transaction,
delete-then-insert per rcept, idempotent.

Why (2026-11-17): this script used to call `extract_report_lines` + `store_report_lines`
only. `layer3_cell_corrections` references `report_lines` ON DELETE CASCADE, so a reload
silently dropped every layer-3 correction of the filing (R232 signs, R154 fills, ...) and
did not write them again; the next std rebuild then used uncorrected values. Notes were not
reloaded either (include_notes=False). The legacy bookkeeping tables
`report_line_load_progress` / `line_anomalies` are no longer written (the daily path never
wrote them).

Usage: python scripts/reload_report_lines_corp.py --corp 00139214,00136101 [--year 2020]
       python scripts/reload_report_lines_corp.py --corp <csv> --year-max 2010  # R31(T22)
       python scripts/reload_report_lines_corp.py --rcept-file hits.txt         # R144
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.verification.ops import _reload_rcept

# Same source selection as _reload_rcept: a completed main XML / XBRL zip, or a web-view print.
_SOURCE_SQL = """
    ((dt.status = 'completed' AND dt.file_type IN ('xml', 'xbrl_zip') AND dt.file_path IS NOT NULL)
     OR dt.viewer_xml_path IS NOT NULL)
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corp", help="쉼표구분 corp_code")
    ap.add_argument("--rcept-file", help="rcept_no 목록 파일(줄바꿈 구분) — 필링 단위 표적 재적재(R144)")
    ap.add_argument("--year", type=int, help="특정 fiscal_year 만(생략 시 전 연도)")
    ap.add_argument("--year-max", type=int,
                     help="fiscal_year <= 이 값만(표적 백필 — 영향권 밖 연도는 건드리지 않는다, R31)")
    ap.add_argument("--year-min", type=int,
                     help="fiscal_year >= 이 값만. 계층2 캠페인 스코프가 2015+ 라 "
                          "그 경계를 지킬 때 쓴다(사용자 지시 2026-09-19)")
    ap.add_argument("--overwrite-reviewed", action="store_true",
                     help="호환용(무시). R139 보호가드는 2026-09-24 폐지됐다.")
    ap.add_argument("--reason", default="reload_report_lines_corp",
                     help="verification.load_reason 에 남길 사유")
    args = ap.parse_args()
    if not args.corp and not args.rcept_file:
        ap.error("--corp 또는 --rcept-file 중 하나는 필요하다")

    with get_session() as s:
        if args.rcept_file:
            rcepts = [t.strip() for t in Path(args.rcept_file).read_text(
                encoding="utf-8").split() if t.strip()]
            print(f"입력 rcept = {len(rcepts)}")
            targets = s.execute(text(f"""
                SELECT DISTINCT dt.rcept_no, f.corp_code, f.fiscal_year
                FROM download_tasks dt JOIN filings f USING(rcept_no)
                WHERE dt.rcept_no = ANY(:rcepts) AND {_SOURCE_SQL}
                ORDER BY f.corp_code, f.fiscal_year, dt.rcept_no
            """), {"rcepts": rcepts}).fetchall()
        else:
            corps = [c.strip() for c in args.corp.split(",") if c.strip()]
            yr_clause = " AND f.fiscal_year = :y" if args.year else ""
            yr_clause += " AND f.fiscal_year <= :ymax" if args.year_max else ""
            yr_clause += " AND f.fiscal_year >= :ymin" if args.year_min else ""
            params = {"corps": tuple(corps)}
            if args.year:
                params["y"] = args.year
            if args.year_max:
                params["ymax"] = args.year_max
            if args.year_min:
                params["ymin"] = args.year_min
            targets = s.execute(text(f"""
                SELECT DISTINCT dt.rcept_no, f.corp_code, f.fiscal_year
                FROM download_tasks dt JOIN filings f USING(rcept_no)
                WHERE f.corp_code IN :corps AND {_SOURCE_SQL}{yr_clause}
                ORDER BY f.corp_code, f.fiscal_year, dt.rcept_no
            """), params).fetchall()

    print(f"대상 filing = {len(targets)}")
    n_done = n_failed = 0
    for r in targets:
        try:
            status, msg = _reload_rcept(r.rcept_no, args.reason)
        except Exception as e:  # noqa: BLE001
            status, msg = "failed", f"{type(e).__name__}: {e}"
        if status == "done":
            n_done += 1
            print(f"  {r.corp_code} {r.fiscal_year} {r.rcept_no}: done", flush=True)
        else:
            n_failed += 1
            logger.error(f"{r.rcept_no}: {status} {msg}")
    print(f"\n완료 — filing {n_done} 재적재 · 실패 {n_failed}")


if __name__ == "__main__":
    main()
