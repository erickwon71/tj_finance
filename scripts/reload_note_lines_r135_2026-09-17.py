#!/usr/bin/env python
"""2015+ 전수 note_lines 재적재 — R135(다중 라벨 셀 조인) 백필 전용, 병렬(corp 단위 샤딩).

배경: R134(SCE "기수" 규칙 앵커행 드롭)·R135(라벨 영역 다중 물리 셀 조인, `_grid_body_rows`)
둘 다 `scripts/reload_report_lines_2015plus_2026-09-12.py`(본문 BS/IS/CF/SCE, `include_notes
=False`)로 이미 백필 완료됐다. 그런데 R135는 주석(note_lines, 2.47억 행)과 **같은 함수를
공유**해 주석에도 똑같이 적용되는데, 본문 재적재는 애초에 notes 를 안 건드리므로 주석은
아직 구버전 라벨(예: "자본의 변동")인 채로 남아있다 — 표본 스캔(2026-09-16, 2,000건) 실측
8.55%(약 2,100만 행 추정) 영향. 이 스크립트가 그 갭을 메운다.

## 왜 본문 재적재 스크립트를 그대로 재사용하지 않는가
`extract_report_lines(include_notes=True)`는 본문+주석을 한 번에 다 뽑지만, 본문(BS/IS/CF/SCE)은
바로 어제 이미 R135 반영해서 재적재했으므로 여기서 또 `store_report_lines`/`store_report_tables`
를 부르면 같은 일을 중복(9시간 규모)한다. 그래서 이 스크립트는 **`store_note_lines`만** 부른다
(`fin2/extract/report_lines.py`) — 본문 저장은 건드리지 않는다.

## 체크포인트가 별도 테이블인 이유
`report_line_load_progress`(rcept_no PK)를 재사용하면 어제 본문 재적재가 남긴 "reload_2015plus
완료" 기록을 이 스크립트의 merge 가 그대로 덮어써 버린다(같은 PK). 그래서 완전히 별도인
`note_line_reload_progress`(마이그레이션 `2026_09_17_note_line_reload_progress`, collector/db.py)
를 쓴다 — 재개 시 이미 done 인 rcept 는 자동으로 건너뛴다(별도 `--exclude` 인자 불필요).

## 유니버스
본문 재적재와 동일 스코프(2015+, KOSPI/KOSDAQ 상장 보통주, coverage_class='periodic',
report_type IN annual/half/quarter, layer2_review_queue.status='pass' 제외) — 일관성 유지.

## 병렬
본문 재적재와 동일 패턴(corp 단위 그리디 샤딩, 회사 경계 커밋). **주석은 본문보다 표당 행수가
훨씬 많아(평균 ~1,300행/필링 vs 본문 ~560행/필링) 필링당 파싱+적재 시간이 더 길다** — 워커
수를 무작정 올리지 말 것(NAS I/O 병목은 본문과 동일 리스크).

## 사용법
    python scripts/reload_note_lines_r135_2026-09-17.py --dry-run
    python scripts/reload_note_lines_r135_2026-09-17.py --workers 4 --limit 200   # 시험
    python scripts/reload_note_lines_r135_2026-09-17.py --workers 4               # 본 실행
    (중간에 죽어도 그냥 다시 실행하면 됨 — note_line_reload_progress 에 done 인 rcept 는 자동 skip)
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
from fin2.extract.report_lines import extract_report_lines, store_note_lines

# 본문 재적재(scripts/reload_report_lines_2015plus_2026-09-12.py)의 _TARGETS_SQL_TMPL 과
# 같은 유니버스 정의(스코프 일관성) — done 인 rcept 만 추가로 제외한다.
_TARGETS_SQL_TMPL = """
    WITH universe AS (
        SELECT c.corp_code
        FROM corporations c
        WHERE c.is_active
          AND c.stock_code IS NOT NULL
          AND c.stock_code NOT LIKE '9%%'
          AND c.coverage_class = 'periodic'
    )
    SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
    FROM download_tasks dt
    JOIN filings f USING (rcept_no)
    JOIN universe u ON u.corp_code = f.corp_code
    LEFT JOIN layer2_review_queue lrq ON lrq.rcept_no = f.rcept_no
    LEFT JOIN note_line_reload_progress nlp ON nlp.rcept_no = f.rcept_no AND nlp.status = 'done'
    WHERE f.report_type IN ('annual', 'half', 'quarter')
      AND f.fiscal_year >= :fy_min
      AND dt.status = 'completed'
      AND dt.file_type = 'xml'
      AND dt.file_path IS NOT NULL
      AND (lrq.status IS NULL OR lrq.status <> 'pass')
      AND f.report_nm NOT LIKE '%제출기한연장%'
      AND nlp.rcept_no IS NULL
      {corp_clause}
      {exclude_corp_clause}
      {rcept_clause}
    ORDER BY f.corp_code, f.fiscal_year, dt.rcept_no
