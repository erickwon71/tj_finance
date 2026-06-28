"""2024+ 연결 CF D&A 갭 복원 — 하이브리드(주석+본문) 적재.

배경/전략: fin2/extract/cf_da.py 참조. Track A 전환(2024+)으로 연결 CF 감가상각이
누락(연결 ebitda 2023:25%→2024:0.8% 절벽). 주석(note_extractor) 우선·본문(Track B
text) 폴백으로 복원하고, 단위가드(da/연결매출 ∈ [0.3%,60%])로 가비지를 차단한다.

대상: std_v2 consolidated, depreciation IS NULL, 연결 CF source 보유, fiscal_year>=year_min.
중복합산 방지: depreciation IS NULL(=본문 D&A 없는 보고서)만 손댐.
단계: 1) note.* fact_v2 upsert  2) 영향기업 standardize2 재실행(reconcile 불변).
중단·재개 안전(upsert idempotent). 실행:
  python scripts/fin2_extract_cf_da_consolidated.py [--year-min 2024] [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.extract.cf_da import recover_cf_da
from fin2.extract.xbrl import store_facts
from fin2.standardize.build import standardize_corp

_TARGET_SQL = """
    SELECT s.corp_code, s.fiscal_year, s.fiscal_period,
           ss.source_rcept_no AS cf_rcept, dt.file_path
    FROM std_financials_v2 s
    JOIN statement_source ss
      ON ss.corp_code=s.corp_code AND ss.fiscal_year=s.fiscal_year
     AND ss.fiscal_period=s.fiscal_period AND ss.basis='consolidated' AND ss.statement='CF'
    JOIN download_tasks dt ON dt.rcept_no = ss.source_rcept_no
    WHERE s.statement_type='consolidated' AND s.version=1 AND s.depreciation IS NULL
      AND s.fiscal_year >= :ymin AND dt.file_path IS NOT NULL
    ORDER BY s.corp_code, s.fiscal_year, s.fiscal_period
"""


def _revenue_by_basis(session, rcept: str) -> dict[str, int]:
    rows = session.execute(text("""
        SELECT basis, MAX(amount_won) FROM fact_v2
        WHERE rcept_no=:r AND canonical_account='is.revenue'
          AND col_index=0 AND NOT is_dimensional AND basis IN ('consolidated','separate')
        GROUP BY basis
    """), {"r": rcept}).fetchall()
    return {b: v for b, v in rows if v}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year-min", type=int, default=2024)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--shard", help="병렬 샤딩 I/N (corp 단위 분할 — 샤드별 corp 가 겹치지 않아 동시 실행 안전)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with get_session() as session:
        targets = session.execute(text(_TARGET_SQL), {"ymin": args.year_min}).fetchall()
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        shard_corps = set(sorted({t.corp_code for t in targets})[i::n])
        targets = [t for t in targets if t.corp_code in shard_corps]
    if args.limit:
        targets = targets[: args.limit]
    logger.info(f"[cf-da] consolidated D&A-NULL 대상 {len(targets):,}건 (fy>={args.year_min}"
                + (f", shard {args.shard}" if args.shard else "") + ")")

    affected: dict[str, None] = {}
    stored = src_note = src_face = skip_nofile = skip_norev = skip_none = 0
    samples = []

    with get_session() as session:
        for i, t in enumerate(targets, 1):
            if not t.file_path or not Path(t.file_path).exists():
                skip_nofile += 1
                continue
            rev = _revenue_by_basis(session, t.cf_rcept)
            if not rev.get("consolidated"):
                skip_norev += 1
                continue

            facts, source = recover_cf_da(
                t.file_path, rcept_no=t.cf_rcept, corp_code=t.corp_code,
                report_fiscal_year=t.fiscal_year, report_fiscal_period=t.fiscal_period,
                basis="consolidated", revenue_by_basis=rev,
            )
            if not facts:
                skip_none += 1
                continue

            if source == "note":
                src_note += 1
            else:
                src_face += 1
            affected[t.corp_code] = None
            da_total = next((f.amount_won for f in facts
                             if f.canonical_account == "note.da_total"), None)
            if len(samples) < 14:
                ratio = abs(da_total) / rev["consolidated"] if da_total else 0
                samples.append((t.corp_code, t.fiscal_year, t.fiscal_period,
                                source, da_total, f"{ratio*100:.1f}%"))
            if not args.dry_run:
                stored += store_facts(session, facts)
            if i % 500 == 0:
                if not args.dry_run:
                    session.commit()
                logger.info(f"[cf-da] {i:,}/{len(targets):,} note={src_note} face={src_face} "
                            f"(없음 {skip_none} 무매출 {skip_norev})")
        if not args.dry_run:
            session.commit()

    logger.info(f"[cf-da] 검사 {len(targets):,} → note {src_note} / face {src_face} / "
                f"미복원 {skip_none} / 무매출 {skip_norev} / 파일없음 {skip_nofile}")
    logger.info("샘플 (corp,fy,fp,source,da_total,da/rev):")
    for s in samples:
        logger.info(f"   {s}")

    if args.dry_run:
        logger.info(f"[cf-da] --dry-run — 쓰기 없이 종료 (복원예정 {src_note+src_face:,}, "
                    f"영향기업 {len(affected):,})")
        return

    logger.success(f"[cf-da] E 완료 — note fact {stored:,} upsert, 영향기업 {len(affected):,}")

    # R 불변(note 는 source 선택 영향 없음) → S 만 재실행
    corps = list(affected)
    n_std = n_fail = 0
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as session:
                n_std += standardize_corp(session, corp)
                session.commit()
        except Exception as e:
            n_fail += 1
            logger.warning(f"[cf-da] S 실패 corp={corp}: {e}")
        if i % 200 == 0:
            logger.info(f"[cf-da] S {i:,}/{len(corps):,} (std_v2 {n_std:,})")
    logger.success(f"[cf-da] 완료 — 영향기업 {len(corps):,}, std_v2 {n_std:,} 재계산, 실패 {n_fail}")


if __name__ == "__main__":
    main()
