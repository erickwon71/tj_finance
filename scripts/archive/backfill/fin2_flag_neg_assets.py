"""자산총계<=0 행 DQ3 플래그 재표준화 배치.

validate_equations 에 추가한 '자산총계<=0 → DQ3' 규칙을 기존 데이터에 적용하려면 영향 기업을
재표준화해야 한다. 영향 기업(as-reported total_assets<=0)만 standardize→quarterly→calendar 재실행.

usage:
  python scripts/fin2_flag_neg_assets.py [--resume-file /tmp/flag_neg.txt]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.standardize.build import standardize_corp, standardize_comparative_corp
from fin2.standardize.quarterly import derive_quarters_corp
from fin2.standardize.calendar import calendarize_corp

_AFFECTED = """
    SELECT DISTINCT corp_code FROM std_financials_v2
    WHERE version=1 AND NOT COALESCE(is_stub,false) AND NOT COALESCE(is_discrete,false)
      AND total_assets IS NOT NULL AND total_assets <= 0
    ORDER BY corp_code
"""


def _neg_rows(session) -> int:
    return session.execute(text(
        "SELECT count(*) FROM std_financials_v2 WHERE version=1 AND NOT COALESCE(is_stub,false) "
        "AND NOT COALESCE(is_discrete,false) AND total_assets IS NOT NULL AND total_assets <= 0 "
        "AND COALESCE(data_quality,1) < 3")).scalar() or 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume-file", default="/tmp/flag_neg.txt")
    args = ap.parse_args()

    with get_session() as s:
        corps = [r[0] for r in s.execute(text(_AFFECTED)).fetchall()]
        before = _neg_rows(s)
    logger.info(f"[flag-neg] 영향 기업 {len(corps)} · 자산총계<=0 & DQ<3 (시작) {before:,}")

    done: set[str] = set()
    rf = Path(args.resume_file)
    if rf.exists():
        done = {ln.strip() for ln in rf.read_text().splitlines() if ln.strip()}
    corps = [c for c in corps if c not in done]

    err = 0
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as s:
                # own-report + 비교컬럼 폴백(둘 다 validate_equations 로 DQ 산출) + 하류 재생성
                standardize_corp(s, corp)
                standardize_comparative_corp(s, corp)
                derive_quarters_corp(s, corp)
                calendarize_corp(s, corp)
                s.commit()
            with open(rf, "a") as fh:
                fh.write(corp + "\n")
        except Exception as e:  # noqa: BLE001
            err += 1
            logger.error(f"[flag-neg] corp={corp} 실패: {type(e).__name__}: {e}")
        if i % 50 == 0 or i == len(corps):
            logger.info(f"  ..{i}/{len(corps)} (오류 {err})")

    with get_session() as s:
        after = _neg_rows(s)
    logger.success(f"[flag-neg] 완료 — 재표준화 {len(corps) - err}/{len(corps)} · "
                   f"자산총계<=0 & DQ<3: {before:,} → {after:,} (−{before - after:,}) · 오류 {err}")


if __name__ == "__main__":
    main()
