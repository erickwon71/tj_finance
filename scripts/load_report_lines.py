"""계층2 전량적재 — 2015+ 원본 XML → report_lines (+ 이상치 표시).

4계층 재설계 §진행순서 1차 패스(`docs/plans/rearchitecture_4layer_2026-07-19.md`).
파일럿(`run.py extract-lines`, --corp 필수)을 전량 실행 경로로 확장한 것:
샤딩 · 재개 · rcept 단위 원자성 · 진행 체크포인트.

## 설계
- **재개**: `report_line_load_progress` 에 rcept 단위로 처리 사실을 남긴다. report_lines 행
  유무로 판단하면 '추출 0행(보류)' 보고서가 매번 재처리된다.
- **원자성**: report_lines / anomalies 모두 rcept 단위 delete-then-insert. 배치 단위 commit
  이라 중단 시 마지막 배치만 되돌아간다(체크포인트도 같은 트랜잭션이므로 어긋나지 않는다).
- **샤딩**: `--shard a/n` 은 rcept_no 해시가 아니라 **정렬 후 i%n** — 대상 집합이 고정이라
  재현 가능하고, 샤드 간 겹침이 없다.
- **주석 제외**: include_notes=False(계획상 1차는 본문). 주석은 볼륨 5배(~150GB)로
  현재 DB 디스크(내장 SSD 여유 87GB)에 들어가지 않는다 — 별도 단계.

## 실측 근거 (착수 전, FY+interim 120건 표본)
  건당 0.085s · 건당 605행 → 전량 102,633건 ≈ 62M행 · 단일 프로세스 2.4시간
  489 바이트/행 → 약 30GB (여유 87GB 내)

사용:
    python scripts/load_report_lines.py --shard 0/4          # 4분할 중 0번
    python scripts/load_report_lines.py --limit 100          # 소량 시험
    python scripts/load_report_lines.py --status             # 진행 현황만 출력
    python scripts/load_report_lines.py --recheck            # done 도 재처리
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.models import ReportLineLoadProgress
from fin2.extract.report_lines import (extract_report_lines, store_report_lines,
                                        store_note_lines, store_report_tables)
from fin2.audit.line_anomaly import detect_anomalies, store_anomalies

FY_MIN = 2015
BATCH = 200          # 커밋 주기(보고서 수)


def _targets(session, args) -> list:
    sql = f"""
        SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
        FROM download_tasks dt JOIN filings f USING(rcept_no)
        WHERE dt.status='completed' AND dt.file_type='xml' AND dt.file_path IS NOT NULL
          AND f.fiscal_year >= {FY_MIN}
        ORDER BY dt.rcept_no
    """
    rows = session.execute(text(sql)).fetchall()
    if getattr(args, "corp", None):
        # 전량 백필 전에 소수 기업으로 end-to-end 확인하기 위한 필터
        # (예: 주석 section_path 헤딩 복원 검증).
        wanted = {c.strip() for c in args.corp.split(",") if c.strip()}
        rows = [r for r in rows if r.corp_code in wanted]
    if args.shard:
        a, n = (int(x) for x in args.shard.split("/"))
        rows = [r for i, r in enumerate(rows) if i % n == a]
    if getattr(args, "redo_empty", False):
        # 제목표/데이터표 분리 서식 수정(2026-07-23) 소급 백필 전용: done 인데 0행인 filing 만
        # 재처리한다(--recheck 는 전량 102k 재처리라 과함). store 는 delete-then-insert 라 멱등.
        empty = {r[0] for r in session.execute(text(
            "SELECT rcept_no FROM report_line_load_progress "
            "WHERE status='done' AND COALESCE(n_lines,0)=0"
        )).fetchall()}
        rows = [r for r in rows if r.rcept_no in empty]
        if args.limit:
            rows = rows[: args.limit]
        return rows
    if not args.recheck:
        if getattr(args, "notes", False):
            # 주석 패스 재개: 이미 note_lines 에 적재된 rcept 은 건너뛴다(본문 progress 와 독립 —
            # note_lines 자체를 done 신호로 사용). --recheck 면 전량 재적재(delete-then-insert 멱등).
            done = {r[0] for r in session.execute(text(
                "SELECT DISTINCT rcept_no FROM note_lines")).fetchall()}
        else:
            done = {r[0] for r in session.execute(text(
                "SELECT rcept_no FROM report_line_load_progress WHERE status IN ('done','skip')"
            )).fetchall()}
        rows = [r for r in rows if r.rcept_no not in done]
    if args.limit:
        rows = rows[: args.limit]
    return rows


def _print_status(session) -> None:
    tot = session.execute(text(f"""
        SELECT count(*) FROM download_tasks dt JOIN filings f USING(rcept_no)
        WHERE dt.status='completed' AND dt.file_type='xml' AND dt.file_path IS NOT NULL
          AND f.fiscal_year >= {FY_MIN}""")).scalar()
    rows = session.execute(text(
        "SELECT status, count(*), sum(n_lines) FROM report_line_load_progress GROUP BY status"
    )).fetchall()
    done = sum(c for s, c, _ in rows)
    print(f"\n=== 계층2 전량적재 진행 ===")
    print(f"  대상(2015+ XML)  {tot:,}")
    for s, c, l in sorted(rows):
        print(f"    {s:6s} {c:8,}  행 {(l or 0):,}")
    print(f"  진행률           {100*done/max(tot,1):.1f}%  ({done:,}/{tot:,})")
    n_lines = session.execute(text("SELECT count(*) FROM report_lines")).scalar()
    n_anom = session.execute(text("SELECT count(*) FROM report_line_anomalies")).scalar()
    size = session.execute(text(
        "SELECT pg_size_pretty(pg_total_relation_size('report_lines'))")).scalar()
    print(f"  report_lines     {n_lines:,} 행 ({size})")
    print(f"  이상치 표시      {n_anom:,} 건")


def _self_disable_if_done(label: str = "com.tjfinance.layer2load") -> None:
    """launchd 연속잡: 남은 대상이 0 이면 잡 unload + plist 삭제(gapfill·phasec 선례)."""
    import subprocess
    with get_session() as s:
        remaining = s.execute(text(f"""
            SELECT count(*) FROM download_tasks dt JOIN filings f USING(rcept_no)
            WHERE dt.status='completed' AND dt.file_type='xml' AND dt.file_path IS NOT NULL
              AND f.fiscal_year >= {FY_MIN}
              AND dt.rcept_no NOT IN (SELECT rcept_no FROM report_line_load_progress
                                      WHERE status IN ('done','skip'))""")).scalar() or 0
    if remaining:
        logger.info(f"[load-lines] 남은 대상 {remaining:,}건 — 잡 유지(다음 실행에서 계속).")
        return
    plist = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
    logger.success(f"[load-lines] 남은 대상 0 — 잡 자기해제({label}) 후 plist 삭제.")
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], check=False)
    subprocess.run(["launchctl", "unload", str(plist)], check=False)
    plist.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", help="a/n 분할(정렬 후 i %% n == a)")
    ap.add_argument("--corp", help="쉼표구분 corp_code 만 처리(전량 백필 전 표적 검증용)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--recheck", action="store_true", help="done 도 재처리")
    ap.add_argument("--notes", action="store_true",
                    help="주석 전용 패스 — note_lines 에만 적재(본문 report_lines 무변경). "
                         "재개는 note_lines 존재로 자체 추적. 볼륨 큼(~303M행)")
    ap.add_argument("--redo-empty", action="store_true",
                    help="done 인데 0행인 filing 만 재처리(제목표/데이터표 분리 수정 소급 백필)")
    ap.add_argument("--status", action="store_true", help="진행 현황만 출력")
    ap.add_argument("--managed", action="store_true",
                    help="launchd 연속잡 모드 — 완주 후 남은 대상 0 이면 스스로 잡 해제")
    args = ap.parse_args()

    with get_session() as s:
        if args.status:
            _print_status(s)
            return
        targets = _targets(s, args)

    tag = f"shard {args.shard}" if args.shard else "all"
    if not targets:
        logger.success(f"[load-lines {tag}] 남은 대상 없음 — 완료")
        if args.managed:
            _self_disable_if_done()
        return
    logger.info(f"[load-lines {tag}] 대상 {len(targets):,}건 시작 (pid {os.getpid()})")

    t0 = time.time()
    n_done = n_skip = n_err = 0
    n_lines = n_anom = 0

    with get_session() as session:
        for i, r in enumerate(targets, 1):
            status, msg, nl, na = "done", None, 0, 0
            if not Path(r.file_path).exists():
                status, msg = "skip", "file missing"
            else:
                try:
                    lines = extract_report_lines(
                        r.file_path, rcept_no=r.rcept_no, corp_code=r.corp_code,
                        report_fiscal_year=r.fiscal_year,
                        report_fiscal_period=r.fiscal_period,
                        include_notes=args.notes,
                    )
                    if args.notes:
                        # 주석 전용 패스: note_lines 만 적재(본문 report_lines 는 이미 로드됨 — 재기록 안 함).
                        nl = store_note_lines(session, r.rcept_no, lines)
                        # ★표 메타(F3)는 주석 패스에서 적는다 — 주석이 표 수의 대부분이고,
                        #   본문 패스가 먼저 돌아 같은 rcept 를 이미 지웠다 해도 여기서 다시
                        #   전체(본문+주석)를 써 넣으므로 결과가 온전하다.
                        store_report_tables(session, r.rcept_no, lines)
                    else:
                        nl = store_report_lines(session, r.rcept_no, lines)
                        store_report_tables(session, r.rcept_no, lines)
                        found = detect_anomalies(lines, rcept_no=r.rcept_no, corp_code=r.corp_code,
                                                 report_fiscal_period=r.fiscal_period)
                        na = store_anomalies(session, r.rcept_no, found)
                except Exception as e:                      # noqa: BLE001 — 한 건 실패가 전량을 멈추면 안 됨
                    status, msg = "error", f"{type(e).__name__}: {e}"[:500]

            if not args.notes:
                # 본문 패스만 progress 테이블에 기록. 주석 패스는 note_lines 존재로 자체 추적하므로
                # 본문 progress 를 덮지 않는다(_targets 의 done 필터 참고).
                session.merge(ReportLineLoadProgress(
                    rcept_no=r.rcept_no, corp_code=r.corp_code, fiscal_year=r.fiscal_year,
                    status=status, n_lines=nl, n_anomalies=na, message=msg,
                    processed_at=datetime.utcnow()))

            if status == "done":
                n_done += 1; n_lines += nl; n_anom += na
            elif status == "skip":
                n_skip += 1
            else:
                n_err += 1
                logger.warning(f"  r{r.rcept_no}: {msg}")

            if i % BATCH == 0:
                session.commit()
                el = time.time() - t0
                rate = i / el
                eta = (len(targets) - i) / rate / 3600
                logger.info(f"  [{tag}] {i:,}/{len(targets):,} "
                            f"({100*i/len(targets):.1f}%) · {rate:.1f}건/s · ETA {eta:.1f}h · "
                            f"행 {n_lines:,} · 이상치 {n_anom:,} · err {n_err}")
        session.commit()

    el = time.time() - t0
    logger.success(
        f"[load-lines {tag}] 완료 {el/3600:.2f}h — done {n_done:,} / skip {n_skip:,} / "
        f"error {n_err:,} · report_lines {n_lines:,}행 · 이상치 {n_anom:,}건")

    if args.managed:
        _self_disable_if_done()


if __name__ == "__main__":
    main()
