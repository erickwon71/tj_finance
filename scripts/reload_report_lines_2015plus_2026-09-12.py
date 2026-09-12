#!/usr/bin/env python
"""2015+ 전수 report_lines 재적재 — 현재 파서 적용, 병렬(corp 단위 샤딩).

배경: 계층2 재적재+원문대조 캠페인(`scripts/layer2_review.py`, 2026-09-08)이 진행되며
`fin2/extract/report_lines.py`/`fin2/audit/layer2_selfcheck.py` 에 여러 파서·검산 버그가
고쳐졌다(예: 2026-09-12 cf_closing_cash 매각예정재분류행 누락). 그 캠페인은 시총순으로
회사를 하나씩 사람이 눈으로 대조하는 절차라 진행이 느리다 — 이 스크립트는 그와 별개로
**2015+ 전 종목**에 지금 이 시점의 파서를 일괄 재적용해, 캠페인이 아직 도달하지 않은
회사에도 이미 고쳐진 버그들의 효과가 미치게 한다.

## 대상
`docs/plans/layer2_review_staged_screening_design_2026-09-11.md` §1 "1단계(2015~현재)"와
같은 스코프 — 현재 시점 KOSPI/KOSDAQ 상장 보통주(개인 거래 가능, `coverage_class='periodic'`,
국내상장 외국기업 제외) × report_type IN (annual/half/quarter) × fiscal_year >= 2015(기본,
`--fiscal-year-min` 로 조정) × 원문이 XML 로 다운로드 완료된 것.

## 제외 — manual 검토 완료 건
1. **`layer2_review_queue.status='pass'`** — 캠페인에서 사람이 이미 원문과 대조해 통과시킨
   건. 파서가 최신이라도 재적재로 CSV/검산이 새로 갱신돼 다시 봐야 하는 착시가 생기지 않게
   건드리지 않는다.
2. **`report_lines.unit_source='manual'`** — 사람이 직접 타이핑해 넣은 값(Track C 계열).
   `store_report_lines()` 자체에 있는 보호가드(2026-09-08)가 자동으로 막는다 — 이 스크립트는
   그 `ValueError`를 흡수해 "manual보호" 로 집계할 뿐 별도로 미리 걸러내지 않는다(가드가
   최종 진실이라 이중 판정을 피한다).

## 병렬
corp_code 단위로 워커에 분배한다(같은 회사의 여러 필링이 같은 워커 안에서 순서대로 처리돼
회사 경계 커밋이 유지된다). 워커 수만큼 회사를 필링수 내림차순 그리디로 나눠 워커 간
부하를 맞춘다. 원문(raw_report)이 NAS(SMB) 마운트라 워커를 너무 많이 올리면 네트워크 I/O
가 병목이 될 수 있다 — 기본 4, 필요시 조정.

## 사용법
    python scripts/reload_report_lines_2015plus_2026-09-12.py --dry-run
    python scripts/reload_report_lines_2015plus_2026-09-12.py --workers 4 --limit 200   # 시험
    python scripts/reload_report_lines_2015plus_2026-09-12.py --workers 4               # 본 실행

재개: 중간에 죽어도 안전하다 — `store_report_lines` 는 rcept 단위 delete-then-insert 라
같은 rcept 를 다시 돌려도 멱등이다. 이어서 돌리려면 이미 끝난 corp 를 `--exclude-corp`
(파일, 줄바꿈/콤마 구분)로 넘기거나 그냥 전체를 다시 돌려도 안전하다(느릴 뿐).
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
from collector.models import ReportLineLoadProgress
from fin2.extract.report_lines import extract_report_lines, store_report_lines, store_report_tables

# 캠페인의 _UNIVERSE_SQL(scripts/layer2_review.py)과 같은 유니버스 정의(코드 중복 —
# 그쪽은 시총 랭킹까지 필요해 이 스크립트에 필요한 것보다 훨씬 무겁다).
_TARGETS_SQL_TMPL = """
    WITH universe AS (
        SELECT c.corp_code
        FROM corporations c
        WHERE c.is_active
          AND c.stock_code IS NOT NULL
          AND c.stock_code NOT LIKE '9%%'   -- R7 국내상장 외국기업 제외
          AND c.coverage_class = 'periodic'
    )
    SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
    FROM download_tasks dt
    JOIN filings f USING (rcept_no)
    JOIN universe u ON u.corp_code = f.corp_code
    LEFT JOIN layer2_review_queue lrq ON lrq.rcept_no = f.rcept_no
    WHERE f.report_type IN ('annual', 'half', 'quarter')
      AND f.fiscal_year >= :fy_min
      AND dt.status = 'completed'
      AND dt.file_type = 'xml'
      AND dt.file_path IS NOT NULL
      AND (lrq.status IS NULL OR lrq.status <> 'pass')
      {corp_clause}
      {exclude_corp_clause}
    ORDER BY f.corp_code, f.fiscal_year, dt.rcept_no
