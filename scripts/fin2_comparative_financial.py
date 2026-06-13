"""
item 4 후속 — 재추출된 금융업 corp 에 한해 비교컬럼 폴백 재실행.

전수 재추출(fin2_reextract_financial.py)로 자기연도 데이터가 새로 적재된 412사에 대해
standardize_comparative_corp 를 재실행. 자기보고서 행 불가침, 비교컬럼에서만 합성
(build.py 참조). 변경 없는 타 기업은 대상 아님. 기업단위 커밋·resume.

    PYTHONPATH=. .venv_tj_finance/bin/python scripts/fin2_comparative_financial.py [--resume-file F] [--dry-run]
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


def main() -> None:
    ap = argparse.ArgumentParser()
    # 재추출(fin2_reextract_financial.py)이 처리한 412사 목록 파일(corp_code 1줄씩).
    ap.add_argument("--corps-file", default="/tmp/reextract_fin.txt")
    ap.add_argument("--resume-file", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    corps = [ln.strip() for ln in Path(args.corps_file).read_text().splitlines() if ln.strip()]

    done = set()
    if args.resume_file and Path(args.resume_file).exists():
        done = {ln.strip() for ln in Path(args.resume_file).read_text().splitlines() if ln.strip()}
    pending = [c for c in corps if c not in done]

    logger.info(f"[comparative-fin] 대상 {len(corps)} / 완료제외 {len(done)} → {len(pending)}")
    if args.dry_run:
        return

    total = affected = n_fail = 0
    for i, corp in enumerate(pending, 1):
        try:
            with get_session() as session:
                w = standardize_comparative_corp(session, corp)
                session.commit()
            total += w
            if w:
                affected += 1
            if args.resume_file:
                with open(args.resume_file, "a") as fh:
                    fh.write(corp + "\n")
        except Exception as e:
            n_fail += 1
            logger.warning(f"[comparative-fin] 실패 corp={corp}: {e}")
        if i % 100 == 0 or i == len(pending):
            logger.info(f"[comparative-fin] {i}/{len(pending)} — rows {total:,} / 영향 {affected} / 실패 {n_fail}")

    logger.success(f"[comparative-fin] 완료 — rows {total:,}, 영향기업 {affected}, 실패 {n_fail}")


if __name__ == "__main__":
    main()
