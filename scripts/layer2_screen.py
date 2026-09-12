#!/usr/bin/env python
"""1단계(2015+) 사전 스크리닝 — 재적재 *전* 우선순위 재편용.

설계: `docs/plans/layer2_review_staged_screening_design_2026-09-11.md`

## 무엇을 하는가
`layer2_review_queue`에 이미 들어있는 pending 대상들에 대해, **재파싱 없이**
현재 DB의 `report_lines`(정기 수집 파이프라인이 이미 채워둔 값) 위에서 저비용
신호 두 가지를 계산해 `screen_severity`/`screen_flags`를 채운다:

  1) 기존 8종 자동검산(`fin2.audit.layer2_selfcheck`, `layer2_review.py next`가
     재적재 시점에 매번 계산하는 바로 그 검산) — 회사 내부 비교(row_count_outlier
     ±50%) 포함.
  2) 전사 로그-IQR — 같은 (statement, 기간유형) 전체 회사 분포에서 벗어난 행수
     (`docs/qa/report_lines_row_count_outlier_scan_2026-09-08.md` 방법론, 2015+
     스코프로 재실측).

이 값은 **검토 순서**(같은 회사 안에서 걸린 건을 안 걸린 건보다 먼저 봄, 사용자
결정 2026-09-11)에만 쓰인다 — 검토 절차(`next`/`pass`/`fail`/`redo`) 자체는
전혀 안 바뀐다.

★한계(설계문서 §5-1 실측): 이 두 기법은 "행수는 정상인데 값이 다른 기간 컬럼과
뒤바뀐" 유형(R85/86/88류)은 원리적으로 못 잡는다. 그 유형은 별도 도구
(`scripts/layer2_period_continuity_check.py`)로 개별 확인한다.

## 사용법
    # 1) 큐를 2015+ 전체 유니버스로 확장(스크리닝 전 1회, 시간 걸림 — 직접 실행 권장)
    python scripts/layer2_review.py init --fiscal-year-min 2015 --top 0

    # 2) 스크리닝(읽기전용 SQL 위주, 그래도 대상 많으면 시간 걸림)
    python scripts/layer2_screen.py scan --fiscal-year-min 2015

    # 부분 실행(검증·재실행용)
    python scripts/layer2_screen.py scan --fiscal-year-min 2015 --corp 00126380
    python scripts/layer2_screen.py report --top 30
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.audit import layer2_selfcheck as sc

_WEIGHT = {sc.GRADE_BLOCKING: 3, sc.GRADE_SUSPECT: 2, sc.GRADE_INFO: 1}
_IQR_WEIGHT = 2
_MIN_BUCKET_SAMPLE = 10   # 이보다 표본 적은 (statement,기간) 버킷은 판정 보류

# ── 전사 로그-IQR 상하한(1회 계산, 스캔 전체에서 재사용) ───────────────────────
_POP_SQL = text(
    """
    SELECT rl.rcept_no, f.fiscal_period, rl.statement, rl.basis, count(*) AS n
    FROM report_lines rl JOIN filings f USING (rcept_no)
    WHERE f.fiscal_year >= :fy_min AND f.report_type IN ('annual','half','quarter')
      AND rl.statement IN ('BS','IS','CF')
    GROUP BY rl.rcept_no, f.fiscal_period, rl.statement, rl.basis
    """
)


def _iqr_bounds(session, fy_min: int) -> dict[tuple[str, str], tuple[float, float]]:
    buckets: dict[tuple[str, str], list[int]] = defaultdict(list)
    for r in session.execute(_POP_SQL, {"fy_min": fy_min}):
        buckets[(r.statement, r.fiscal_period)].append(r.n)

    def pct(logs: list[float], p: float) -> float:
        i = (len(logs) - 1) * p
        lo, hi = int(math.floor(i)), int(math.ceil(i))
        return logs[lo] + (logs[hi] - logs[lo]) * (i - lo)

    bounds = {}
    for k, ns in buckets.items():
        logs = sorted(math.log(n) for n in ns if n > 0)
        if len(logs) < _MIN_BUCKET_SAMPLE:
            continue
        q1, q3 = pct(logs, 0.25), pct(logs, 0.75)
        iqr = q3 - q1
        bounds[k] = (math.exp(q1 - 1.5 * iqr), math.exp(q3 + 1.5 * iqr))
    return bounds


_TARGET_SQL = text(
    """
    SELECT rcept_no, corp_code, fiscal_year, fiscal_period
    FROM layer2_review_queue
    WHERE status = 'pending'
      AND (CAST(:fy_min AS smallint) IS NULL OR fiscal_year >= :fy_min)
      AND (CAST(:corp AS text) IS NULL OR corp_code = :corp)
    ORDER BY corp_rank NULLS LAST, seq_in_corp
    """
)

_CELL_SQL = text(
    """
    SELECT statement, basis, count(*) AS n
    FROM report_lines WHERE rcept_no = :r AND statement IN ('BS','IS','CF')
    GROUP BY 1, 2
    """
)

_UPDATE_SQL = text(
    """
    UPDATE layer2_review_queue
    SET screen_severity = :sev, screen_flags = :flags, screened_at = now()
    WHERE rcept_no = :r
    """
)


def cmd_scan(args) -> None:
    with get_session() as session:
        logger.info(f"전사 로그-IQR 상하한 계산 중(fiscal_year>={args.fiscal_year_min})...")
        bounds = _iqr_bounds(session, args.fiscal_year_min)
        logger.info(f"  버킷 {len(bounds)}개(statement×기간유형) 확정")

        targets = session.execute(_TARGET_SQL, {
            "fy_min": args.fiscal_year_min, "corp": args.corp}).fetchall()
        logger.info(f"스크리닝 대상 {len(targets):,}건(status=pending)")

        n_flagged = 0
        for i, t in enumerate(targets, 1):
            flags: list[dict] = []

            # 1) 기존 8종 자동검산 — `next`가 재적재 시점에 매번 계산하는 것과 동일 함수.
            results = sc.run_checks(
                session, t.rcept_no, corp_code=t.corp_code,
                fiscal_period=t.fiscal_period, fiscal_year=t.fiscal_year)
            for r in sc.suspects(results):
                flags.append({"code": r.code, "grade": r.grade, "scope": r.scope,
                             "message": r.message, "weight": _WEIGHT.get(r.grade, 1)})

            # 2) 전사 로그-IQR — 같은 회사 안 비교가 아니라 전체 회사 분포 기준.
            for cell in session.execute(_CELL_SQL, {"r": t.rcept_no}):
                b = bounds.get((cell.statement, t.fiscal_period))
                if b and not (b[0] <= cell.n <= b[1]):
                    flags.append({
                        "code": "cross_corp_row_count_outlier", "grade": sc.GRADE_SUSPECT,
                        "scope": f"[{cell.basis}] {cell.statement}",
                        "message": f"{cell.n}행 (전사 정상범위 {b[0]:.0f}~{b[1]:.0f})",
                        "weight": _IQR_WEIGHT,
                    })

            severity = sum(f["weight"] for f in flags)
            if severity:
                n_flagged += 1
            session.execute(_UPDATE_SQL, {
                "sev": severity, "flags": json.dumps(flags, ensure_ascii=False), "r": t.rcept_no})

            if i % 500 == 0:
                session.commit()
                logger.info(f"  {i:,}/{len(targets):,} 처리 ({n_flagged:,}건 걸림)")
        session.commit()
    logger.success(f"스크리닝 완료 — {len(targets):,}건 중 {n_flagged:,}건 걸림 "
                   "(`layer2_review.py next`가 이제 걸린 건부터 회사 안에서 먼저 보여줍니다)")


def cmd_report(args) -> None:
    with get_session() as session:
        rows = session.execute(text(
            """
            SELECT rcept_no, corp_name, corp_rank, fiscal_year, fiscal_period,
                   screen_severity, screen_flags
            FROM layer2_review_queue
            WHERE status = 'pending' AND COALESCE(screen_severity, 0) > 0
            ORDER BY screen_severity DESC, corp_rank NULLS LAST
            LIMIT :n
            """), {"n": args.top}).mappings().all()
    if not rows:
        print("걸린 건 없음(스크리닝을 아직 안 돌렸거나, 전부 정상범위).")
        return
    print(f"=== 스크리닝 상위 {len(rows)}건 ===")
    for r in rows:
        print(f"\n[severity={r['screen_severity']}] 시총{r['corp_rank']}위 "
              f"{r['corp_name']} {r['fiscal_year']}{r['fiscal_period']}  r{r['rcept_no']}")
        for f in (r["screen_flags"] or []):
            print(f"    · [{f['grade']}] {f['code']} {f.get('scope','')} — {f['message']}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan", help="pending 대상 스크리닝(screen_severity/flags 채움)")
    p.add_argument("--fiscal-year-min", type=int, default=2015)
    p.add_argument("--corp", help="쉼표 아님 — corp_code 1개만(검증용)")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("report", help="걸린 건 상위 N 출력")
    p.add_argument("--top", type=int, default=30)
    p.set_defaults(func=cmd_report)

    return ap


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
