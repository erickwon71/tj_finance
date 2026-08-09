"""Phase 0 probe (biz_content_layer2_migration_2026-08-09) — measure the cost of re-parsing
every annual-report XML to extract order_backlog raw subsection grids (the part that will move
into the new layer2 writer, fin2/layer2/biz_raw_tables.py).

Times `_load_root` (XML parse, the dominant cost) + `find_order_subsections` (heading/grid
detection) on a random sample, then extrapolates to the full annual-report population. Does NOT
time `map_order_table` (cheap list processing, negligible next to XML parsing).

usage:
    python scripts/probe_order_backlog_reparse_cost.py [--sample N]
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.extract.order_backlog import _load_root, find_order_subsections

_SQL = """
    SELECT f.rcept_no, dt.file_path
    FROM filings f
    JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
    WHERE f.report_type = 'annual'
      AND dt.status = 'completed'
      AND dt.file_type = 'xml'
      AND dt.file_path IS NOT NULL
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    with get_session() as s:
        rows = s.execute(text(_SQL)).fetchall()
    total_population = len(rows)
    logger.info(f"[probe] annual filings w/ completed XML = {total_population:,}")

    rng = random.Random(args.seed)
    sample = rng.sample(rows, min(args.sample, total_population))
    logger.info(f"[probe] sampling {len(sample):,} filings")

    durations: list[float] = []
    missing = 0
    errors = 0
    n_subsections = 0
    for i, r in enumerate(sample, 1):
        fp = Path(r.file_path)
        if not fp.exists():
            missing += 1
            continue
        t0 = time.perf_counter()
        try:
            root = _load_root(fp)
            if root is not None:
                subs = find_order_subsections(root)
                n_subsections += len(subs)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            logger.warning(f"[probe] {r.rcept_no} 실패: {type(exc).__name__}: {exc}")
            continue
        durations.append(time.perf_counter() - t0)
        if i % 100 == 0:
            logger.info(f"  ..{i}/{len(sample)}")

    if not durations:
        logger.error("[probe] 표본에서 측정 가능한 필링이 없음")
        return

    mean = statistics.mean(durations)
    median = statistics.median(durations)
    p95 = sorted(durations)[int(len(durations) * 0.95)]
    total_est_sec = mean * total_population

    logger.success(
        f"[probe] 표본={len(durations)} 결측={missing} 오류={errors} "
        f"소제목표({n_subsections}건 발견, 표본 전체) "
        f"평균={mean*1000:.1f}ms 중앙값={median*1000:.1f}ms p95={p95*1000:.1f}ms"
    )
    logger.success(
        f"[probe] 전체 모집단({total_population:,}건) 추정 소요시간 = "
        f"{total_est_sec:.0f}초 ({total_est_sec/60:.1f}분)"
    )


if __name__ == "__main__":
    main()
