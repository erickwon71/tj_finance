"""operating_income == net_income 오선택 교정 재표준화 배치.

build._collect 의 교정(순이익과 원단위 정확일치하는 영업이익 후보를 비-순이익 후보로 대체)을
기존 데이터에 적용하려면 영향 기업을 재표준화해야 한다. 영향 기업(FY/Q1 as-reported 에서
operating_income==net_income) 만 대상으로 standardize→quarterly→calendar 재실행(extract/reconcile
불변). 기업 단위 커밋·재개.

usage:
  python scripts/fin2_fix_op_eq_ni.py [--resume-file /tmp/fix_opni.txt] [--limit N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from run import process_corp

_AFFECTED_SQL = """
    SELECT DISTINCT corp_code FROM std_financials_v2
    WHERE version=1 AND NOT COALESCE(is_stub,false) AND NOT COALESCE(is_discrete,false)
      AND fiscal_period IN ('FY','Q1')
      AND operating_income IS NOT NULL AND operating_income = net_income
    ORDER BY corp_code
"""


def _op_eq_ni_rows(session) -> int:
    return session.execute(text(
        "SELECT count(*) FROM std_financials_v2 WHERE version=1 "
        "AND NOT COALESCE(is_stub,false) AND NOT COALESCE(is_discrete,false) "
        "AND fiscal_period IN ('FY','Q1') AND operating_income IS NOT NULL "
        "AND operating_income = net_income")).scalar() or 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume-file", default="/tmp/fix_opni.txt")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    with get_session() as s:
        corps = [r[0] for r in s.execute(text(_AFFECTED_SQL)).fetchall()]
        before = _op_eq_ni_rows(s)
    logger.info(f"[fix-opni] 영향 기업 {len(corps)} · op==ni 행(시작) {before:,}")

    done: set[str] = set()
    rf = Path(args.resume_file)
    if rf.exists():
        done = {ln.strip() for ln in rf.read_text().splitlines() if ln.strip()}
    corps = [c for c in corps if c not in done]
    if args.limit:
        corps = corps[: args.limit]

    agg = {"s": 0, "q": 0, "c": 0, "err": 0}
    total = len(corps)
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as s:
                out = process_corp(s, corp, stages=("standardize", "quarterly", "calendar"))
                s.commit()
            for k in ("s", "q", "c"):
                agg[k] += out[k]
            with open(rf, "a") as fh:
                fh.write(corp + "\n")
        except Exception as e:  # noqa: BLE001
            agg["err"] += 1
            logger.error(f"[fix-opni] corp={corp} 실패: {type(e).__name__}: {e}")
        if i % 50 == 0 or i == total:
            logger.info(f"  ..{i}/{total} (std {agg['s']:,} 오류 {agg['err']})")

    with get_session() as s:
        after = _op_eq_ni_rows(s)
    logger.success(f"[fix-opni] 완료 — 재표준화 {total - agg['err']}/{total} · "
                   f"op==ni 행 {before:,} → {after:,} (−{before - after:,}) · 오류 {agg['err']}")


if __name__ == "__main__":
    main()
