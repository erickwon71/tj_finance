#!/usr/bin/env python
"""R219 백필 — note_lines 는 있는데 주석 표 메타(report_tables statement='note')가 없는 필링 복구.

배경(docs/PARSING_RULES.md R219): `store_report_tables()` 가 rcept 의 메타를 **전부** 지우고
넘겨받은 lines 만 다시 썼다. 본문만 추출한 재적재(2015+ 전사 재적재 2026-09-12 등, 데일리
XBRL 인스턴스 경로)가 주석 메타를 지웠고, R135 주석 재적재(2026-09-17)는 `store_note_lines`
만 불러 메타를 되살리지 않았다. 주석 제목(section_path)이 없으면 계층3 주석 해석
(`fin2/layer3/note_da.py` D&A 등)이 그 필링의 주석을 못 본다. 2026-10-05 실측 77,672필링.

## 하는 일 (필링마다 한 트랜잭션)
1. 원문 XML 을 `include_notes=True` 로 다시 추출한다.
2. 추출한 주석 표가 DB note_lines 의 표와 같은지 본다: (basis, table_seq) 키 집합이 같고,
   표마다 라벨이 하나 이상 겹치면 같은 표다. 행 수는 비교하지 않는다 — 9/17 이후 행 단위
   규칙(R136~)이 바뀌어 행 수는 대부분 다르지만 표 번호 체계는 그대로다(표본 6/6 표 집합 일치).
   - 같으면 → 주석 메타만 쓴다(`store_report_tables(scope='note')`). note_lines 무변경.
   - 다르면 → 현재 코드 기준으로 note_lines 도 다시 쓴다(`store_note_lines`) — 메타와
     행이 같은 추출에서 와야 table_seq 가 맞는다.
3. report_lines·본문 메타는 건드리지 않는다.

## 재개
대상 = "note_lines 있음 AND 주석 메타 없음" 이라 처리된 필링은 자동으로 빠진다.
주석 0행으로 추출된 필링은 메타를 만들 수 없어 대상에 남는다 — 로그의 empty 로 확인.

## 사용법
    python scripts/restore_note_table_meta_r219_2026-10-05.py --dry-run
    python scripts/restore_note_table_meta_r219_2026-10-05.py --corp 00126955
    python scripts/restore_note_table_meta_r219_2026-10-05.py --workers 6 --sd-mirror
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
from fin2.extract.report_lines import (extract_report_lines, store_note_lines,
                                       store_report_tables)

_TARGETS_SQL = """
    SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period,
           (SELECT dt.file_path FROM download_tasks dt
             WHERE dt.rcept_no = f.rcept_no AND dt.status = 'completed'
               AND dt.file_type = 'xml' AND dt.file_path IS NOT NULL
             LIMIT 1) AS file_path
    FROM filings f
    WHERE EXISTS (SELECT 1 FROM note_lines n WHERE n.rcept_no = f.rcept_no)
      AND NOT EXISTS (SELECT 1 FROM report_tables rt
                       WHERE rt.rcept_no = f.rcept_no AND rt.statement = 'note')
      {corp_clause}
    ORDER BY f.corp_code, f.fiscal_year, f.rcept_no
"""

_DB_LABELS_SQL = text("""
    SELECT basis, table_seq, label_raw FROM note_lines WHERE rcept_no = :r
