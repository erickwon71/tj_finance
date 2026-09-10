"""R74(sanemax-reject 컬럼밀림 버그, 2026-09-06 수정) 전수 영향범위 census.

수정된 `extract_report_lines()`를 전 필링(XML 원문)에 대해 다시 돌려(DB에는 쓰지 않음,
읽기전용), 결과에서 이 버그의 지문을 찾는다: 같은 (rcept_no, statement, basis,
table_seq, label_raw) 그룹에서 col_index=0 이 없는데 col_index 1 또는 2 는 있는 경우
— 수정 전에는 "당기 값이 거부되고 전기 값이 당기 열로 밀려 들어감"으로 나타났을
자리가, 수정 후에는 "당기 결측 + 전기/전전기 제자리"로 정직하게 나타난다. 표본
필터링 없이 전수 재추출이라 시간이 걸린다 — multiprocessing 사용.

Usage:
    python scripts/census_sanemax_shift_2026-09-06.py --sample 500   # 표본으로 속도 가늠
    python scripts/census_sanemax_shift_2026-09-06.py --all          # 전수(백그라운드 권장)
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from collector.db import get_session

OUT = Path(__file__).parent.parent / "scratch_census_sanemax_shift.csv"


def _fetch_targets(sample: int | None):
    sql = """
        SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
        FROM download_tasks dt JOIN filings f USING(rcept_no)
        WHERE dt.status='completed' AND dt.file_type='xml' AND dt.file_path IS NOT NULL
        ORDER BY f.corp_code, f.fiscal_year, dt.rcept_no
    """
    if sample:
        sql += f" LIMIT {sample}"
    with get_session() as session:
        return session.execute(text(sql)).fetchall()


def _init_worker():
    """워커 프로세스당 한 번 — 정상 보류 DEBUG 로그가 대량실행에서 stdout을 덮는 것 방지."""
    from loguru import logger
    logger.remove()


def _check_one(row):
    """한 필링을 재추출해 sanemax-shift 지문(그룹에 col0 없고 1/2는 있음)을 찾는다."""
    from fin2.extract.report_lines import extract_report_lines

    rcept_no, file_path, corp_code, fiscal_year, fiscal_period = row
    p = Path(file_path)
    if not p.exists():
        return []
    try:
        lines = extract_report_lines(
            p, rcept_no=rcept_no, corp_code=corp_code,
            report_fiscal_year=fiscal_year, report_fiscal_period=fiscal_period,
            include_notes=False,
        )
    except Exception as e:  # noqa: BLE001 — census는 개별 필링 예외로 중단되면 안 됨
        return [("ERROR", rcept_no, corp_code, fiscal_year, str(e)[:200])]

    groups: dict[tuple, set[int]] = {}
    for l in lines:
        if l.statement not in ("BS", "IS", "CF") or l.report_fiscal_period != "FY":
            continue
        key = (l.statement, l.basis, l.table_seq, l.label_raw)
        groups.setdefault(key, set()).add(l.col_index)

    hits = []
    for (statement, basis, table_seq, label_raw), cols in groups.items():
        if 0 not in cols and (1 in cols or 2 in cols):
            hits.append((corp_code, rcept_no, fiscal_year, statement, basis,
                         table_seq, label_raw, sorted(cols)))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    if not args.all and not args.sample:
        args.sample = 500

    targets = _fetch_targets(args.sample)
    print(f"targets: {len(targets)}")
    t0 = time.time()

    all_hits = []
    errors = []
    with Pool(args.workers, initializer=_init_worker) as pool:
        for i, hits in enumerate(pool.imap_unordered(_check_one, targets, chunksize=20)):
            for h in hits:
                if h[0] == "ERROR":
                    errors.append(h)
                else:
                    all_hits.append(h)
            if (i + 1) % 2000 == 0:
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed
                eta = (len(targets) - (i + 1)) / rate if rate else 0
                print(f"  {i+1}/{len(targets)} done, {elapsed:.0f}s elapsed, "
                      f"eta {eta/60:.1f}min, hits so far={len(all_hits)}, errors={len(errors)}",
                      flush=True)

    elapsed = time.time() - t0
    print(f"done in {elapsed:.0f}s. candidate hits: {len(all_hits)}, errors: {len(errors)}")

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["corp_code", "rcept_no", "fiscal_year", "statement", "basis",
                    "table_seq", "label_raw", "cols_present"])
        for h in all_hits:
            w.writerow(h)
    print(f"saved: {OUT}")

    n_rcept = len({(h[0], h[1]) for h in all_hits})
    n_corp = len({h[0] for h in all_hits})
    print(f"distinct filings affected: {n_rcept}, distinct corps: {n_corp}")

    if errors:
        err_out = OUT.with_name("scratch_census_sanemax_shift_errors.csv")
        with open(err_out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerows(errors)
        print(f"errors saved: {err_out} ({len(errors)})")


if __name__ == "__main__":
    main()
