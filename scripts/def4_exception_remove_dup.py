"""DEF-4 예외처리 — Q1 보고서 내 col0==col1 위조 중복 제거(구조무관 안전제거).

DEF-4 메인 수정(fin2/extract/text.py Q1 interim_flow) 후에도 남은 잔여 인접연도 CQ1 중복은
구 K-GAAP 교차빈셀·요약표 red herring 등 원천 표 구조가 제각각이라 메인 파이프라인으로는
못 잡힌다. 그러나 모든 잔여의 공통 시그니처는 **한 보고서(rcept)·한 basis 안에서 당기(col0)와
전기(col1)의 금액이 소수점까지 동일** — 분기보고서에서 이는 사실상 항상 추출 버그(실제 우연
아님)다. 사용자 결정: 원값 복구가 아니라 **안전 제거**(위조 중복을 걷어내 "데이터 없음"으로).

동작:
  1) 탐지: Q1 보고서 중 is.revenue col0==col1(≠0)인 (rcept, basis) 후보(self-validating).
  2) 덤프: 삭제 대상 fact_v2 행 전체를 CSV로(가역성).
  3) 삭제: 후보 (rcept,basis)의 flow 계정(is.%/cf.%) col_index>=1 행 삭제(당기 col0만 보존).
  4) 영향 corp 목록 출력 → 이후 `def4_reprocess_pass2.py --corps-file` 로 재파생.

메인 추출 코드는 건드리지 않음(2015+ 정상경로 회귀 위험 0).

usage:
  python scripts/def4_exception_remove_dup.py --dry-run          # 규모만 출력, DB 미변경
  python scripts/def4_exception_remove_dup.py \
      --dump-file docs/qa/results/def4_exception_deleted_facts.csv \
      --corps-out /tmp/def4_exception_corps.txt
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session

# Q1 보고서에서 한 보고서·basis 내 당기(col0)==전기(col1) is.revenue(≠0) → 버그 보고서.
# (다른 rcept 간 우연 동일값은 자연히 제외 — 한 rcept 내부만 조인)
_CANDIDATES_SQL = """
SELECT DISTINCT a.rcept_no, a.basis, a.corp_code
FROM fact_v2 a
JOIN fact_v2 b
  ON a.rcept_no = b.rcept_no AND a.basis = b.basis
 AND a.canonical_account = b.canonical_account
 AND a.col_index = 0 AND b.col_index = 1
WHERE a.report_fiscal_period = 'Q1' AND NOT a.is_dimensional
  AND a.canonical_account = 'is.revenue'
  AND a.amount_won = b.amount_won AND a.amount_won <> 0
ORDER BY a.corp_code, a.rcept_no, a.basis
"""

# 후보 (rcept,basis)에서 삭제할 대상 = flow 계정(is.%/cf.%)의 전기·전전기(col_index>=1).
# 당기(col0)는 신뢰 가능하므로 보존.
_DELETE_TARGET_PRED = (
    "rcept_no = :r AND basis = :b AND col_index >= 1 "
    "AND (canonical_account LIKE 'is.%' OR canonical_account LIKE 'cf.%')"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="규모만 출력, DB 미변경")
    ap.add_argument("--dump-file", default="docs/qa/results/def4_exception_deleted_facts.csv",
                    help="삭제 전 대상 행 CSV 덤프 경로(가역성)")
    ap.add_argument("--corps-out", default="/tmp/def4_exception_corps.txt",
                    help="영향 corp_code 목록 출력 경로(pass2 입력)")
    args = ap.parse_args()

    with get_session() as session:
        logger.info("[exc] 후보 탐지 중(fact_v2 셀프조인 — 수 분 소요)…")
        cands = session.execute(text(_CANDIDATES_SQL)).fetchall()
    rcept_basis = [(r.rcept_no, r.basis) for r in cands]
    corps = sorted({r.corp_code for r in cands})
    logger.info(f"[exc] 버그 후보 (rcept,basis) {len(rcept_basis):,}개 · 영향 corp {len(corps):,}개")

    if not rcept_basis:
        logger.success("[exc] 대상 없음 — 종료")
        return

    # 삭제 대상 행 수 집계 + (실행 시) CSV 덤프
    dump_rows: list[dict] = []
    total_del = 0
    with get_session() as session:
        cols = [c[0] for c in session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='fact_v2' ORDER BY ordinal_position")).fetchall()]
        for rcept, basis in rcept_basis:
            rows = session.execute(text(
                f"SELECT {', '.join(cols)} FROM fact_v2 WHERE {_DELETE_TARGET_PRED}"),
                {"r": rcept, "b": basis}).fetchall()
            total_del += len(rows)
            if not args.dry_run:
                dump_rows.extend(dict(zip(cols, row)) for row in rows)

    logger.info(f"[exc] 삭제 예정 fact_v2 행 {total_del:,}개(당기 col0 보존, flow col>=1만)")

    if args.dry_run:
        logger.success(f"[exc] dry-run — 미변경. 후보 {len(rcept_basis):,}(rcept,basis) / "
                       f"삭제예정 {total_del:,}행 / 영향 corp {len(corps):,}")
        return

    # 가역성: 삭제 대상 CSV 덤프
    dump_path = Path(args.dump_file)
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    with dump_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for d in dump_rows:
            w.writerow(d)
    logger.info(f"[exc] 삭제 대상 {len(dump_rows):,}행 덤프 저장: {dump_path}")

    # 삭제 실행(보고서 단위 커밋)
    deleted = 0
    for i, (rcept, basis) in enumerate(rcept_basis, 1):
        with get_session() as session:
            res = session.execute(text(f"DELETE FROM fact_v2 WHERE {_DELETE_TARGET_PRED}"),
                                  {"r": rcept, "b": basis})
            deleted += res.rowcount or 0
            session.commit()
        if i % 100 == 0 or i == len(rcept_basis):
            logger.info(f"[exc] 삭제 진행 {i}/{len(rcept_basis)} — 누적 {deleted:,}행")

    Path(args.corps_out).write_text("\n".join(corps) + "\n")
    logger.success(f"[exc] 완료 — fact_v2 삭제 {deleted:,}행 · 영향 corp {len(corps):,}개 → "
                   f"{args.corps_out}\n  다음: python scripts/def4_reprocess_pass2.py "
                   f"--corps-file {args.corps_out} --resume-file /tmp/def4_exc_pass2_done.txt")


if __name__ == "__main__":
    main()
