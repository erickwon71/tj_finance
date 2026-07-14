"""controlling_ni 총포괄 오염 교정 — 비교컬럼(comparative_fallback) 경로 배치.

`fin2_fix_controlling_ni.py`(자기보고서 경로, build._collect)의 자매 배치. 비교컬럼 폴백으로
합성된 std_v2 행은 `_collect_comparative`의 max-abs가 총포괄분을 오선택했는데, 여기에는
`_collect`가 받은 항등식 재선택 교정이 없었다(2026-07-15 추가). 그 교정을 소급 적용한다.

영향 기업(comparative_fallback 행 중 |controlling_ni|>|net_income|*1.02 위반)만 대상으로
standardize_comparative_corp 재실행(재실행은 controlling_ni 만 변경 — 블라스트 반경 검증됨).
기업 단위 커밋·재개. 후보가 하나뿐인 셀은 무변경(정당/재추출대상 B2).

usage:
  python scripts/fin2_fix_controlling_ni_comparative.py [--resume-file /tmp/fix_ctrlni_comp.txt] [--limit N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.standardize.build import standardize_comparative_corp

# 비교컬럼 파생행의 총포괄 오염 프록시(자매 배치와 동일 임계).
_COMP_VIOL = (
    "version=1 AND applied_rules @> '[\"comparative_fallback\"]' "
    "AND NOT COALESCE(is_stub,false) AND NOT COALESCE(is_discrete,false) "
    "AND net_income IS NOT NULL AND controlling_ni IS NOT NULL AND net_income <> 0 "
    "AND ABS(controlling_ni) > ABS(net_income) * 1.02"
)
_AFFECTED_SQL = f"SELECT DISTINCT corp_code FROM std_financials_v2 WHERE {_COMP_VIOL} ORDER BY corp_code"


def _violation_rows(session) -> int:
    return session.execute(text(
        f"SELECT count(*) FROM std_financials_v2 WHERE {_COMP_VIOL}")).scalar() or 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume-file", default="/tmp/fix_ctrlni_comp.txt")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    with get_session() as s:
        corps = [r[0] for r in s.execute(text(_AFFECTED_SQL)).fetchall()]
        before = _violation_rows(s)
    logger.info(f"[fix-ctrlni-comp] 영향 기업 {len(corps)} · 비교컬럼 위반 행(시작) {before:,}")

    done: set[str] = set()
    rf = Path(args.resume_file)
    if rf.exists():
        done = {ln.strip() for ln in rf.read_text().splitlines() if ln.strip()}
    corps = [c for c in corps if c not in done]
    if args.limit:
        corps = corps[: args.limit]

    n_written = err = 0
    total = len(corps)
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as s:
                n_written += standardize_comparative_corp(s, corp)
                s.commit()
            with open(rf, "a") as fh:
                fh.write(corp + "\n")
        except Exception as e:  # noqa: BLE001
            err += 1
            logger.error(f"[fix-ctrlni-comp] corp={corp} 실패: {type(e).__name__}: {e}")
        if i % 50 == 0 or i == total:
            logger.info(f"  ..{i}/{total} (재작성 {n_written:,} 오류 {err})")

    with get_session() as s:
        after = _violation_rows(s)
    logger.success(f"[fix-ctrlni-comp] 완료 — 재처리 {total - err}/{total} · "
                   f"비교컬럼 위반 행 {before:,} → {after:,} (−{before - after:,}) · 오류 {err}")


if __name__ == "__main__":
    main()