"""


def _load_targets(fy_min: int, corps: list[str] | None,
                   exclude_corps: list[str] | None,
                   rcepts: list[str] | None = None) -> list[dict]:
    corp_clause = "AND f.corp_code = ANY(:corps)" if corps else ""
    exclude_clause = "AND f.corp_code <> ALL(:exclude_corps)" if exclude_corps else ""
    rcept_clause = "AND f.rcept_no = ANY(:rcepts)" if rcepts else ""
    sql = text(_TARGETS_SQL_TMPL.format(corp_clause=corp_clause,
                                        exclude_corp_clause=exclude_clause,
                                        rcept_clause=rcept_clause))
    params: dict = {"fy_min": fy_min}
    if corps:
        params["corps"] = corps
    if exclude_corps:
        params["exclude_corps"] = exclude_corps
    if rcepts:
        params["rcepts"] = rcepts
    with get_session() as s:
        return [dict(r) for r in s.execute(sql, params).mappings()]


def _partition_by_corp(rows: list[dict], n_workers: int) -> list[list[dict]]:
    by_corp: dict[str, list[dict]] = {}
    for r in rows:
        by_corp.setdefault(r["corp_code"], []).append(r)
    groups = sorted(by_corp.values(), key=len, reverse=True)
    shards: list[list[dict]] = [[] for _ in range(n_workers)]
    loads = [0] * n_workers
    for g in groups:
        i = loads.index(min(loads))
        shards[i].extend(g)
        loads[i] += len(g)
    return shards


def _record_progress(s, rcept_no: str, corp_code: str, fiscal_year: int,
                      status: str, n_lines: int | None, message: str) -> None:
    s.execute(text("""
        INSERT INTO note_line_reload_progress
            (rcept_no, corp_code, fiscal_year, status, n_lines, message, processed_at)
        VALUES (:rcept_no, :corp_code, :fiscal_year, :status, :n_lines, :message, :processed_at)
        ON CONFLICT (rcept_no) DO UPDATE SET
            corp_code = EXCLUDED.corp_code, fiscal_year = EXCLUDED.fiscal_year,
            status = EXCLUDED.status, n_lines = EXCLUDED.n_lines,
            message = EXCLUDED.message, processed_at = EXCLUDED.processed_at
    """), {"rcept_no": rcept_no, "corp_code": corp_code, "fiscal_year": fiscal_year,
           "status": status, "n_lines": n_lines, "message": message[:200],
           "processed_at": datetime.utcnow()})


def _worker(shard_id: int, targets: list[dict], use_sd_mirror: bool = False) -> dict:
    n_done = n_error = n_empty = 0
    t0 = time.time()
    total = len(targets)
    with get_session() as s:
        prev_corp = None
        for i, r in enumerate(targets, start=1):
            if prev_corp is not None and r["corp_code"] != prev_corp:
                s.commit()
            prev_corp = r["corp_code"]

            path = Path(r["file_path"])
            if use_sd_mirror:
                path = BACKUP_ROOT / path.relative_to(_RAW_REPORT_SYMLINK)
            if not path.exists():
                n_error += 1
                logger.warning(f"[w{shard_id}] 파일 없음 {r['rcept_no']} ({path})")
                continue
            try:
                lines = extract_report_lines(
                    str(path), rcept_no=r["rcept_no"], corp_code=r["corp_code"],
                    report_fiscal_year=r["fiscal_year"],
                    report_fiscal_period=r["fiscal_period"], include_notes=True)
            except Exception as exc:  # noqa: BLE001
                n_error += 1
                logger.error(f"[w{shard_id}] 추출 실패 {r['rcept_no']}: "
                             f"{type(exc).__name__}: {exc}")
                continue

            notes = [l for l in lines if l.statement == "note"]
            if not notes:
                n_empty += 1
                _record_progress(s, r["rcept_no"], r["corp_code"], r["fiscal_year"],
                                  "done", 0, "reload_note_r135: 0행(보류) — 주석 미검출")
                continue

            try:
                nl = store_note_lines(s, r["rcept_no"], lines)
            except Exception as exc:  # noqa: BLE001
                s.rollback()
                n_error += 1
                logger.error(f"[w{shard_id}] 적재 실패 {r['rcept_no']}: "
                             f"{type(exc).__name__}: {exc}")
                continue

            _record_progress(s, r["rcept_no"], r["corp_code"], r["fiscal_year"],
                              "done", nl, "reload_note_r135")
            n_done += 1

            if i % 200 == 0 or i == total:
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed else 0
                eta = (total - i) / rate if rate else 0
                logger.info(f"[w{shard_id}] {i:,}/{total:,} "
                            f"(완료 {n_done:,} · 보류 {n_empty:,} · 오류 {n_error:,}) — "
                            f"{elapsed/60:.1f}분 경과 · 잔여 ~{eta/60:.1f}분")
        s.commit()
    return {"shard": shard_id, "total": total, "done": n_done,
            "error": n_error, "empty": n_empty}


def _read_corp_list(path: str) -> list[str]:
    raw = Path(path).read_text(encoding="utf-8")
    seen: dict[str, None] = {}
    for tok in raw.replace(",", "\n").split():
        tok = tok.strip()
        if tok:
            seen.setdefault(tok, None)
    return list(seen)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fiscal-year-min", type=int, default=2015)
    ap.add_argument("--corp", help="쉼표구분 corp_code — 지정 시 그 회사만(시험용)")
    ap.add_argument("--exclude-corp-file")
    ap.add_argument("--rcept-file")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=4,
                    help="병렬 워커 수(기본 4 — 주석은 본문보다 무거워 과도하게 올리지 말 것)")
    ap.add_argument("--sd-mirror", action="store_true",
                    help="원문을 NAS 대신 SD카드 미러에서 읽는다(대량 read 전용, 순수 읽기)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    corps = [c.strip() for c in args.corp.split(",") if c.strip()] if args.corp else None
    exclude_corps = _read_corp_list(args.exclude_corp_file) if args.exclude_corp_file else None
    rcepts = _read_corp_list(args.rcept_file) if args.rcept_file else None

    rows = _load_targets(args.fiscal_year_min, corps, exclude_corps, rcepts)
    if args.limit:
        rows = rows[: args.limit]

    n_corps = len({r["corp_code"] for r in rows})
    logger.info(f"대상 filing {len(rows):,}건 / {n_corps:,}개사 "
                f"(fiscal_year >= {args.fiscal_year_min}, 이미 done 인 rcept 자동 제외)")
    if not rows:
        return
    if args.dry_run:
        logger.info("--dry-run — 재적재하지 않고 종료")
        return

    if args.sd_mirror:
        sample = rows[:200]
        missing = [r["rcept_no"] for r in sample
                   if not (BACKUP_ROOT / Path(r["file_path"]).relative_to(
                       _RAW_REPORT_SYMLINK)).exists()]
        if missing:
            miss_rate = len(missing) / len(sample)
            logger.warning(f"[sd-mirror 프리플라이트] 표본 {len(sample)}건 중 "
                            f"{len(missing)}건({miss_rate:.0%}) SD 미러에 없음: "
                            f"{missing[:5]}{'...' if len(missing) > 5 else ''}")
            if miss_rate > 0.02:
                raise SystemExit(
                    "SD 미러 결측률이 2%를 넘어 중단 — 미러가 stale일 가능성. "
                    "scripts/sync_storage_mirror.py 로 먼저 갱신하거나 --sd-mirror 없이 실행할 것.")
        logger.info(f"[sd-mirror 프리플라이트] 표본 {len(sample)}건 전부 확인됨 — SD 미러로 읽는다.")

    n_workers = max(1, min(args.workers, n_corps))
    shards = _partition_by_corp(rows, n_workers)
    logger.info(f"워커 {n_workers}개 분배: " + ", ".join(f"{len(sh):,}건" for sh in shards)
                + (" (SD 미러 read)" if args.sd_mirror else " (NAS read)"))

    t0 = time.time()
    with Pool(processes=n_workers) as pool:
        results = pool.starmap(
            _worker, [(i, sh, args.sd_mirror) for i, sh in enumerate(shards, start=1)])

    agg = {"done": 0, "error": 0, "empty": 0, "total": 0}
    for r in results:
        for k in agg:
            agg[k] += r[k]
    elapsed = time.time() - t0
    logger.success(
        f"완료 — 재적재 {agg['done']:,} · 0행(보류) {agg['empty']:,} · "
        f"오류 {agg['error']:,} / 전체 {agg['total']:,} — {elapsed/60:.1f}분")


if __name__ == "__main__":
    main()
