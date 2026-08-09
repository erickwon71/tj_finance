"""Phase 2 sanity probe (biz_content_layer2_migration_2026-08-09) — verify
`fin2.layer2.biz_raw_tables.extract_biz_raw_tables` reproduces the existing
production/sales/catalog grids byte-for-byte, and sanity-checks the newly-added
order_backlog grids (which had no prior store to diff against).

usage:
    python scripts/probe_biz_raw_tables_parity.py [--sample N]
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.extract.biz_section import _narrative_unit
from fin2.layer2.biz_raw_tables import extract_biz_raw_tables

_SAMPLE_SQL = """
    SELECT DISTINCT bst.rcept_no, bst.corp_code, bst.fiscal_year, dt.file_path
    FROM biz_section_tables bst
    JOIN filings f ON f.rcept_no = bst.rcept_no
    JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
    WHERE dt.status = 'completed' AND dt.file_type = 'xml' AND dt.file_path IS NOT NULL
"""

_ORDER_BACKLOG_CORP_SQL = """
    SELECT DISTINCT bst.rcept_no, bst.corp_code, bst.fiscal_year, dt.file_path
    FROM biz_section_tables bst
    JOIN filings f ON f.rcept_no = bst.rcept_no
    JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
    JOIN order_backlog ob ON ob.corp_code = bst.corp_code AND ob.fiscal_year = bst.fiscal_year
    WHERE dt.status = 'completed' AND dt.file_type = 'xml' AND dt.file_path IS NOT NULL
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=50)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    with get_session() as s:
        general = s.execute(text(_SAMPLE_SQL)).fetchall()
        ob_filings = s.execute(text(_ORDER_BACKLOG_CORP_SQL)).fetchall()

    sample = rng.sample(general, min(args.sample, len(general)))
    ob_sample = rng.sample(ob_filings, min(10, len(ob_filings)))
    logger.info(f"[probe] parity 표본={len(sample)} / order_backlog 표본={len(ob_sample)}")

    # ── 1) production/sales/catalog grid parity vs existing DB rows ──────────
    mismatches = 0
    checked = 0
    with get_session() as s:
        for r in sample:
            new_rows = extract_biz_raw_tables(Path(r.file_path), r.corp_code, r.fiscal_year)
            new_by_ord = {row["table_ord"]: row for row in new_rows if row["domain"] != "order_backlog"}
            db_rows = s.execute(text(
                "SELECT table_ord, metric, narrative, grid FROM biz_section_tables "
                "WHERE rcept_no=:rc AND domain != 'order_backlog'"
            ), {"rc": r.rcept_no}).fetchall()
            for db_row in db_rows:
                checked += 1
                nr = new_by_ord.get(db_row.table_ord)
                if nr is None:
                    mismatches += 1
                    logger.warning(f"[probe] {r.rcept_no} table_ord={db_row.table_ord} 신규추출 누락")
                    continue
                if (nr["metric"] != db_row.metric or nr["narrative"] != db_row.narrative
                        or nr["grid"] != db_row.grid):
                    mismatches += 1
                    logger.warning(f"[probe] {r.rcept_no} table_ord={db_row.table_ord} 불일치")

    logger.success(f"[probe] production/sales/catalog parity — 대조 {checked}행, 불일치 {mismatches}건")

    # ── 2) order_backlog grid sanity (no prior store — round-trip narrative->unit only) ──
    n_ob_tables = 0
    unit_recovered = 0
    for r in ob_sample:
        rows = extract_biz_raw_tables(Path(r.file_path), r.corp_code, r.fiscal_year)
        for row in rows:
            if row["domain"] != "order_backlog":
                continue
            n_ob_tables += 1
            u = _narrative_unit(row["narrative"])
            if u:
                unit_recovered += 1
            logger.info(f"[probe] order_backlog {r.rcept_no} table_ord={row['table_ord']} "
                        f"narrative={row['narrative']!r} unit_recovered={u!r} "
                        f"grid_shape={len(row['grid'])}x{len(row['grid'][0]) if row['grid'] else 0}")

    logger.success(f"[probe] order_backlog 신규 추출 — {len(ob_sample)}개 필링, "
                    f"표 {n_ob_tables}건, 단위 복원 {unit_recovered}건")


if __name__ == "__main__":
    main()
