"""
parity removed-keys 트리아지.

parity_v2.json 의 removed_keys(레거시 standard_financials 엔 있고 std_financials_v2 엔
없는 (corp,year,period,basis,version))를 파이프라인 단계별 원인으로 분류한다.

분류(우선순위):
  STMTSRC_NO_STDV2 : statement_source 는 있는데 std_v2 없음        → S(standardize) 드롭
  FACT_NO_STMTSRC  : fact_v2(ctx-year+basis) 있는데 stmt_src 없음  → R(reconcile) 드롭
  FACT_OTHERBASIS  : 해당 basis 는 없지만 같은 corp+year 다른 basis fact 존재 → basis 갭
  FACT_REPORTONLY  : ctx-year 매칭은 없지만 report(연도,기간) 추출은 있음 → 비교연도 전용(레거시가 비교컬럼으로 행 생성 추정)
  NO_FACT          : 해당 corp+year fact_v2 전무                    → E(추출) 갭(파일포맷/Track A·B 실패 또는 비교연도)

실행: python scripts/parity_triage_removed.py [--json /tmp/parity_v2.json] [--show 15]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from collector.db import get_session


def parse_key(k):
    # "corp|year|period|basis|version"
    p = k.split("|")
    corp, year, period, basis = p[0], int(p[1]), p[2], p[3]
    return corp, year, period, basis


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="/tmp/parity_v2.json")
    ap.add_argument("--show", type=int, default=15)
    args = ap.parse_args()

    d = json.load(open(args.json))
    removed = [parse_key(k) for k in d["removed_keys"]]
    print(f"removed keys: {len(removed):,}")

    with get_session() as s:
        print("loading existence sets ...")
        # fact_v2: 데이터연도+basis 정렬 (ix_fact_v2_lookup)
        fact_ctx = {(r[0], r[1], r[2]) for r in s.execute(text(
            "SELECT DISTINCT corp_code, context_fiscal_year, basis FROM fact_v2"
            " WHERE context_fiscal_year IS NOT NULL")).fetchall()}
        # fact_v2: corp+year (basis 무관)
        fact_corp_year = {(c, y) for (c, y, b) in fact_ctx}
        # fact_v2: report(보고서 연도,기간) 정렬 — basis 무관
        fact_rep = {(r[0], r[1], r[2]) for r in s.execute(text(
            "SELECT DISTINCT corp_code, report_fiscal_year, report_fiscal_period FROM fact_v2"
            )).fetchall()}
        # fact_v2: report 연도,기간,basis — reconcile 후보 키 정렬(자체기간 vs 비교연도 판별)
        fact_rep_b = {(r[0], r[1], r[2], r[3]) for r in s.execute(text(
            "SELECT DISTINCT corp_code, report_fiscal_year, report_fiscal_period, basis FROM fact_v2"
            " WHERE basis IS NOT NULL")).fetchall()}
        # statement_source: (corp,fy,period,basis)
        stmt = {(r[0], r[1], r[2], r[3]) for r in s.execute(text(
            "SELECT DISTINCT corp_code, fiscal_year, fiscal_period, basis FROM statement_source"
            )).fetchall()}
        print(f"  fact_ctx={len(fact_ctx):,} fact_rep={len(fact_rep):,} stmt={len(stmt):,}")

    cat = Counter()
    by_cat_year = {}
    by_cat_period = {}
    samples = {}
    for corp, year, period, basis in removed:
        if (corp, year, period, basis) in stmt:
            c = "STMTSRC_NO_STDV2"
        elif (corp, year, basis) in fact_ctx:
            # fact 존재. 보고서 자체기간(report-aligned)인지 비교연도 전용인지 구분
            if (corp, year, period, basis) in fact_rep_b:
                c = "RECON_DROP_OWNPERIOD"   # 자체기간+basis 추출O + stmt_src X → 순수 reconcile 드롭
            elif (corp, year, period) in fact_rep:
                c = "OWNREPORT_BASIS_NULL"   # 자체보고서 추출O 인데 basis 미해결(NULL) → reconcile 드롭(진짜 버그)
            else:
                c = "COMPARATIVE_ONLY"        # 비교연도(전기 컬럼)뿐 → fin2 의도상 행 미생성(양성)
        elif (corp, year) in fact_corp_year:
            c = "FACT_OTHERBASIS"
        elif (corp, year, period) in fact_rep:
            c = "FACT_REPORTONLY"
        else:
            c = "NO_FACT"
        cat[c] += 1
        by_cat_year.setdefault(c, Counter())[year] += 1
        by_cat_period.setdefault(c, Counter())[period] += 1
        samples.setdefault(c, []).append(f"{corp}|{year}|{period}|{basis}")

    tot = len(removed)
    print("\n=== 원인 분류 ===")
    for c, n in cat.most_common():
        print(f"  {c:18} {n:>7,}  ({100*n/tot:4.1f}%)")

    print("\n=== 카테고리별 연도 분포(top6) ===")
    for c, _ in cat.most_common():
        top = ", ".join(f"{y}:{n}" for y, n in by_cat_year[c].most_common(6))
        print(f"  {c:18} {top}")

    print("\n=== 카테고리별 기간 분포 ===")
    for c, _ in cat.most_common():
        top = ", ".join(f"{p}:{n}" for p, n in sorted(by_cat_period[c].items()))
        print(f"  {c:18} {top}")

    print(f"\n=== 샘플 (각 {args.show}) ===")
    for c, _ in cat.most_common():
        print(f"  [{c}]")
        for k in samples[c][:args.show]:
            print(f"     {k}")


if __name__ == "__main__":
    main()
