"""PDF-only 적재(source_format='pdf') 후, 그 corp 들을 reconcile→standardize→comparative→kgaap.

⚠ purge/재추출 없음 — 기존 fact_v2(PDF 포함) 위에서 R→S 만 재실행해 std_v2 갭을 채운다.
모집단 = fact_v2 에 source_format='pdf' 셀을 가진 corp.

실행: python scripts/fin2_rs_pdf_corps.py [--corps S:E] [--resume-file F] [--limit N]
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
from fin2.standardize.build import (
    standardize_corp, standardize_comparative_corp, standardize_kgaap_gap_corp,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corps", help="START:END 위치 슬라이스(병렬 분할)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--resume-file")
    args = ap.parse_args()

    with get_session() as s:
        corps = sorted({r[0] for r in s.execute(text(
            "SELECT DISTINCT corp_code FROM fact_v2 WHERE source_format='pdf'"))})
    if args.corps and ":" in args.corps:
        a, _, b = args.corps.partition(":")
        corps = corps[(int(a) if a else None):(int(b) if b else None)]
    done = set()
    if args.resume_file and Path(args.resume_file).exists():
        done = {ln.strip() for ln in Path(args.resume_file).read_text().splitlines() if ln.strip()}
    corps = [c for c in corps if c not in done]
    if args.limit:
        corps = corps[:args.limit]
    logger.info(f"[pdf-rs] 대상 corp {len(corps)}")

    agg = {"r": 0, "s": 0, "comp": 0, "kg": 0, "err": 0}
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as s:
                agg["r"] += reconcile_corp(s, corp)
                agg["s"] += standardize_corp(s, corp)
                agg["comp"] += standardize_comparative_corp(s, corp)
                agg["kg"] += standardize_kgaap_gap_corp(s, corp)
                s.commit()
            if args.resume_file:
                with open(args.resume_file, "a") as fh:
                    fh.write(corp + "\n")
        except Exception as e:
            agg["err"] += 1
            logger.error(f"[pdf-rs] corp={corp} 실패: {type(e).__name__}: {e}")
        if i % 50 == 0 or i == len(corps):
            logger.info(f"  ..{i}/{len(corps)} stmt_src {agg['r']} std {agg['s']} "
                        f"comp {agg['comp']} kgaap {agg['kg']} err {agg['err']}")

    logger.success(f"[pdf-rs] 완료 — corp {len(corps)}, stmt_src {agg['r']}, std {agg['s']}, "
                   f"comparative {agg['comp']}, kgaap {agg['kg']}, 오류 {agg['err']}")


if __name__ == "__main__":
    main()
