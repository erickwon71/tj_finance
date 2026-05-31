"""
fin2 전수 적재 커버리지 점검.

대상 유니버스(다운로드 완료 XML 보유 기업) 대비 각 레이어(fact_v2 / statement_source /
std_financials_v2)에 실제로 적재된 기업을 비교해 갭을 보고한다. fin2-all 슬라이스 분할
실행 후 "전 기업에 잘 적용됐는지" 확인용.

실행: python scripts/fin2_coverage.py [--show N]
  --show N: 갭 기업코드 샘플 N개 출력(기본 20)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from collector.db import get_session


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=20, help="갭 기업코드 샘플 개수")
    args = ap.parse_args()

    with get_session() as s:
        # 대상 유니버스: 다운로드 완료 XML 보유 기업
        universe = {r[0] for r in s.execute(text("""
            SELECT DISTINCT f.corp_code
            FROM download_tasks dt JOIN filings f ON f.rcept_no = dt.rcept_no
            WHERE dt.status='completed' AND dt.file_type='xml' AND dt.file_path IS NOT NULL
        """)).fetchall()}

        fact_corps = {r[0] for r in s.execute(text(
            "SELECT DISTINCT corp_code FROM fact_v2")).fetchall()}
        stmt_corps = {r[0] for r in s.execute(text(
            "SELECT DISTINCT corp_code FROM statement_source")).fetchall()}
        std_corps = {r[0] for r in s.execute(text(
            "SELECT DISTINCT corp_code FROM std_financials_v2")).fetchall()}
        # 레거시(현 파이프라인) 성공 기업 — '진짜 갭' 판정 기준
        legacy_corps = {r[0] for r in s.execute(text(
            "SELECT DISTINCT corp_code FROM standard_financials")).fetchall()}

        # 레코드 수
        n_fact = s.execute(text("SELECT COUNT(*) FROM fact_v2")).scalar()
        n_stmt = s.execute(text("SELECT COUNT(*) FROM statement_source")).scalar()
        n_std = s.execute(text("SELECT COUNT(*) FROM std_financials_v2")).scalar()

    U = len(universe)
    print("=== fin2 적재 커버리지 ===")
    print(f"  대상 유니버스(완료 XML 기업)  : {U:,}")
    print(f"  fact_v2 적재 기업             : {len(fact_corps & universe):,}  (레코드 {n_fact:,})")
    print(f"  statement_source 적재 기업    : {len(stmt_corps & universe):,}  (레코드 {n_stmt:,})")
    print(f"  std_financials_v2 적재 기업   : {len(std_corps & universe):,}  (레코드 {n_std:,})")

    # 갭 분석
    no_fact = universe - fact_corps
    fact_no_std = (fact_corps & universe) - std_corps
    real_gap = no_fact & legacy_corps          # 추출 0행인데 레거시는 성공 → 조사 대상
    pdf_only = no_fact - legacy_corps           # 레거시도 없음 → PDF-only/구조적 부재(정상)

    print("\n--- 갭 분석 ---")
    print(f"  fact_v2 없음(추출 0행)        : {len(no_fact):,}")
    print(f"    ├ 레거시도 없음(PDF-only 등) : {len(pdf_only):,}  (대체로 정상)")
    print(f"    └ ★레거시는 성공(진짜 갭)    : {len(real_gap):,}  ← 조사 대상")
    print(f"  fact_v2 있으나 std_v2 없음    : {len(fact_no_std):,}  ← R/S 단계 누락(재실행 필요)")

    def _sample(label, codes):
        if codes:
            shown = sorted(codes)[:args.show]
            print(f"\n  [{label}] 샘플 {len(shown)}/{len(codes)}:")
            print("    " + " ".join(shown))

    _sample("진짜 갭(레거시 성공·fin2 추출 0)", real_gap)
    _sample("fact_v2 있으나 std_v2 없음", fact_no_std)

    # 종합 판정
    print("\n--- 판정 ---")
    if not real_gap and not fact_no_std:
        print("  ✅ 유니버스 전 기업이 std_v2 까지 적재됨(또는 PDF-only 만 누락).")
    else:
        if fact_no_std:
            print(f"  ⚠ {len(fact_no_std):,}개 기업이 fact_v2 만 있고 std_v2 없음 →")
            print("     해당 기업에 reconcile2/standardize2 재실행 필요(또는 fin2-all --stage 로).")
        if real_gap:
            print(f"  ⚠ {len(real_gap):,}개 기업이 추출 0행(레거시는 성공) → 파일포맷/파서 조사 대상.")


if __name__ == "__main__":
    main()
