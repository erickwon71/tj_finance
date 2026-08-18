"""Backfill layer-2 lines (body + notes) for the `file_type='xml'` path, in batches.

Companion to scripts/backfill_xbrl_instance_lines_2026-08-18.py, which covers the
`file_type='xbrl_zip'` path. This one drives `collector/note_lines_sync.py::
sync_layer2_lines()` — the function `collect_new.py::_sync_layer2_lines()` (④-3) calls.

Why a separate driver (2026-08-18): the ④-3 step runs at the very end of
`collect_new.py --standardize-only`, after the per-corp standardization loop. On a large
corp list that loop dominates the runtime (measured 44.4s/corp), so ④-3 is reached hours
in — and if the run is interrupted before it, the standardization is committed while the
layer-2 transcription silently never happens. That is exactly what occurred for the
2026 H1 xml-path backlog: 374/374 corps standardized (std_v2 27,311 rows), then the run
ended during the post-steps, leaving all 374 corps with zero report_lines.

Batches commit separately (sync_layer2_lines commits per call) and pending work is
recomputed from the DB on every run, so an interrupted run is resumed by re-running.

Usage:
  .venv/bin/python scripts/backfill_layer2_lines_2026-08-18.py --corp-file <path> --dry-run
  .venv/bin/python scripts/backfill_layer2_lines_2026-08-18.py --corp-file <path>
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

from collector.note_lines_sync import FY_MIN, sync_layer2_lines


def _read_corps(path: str) -> list[str]:
    raw = Path(path).read_text(encoding="utf-8")
    seen: dict[str, None] = {}
    for tok in raw.replace(",", "\n").split():
        tok = tok.strip()
        if tok:
            seen.setdefault(tok, None)
    return list(seen)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corp-file", required=True,
                    help="corp_code 목록 파일(줄바꿈 또는 콤마 구분)")
    ap.add_argument("--year-min", type=int, default=FY_MIN)
    ap.add_argument("--batch-size", type=int, default=20,
                    help="한 번의 sync 호출에 넘길 기업 수. 배치마다 커밋된다")
    ap.add_argument("--limit", type=int, default=None, help="처리할 기업 수 상한(시험용)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    corps = _read_corps(args.corp_file)
    logger.info(f"[backfill-layer2] 입력 기업 {len(corps):,} (fy >= {args.year_min})")
    if args.limit:
        corps = corps[: args.limit]
        logger.info(f"[backfill-layer2] --limit 적용 — 기업 {len(corps):,}")
    if args.dry_run:
        logger.info("[backfill-layer2] --dry-run — 적재하지 않고 종료")
        return

    agg = {"corps": 0, "filings": 0, "rows": 0, "body_rows": 0, "errors": 0}
    t0 = time.time()
    for i in range(0, len(corps), args.batch_size):
        batch = corps[i : i + args.batch_size]
        try:
            r = sync_layer2_lines(batch, year_min=args.year_min)
        except Exception as exc:  # noqa: BLE001 — one batch must not kill the run
            agg["errors"] += 1
            logger.error(f"[backfill-layer2] 배치 실패({batch[0]}~{batch[-1]}): "
                         f"{type(exc).__name__}: {exc}")
            continue
        for k in agg:
            agg[k] += r.get(k, 0)
        done = min(i + args.batch_size, len(corps))
        elapsed = time.time() - t0
        rate = done / elapsed if elapsed else 0
        eta = (len(corps) - done) / rate if rate else 0
        logger.info(f"[backfill-layer2]   진행 {done:,}/{len(corps):,} "
                    f"(보고서 {agg['filings']:,} · 본문 {agg['body_rows']:,}행 · "
                    f"주석 {agg['rows']:,}행 · 오류 {agg['errors']}) — "
                    f"경과 {elapsed/60:.1f}분 · 잔여 ~{eta/60:.1f}분")

    logger.success(f"[backfill-layer2] 완료 — 기업 {agg['corps']:,} · 보고서 {agg['filings']:,} · "
                   f"본문 {agg['body_rows']:,}행 · 주석 {agg['rows']:,}행 · "
                   f"오류 {agg['errors']} · {(time.time()-t0)/60:.1f}분")


if __name__ == "__main__":
    main()