"""


def _load_targets(fy_min: int, corps: list[str] | None,
                   exclude_corps: list[str] | None) -> list[dict]:
    corp_clause = "AND f.corp_code = ANY(:corps)" if corps else ""
    exclude_clause = "AND f.corp_code <> ALL(:exclude_corps)" if exclude_corps else ""
    sql = text(_TARGETS_SQL_TMPL.format(corp_clause=corp_clause,
                                        exclude_corp_clause=exclude_clause))
    params: dict = {"fy_min": fy_min}
    if corps:
        params["corps"] = corps
    if exclude_corps:
        params["exclude_corps"] = exclude_corps
    with get_session() as s:
        return [dict(r) for r in s.execute(sql, params).mappings()]


def _partition_by_corp(rows: list[dict], n_workers: int) -> list[list[dict]]:
    """corp_code 별로 묶은 뒤, 필링수 내림차순으로 가장 적게 찬 워커에 그리디 배분(LPT)."""
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


def _worker(shard_id: int, targets: list[dict]) -> dict:
    """워커 1개 = corp 여러 개, 자기 자신의 DB 세션·회사 경계 커밋으로 순차 처리."""
    n_done = n_skip_manual = n_error = n_empty = 0
    t0 = time.time()
    total = len(targets)
    with get_session() as s:
        prev_corp = None
        for i, r in enumerate(targets, start=1):
            # ★회사 경계 커밋 — 대량 배치가 중간에 죽어도 이미 처리한 회사분은 살아남는다
            #   (R31/T22 재현 방지, reload_report_lines_corp.py 와 같은 이유).
            if prev_corp is not None and r["corp_code"] != prev_corp:
                s.commit()
            prev_corp = r["corp_code"]

            path = Path(r["file_path"])
            if not path.exists():
                n_error += 1
                logger.warning(f"[w{shard_id}] 파일 없음 {r['rcept_no']} ({path})")
                continue
            try:
                lines = extract_report_lines(
                    str(path), rcept_no=r["rcept_no"], corp_code=r["corp_code"],
                    report_fiscal_year=r["fiscal_year"],
                    report_fiscal_period=r["fiscal_period"], include_notes=False)
            except Exception as exc:  # noqa: BLE001 — 파일 1건이 배치 전체를 죽이면 안 됨
                n_error += 1
                logger.error(f"[w{shard_id}] 추출 실패 {r['rcept_no']}: "
                             f"{type(exc).__name__}: {exc}")
                continue

            if not lines:
                n_empty += 1
                s.merge(ReportLineLoadProgress(
                    rcept_no=r["rcept_no"], corp_code=r["corp_code"],
                    fiscal_year=r["fiscal_year"], status="done", n_lines=0,
                    message="reload_2015plus: 0행(보류) — 섹션/표 미검출",
                    processed_at=datetime.utcnow()))
                continue

            try:
                nl = store_report_lines(s, r["rcept_no"], lines)
                store_report_tables(s, r["rcept_no"], lines)
            except ValueError as exc:      # manual 보호가드(report_lines.py:1429)
                s.rollback()
                n_skip_manual += 1
                s.merge(ReportLineLoadProgress(
                    rcept_no=r["rcept_no"], corp_code=r["corp_code"],
                    fiscal_year=r["fiscal_year"], status="skip",
                    message=f"manual-protected: {exc}", processed_at=datetime.utcnow()))
                continue
            except Exception as exc:  # noqa: BLE001
                s.rollback()
                n_error += 1
                logger.error(f"[w{shard_id}] 적재 실패 {r['rcept_no']}: "
                             f"{type(exc).__name__}: {exc}")
                continue

            s.merge(ReportLineLoadProgress(
                rcept_no=r["rcept_no"], corp_code=r["corp_code"],
                fiscal_year=r["fiscal_year"], status="done", n_lines=nl,
                message="reload_2015plus", processed_at=datetime.utcnow()))
            n_done += 1

            if i % 200 == 0 or i == total:
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed else 0
                eta = (total - i) / rate if rate else 0
                logger.info(f"[w{shard_id}] {i:,}/{total:,} "
                            f"(완료 {n_done:,} · manual제외 {n_skip_manual:,} · "
                            f"보류 {n_empty:,} · 오류 {n_error:,}) — "
                            f"{elapsed/60:.1f}분 경과 · 잔여 ~{eta/60:.1f}분")
        s.commit()
    return {"shard": shard_id, "total": total, "done": n_done,
            "skip_manual": n_skip_manual, "error": n_error, "empty": n_empty}


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
    ap.add_argument("--fiscal-year-min", type=int, default=2015,
                    help="이 연도 이상 필링만(기본 2015 — 시대1단계)")
    ap.add_argument("--corp", help="쉼표구분 corp_code — 지정 시 그 회사만(시험용)")
    ap.add_argument("--exclude-corp-file",
                    help="줄바꿈/콤마구분 corp_code 목록 파일 — 이미 처리한 회사 재개 시 제외용")
    ap.add_argument("--limit", type=int, default=None,
                    help="대상 filing 수 상한(정렬된 앞부분부터, 시험용)")
    ap.add_argument("--workers", type=int, default=4,
                    help="병렬 워커 수(기본 4 — NAS raw_report I/O 고려해 과도하게 올리지 말 것)")
    ap.add_argument("--dry-run", action="store_true", help="대상 개수만 세고 종료(적재 안 함)")
    args = ap.parse_args()

    corps = [c.strip() for c in args.corp.split(",") if c.strip()] if args.corp else None
    exclude_corps = _read_corp_list(args.exclude_corp_file) if args.exclude_corp_file else None

    rows = _load_targets(args.fiscal_year_min, corps, exclude_corps)
    if args.limit:
        rows = rows[: args.limit]

    n_corps = len({r["corp_code"] for r in rows})
    logger.info(f"대상 filing {len(rows):,}건 / {n_corps:,}개사 "
                f"(fiscal_year >= {args.fiscal_year_min}, "
                f"layer2_review_queue.status='pass' 및 unit_source='manual' 제외)")
    if not rows:
        return
    if args.dry_run:
        logger.info("--dry-run — 재적재하지 않고 종료")
        return

    n_workers = max(1, min(args.workers, n_corps))
    shards = _partition_by_corp(rows, n_workers)
    logger.info(f"워커 {n_workers}개 분배: " + ", ".join(f"{len(sh):,}건" for sh in shards))

    t0 = time.time()
    with Pool(processes=n_workers) as pool:
        results = pool.starmap(_worker, [(i, sh) for i, sh in enumerate(shards, start=1)])

    agg = {"done": 0, "skip_manual": 0, "error": 0, "empty": 0, "total": 0}
    for r in results:
        for k in agg:
            agg[k] += r[k]
    elapsed = time.time() - t0
    logger.success(
        f"완료 — 재적재 {agg['done']:,} · manual제외 {agg['skip_manual']:,} · "
        f"0행(보류) {agg['empty']:,} · 오류 {agg['error']:,} / 전체 {agg['total']:,} "
        f"— {elapsed/60:.1f}분")


if __name__ == "__main__":
    main()
