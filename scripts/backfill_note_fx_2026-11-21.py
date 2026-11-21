"""R370 backfill - read the foreign-currency amounts (USD/EUR/JPY/CNY) of every note into
`note_fx_amounts` for filings already loaded.

The daily pipeline writes them for new filings through `store_note_lines`. Old filings need this
pass: it runs the extractor (`include_notes=True`) and writes ONLY the child table
(`store_note_fx_amounts`, rcept-level delete-then-insert). note_lines, report_lines and the
verification triggers are not touched.

Idempotent: a filing is skipped once `note_fx_backfill_progress` says 'done' (most filings have no
foreign amount at all, so the table is the only proof it was read). Re-run with `--redo` after a
change of fx_amounts.py to read everything again.

    .venv/bin/python scripts/backfill_note_fx_2026-11-21.py --sd-mirror --workers 8
    .venv/bin/python scripts/backfill_note_fx_2026-11-21.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.storage_guard import BACKUP_ROOT, SYMLINK as _RAW_REPORT_SYMLINK
from fin2.extract.report_lines import extract_report_lines, store_note_fx_amounts

_TARGETS_SQL = """
    WITH universe AS (
        SELECT c.corp_code FROM corporations c
        WHERE c.is_active AND c.stock_code IS NOT NULL AND c.stock_code NOT LIKE '9%%'
          AND c.coverage_class = 'periodic'
    )
    SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
    FROM download_tasks dt
    JOIN filings f USING (rcept_no)
    JOIN universe u ON u.corp_code = f.corp_code
    LEFT JOIN note_fx_backfill_progress p ON p.rcept_no = f.rcept_no AND p.status = 'done'
    WHERE f.report_type IN ('annual', 'half', 'quarter')
      AND f.fiscal_year >= :fy_min AND f.fiscal_year <= :fy_max
      AND dt.status = 'completed' AND dt.file_type = 'xml' AND dt.file_path IS NOT NULL
      AND f.report_nm NOT LIKE '%%제출기한연장%%'
      {redo_clause}
    ORDER BY f.corp_code, f.fiscal_year, dt.rcept_no
"""


def _load_targets(fy_min: int, fy_max: int, redo: bool) -> list[dict]:
    sql = text(_TARGETS_SQL.format(redo_clause="" if redo else "AND p.rcept_no IS NULL"))
    with get_session() as s:
        return [dict(r) for r in s.execute(sql, {"fy_min": fy_min, "fy_max": fy_max}).mappings()]


def _partition_by_corp(rows: list[dict], n: int) -> list[list[dict]]:
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


def _progress(s, r: dict, status: str, n_fx: int | None, msg: str) -> None:
    s.execute(text("""
        INSERT INTO note_fx_backfill_progress (rcept_no, corp_code, fiscal_year, status, n_fx, message, processed_at)
        VALUES (:rc, :cc, :fy, :st, :n, :m, :t)
        ON CONFLICT (rcept_no) DO UPDATE SET status = EXCLUDED.status, n_fx = EXCLUDED.n_fx,
            message = EXCLUDED.message, processed_at = EXCLUDED.processed_at"""),
        {"rc": r["rcept_no"], "cc": r["corp_code"], "fy": r["fiscal_year"], "st": status,
         "n": n_fx, "m": msg[:200], "t": datetime.utcnow()})


def _worker(shard_id: int, targets: list[dict], use_sd: bool) -> dict:
    done = err = with_fx = n_fx_total = 0
    t0 = time.time()
    with get_session() as s:
        for i, r in enumerate(targets, start=1):
            path = Path(r["file_path"])
            if use_sd:
                path = BACKUP_ROOT / path.relative_to(_RAW_REPORT_SYMLINK)
            if not path.exists():
                err += 1
                logger.warning(f"[w{shard_id}] no file {r['rcept_no']} ({path})")
                continue
            try:
                lines = extract_report_lines(
                    str(path), rcept_no=r["rcept_no"], corp_code=r["corp_code"],
                    report_fiscal_year=r["fiscal_year"], report_fiscal_period=r["fiscal_period"],
                    include_notes=True)
                n = store_note_fx_amounts(s, r["rcept_no"], getattr(lines, "note_fx", []))
                _progress(s, r, "done", n, "r370")
                s.commit()
            except Exception as exc:  # noqa: BLE001
                s.rollback()
                err += 1
                logger.error(f"[w{shard_id}] {r['rcept_no']}: {type(exc).__name__}: {exc}")
                continue
            done += 1
            with_fx += 1 if n else 0
            n_fx_total += n
            if i % 500 == 0 or i == len(targets):
                el = time.time() - t0
                logger.info(f"[w{shard_id}] {i:,}/{len(targets):,} done {done:,} with_fx {with_fx:,} "
                            f"fx_rows {n_fx_total:,} err {err:,} - {el/60:.1f} min, "
                            f"~{(len(targets) - i) / (i / el) / 60:.0f} min left")
    return {"total": len(targets), "done": done, "error": err, "with_fx": with_fx, "fx": n_fx_total}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fiscal-year-min", type=int, default=2015)
    ap.add_argument("--fiscal-year-max", type=int, default=2100)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--sd-mirror", action="store_true", help="read the sources from the SD mirror")
    ap.add_argument("--redo", action="store_true", help="ignore the progress table")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    rows = _load_targets(a.fiscal_year_min, a.fiscal_year_max, a.redo)
    if a.limit:
        rows = rows[: a.limit]
    logger.info(f"targets {len(rows):,} filings / {len({r['corp_code'] for r in rows}):,} corps "
                f"(fy {a.fiscal_year_min}..{a.fiscal_year_max}, done ones skipped unless --redo)")
    if not rows or a.dry_run:
        return
    if a.sd_mirror:
        sample = rows[:200]
        miss = [r["rcept_no"] for r in sample
                if not (BACKUP_ROOT / Path(r["file_path"]).relative_to(_RAW_REPORT_SYMLINK)).exists()]
        if len(miss) / len(sample) > 0.02:
            raise SystemExit(f"SD mirror misses {len(miss)}/{len(sample)} of the sample - stop")
    n = max(1, min(a.workers, len({r['corp_code'] for r in rows})))
    shards = _partition_by_corp(rows, n)
    t0 = time.time()
    with Pool(processes=n) as pool:
        res = pool.starmap(_worker, [(i, sh, a.sd_mirror) for i, sh in enumerate(shards, start=1)])
    agg = {k: sum(r[k] for r in res) for k in ("total", "done", "error", "with_fx", "fx")}
    logger.success(f"finished {agg} in {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
