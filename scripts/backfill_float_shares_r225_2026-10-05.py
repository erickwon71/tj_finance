#!/usr/bin/env python
"""R225 소급 — report_shares_outstanding 에 Ⅴ 자기주식수·Ⅵ 유통주식수(보통주)를 채운다.

docs/PARSING_RULES.md R225 (사용자 결정 2026-10-05: 밸류에이션 주식수 = 유통주식수).
기존 행의 원문을 `extract_share_counts` 로 다시 읽어 treasury_shares/float_shares 만 UPDATE 한다.
shares_out(Ⅳ)은 건드리지 않는다 — 재추출 Ⅳ 가 기존 값과 다르면 세기만 한다(같은 규칙이라 0 기대).

    python scripts/backfill_float_shares_r225_2026-10-05.py --limit 200
    python scripts/backfill_float_shares_r225_2026-10-05.py --workers 6 --sd-mirror
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
from fin2.extract.shares import extract_share_counts

_TARGETS_SQL = """
    SELECT r.rcept_no, r.shares_out,
           (SELECT d.file_path FROM download_tasks d WHERE d.rcept_no = r.rcept_no
              AND d.status = 'completed' AND d.file_type = 'xml' LIMIT 1) AS file_path
    FROM report_shares_outstanding r
    WHERE r.float_shares IS NULL AND r.treasury_shares IS NULL
    ORDER BY r.corp_code, r.rcept_no
"""


def _work(args):
    rows, use_sd = args
    agg = Counter()
    with get_session() as s:
        for i, r in enumerate(rows, 1):
            if not r["file_path"]:
                agg["no_xml"] += 1
                continue
            p = Path(r["file_path"])
            if use_sd:
                p = BACKUP_ROOT / p.relative_to(_RAW_REPORT_SYMLINK)
            try:
                c = extract_share_counts(p)
            except Exception as exc:  # noqa: BLE001
                agg["error"] += 1
                logger.error(f"{r['rcept_no']}: {type(exc).__name__}: {exc}")
                continue
            if not c:
                agg["not_found"] += 1
                continue
            if c["issued"] != r["shares_out"]:
                agg["issued_differs"] += 1
            s.execute(text("""UPDATE report_shares_outstanding
                SET treasury_shares = :t, float_shares = :f WHERE rcept_no = :r"""),
                {"t": c["treasury"], "f": c["float"], "r": r["rcept_no"]})
            agg["float" if c["float"] else "no_float"] += 1
            if i % 200 == 0:
                s.commit()
        s.commit()
    return agg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--sd-mirror", action="store_true")
    args = ap.parse_args()
    with get_session() as s:
        rows = [dict(r) for r in s.execute(text(_TARGETS_SQL)).mappings()]
    if args.limit:
        rows = rows[: args.limit]
    logger.info(f"대상 {len(rows):,}행")
    chunks = [rows[i::args.workers] for i in range(args.workers)]
    t0 = time.time()
    agg = Counter()
    with Pool(args.workers) as pool:
        for a in pool.imap_unordered(_work, [(c, args.sd_mirror) for c in chunks]):
            agg.update(a)
    logger.success(f"완료 {dict(agg)} — {(time.time() - t0) / 60:.1f}분")
    return 0


if __name__ == "__main__":
    sys.exit(main())
