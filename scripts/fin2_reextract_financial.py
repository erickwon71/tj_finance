"""
item 4 — 금융업/레거시 <P>헤더 면표 재추출 (section_detector 수정 반영).

배경: 보험·증권·지주·SPAC 등 레거시 ACODE 보고서는 재무제표를 ifrs-full_ XBRL 로
태깅하지 않아 Track A 0행 + (수정 전) Track B 섹션탐지 실패 → fact_v2 0행이었다.
section_detector 의 <P>헤더 탐지 수정(commit 9b1c44f) 후, 이들 보고서를 재추출하면
Track B 가 면표(BS/IS/CF)를 잡아 fact_v2 가 채워진다.

대상: download_tasks 가 Gate A REVIEW/EXTRACT_EMPTY 로 표시한 **XML** 완료본을 가진
기업(기본 fiscal_year ≥ 2010). 기업 단위로 E→R→S(extract2 → reconcile → standardize)
재실행(fin2-all 과 동일 파이프라인). 기업 단위 커밋·예외격리·resume.
⚠ 비교컬럼/ K-GAAP 폴백은 별도 패스(이후 fin2_comparative_fallback.py 재실행 권장).

⚠ 파일 다수 open(heavy) → 사용자 직접 실행 권장:
    caffeinate -i .venv_tj_finance/bin/python scripts/fin2_reextract_financial.py \
        --resume-file /tmp/reextract_fin.txt 2>&1 | tee -a /tmp/reextract_fin.log

옵션:
    --min-year Y     대상 EXTRACT_EMPTY 최소 회계연도(기본 2010)
    --limit N        대상 기업 N개만(시범)
    --dry-run        대상 기업 목록·수만 출력(쓰기 없음)
    --resume-file F  완료 기업 corp_code 누적 기록(중단 시 재개)
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

# run.py 의 per-corp 추출 헬퍼 재사용(Track A→B 폴백).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run import _extract2_corp  # noqa: E402

TARGET_CORPS_SQL = """
SELECT DISTINCT f.corp_code
FROM download_tasks dt
JOIN filings f ON f.rcept_no = dt.rcept_no
WHERE dt.gate_a_status = 'REVIEW'
  AND dt.gate_a_reason = 'EXTRACT_EMPTY'
  AND dt.file_type = 'xml'
  AND f.is_final = TRUE
  AND f.fiscal_year >= :min_year
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
    ap.add_argument("--min-year", type=int, default=2010)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--resume-file", default=None)
    args = ap.parse_args()

    with get_session() as session:
        corps = [r.corp_code for r in session.execute(
            text(TARGET_CORPS_SQL), {"min_year": args.min_year}).fetchall()]

    done = load_done(args.resume_file)
    pending = [c for c in corps if c not in done]
    if args.limit:
        pending = pending[:args.limit]

    logger.info(f"[reextract-fin] EXTRACT_EMPTY(xml, fy≥{args.min_year}) 기업 "
                f"{len(corps)} / 완료제외 {len(done)} → 대상 {len(pending)}")
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
                # ⚠ fact_v2 는 (acode) 키 upsert 라 파서 변경 시 옛 계정명 cell 이 orphan
                # 으로 남는다(예: 옛 "당기순이익" vs 새 "반기순이익"). 재추출 전 corp 단위
                # purge 로 제거 → 깨끗이 재적재. statement_source/std_v2 는 키안정 upsert 라
                # 별도 purge 불필요(comparative/kgaap 파생행 보존).
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
            logger.error(f"[reextract-fin] corp={corp} 실패: {e}")
        if i % 20 == 0 or i == total:
            logger.info(f"[reextract-fin] {i}/{total} — facts {agg['e_facts']:,} "
                        f"(TrackB {agg['track_b']:,}) / stmt_src {agg['r']:,} / "
                        f"std_v2 {agg['s']:,} / 오류 {agg['err']}")

    logger.success(
        f"[reextract-fin] 완료 — 기업 {total}, fact {agg['e_facts']:,}행, "
        f"TrackB 파일 {agg['track_b']:,}, stmt_src {agg['r']:,}, std_v2 {agg['s']:,}, "
        f"오류 {agg['err']}")


if __name__ == "__main__":
    main()
