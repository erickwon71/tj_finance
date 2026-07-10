"""주식수 백필 — 보고서 본문 '주식의 총수' 파싱 (DART 결측분: pre-2016 + 2016+ DART-miss).

DART stockTotqySttus(~2016+) 가 못 채운 std_financials_v2.shares_out 를 사업보고서 본문에서 직접
파싱(fin2.extract.shares.extract_issued_common_shares)해 채운다. 로컬 파일 read 만(외부 API 없음).

대상 = std_v2 FY 행 shares 결측 ∩ 해당 corp·fy 의 is_final annual xml 보고서.

usage:
  python scripts/fin2_backfill_shares_report.py --corp 00126380       # 단일
  python scripts/fin2_backfill_shares_report.py --shard 0/4 --resume-file /tmp/shr_0.txt
  python scripts/fin2_backfill_shares_report.py --limit 200
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.extract.shares import extract_issued_common_shares


def _targets(corp: str | None):
    """(corp_code, fiscal_year, file_path) — shares 결측 FY × is_final annual xml."""
    where = "AND f.corp_code = :corp" if corp else ""
    sql = f"""
        SELECT DISTINCT ON (s.corp_code, s.fiscal_year)
               s.corp_code, s.fiscal_year, d.file_path
        FROM std_financials_v2 s
        JOIN filings f ON f.corp_code = s.corp_code AND f.fiscal_year = s.fiscal_year
                      AND f.report_type = 'annual' AND f.is_final = true
        JOIN download_tasks d ON d.rcept_no = f.rcept_no AND d.file_type = 'xml'
                             AND d.file_path IS NOT NULL
        WHERE s.version = 1 AND s.fiscal_period = 'FY'
          AND NOT COALESCE(s.is_discrete, false) AND NOT COALESCE(s.is_stub, false)
          AND (s.shares_out IS NULL OR s.shares_out = 0)
          {where}
        ORDER BY s.corp_code, s.fiscal_year, f.filed_at DESC
    """
    params = {"corp": corp} if corp else {}
    with get_session() as s:
        return [(r[0], r[1], r[2]) for r in s.execute(text(sql), params)]


def _apply(corp_code: str, fiscal_year: int, shares: int) -> None:
    with get_session() as s:
        s.execute(text("""
            UPDATE std_financials_v2 SET shares_out = :n
            WHERE corp_code = :c AND fiscal_year = :y AND fiscal_period = 'FY'
              AND version = 1 AND (shares_out IS NULL OR shares_out = 0)
        """), {"n": shares, "c": corp_code, "y": fiscal_year})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", help="병렬 샤딩 I/N")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--resume-file")
    ap.add_argument("--corp")
    args = ap.parse_args()

    targets = _targets(args.corp)
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        targets = targets[i::n]
    done = set()
    if args.resume_file and Path(args.resume_file).exists():
        done = {ln.strip() for ln in Path(args.resume_file).read_text().splitlines() if ln.strip()}
    targets = [t for t in targets if f"{t[0]}:{t[1]}" not in done]
    if args.limit:
        targets = targets[:args.limit]

    total = len(targets)
    logger.info(f"[shares-report] 결측 (corp,fy) {total}건 파싱")
    agg = {"found": 0, "miss": 0, "err": 0}

    for idx, (corp, fy, path) in enumerate(targets, 1):
        key = f"{corp}:{fy}"
        try:
            shares = extract_issued_common_shares(path) if path and Path(path).exists() else None
            if shares and shares > 0:
                _apply(corp, fy, shares)
                agg["found"] += 1
            else:
                agg["miss"] += 1
            if args.resume_file:
                with open(args.resume_file, "a") as fh:
                    fh.write(key + "\n")
        except Exception as e:
            agg["err"] += 1
            logger.error(f"[shares-report] {key} 실패: {type(e).__name__}: {e}")
        if idx % 500 == 0 or idx == total:
            logger.info(f"  ..{idx}/{total} found {agg['found']} miss {agg['miss']} 오류 {agg['err']}")

    logger.success(
        f"[shares-report] 완료 — (corp,fy) {total}, found {agg['found']}, "
        f"miss {agg['miss']}, 오류 {agg['err']}")


if __name__ == "__main__":
    main()
