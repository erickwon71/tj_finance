"""controlling_ni 총포괄 오염 교정 — 재추출(Track B 텍스트) 배치 [P3].

`_collect`/`_collect_comparative` 의 재선택은 fact_v2 에 '지배주주 귀속 당기순이익' 후보가
존재할 때만 교정할 수 있다. 그러나 단일 결합 포괄손익계산서에서 '총포괄손익 귀속' 소항목이
'귀속' 키워드 없이 번호형('1.지배기업소유주지분')으로만 나오면, 추출 dedup(max-abs)이
총포괄 귀속값(더 큼)을 채택해 '당기순이익 귀속' 정답값을 파괴 → fact_v2 에 후보가 하나뿐이라
재선택 불가(B2). fin2/extract/text.py 를 고쳐(총포괄손익 총계 통과 후 지배/비지배 귀속 제외)
정답값을 살렸으므로, 이를 소급 재추출로 적용한다.

영향 기업(항등식 재구성 실패 = refined WARN 대상, docs/qa/triage_controlling_ni_residual_*)만
대상으로 **fact_v2 purge → 재추출 → reconcile → standardize(+comparative) → quarterly → calendar**
를 기업 단위로 재실행한다. 재추출은 controlling_ni/noncontrolling_ni fact 만 변경(블라스트 반경
검증됨). 기업 단위 커밋·재개(중단 시 안전). 실패 corp 는 롤백(기존 fact 보존)+스킵.

usage:
  python scripts/fin2_fix_controlling_ni_reextract.py [--resume-file /tmp/fix_ctrlni_reextract.txt]
      [--limit N] [--corps-file PATH]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from run import _extract2_corp, process_corp
from fin2.standardize.build import standardize_comparative_corp

# 항등식 재구성 실패(진짜 총포괄 오염) — refined WARN 과 동일 판별식.
_GENUINE = (
    "s.version=1 AND NOT COALESCE(s.is_stub,false) AND NOT COALESCE(s.is_discrete,false) "
    "AND s.net_income IS NOT NULL AND s.controlling_ni IS NOT NULL AND s.net_income<>0 "
    "AND ABS(s.controlling_ni) > ABS(s.net_income)*1.02 "
    "AND ABS(s.net_income - s.controlling_ni) > ABS(s.net_income)*0.02 + 1000000 "
    "AND NOT EXISTS (SELECT 1 FROM fact_v2 f WHERE f.rcept_no IN (s.bs_rcept,s.is_rcept,s.cf_rcept) "
    "  AND f.basis=s.statement_type AND f.col_index=0 AND NOT f.is_dimensional "
    "  AND f.canonical_account='is.noncontrolling_ni' AND f.amount_won IS NOT NULL "
    "  AND ABS(f.amount_won-(s.net_income-s.controlling_ni))<=ABS(s.net_income)*0.02+1000000)"
)
_AFFECTED_SQL = f"SELECT DISTINCT s.corp_code FROM std_financials_v2 s WHERE {_GENUINE} ORDER BY s.corp_code"
_COUNT_SQL = f"SELECT count(*) FROM std_financials_v2 s WHERE {_GENUINE}"


def _process_one(session, corp: str) -> None:
    """한 기업 재추출→재표준화. 예외는 상위에서 잡아 롤백."""
    session.execute(text("DELETE FROM fact_v2 WHERE corp_code=:c"), {"c": corp})
    _extract2_corp(session, corp, dry_run=False, verbose=False)
    # 재추출 후: reconcile→standardize(자기보고서) → comparative(비교컬럼 파생) → quarterly/calendar
    # (quarterly/calendar 는 own+comparative std 를 모두 반영해야 하므로 마지막에 한 번만).
    process_corp(session, corp, stages=("reconcile", "standardize"))
    standardize_comparative_corp(session, corp)
    process_corp(session, corp, stages=("quarterly", "calendar"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume-file", default="/tmp/fix_ctrlni_reextract.txt")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--corps-file", help="개행구분 corp_code 목록(검증배치용). 없으면 전수 자동선정.")
    args = ap.parse_args()

    if args.corps_file:
        corps = [ln.strip() for ln in Path(args.corps_file).read_text().splitlines() if ln.strip()]
    else:
        with get_session() as s:
            corps = [r[0] for r in s.execute(text(_AFFECTED_SQL)).fetchall()]
    with get_session() as s:
        before = s.execute(text(_COUNT_SQL)).scalar() or 0
    logger.info(f"[fix-ctrlni-reextract] 영향 기업 {len(corps)} · 진짜 오염 행(시작) {before:,}")

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
                _process_one(s, corp)
                s.commit()
            with open(rf, "a") as fh:
                fh.write(corp + "\n")
        except Exception as e:  # noqa: BLE001
            err += 1
            logger.error(f"[fix-ctrlni-reextract] corp={corp} 실패(롤백): {type(e).__name__}: {e}")
        if i % 25 == 0 or i == total:
            logger.info(f"  ..{i}/{total} (오류 {err})")

    with get_session() as s:
        after = s.execute(text(_COUNT_SQL)).scalar() or 0
    logger.success(f"[fix-ctrlni-reextract] 완료 — 재처리 {total - err}/{total} · "
                   f"진짜 오염 행 {before:,} → {after:,} (−{before - after:,}) · 오류 {err}")


if __name__ == "__main__":
    main()
