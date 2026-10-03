"""controlling_ni 교정 — 별도재무제표 지배순이익≡당기순이익 강제 재표준화 배치.

rule_controlling_ni_fill 확장(별도는 net 과 다르면 강제)을 소급 적용한다. 별도행에서
controlling_ni 가 net_income 과 어긋난 기업만 대상으로 standardize→comparative→quarterly→
calendar 재실행(재추출 불필요 — fact_v2 불변, 규칙만 재적용). 기업 단위 커밋·재개.

usage:
  python scripts/fin2_fix_controlling_ni_separate.py [--resume-file /tmp/fix_ctrlni_sep.txt] [--limit N]
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
from fin2.standardize.build import standardize_comparative_corp

_SEP_VIOL = (
    "version=1 AND statement_type='separate' AND NOT COALESCE(is_stub,false) "
    "AND NOT COALESCE(is_discrete,false) AND controlling_ni IS NOT NULL "
    "AND net_income IS NOT NULL AND net_income<>0 "
    "AND ABS(controlling_ni - net_income) > ABS(net_income)*0.02 + 1000000"
)
_AFFECTED_SQL = f"SELECT DISTINCT corp_code FROM std_financials_v2 WHERE {_SEP_VIOL} ORDER BY corp_code"


def _viol_rows(session) -> int:
    return session.execute(text(f"SELECT count(*) FROM std_financials_v2 WHERE {_SEP_VIOL}")).scalar() or 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume-file", default="/tmp/fix_ctrlni_sep.txt")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    with get_session() as s:
        corps = [r[0] for r in s.execute(text(_AFFECTED_SQL)).fetchall()]
        before = _viol_rows(s)
    logger.info(f"[fix-ctrlni-sep] 영향 기업 {len(corps)} · 별도 위반 행(시작) {before:,}")

    done: set[str] = set()
    rf = Path(args.resume_file)
    if rf.exists():
        done = {ln.strip() for ln in rf.read_text().splitlines() if ln.strip()}
    corps = [c for c in corps if c not in done]
    if args.limit:
        corps = corps[: args.limit]

    err = 0
    total = len(corps)
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as s:
                process_corp(s, corp, stages=("standardize",))
                standardize_comparative_corp(s, corp)
                process_corp(s, corp, stages=("quarterly", "calendar"))
                s.commit()
            with open(rf, "a") as fh:
                fh.write(corp + "\n")
        except Exception as e:  # noqa: BLE001
            err += 1
            logger.error(f"[fix-ctrlni-sep] corp={corp} 실패(롤백): {type(e).__name__}: {e}")
        if i % 25 == 0 or i == total:
            logger.info(f"  ..{i}/{total} (오류 {err})")

    with get_session() as s:
        after = _viol_rows(s)
    logger.success(f"[fix-ctrlni-sep] 완료 — 재표준화 {total - err}/{total} · "
                   f"별도 위반 행 {before:,} → {after:,} (−{before - after:,}) · 오류 {err}")


if __name__ == "__main__":
    main()
