"""증권 19사 revenue 판정 진단 — 실제 combine 로직을 돌려 프로파일이
무엇을 어떻게 결정하는지(defer/compose/general)와 그 근거를 firm별로 리포트.

사용: python scripts/diag_securities_revenue.py [--year 2025]
계층3 combine 을 그대로 호출하므로 std_v3 빌드와 동일한 경로를 재현한다(읽기 전용).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import SessionLocal
from fin2.layer3.combine import build_merged_lines, combine_full
from fin2.layer3.industry_profiles import (norm, REVENUE_PROFILES, SECURITIES,
                                           apply_revenue_profile)


def _induty(session, corp):
    return session.execute(text(
        "SELECT induty_code FROM corporations WHERE corp_code=:c"), {"c": corp}).scalar()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    args = ap.parse_args()

    session = SessionLocal()
    rows = session.execute(text("""
        SELECT corp_code, corp_name FROM corporations
        WHERE induty_code LIKE '6612%' AND is_active ORDER BY corp_name
    """)).fetchall()

    print(f"=== 증권 {len(rows)}사 revenue 판정 진단 (FY{args.year}, consolidated) ===\n")
    for corp, name in rows:
        merged = build_merged_lines(session, corp, args.year, "FY")
        if not merged:
            print(f"{name:14s} merged 없음(해당연도 미보고)")
            continue
        # 연결 우선, 없으면 별도(소형 증권사는 별도만 공시) — combine 의 basis_fallback 과 동일
        basis = "consolidated"
        is_lines = [r for r in merged if r["statement"] == "IS" and r["basis"] == basis]
        if not is_lines:
            basis = "separate"
            is_lines = [r for r in merged if r["statement"] == "IS" and r["basis"] == basis]
        # 영업수익 총계 라인(norm) 존재?
        op_totals = [(r["label_raw"], r["value_won"]) for r in is_lines
                     if norm(r["label_raw"]) in SECURITIES.total_labels and r["value_won"]]
        # signature 존재?
        sig = [r["label_raw"] for r in is_lines
               if norm(r["label_raw"]) in SECURITIES.signature_labels]
        applied = apply_revenue_profile(is_lines, _induty(session, corp))
        col, _, _ = combine_full(session, corp, args.year, "FY", basis, merged=merged)
        rev = col.get("revenue")
        rev_s = f"{rev/1e12:8.2f}조" if rev is not None else "   NULL "
        prof = applied[0] if applied else "-"
        ot = f"영업수익총계={op_totals[0][1]/1e12:.2f}조" if op_totals else "영업수익총계 없음"
        sg = f"sig={sig[0][:14]}" if sig else "sig 없음"
        bt = "별도" if basis == "separate" else "연결"
        print(f"{name:14s} [{bt}] rev={rev_s} prof={prof:10s} {ot:22s} {sg}")
        if applied:
            print(f"                 components={applied[2]}")
        else:
            # 프로파일 미적용 → 일반매퍼가 무엇을 봤는지: 정본 IS 상위 금액 라인 덤프
            seen = set()
            tops = sorted((r for r in is_lines if r["value_won"]),
                          key=lambda r: -abs(r["value_won"]))
            for r in tops:
                key = (r["label_raw"], r["value_won"])
                if key in seen:
                    continue
                seen.add(key)
                print(f"                   · {r['label_raw'][:42]:42s} {r['value_won']/1e12:8.3f}조")
                if len(seen) >= 10:
                    break

    session.close()


if __name__ == "__main__":
    main()
