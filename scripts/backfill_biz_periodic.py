"""소급 백필 — 분기·반기보고서 '사업의 내용' 부문별 사업 실적 (R288 계층2 + R289 계층3).

    python scripts/backfill_biz_periodic.py --shard 0/6 --year-min 2015

회사 단위로 샤딩한다(같은 회사·기간의 delete-then-insert 를 두 프로세스가 섞지 않게). 멱등: 이미 적재된
필링은 계층2 를 다시 쓰지 않고(ensure_biz_raw_tables) 계층3 만 기간 단위로 다시 만든다.
runbook_new_parser_pipeline_integration.md ② 소급 백필 — 자동이 아니다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger  # noqa: E402
from sqlalchemy import text  # noqa: E402

from collector.biz_metrics_periodic import sync_biz_periodic  # noqa: E402
from collector.db import engine  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", default="0/1", help="i/n — int(corp_code) %% n == i")
    ap.add_argument("--year-min", type=int, default=2015)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    i, n = (int(x) for x in a.shard.split("/"))
    with engine.connect() as c:
        corps = [r[0] for r in c.execute(text("""
            SELECT DISTINCT f.corp_code FROM filings f
            JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
            WHERE f.report_type IN ('quarter', 'half') AND f.fiscal_year >= :y
              AND dt.status = 'completed' AND dt.file_type = 'xml' AND dt.file_path IS NOT NULL
            ORDER BY 1"""), {"y": a.year_min}).fetchall()]
    corps = [c for c in corps if int(c) % n == i]
    if a.limit:
        corps = corps[:a.limit]
    logger.info(f"[backfill-biz-periodic] shard {i}/{n}: {len(corps)} corps, year >= {a.year_min}")
    print(sync_biz_periodic(corps, year_min=a.year_min))


if __name__ == "__main__":
    main()