""")


def _same_tables(db_rows, notes) -> bool:
    """True if note_lines in the DB and the fresh extraction enumerate the same tables."""
    db: dict[tuple, set] = {}
    for b, t, label in db_rows:
        db.setdefault((b, t), set()).add(label)
    ex: dict[tuple, set] = {}
    for l in notes:
        ex.setdefault((l.basis, l.table_seq), set()).add(l.label_raw)
    if db.keys() != ex.keys():
        return False
    return all(db[k] & ex[k] for k in db)


def _load_targets(corps: list[str] | None) -> list[dict]:
    clause = "AND f.corp_code = ANY(:corps)" if corps else ""
    params = {"corps": corps} if corps else {}
    with get_session() as s:
        return [dict(r) for r in s.execute(text(_TARGETS_SQL.format(corp_clause=clause)),
                                           params).mappings()]


def _partition_by_corp(rows: list[dict], n_workers: int) -> list[list[dict]]:
    by_corp: dict[str, list[dict]] = {}
    for r in rows:
        by_corp.setdefault(r["corp_code"], []).append(r)
    shards: list[list[dict]] = [[] for _ in range(n_workers)]
    loads = [0] * n_workers
    for g in sorted(by_corp.values(), key=len, reverse=True):
        i = loads.index(min(loads))
        shards[i].extend(g)
        loads[i] += len(g)
    return shards


def _worker(shard_id: int, targets: list[dict], use_sd_mirror: bool) -> dict:
    agg = Counter()
    t0 = time.time()
    total = len(targets)
    for i, r in enumerate(targets, start=1):
        if not r["file_path"]:
            agg["no_xml"] += 1
            continue
        path = Path(r["file_path"])
        if use_sd_mirror:
            path = BACKUP_ROOT / path.relative_to(_RAW_REPORT_SYMLINK)
        if not path.exists():
            agg["missing_file"] += 1
            logger.warning(f"[w{shard_id}] 파일 없음 {r['rcept_no']} ({path})")
            continue
        try:
            lines = extract_report_lines(
                str(path), rcept_no=r["rcept_no"], corp_code=r["corp_code"],
                report_fiscal_year=r["fiscal_year"],
                report_fiscal_period=r["fiscal_period"], include_notes=True)
        except Exception as exc:  # noqa: BLE001 — one bad file must not stop the shard
            agg["error"] += 1
            logger.error(f"[w{shard_id}] 추출 실패 {r['rcept_no']}: {type(exc).__name__}: {exc}")
            continue
        notes = [l for l in lines if l.statement == "note"]
        if not notes:
            agg["empty"] += 1
            logger.warning(f"[w{shard_id}] 주석 0행 {r['rcept_no']} — 메타 못 만듦, 보류")
            continue
        try:
            with get_session() as s:
                db_rows = s.execute(_DB_LABELS_SQL, {"r": r["rcept_no"]}).fetchall()
                if not _same_tables(db_rows, notes):
                    store_note_lines(s, r["rcept_no"], lines)
                    agg["notes_rewritten"] += 1
                else:
                    agg["meta_only"] += 1
                store_report_tables(s, r["rcept_no"], lines, scope="note")
        except Exception as exc:  # noqa: BLE001
            agg["error"] += 1
            logger.error(f"[w{shard_id}] 적재 실패 {r['rcept_no']}: {type(exc).__name__}: {exc}")
            continue
        if i % 500 == 0 or i == total:
            el = time.time() - t0
            eta = (total - i) / (i / el) if el else 0
            logger.info(f"[w{shard_id}] {i:,}/{total:,} {dict(agg)} — "
                        f"{el/60:.1f}분 경과 · 잔여 ~{eta/60:.1f}분")
    return dict(agg, total=total)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corp", help="comma-separated corp_code (trial)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--sd-mirror", action="store_true",
                    help="read raw XML from the SD-card mirror instead of NAS (bulk reads)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    corps = [c.strip() for c in args.corp.split(",") if c.strip()] if args.corp else None
    rows = _load_targets(corps)
    if args.limit:
        rows = rows[: args.limit]
    n_corps = len({r["corp_code"] for r in rows})
    logger.info(f"대상 {len(rows):,}필링 / {n_corps:,}개사")
    if not rows or args.dry_run:
        return

    n_workers = max(1, min(args.workers, n_corps))
    shards = _partition_by_corp(rows, n_workers)
    t0 = time.time()
    with Pool(processes=n_workers) as pool:
        results = pool.starmap(_worker, [(i, sh, args.sd_mirror)
                                         for i, sh in enumerate(shards, start=1)])
    agg = Counter()
    for r in results:
        agg.update(r)
    logger.success(f"완료 {dict(agg)} — {(time.time() - t0)/60:.1f}분")


if __name__ == "__main__":
    main()
