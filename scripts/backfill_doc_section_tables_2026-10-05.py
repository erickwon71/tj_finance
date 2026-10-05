#!/usr/bin/env python
"""doc_section_tables 소급 적재 — API→문서 전환 Phase 0 (계층2, 원문 격자만, 해석 없음).

docs/plans/api_to_document_migration_plan_2026-10-05.md. 데일리 경로는
`collector/note_lines_sync.py` 가 같은 writer(`fin2/layer2/doc_sections.py`)를 부른다.
1차 범위 = 2015+ (사용자 결정 2026-10-05). 2014 이전은 표제 폴백 매핑과 함께 후속.

재개: 대상 = 아직 doc_section_tables 에 행이 없는 rcept. 표 0개 필링은 재실행 때 다시
스캔된다(드묾, 로그의 empty 로 확인).

    python scripts/backfill_doc_section_tables_2026-10-05.py --dry-run
    python scripts/backfill_doc_section_tables_2026-10-05.py --corp 00126955
    python scripts/backfill_doc_section_tables_2026-10-05.py --workers 3 --sd-mirror
    python scripts/backfill_doc_section_tables_2026-10-05.py --report-types half,quarter --workers 3 --sd-mirror
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.storage_guard import BACKUP_ROOT, SYMLINK as _RAW_REPORT_SYMLINK
from fin2.layer2.doc_sections import extract_from_file, store_doc_section_tables

_TARGETS_SQL = """
    SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period, d.file_path
    FROM filings f JOIN download_tasks d USING (rcept_no)
    JOIN corporations c ON c.corp_code = f.corp_code
    WHERE f.report_type = ANY(:rts) AND f.fiscal_year >= :fy_min
      AND d.status = 'completed' AND d.file_type = 'xml' AND d.file_path IS NOT NULL
      AND c.stock_code IS NOT NULL AND c.stock_code NOT LIKE '9%%'
      AND NOT EXISTS (SELECT 1 FROM doc_section_tables x WHERE x.rcept_no = f.rcept_no)
      {corp_clause}
    ORDER BY f.corp_code, f.fiscal_year, f.rcept_no
"""


def _shards(rows: list[dict], n: int) -> list[list[dict]]:
    by_corp: dict[str, list[dict]] = {}
    for r in rows:
        by_corp.setdefault(r["corp_code"], []).append(r)
    shards: list[list[dict]] = [[] for _ in range(n)]
    loads = [0] * n
    for g in sorted(by_corp.values(), key=len, reverse=True):
        i = loads.index(min(loads))
        shards[i].extend(g)
        loads[i] += len(g)
    return shards


def _worker(shard_id: int, targets: list[dict], use_sd: bool) -> dict:
    agg = Counter()
    t0 = time.time()
    with get_session() as s:
        for i, r in enumerate(targets, start=1):
            p = Path(r["file_path"])
            if use_sd:
                p = BACKUP_ROOT / p.relative_to(_RAW_REPORT_SYMLINK)
            if not p.exists():
                agg["missing_file"] += 1
                continue
            try:
                tables = extract_from_file(str(p))
                n = store_doc_section_tables(s, r["rcept_no"], r["corp_code"],
                                             r["fiscal_year"], r["fiscal_period"], tables)
                agg["tables"] += n
                agg["done" if n else "empty"] += 1
            except Exception as exc:  # noqa: BLE001 — one bad file must not stop the shard
                s.rollback()
                agg["error"] += 1
                logger.error(f"[w{shard_id}] {r['rcept_no']}: {type(exc).__name__}: {exc}")
                continue
            if i % 100 == 0:
                s.commit()
            if i % 1000 == 0 or i == len(targets):
                el = time.time() - t0
                logger.info(f"[w{shard_id}] {i:,}/{len(targets):,} {dict(agg)} — {el/60:.1f}분, "
                            f"잔여 ~{(len(targets) - i) / (i / el) / 60:.0f}분")
        s.commit()
    return dict(agg)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report-types", default="annual")
    ap.add_argument("--fy-min", type=int, default=2015)
    ap.add_argument("--corp")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--sd-mirror", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    corps = [c.strip() for c in args.corp.split(",")] if args.corp else None
    sql = _TARGETS_SQL.format(corp_clause="AND f.corp_code = ANY(:corps)" if corps else "")
    params = {"rts": args.report_types.split(","), "fy_min": args.fy_min}
    if corps:
        params["corps"] = corps
    with get_session() as s:
        rows = [dict(r) for r in s.execute(text(sql), params).mappings()]
    if args.limit:
        rows = rows[: args.limit]
    n_corps = len({r["corp_code"] for r in rows})
    logger.info(f"대상 {len(rows):,}필링 / {n_corps:,}개사 ({args.report_types}, fy>={args.fy_min})")
    if not rows or args.dry_run:
        return
    n = max(1, min(args.workers, n_corps))
    t0 = time.time()
    with Pool(n) as pool:
        res = pool.starmap(_worker, [(i, sh, args.sd_mirror)
                                     for i, sh in enumerate(_shards(rows, n), start=1)])
    agg = Counter()
    for r in res:
        agg.update(r)
    logger.success(f"완료 {dict(agg)} — {(time.time() - t0)/60:.1f}분")


if __name__ == "__main__":
    main()
