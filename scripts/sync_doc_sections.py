#!/usr/bin/env python
"""원문 비재무 섹션 10테이블 재구축 CLI (API→문서 전환, collector/doc_sections_sync.py).

데일리는 `scripts/collect_new.py::_sync_doc_sections` 가 신규 표준화 기업만 돌린다. 이 스크립트는
소급·재실행용이다. `--all` 은 doc_section_tables 에 있는 회사 ∪ 10개 테이블에 행이 있는 회사
전부 — 원문에 표가 없는 (회사, 연도)의 옛 API 행은 이 실행으로 사라진다(원칙: 원문에서만).

    python scripts/sync_doc_sections.py --corp 00126955
    python scripts/sync_doc_sections.py --all
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.doc_sections_sync import TABLES, sync_doc_sections


def _all_corps() -> list[str]:
    union = " UNION ".join(f"SELECT corp_code FROM {t}" for t in TABLES)
    with get_session() as s:
        return [r[0] for r in s.execute(text(
            f"SELECT DISTINCT corp_code FROM doc_section_tables UNION {union}"))]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--corp", help="comma-separated corp_code")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--fy-min", type=int, default=2015)
    args = ap.parse_args()
    corps = _all_corps() if args.all else [c.strip() for c in args.corp.split(",") if c.strip()]
    logger.info(f"대상 {len(corps):,}개사 (fy>={args.fy_min})")
    t0 = time.time()
    agg = sync_doc_sections(corps, fy_min=args.fy_min)
    logger.success(f"완료 {agg} — {(time.time() - t0) / 60:.1f}분")
    return 0


if __name__ == "__main__":
    sys.exit(main())
