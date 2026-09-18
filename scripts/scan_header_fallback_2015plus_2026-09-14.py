"""2015+ 필링 전수 스캔 — BS/IS/CF 표 중 `parse_header_columns()`가 None(구버전
cum_map/multicol/else 폴백)으로 떨어지는 비율과 사유를 집계한다.

배경: 사용자 요청("2015+ 이면 정상 file parser를 사용했어야 하는데, 폴백으로
파싱한 것들이 더 있나도 찾아봐. 이유도 정리해주고") — CF_separate 저조 이상치
스크리닝 중 21/99건이 폴백 경로였고 그중 3건은 R122(괄호 뒤 "기" 탈락 오타)로
해소됐다. 전체 스코프에서 폴백 비중과 잔여 사유를 파악하기 위한 전수조사.

멀티프로세스(--workers)로 병렬화 — 단일 프로세스로는 94,589건에 ~5시간 추정.

사용:
    python scripts/scan_header_fallback_2015plus_2026-09-14.py [--limit N] [--out PATH] [--workers N]
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

RAW_ROOT = Path("/Volumes/dart_data/raw_report")
_DIR_CACHE: dict[str, str] = {}


def _find_corp_dir(market: str, corp_code: str) -> str | None:
    key = f"{market}/{corp_code}"
    if key in _DIR_CACHE:
        return _DIR_CACHE[key]
    base = RAW_ROOT / market
    if not base.exists():
        return None
    for d in os.listdir(base):
        if d.startswith(corp_code + "_"):
            _DIR_CACHE[key] = d
            return d
    return None


def _find_xml(corp_code: str, market_guess: str | None, report_type: str, fiscal_year: int,
              rcept_no: str) -> Path | None:
    # raw_report 폴더는 접수(period-end) 연도 기준 — filings.fiscal_year 와 1년 어긋나는
    # 필링(접수일이 전년도인데 fiscal_year 는 다음해로 저장된 케이스, 푸른저축은행류
    # 실측 확인)이 있어 인접 연도도 시도한다(짐작 아님 — 파일 존재 여부로 확정).
    markets = [market_guess] if market_guess else []
    markets += [m for m in ("KOSPI", "KOSDAQ") if m not in markets]
    for mkt in markets:
        d = _find_corp_dir(mkt, corp_code)
        if not d:
            continue
        for fy in (fiscal_year, fiscal_year - 1, fiscal_year + 1):
            p = RAW_ROOT / mkt / d / report_type / str(fy) / f"{rcept_no}.xml"
            if p.exists():
                return p
    return None


def _classify_reason(tbl) -> str:
    thead = tbl.find("THEAD")
    if thead is None:
        return "no_thead_and_headerless_failed"
    return "thead_present_but_pattern_unrecognized"


def _process_one(args):
    rcept_no, corp_code, corp_cls, report_type, fiscal_year = args
    # 워커 프로세스 안에서 import(pickle 문제 회피, fork 후 지연 로딩).
    from parser.xml.dart_xml_parser import _parse_xml_file
    from fin2.extract.text import _detect_body_statement_tables, _detect_fin_type
    from parser.xml.table_extractor import parse_header_columns

    market = "KOSPI" if corp_cls == "Y" else "KOSDAQ" if corp_cls == "K" else None
    path = _find_xml(corp_code, market, report_type, fiscal_year, rcept_no)
    if path is None:
        return ("missing", None)
    try:
        root = _parse_xml_file(path)
        if root is None:
            return ("error", None)
        fin_type = _detect_fin_type(root, file_path=path)
        groups = _detect_body_statement_tables(root, fin_type, include_sce=False)
    except Exception:
        return ("error", None)

    results = []
    n_tables = 0
    for sec in ("BS_S", "BS_C", "IS_S", "IS_C", "CF_S", "CF_C"):
        tbls = groups.get(sec)
        if not tbls:
            continue
        tbl, unit, kind = tbls[0]
        n_tables += 1
        try:
            # ★R138(2026-09-18) — report_lines.py(운영 경로)는 report_fiscal_year>=2015
            #   면 항상 allow_duplicate_subtype=True 를 넘긴다(R125). 이 스캔이 그 플래그
            #   없이(기본값 False) 테스트하면 R125가 이미 해석하는 표까지 "미인식"으로
            #   오탐한다 — 실측으로 559건 중 548건(98%)이 이 오탐이었음을 확인.
            cols = parse_header_columns(tbl, allow_duplicate_subtype=(fiscal_year >= 2015))
        except Exception:
            cols = None
        if cols is None:
            reason = _classify_reason(tbl)
            results.append((rcept_no, corp_code, report_type, fiscal_year, sec, reason))
    return ("ok", (n_tables, results))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default="manual_review/header_fallback_scan_2026-09-14.csv")
    ap.add_argument("--fiscal-year-min", type=int, default=2015)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    from collector.db import get_session
    from sqlalchemy import text as sa_text
    with get_session() as session:
        rows = session.execute(sa_text("""
            SELECT rcept_no, corp_code, corp_cls, report_type, fiscal_year
            FROM filings
            WHERE fiscal_year >= :fy
            ORDER BY rcept_no
        """), {"fy": args.fiscal_year_min}).fetchall()

    if args.limit:
        rows = rows[:args.limit]
    rows = [tuple(r) for r in rows]

    total_filings = len(rows)
    total_tables = 0
    fallback_tables = 0
    reason_counts: dict[str, int] = {}
    fallback_rows = []
    missing_file = 0
    errors = 0

    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_process_one, r): r for r in rows}
        for fut in as_completed(futures):
            done += 1
            if done % 2000 == 0:
                elapsed = time.time() - t0
                logger.info(f"진행 {done}/{total_filings} ({elapsed:.0f}s, "
                            f"폴백 {fallback_tables}/{total_tables})")
            status, payload = fut.result()
            if status == "missing":
                missing_file += 1
                continue
            if status == "error":
                errors += 1
                continue
            n_tables, results = payload
            total_tables += n_tables
            fallback_tables += len(results)
            for row in results:
                reason_counts[row[-1]] = reason_counts.get(row[-1], 0) + 1
                fallback_rows.append(row)

    logger.info(f"완료: 필링 {total_filings}건(파일없음 {missing_file}, 오류 {errors}), "
                f"표 {total_tables}건 중 폴백 {fallback_tables}건 "
                f"({100*fallback_tables/max(total_tables,1):.2f}%)")
    for reason, cnt in sorted(reason_counts.items(), key=lambda x: -x[1]):
        logger.info(f"  사유별: {reason} = {cnt}건")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["rcept_no", "corp_code", "report_type", "fiscal_year", "section", "reason"])
        w.writerows(fallback_rows)
    logger.info(f"폴백 상세 → {out_path}")


if __name__ == "__main__":
    main()
