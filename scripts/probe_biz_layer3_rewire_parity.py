"""Phase 3 parity probe (biz_content_layer2_migration_2026-08-09) — verify the DB-only
`collector.biz_metrics.sync_biz_metrics_corp` / `collector.order_backlog.sync_order_backlog_corp`
reproduce the existing `biz_metrics`/`order_backlog` rows exactly.

Runs the new code inside a session that is **rolled back at the end, never committed** — this
never touches production data. `order_backlog` domain rows don't exist in `biz_section_tables`
yet (Phase 5 backfill), so this script also seeds them on the fly (via
`fin2.layer2.biz_raw_tables`) for the sampled corps, inside the same rollback-only session.

usage:
    python scripts/probe_biz_layer3_rewire_parity.py [--sample N]
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import SessionLocal
from fin2.layer2.biz_raw_tables import extract_biz_raw_tables, store_biz_raw_tables

_SAMPLE_SQL = """
    SELECT DISTINCT corp_code FROM biz_metrics
    WHERE corp_code IN (SELECT corp_code FROM order_backlog)
"""

_ROW_COLS = ("corp_code", "fiscal_year", "table_ord", "metric", "channel", "segment", "item",
             "period_label", "period_year", "value", "unit", "is_ratio")
_OB_COLS = ("corp_code", "fiscal_year", "category", "backlog_amt", "new_orders", "completed", "unit")


def _snapshot(session, table: str, cols: tuple[str, ...], corps: list[str]) -> set[tuple]:
    col_sql = ", ".join(cols)
    rows = session.execute(text(
        f"SELECT {col_sql} FROM {table} WHERE corp_code = ANY(:corps)"),
        {"corps": corps}).fetchall()
    return {tuple(r) for r in rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=30)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    session = SessionLocal()
    try:
        candidates = [r[0] for r in session.execute(text(_SAMPLE_SQL)).fetchall()]
        rng = random.Random(args.seed)
        corps = rng.sample(candidates, min(args.sample, len(candidates)))
        logger.info(f"[probe] 표본 기업 {len(corps)}개")

        # ── baseline (기존 코드가 만든, 현재 DB의 값) ──────────────────────────
        base_metrics = _snapshot(session, "biz_metrics", _ROW_COLS, corps)
        base_ob = _snapshot(session, "order_backlog", _OB_COLS, corps)
        logger.info(f"[probe] baseline biz_metrics={len(base_metrics)}행 order_backlog={len(base_ob)}행")

        # ── order_backlog 도메인 raw grid 선-백필(Phase5 시뮬레이션, 표본 한정) ──
        filings = session.execute(text("""
            SELECT f.rcept_no, f.corp_code, f.fiscal_year, dt.file_path
            FROM filings f
            JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
            WHERE f.corp_code = ANY(:corps) AND f.report_type = 'annual'
              AND dt.status = 'completed' AND dt.file_type = 'xml' AND dt.file_path IS NOT NULL
        """), {"corps": corps}).fetchall()
        seeded = 0
        for flt in filings:
            has_ob = session.execute(text(
                "SELECT 1 FROM biz_section_tables WHERE rcept_no=:r AND domain='order_backlog' LIMIT 1"),
                {"r": flt.rcept_no}).scalar()
            if has_ob:
                continue
            fp = Path(flt.file_path)
            if not fp.exists():
                continue
            rows = extract_biz_raw_tables(fp, flt.corp_code, flt.fiscal_year)
            ob_rows = [r for r in rows if r["domain"] == "order_backlog"]
            if ob_rows:
                # 기존 production/sales/catalog 행은 그대로 두고 order_backlog 행만 추가
                # (store_biz_raw_tables 는 rcept 전체를 delete-then-insert 하므로, 표본 검증
                # 목적상 이미 있는 도메인 행도 같이 다시 써서 최신 extract_biz_raw_tables 결과로 맞춘다).
                store_biz_raw_tables(session, flt.rcept_no, rows)
                seeded += 1
        logger.info(f"[probe] order_backlog 도메인 선-백필: {seeded}개 필링에 신규 grid 추가")

        # ── 신규 코드 실행(같은 세션, 아직 커밋 안 함) ──────────────────────────
        from collector.biz_metrics import sync_biz_metrics_corp
        from collector.order_backlog import sync_order_backlog_corp
        for corp in corps:
            sync_biz_metrics_corp(session, corp, latest_only=False)
            sync_order_backlog_corp(session, corp, latest_only=False)

        new_metrics = _snapshot(session, "biz_metrics", _ROW_COLS, corps)
        new_ob = _snapshot(session, "order_backlog", _OB_COLS, corps)
        logger.info(f"[probe] 재생성 biz_metrics={len(new_metrics)}행 order_backlog={len(new_ob)}행")

        only_base_m = base_metrics - new_metrics
        only_new_m = new_metrics - base_metrics
        only_base_ob = base_ob - new_ob
        only_new_ob = new_ob - base_ob

        logger.success(
            f"[probe] biz_metrics 대칭차 — baseline에만 {len(only_base_m)}건 / 신규에만 {len(only_new_m)}건")
        logger.success(
            f"[probe] order_backlog 대칭차 — baseline에만 {len(only_base_ob)}건 / 신규에만 {len(only_new_ob)}건")
        for row in list(only_base_m)[:5]:
            logger.warning(f"  [biz_metrics] baseline에만: {row}")
        for row in list(only_new_m)[:5]:
            logger.warning(f"  [biz_metrics] 신규에만: {row}")
        for row in list(only_base_ob)[:5]:
            logger.warning(f"  [order_backlog] baseline에만: {row}")
        for row in list(only_new_ob)[:5]:
            logger.warning(f"  [order_backlog] 신규에만: {row}")
    finally:
        session.rollback()
        session.close()
        logger.info("[probe] 세션 rollback 완료 — DB 변경사항 없음")


if __name__ == "__main__":
    main()
