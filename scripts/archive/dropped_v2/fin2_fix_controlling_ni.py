"""controlling_ni 총포괄 오염 교정 재표준화 배치.

build._collect 의 교정(지배주주 귀속 '순이익'과 '총포괄손익'이 텍스트에서 동일 축약 라벨로
나와 둘 다 is.controlling_ni 로 매핑 → max-abs 가 총포괄분을 오선택하던 것을, 항등식
controlling+noncontrolling=net 으로 재선택)을 기존 데이터에 적용한다. 영향 기업(FY 등에서
|controlling_ni| > |net_income|*1.02 = 항등식 위반)만 대상으로 standardize→quarterly→calendar
재실행(extract/reconcile 불변). 기업 단위 커밋·재개.

usage:
  python scripts/fin2_fix_controlling_ni.py [--resume-file /tmp/fix_ctrlni.txt] [--limit N]
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

# 항등식 위반: 지배주주 귀속 순이익이 당기순이익을 유의미하게 초과(총포괄 오염 신호).
# (정당한 비지배 음수 케이스도 일부 포함될 수 있으나, 재선택 로직은 후보가 1개면 무변경이라 안전.)
_VIOLATION_COND = (
    "version=1 AND NOT COALESCE(is_stub,false) AND NOT COALESCE(is_discrete,false) "
    "AND net_income IS NOT NULL AND controlling_ni IS NOT NULL AND net_income <> 0 "
    "AND ABS(controlling_ni) > ABS(net_income) * 1.02"
)
_AFFECTED_SQL = f"SELECT DISTINCT corp_code FROM std_financials_v2 WHERE {_VIOLATION_COND} ORDER BY corp_code"


def _violation_rows(session) -> int:
    return session.execute(text(
        f"SELECT count(*) FROM std_financials_v2 WHERE {_VIOLATION_COND}")).scalar() or 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume-file", default="/tmp/fix_ctrlni.txt")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    with get_session() as s:
        corps = [r[0] for r in s.execute(text(_AFFECTED_SQL)).fetchall()]
        before = _violation_rows(s)
    logger.info(f"[fix-ctrlni] 영향 기업 {len(corps)} · 항등식 위반 행(시작) {before:,}")

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
            logger.error(f"[fix-ctrlni] corp={corp} 실패: {type(e).__name__}: {e}")
        if i % 50 == 0 or i == total:
            logger.info(f"  ..{i}/{total} (std {agg['s']:,} 오류 {agg['err']})")

    with get_session() as s:
        after = _violation_rows(s)
    logger.success(f"[fix-ctrlni] 완료 — 재표준화 {total - agg['err']}/{total} · "
                   f"위반 행 {before:,} → {after:,} (−{before - after:,}) · 오류 {agg['err']}")


if __name__ == "__main__":
    main()
