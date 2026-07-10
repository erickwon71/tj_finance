"""DEF-4 근본수정 재처리 — Q1 Track B(xml_text) 추출버그(fin2/extract/text.py) 수정 후
영향 기업의 fact_v2/std_financials_v2/std_financials_calendar 재생성.

버그: Q1(분기보고서) IS/CF 표의 [당기3개월,당기누적,전기3개월,전기누적] 4열이 num_cols=3
위치기반 절삭으로 [당기3개월,당기누적,전기3개월]로 잘려 전기(col1)에 당기값이 중복되고
전전기(col2)에 실제 전기값이 오라벨링되던 문제(계획서 참고, docs/qa/results/defects/DEF-4.md).

절차(기업 단위 커밋, 중단 시 재개 가능 — fin2_reextract_all.py와 동일 idempotent 패턴):
  1. fact_v2 purge(corp 단위 — 재추출 전 필수, orphan cell 제거)
  2. E→R→S+분기+달력 1패스(run.py.process_corp 재사용)
  3. 비교컬럼 폴백 재실행(standardize_comparative_corp) — 이제 교정된 fact_v2 기준
  4. 분기·달력 재계산(3에서 새로 채워진 std_v2 행 반영, derive_quarters_corp+calendarize_corp)

usage:
  python scripts/def4_reprocess.py --corps-file /tmp/def4_affected_corps.txt \
      --resume-file /tmp/def4_reprocess_done.txt
  python scripts/def4_reprocess.py --corps-file /tmp/def4_affected_corps.txt --limit 20 --dry-run
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
from fin2.standardize.quarterly import derive_quarters_corp
from fin2.standardize.calendar import calendarize_corp
from run import process_corp


def _load_corps(path: str) -> list[str]:
    raw = Path(path).read_text()
    return [c.strip() for c in raw.replace(",", "\n").splitlines() if c.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corps-file", required=True, help="영향 corp_code 목록 파일(줄바꿈 구분)")
    ap.add_argument("--resume-file", help="완료 corp_code 기록 파일(중단 후 재개용)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true", help="purge/재처리 생략, 대상 목록만 출력")
    args = ap.parse_args()

    corps = _load_corps(args.corps_file)
    done: set[str] = set()
    if args.resume_file and Path(args.resume_file).exists():
        done = {ln.strip() for ln in Path(args.resume_file).read_text().splitlines() if ln.strip()}
    corps = [c for c in corps if c not in done]
    if args.limit:
        corps = corps[: args.limit]
    total = len(corps)
    logger.info(f"[def4-reprocess] 대상 corp {total}개"
                + (f" (완료 {len(done)}개 제외)" if done else ""))
    if args.dry_run:
        logger.info(f"[def4-reprocess] dry-run — 실제 처리 없음. 대상 예시: {corps[:5]}")
        return

    agg = {"purged": 0, "e_facts": 0, "s": 0, "comp": 0, "q": 0, "c": 0, "errors": 0}
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as session:
                # 1) fact_v2 purge — orphan cell(옛 mislabel) 제거 필수(계획서 §5-1 참고)
                session.execute(text("DELETE FROM fact_v2 WHERE corp_code=:c"), {"c": corp})
                agg["purged"] += 1
                # 2) E→R→S+분기+달력 1패스(own-report 기준)
                out = process_corp(session, corp, stages=(
                    "extract", "reconcile", "standardize", "quarterly", "calendar"))
                agg["e_facts"] += out["e_facts"]
                agg["s"] += out["s"]
                agg["q"] += out["q"]
                agg["c"] += out["c"]
                # 3) 비교컬럼 폴백 재실행(교정된 fact_v2 기준으로 gap 재합성)
                agg["comp"] += standardize_comparative_corp(session, corp)
                # 4) 3에서 새로 채워진 std_v2 행에 대한 분기·달력 재계산
                derive_quarters_corp(session, corp)
                calendarize_corp(session, corp)
                session.commit()
            if args.resume_file:
                with open(args.resume_file, "a") as f:
                    f.write(corp + "\n")
        except Exception as e:  # noqa: BLE001
            agg["errors"] += 1
            logger.error(f"[def4-reprocess] corp={corp} 실패: {e}")
        if i % 50 == 0 or i == total:
            logger.info(f"[def4-reprocess] 진행 {i}/{total} — "
                        f"fact {agg['e_facts']:,} / std_v2 {agg['s']:,} / "
                        f"comparative {agg['comp']:,} / 오류 {agg['errors']}")

    logger.success(f"[def4-reprocess] 완료 — corp {total}개 처리, purge {agg['purged']}, "
                   f"오류 {agg['errors']}")


if __name__ == "__main__":
    main()
