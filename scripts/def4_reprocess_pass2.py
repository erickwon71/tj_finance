"""DEF-4 재처리 pass 2 — stale comparative_fallback 행 교정.

pass 1(def4_reprocess.py)은 fact_v2 를 purge·재추출해 own-report 행은 교정했으나,
standardize_comparative_corp 이 '기존 std_v2 키는 불가침'(build.py:279,303)이라 예전
버그값으로 만들어진 comparative_fallback 파생행(예: 2012 Q1 = 2013 report col1 오값)을
덮어쓰지 못하고 스킵했다 → 인접연도 CQ1 중복이 그대로 남음.

더 큰 함정: comparative_fallback 로 만들어진 (own report 없는) 누적행을 지워도, 그로부터
derive_quarters 가 만든 is_discrete=True(quarterly_derived) 이산행이 남아 stale 값을 유지한다.
게다가 standardize_comparative_corp 의 `own` 집합은 comparative_fallback 이 아닌 모든
version=1 행(quarterly_derived 이산행 포함)을 own 으로 간주해(build.py:370-376) 재합성을
스킵한다 → 이산행이 존재하는 한 2012 등은 영원히 교정 안 됨.

pass 2: 영향 corp 의 (a) comparative_fallback 누적행 + (b) is_discrete=True 이산행을 모두
DELETE(own 누적행·kgaap 갭행은 보존) 한 뒤, 교정된 fact_v2 기준으로 comparative fallback 을
재합성 → 분기 재파생 → 달력 재계산. fact_v2 재추출은 불필요(빠름·pass1 에서 이미 교정됨).

usage:
  python scripts/def4_reprocess_pass2.py --corps-file /tmp/def4_affected_corps.txt \
      --resume-file /tmp/def4_pass2_done.txt
  python scripts/def4_reprocess_pass2.py --corps 00445841,00288343   # 특정 corp 만
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

_COMP_MARKER = '["comparative_fallback"]'


def _load(path_or_list: str) -> list[str]:
    if Path(path_or_list).exists():
        raw = Path(path_or_list).read_text()
    else:
        raw = path_or_list
    return [c.strip() for c in raw.replace(",", "\n").splitlines() if c.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--corps-file")
    g.add_argument("--corps")
    ap.add_argument("--resume-file")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    corps = _load(args.corps_file or args.corps)
    done: set[str] = set()
    if args.resume_file and Path(args.resume_file).exists():
        done = {ln.strip() for ln in Path(args.resume_file).read_text().splitlines() if ln.strip()}
    corps = [c for c in corps if c not in done]
    if args.limit:
        corps = corps[: args.limit]
    total = len(corps)
    logger.info(f"[def4-pass2] 대상 corp {total}개" + (f" (완료 {len(done)}개 제외)" if done else ""))

    agg = {"deleted": 0, "comp": 0, "errors": 0}
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as session:
                # 1) stale 파생행 삭제 — comparative_fallback 누적행 + 모든 이산행(quarterly_derived).
                #    own 누적행·kgaap 갭행은 보존(재추출 불필요, 값 정상).
                res = session.execute(text(
                    "DELETE FROM std_financials_v2 "
                    "WHERE corp_code=:c AND version=1 "
                    "  AND (applied_rules @> CAST(:m AS jsonb) OR is_discrete=true)"),
                    {"c": corp, "m": _COMP_MARKER})
                agg["deleted"] += res.rowcount or 0
                # 2) 교정된 fact_v2 기준 comparative fallback 재합성
                agg["comp"] += standardize_comparative_corp(session, corp)
                # 3) 분기·달력 재계산
                derive_quarters_corp(session, corp)
                calendarize_corp(session, corp)
                session.commit()
            if args.resume_file:
                with open(args.resume_file, "a") as f:
                    f.write(corp + "\n")
        except Exception as e:  # noqa: BLE001
            agg["errors"] += 1
            logger.error(f"[def4-pass2] corp={corp} 실패: {e}")
        if i % 100 == 0 or i == total:
            logger.info(f"[def4-pass2] 진행 {i}/{total} — "
                        f"삭제 {agg['deleted']:,} / 재합성 {agg['comp']:,} / 오류 {agg['errors']}")

    logger.success(f"[def4-pass2] 완료 — corp {total}개, comparative 삭제 {agg['deleted']:,} "
                   f"/ 재합성 {agg['comp']:,} / 오류 {agg['errors']}")


if __name__ == "__main__":
    main()
