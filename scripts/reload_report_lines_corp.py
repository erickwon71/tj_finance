"""Targeted report_lines re-load for specific corp-years (B1 stale-data recovery).

Some (corp, fiscal_year) had report_lines loaded by an OLDER extractor and are missing
the IS statement, even though the CURRENT extractor (post split-table fix, 2026-07-23)
extracts it. --redo-empty didn't catch them (they had non-zero BS rows). This re-extracts
and re-stores every completed-XML filing for the given corps (delete-then-insert per
rcept, idempotent), updating report_line_load_progress. Nothing destructive beyond the
per-rcept re-store the normal loader already does.

Usage: python scripts/reload_report_lines_corp.py --corp 00139214,00136101 [--year 2020]
       python scripts/reload_report_lines_corp.py --corp <csv> --year-max 2010  # R31(T22)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.models import ReportLineLoadProgress
from fin2.extract.report_lines import extract_report_lines, store_report_lines
from fin2.audit.line_anomaly import detect_anomalies, store_anomalies


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corp", required=True, help="쉼표구분 corp_code")
    ap.add_argument("--year", type=int, help="특정 fiscal_year 만(생략 시 전 연도)")
    ap.add_argument("--year-max", type=int,
                     help="fiscal_year <= 이 값만(표적 백필 — 영향권 밖 연도는 건드리지 않는다, R31)")
    args = ap.parse_args()
    corps = [c.strip() for c in args.corp.split(",") if c.strip()]

    with get_session() as s:
        yr_clause = " AND f.fiscal_year = :y" if args.year else ""
        yr_clause += " AND f.fiscal_year <= :ymax" if args.year_max else ""
        params = {"corps": tuple(corps)}
        if args.year:
            params["y"] = args.year
        if args.year_max:
            params["ymax"] = args.year_max
        targets = s.execute(text(f"""
            SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
            FROM download_tasks dt JOIN filings f USING(rcept_no)
            WHERE f.corp_code IN :corps AND dt.status='completed' AND dt.file_type='xml'
              AND dt.file_path IS NOT NULL{yr_clause}
            ORDER BY f.corp_code, f.fiscal_year, dt.rcept_no
        """), params).fetchall()

        print(f"대상 filing = {len(targets)}")
        n_done = n_is = 0
        prev_corp = None
        for r in targets:
            # ★대량 배치(수백 corp)가 백그라운드 실행시간 제한에 걸려 죽는 사고 재현
            #   (R31/T22, 2026-08-17) — 예전엔 커밋을 루프 끝에 딱 한 번만 해서, 중간에
            #   죽으면 이미 처리한 만큼도 전부 롤백돼 재시도가 처음부터 다시 시작해야 했다.
            #   corp 경계에서 커밋해 부분 진행을 살린다(멱등 재적재라 재시작해도 안전).
            if prev_corp is not None and r.corp_code != prev_corp:
                s.commit()
            prev_corp = r.corp_code
            if not Path(r.file_path).exists():
                logger.warning(f"file missing {r.rcept_no}")
                continue
            try:
                lines = extract_report_lines(
                    r.file_path, rcept_no=r.rcept_no, corp_code=r.corp_code,
                    report_fiscal_year=r.fiscal_year,
                    report_fiscal_period=r.fiscal_period, include_notes=False)
                nl = store_report_lines(s, r.rcept_no, lines)
                found = detect_anomalies(lines, rcept_no=r.rcept_no, corp_code=r.corp_code,
                                         report_fiscal_period=r.fiscal_period)
                na = store_anomalies(s, r.rcept_no, found)
                nis = sum(1 for ln in lines if ln.statement == "IS")
                n_is += nis
                s.merge(ReportLineLoadProgress(
                    rcept_no=r.rcept_no, corp_code=r.corp_code, fiscal_year=r.fiscal_year,
                    status="done", n_lines=nl, n_anomalies=na, message="reload",
                    processed_at=datetime.utcnow()))
                n_done += 1
                print(f"  {r.corp_code} {r.fiscal_year} {r.rcept_no}: {nl}행 (IS {nis})", flush=True)
            except Exception as e:  # noqa: BLE001
                logger.error(f"{r.rcept_no}: {type(e).__name__}: {e}")
        s.commit()
        print(f"\n완료 — filing {n_done} 재적재 · IS 총 {n_is}행")


if __name__ == "__main__":
    main()
