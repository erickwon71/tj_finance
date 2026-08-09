"""Phase 6-1 parity probe (docs/plans/biz_content_layer2_migration_todo_2026-08-09.md).

"재배선 전/후" diff — but by the time Phase 6 runs, Phase 5 has already overwritten the
production `biz_metrics`/`order_backlog` tables with the NEW (DB-only) code's output, so
there is no "before" snapshot left in the DB to diff against (unlike the smaller Phase 3
probe `probe_biz_layer3_rewire_parity.py`, which ran while the DB still held OLD-code
output).

Instead this script recomputes the OLD path fresh: it calls the pre-rewiring, file-reading
functions (`fin2.extract.biz_section.parse_biz_metrics`,
`fin2.extract.order_backlog.parse_order_backlog`) directly against the raw report files —
completely bypassing `biz_section_tables`/layer2 — then merges them with the exact same
period-grouping + merge logic the sync functions use (`period_groups` + `merge_filings` for
biz_metrics; the inline `category`-keyed dict for order_backlog, including
`_drop_out_of_range`). That reproduces what the OLD code would have produced today.

It then diffs that against the CURRENT `biz_metrics`/`order_backlog` DB rows (NEW code,
already committed by Phase 5) for the same sampled companies. Read-only — no DB writes.

usage:
    python scripts/probe_phase6_before_after.py [--sample N] [--seed N]
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.biz_merge import merge_filings
from collector.db import SessionLocal
from collector.filing_select import period_groups
from collector.order_backlog import _drop_out_of_range
from fin2.extract.biz_section import parse_biz_metrics
from fin2.extract.order_backlog import parse_order_backlog

_SAMPLE_SQL = """
    SELECT DISTINCT corp_code FROM biz_metrics
    WHERE corp_code IN (SELECT corp_code FROM order_backlog)
"""

_ROW_COLS = ("corp_code", "fiscal_year", "table_ord", "metric", "channel", "segment", "item",
             "period_label", "period_year", "value", "unit", "is_ratio")
_OB_COLS = ("corp_code", "fiscal_year", "category", "backlog_amt", "new_orders", "completed", "unit")


def _db_snapshot(session, table: str, cols: tuple[str, ...], corps: list[str]) -> set[tuple]:
    col_sql = ", ".join(cols)
    rows = session.execute(text(
        f"SELECT {col_sql} FROM {table} WHERE corp_code = ANY(:corps)"),
        {"corps": corps}).fetchall()
    return {tuple(r) for r in rows}


def _old_biz_metrics_for_corp(session, corp_code: str) -> set[tuple]:
    """Recompute biz_metrics rows the OLD (file-reading) path would produce, for one corp,
    across its whole annual-report history — mirrors sync_biz_metrics_corp's grouping/merge."""
    out: set[tuple] = set()
    for group in period_groups(session, corp_code, "annual", latest_only=False):
        fy = group[0].fiscal_year
        parsed: list[tuple[str, list[dict], list[dict]]] = []
        for f in group:
            fp = Path(f.file_path)
            if not fp.exists():
                continue
            try:
                sec_rows, met_rows = parse_biz_metrics(fp, corp_code, f.fiscal_year)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[old-biz] {corp_code} {f.rcept_no} 파싱 실패: "
                               f"{type(exc).__name__}: {exc}")
                continue
            parsed.append((f.rcept_no, sec_rows, met_rows))
        if not parsed:
            continue
        _, met_merged, _ = merge_filings(parsed)
        for m in met_merged:
            out.add((m["corp_code"], m["fiscal_year"], m["table_ord"], m["metric"],
                      m.get("channel"), m["segment"], m["item"], m["period_label"],
                      m["period_year"], m["value"], m["unit"], m["is_ratio"]))
        _ = fy
    return out


def _old_order_backlog_for_corp(session, corp_code: str) -> set[tuple]:
    """Recompute order_backlog rows the OLD (file-reading) path would produce, for one corp —
    mirrors sync_order_backlog_corp's grouping/merge (category-keyed, _drop_out_of_range)."""
    out: set[tuple] = set()
    for group in period_groups(session, corp_code, "annual", latest_only=False):
        fy = group[0].fiscal_year
        merged: dict[str, dict] = {}
        parsed_any = False
        for f in group:
            fp = Path(f.file_path)
            if not fp.exists():
                continue
            try:
                rows = parse_order_backlog(fp, corp_code, f.fiscal_year)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[old-ob] {corp_code} {f.rcept_no} 파싱 실패: "
                               f"{type(exc).__name__}: {exc}")
                continue
            parsed_any = True
            for r in rows:
                row = {**r, "rcept_no": f.rcept_no}
                _drop_out_of_range(row)
                merged[(row.get("category") or "")] = row
        if not parsed_any:
            continue
        for row in merged.values():
            out.add((row["corp_code"], fy, row.get("category"), row.get("backlog_amt"),
                      row.get("new_orders"), row.get("completed"), row.get("unit")))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=150)
    ap.add_argument("--seed", type=int, default=6)
    args = ap.parse_args()

    session = SessionLocal()
    try:
        candidates = [r[0] for r in session.execute(text(_SAMPLE_SQL)).fetchall()]
        rng = random.Random(args.seed)
        corps = rng.sample(candidates, min(args.sample, len(candidates)))
        logger.info(f"[probe6-1] 표본 기업 {len(corps)}개 (모집단 {len(candidates)}개)")

        new_metrics = _db_snapshot(session, "biz_metrics", _ROW_COLS, corps)
        new_ob = _db_snapshot(session, "order_backlog", _OB_COLS, corps)
        logger.info(f"[probe6-1] 현재(신규코드) biz_metrics={len(new_metrics)}행 "
                    f"order_backlog={len(new_ob)}행")

        old_metrics: set[tuple] = set()
        old_ob: set[tuple] = set()
        for i, corp in enumerate(corps, 1):
            old_metrics |= _old_biz_metrics_for_corp(session, corp)
            old_ob |= _old_order_backlog_for_corp(session, corp)
            if i % 25 == 0 or i == len(corps):
                logger.info(f"  ..{i}/{len(corps)}")
        logger.info(f"[probe6-1] 재계산(구코드) biz_metrics={len(old_metrics)}행 "
                    f"order_backlog={len(old_ob)}행")

        only_old_m = old_metrics - new_metrics
        only_new_m = new_metrics - old_metrics
        only_old_ob = old_ob - new_ob
        only_new_ob = new_ob - old_ob

        logger.success(
            f"[probe6-1] biz_metrics 대칭차 — 구코드에만 {len(only_old_m)}건 / "
            f"신규코드에만 {len(only_new_m)}건")
        logger.success(
            f"[probe6-1] order_backlog 대칭차 — 구코드에만 {len(only_old_ob)}건 / "
            f"신규코드에만 {len(only_new_ob)}건")
        for row in list(only_old_m)[:10]:
            logger.warning(f"  [biz_metrics] 구코드에만: {row}")
        for row in list(only_new_m)[:10]:
            logger.warning(f"  [biz_metrics] 신규코드에만: {row}")
        for row in list(only_old_ob)[:10]:
            logger.warning(f"  [order_backlog] 구코드에만: {row}")
        for row in list(only_new_ob)[:10]:
            logger.warning(f"  [order_backlog] 신규코드에만: {row}")
    finally:
        session.close()
        logger.info("[probe6-1] 읽기전용 — DB 변경사항 없음")


if __name__ == "__main__":
    main()
