"""금융섹터 revenue 진단/회귀 — induty(KSIC) 프리픽스별 전수조사 도구.

신 profile 코드(combine 로직)로 재계산한 revenue 를 기존 std_v3(구 코드 빌드) 와 대조해
① 회귀(insurance/bank 등 변경 의도 없는 섹터가 바뀌었나) ② 의도된 변경을 확인한다.

사용:
  python scripts/diag_financial_revenue.py --induty 651   # 생명보험
  python scripts/diag_financial_revenue.py --induty 652   # 손해보험
  python scripts/diag_financial_revenue.py --induty 64121 # 은행
  python scripts/diag_financial_revenue.py --induty 64992 # 지주
읽기 전용. combine 을 그대로 호출하므로 std_v3 빌드와 동일 경로.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import SessionLocal
from fin2.layer3.combine import build_merged_lines, combine_full


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--induty", required=True, help="KSIC 프리픽스 (예: 651, 652, 64121, 66121)")
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--diff-only", action="store_true", help="신≠구 인 행만 출력")
    args = ap.parse_args()

    session = SessionLocal()
    rows = session.execute(text("""
        SELECT corp_code, corp_name FROM corporations
        WHERE induty_code LIKE :p AND is_active ORDER BY corp_name
    """), {"p": args.induty + "%"}).fetchall()

    print(f"=== induty {args.induty}* · {len(rows)}사 · FY{args.year} 신 revenue vs 구 std_v3 ===\n")
    n_diff = 0
    for corp, name in rows:
        merged = build_merged_lines(session, corp, args.year, "FY")
        basis = "consolidated"
        if merged and not any(r["statement"] == "IS" and r["basis"] == basis for r in merged):
            basis = "separate"
        new_rev = new_lines = None
        if merged:
            col, _, prov = combine_full(session, corp, args.year, "FY", basis, merged=merged)
            new_rev = col.get("revenue")
            new_lines = prov.get("industry_lines")
        old_rev = session.execute(text("""
            SELECT revenue FROM std_financials_v3
            WHERE corp_code=:c AND fiscal_year=:y AND fiscal_period='FY' AND statement_type=:b
        """), {"c": corp, "y": args.year, "b": basis}).scalar()

        def _t(v):
            return f"{v/1e12:8.3f}조" if v is not None else "   NULL "
        same = (new_rev == old_rev)
        if not same:
            n_diff += 1
        if args.diff_only and same:
            continue
        mark = "  " if same else "≠ "
        prof = (new_lines or {}).get("profile", "-")
        print(f"{mark}{name:16s} 신={_t(new_rev)} 구={_t(old_rev)} prof={prof}")
        if new_lines and not same:
            print(f"                     {new_lines}")
    print(f"\n신≠구: {n_diff}/{len(rows)} 사")
    session.close()


if __name__ == "__main__":
    main()
