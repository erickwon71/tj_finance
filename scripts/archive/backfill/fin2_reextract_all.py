"""
표제기반 본문표 식별(commit 69b6125) 전수 반영 — 전 코퍼스 재추출.

배경: 추출기 text.py 가 표제기반 본문표 식별로 바뀌어(1차 승격 + 레거시 갭필 폴백)
복잡문서(분할·기재정정)의 오연결(00259545류 정정/요약표 오추출)을 제거하고 0행 파일
(00111838류)을 복구한다. 이는 **전 Track B 보고서의 추출 결과를 바꾸므로** 전수 재추출이
필요하다. 또한 account_maps 마퍼 수정(commit ac666c9, 세전이익→is.ebt)도 함께 반영된다.

⚠ fact_v2 는 (acode) 키 upsert 라 파서/표 식별 변경 시 옛 cell 이 orphan 으로 남는다
(예: 00259545 가 옛 정정요약표에서 뽑던 175.7B cell). 재추출 전 corp 단위 purge 필수.
statement_source/std_v2 는 키안정 upsert 라 별도 purge 불필요(comparative/kgaap 파생행 보존).

대상: fin2-all 과 동일 모집단(완료 XML 다운로드 보유 전 기업). 기업 단위 purge → E→R→S
(extract2 → reconcile → standardize own-report) 재실행 + 기업 단위 커밋·예외격리·resume.

⚠ 비교컬럼/K-GAAP 폴백은 **별도 후속 패스**(이 스크립트는 own-report 까지만):
    1) python scripts/fin2_reextract_all.py --resume-file /tmp/reextract_all.txt
    2) python scripts/fin2_comparative_financial.py   (또는 fin2_comparative_fallback.py)
    3) python scripts/fin2_kgaap_gap.py
  ⟹ 3패스 순서(standardize → comparative → kgaap)를 지켜야 comparative/kgaap clobber 방지.

⚠ 파일 다수 open(heavy, 수 시간) → 사용자 직접 실행 권장:
    caffeinate -i .venv_tj_finance/bin/python scripts/fin2_reextract_all.py \
        --resume-file /tmp/reextract_all.txt 2>&1 | tee -a /tmp/reextract_all.log

옵션:
    --corps START:END  모집단 슬라이스(병렬 분할/부분 실행)
    --limit N          대상 기업 N개만(시범)
    --dry-run          대상 기업 수만 출력(쓰기 없음)
    --resume-file F    완료 기업 corp_code 누적 기록(중단 시 재개)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.reconcile import reconcile_corp
from fin2.standardize.build import standardize_corp
from run import _extract2_corp  # noqa: E402  per-corp 추출 헬퍼(Track A→B 폴백)

# fin2-all 과 동일 모집단: 완료 XML 다운로드 보유 전 기업.
POPULATION_SQL = """
SELECT DISTINCT f.corp_code
FROM download_tasks dt JOIN filings f ON f.rcept_no = dt.rcept_no
WHERE dt.status='completed' AND dt.file_type='xml' AND dt.file_path IS NOT NULL
ORDER BY f.corp_code
"""


def load_done(resume_file: str | None) -> set[str]:
    if not resume_file:
        return set()
    p = Path(resume_file)
    if not p.exists():
        return set()
    return {ln.strip() for ln in p.read_text().splitlines() if ln.strip()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corps", default=None, help="START:END 슬라이스")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--resume-file", default=None)
    args = ap.parse_args()

    with get_session() as session:
        corps = [r[0] for r in session.execute(text(POPULATION_SQL)).fetchall()]

    if args.corps:
        if ":" in args.corps:
            a, _, b = args.corps.partition(":")
            corps = corps[(int(a) if a else None):(int(b) if b else None)]
        else:
            corps = corps[int(args.corps):int(args.corps) + 1]

    done = load_done(args.resume_file)
    pending = [c for c in corps if c not in done]
    if args.limit:
        pending = pending[:args.limit]

    logger.info(f"[reextract-all] 모집단 {len(corps)} / 완료제외 {len(done)} → 대상 {len(pending)}")
    if args.dry_run:
        for c in pending[:40]:
            print(f"  {c}")
        if len(pending) > 40:
            print(f"  ... (+{len(pending) - 40})")
        return

    agg = {"e_files": 0, "e_facts": 0, "track_b": 0, "r": 0, "s": 0, "err": 0}
    total = len(pending)
    for i, corp in enumerate(pending, 1):
        try:
            with get_session() as session:
                # ⚠ 재추출 전 corp 단위 purge(orphan cell 제거). 표 식별 변경으로 옛 cell 무효화.
                session.execute(text("DELETE FROM fact_v2 WHERE corp_code=:c"), {"c": corp})
                files, a, b, facts = _extract2_corp(session, corp, verbose=False)
                agg["e_files"] += files
                agg["e_facts"] += facts
                agg["track_b"] += b
                agg["r"] += reconcile_corp(session, corp)
                agg["s"] += standardize_corp(session, corp)
                session.commit()
            if args.resume_file:
                with open(args.resume_file, "a") as fh:
                    fh.write(corp + "\n")
        except Exception as e:
            agg["err"] += 1
            logger.error(f"[reextract-all] corp={corp} 실패: {e}")
        if i % 50 == 0 or i == total:
            logger.info(f"[reextract-all] {i}/{total} — facts {agg['e_facts']:,} "
                        f"(TrackB {agg['track_b']:,}) / stmt_src {agg['r']:,} / "
                        f"std_v2 {agg['s']:,} / 오류 {agg['err']}")

    logger.success(
        f"[reextract-all] 완료 — 기업 {total}, fact {agg['e_facts']:,}행, "
        f"TrackB 파일 {agg['track_b']:,}, stmt_src {agg['r']:,}, std_v2 {agg['s']:,}, "
        f"오류 {agg['err']}")
    logger.info("다음: scripts/fin2_comparative_financial.py → scripts/fin2_kgaap_gap.py (3패스)")


if __name__ == "__main__":
    main()
