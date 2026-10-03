"""std_v3 D&A enrichment 표본 검증 (READ-ONLY — combine 만 돌리고 DB 에 쓰지 않는다).

전량 재빌드(build_std_v3 --all) 전에 확인할 것:
  1. da_total/ebitda 채움률 — 주석 소스가 실제로 얼마나 메우는가
  2. v2 대조 — v2 에 da_total 이 있는 건과 얼마나 맞는가
     ★V2 는 정답이 아니다(DART 원문이 기준). 불일치는 조사 단서일 뿐 실패가 아니다.
  3. ebitda 항등식 — ebitda == operating_income + da_total

Usage
-----
    python scripts/layer3_da_enrichment_probe.py --corps 120
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.layer3.combine import combine_full

V2_SQL = text(
    """
    SELECT da_total FROM std_financials_v2
    WHERE corp_code = :corp AND fiscal_year = :fy AND fiscal_period = :fp
      AND statement_type = :st AND NOT is_stub AND NOT is_discrete
    ORDER BY version DESC LIMIT 1
    """
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corps", type=int, default=120)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--basis", default="consolidated")
    ap.add_argument("--seed", type=int, default=20260728)
    args = ap.parse_args()

    st = "consolidated" if args.basis == "consolidated" else "separate"
    tally: Counter[str] = Counter()
    diffs: list[str] = []

    with get_session() as session:
        corps = [
            r[0] for r in session.execute(
                text("SELECT DISTINCT corp_code FROM std_financials_v3 ORDER BY corp_code")
            ).fetchall()
        ]
        random.Random(args.seed).shuffle(corps)
        corps = corps[: args.corps]

        for corp in corps:
            try:
                col, _, _ = combine_full(session, corp, args.year, "FY", args.basis)
            except Exception:  # noqa: BLE001
                tally["ERROR"] += 1
                continue
            tally["total"] += 1
            da, eb, op = col.get("da_total"), col.get("ebitda"), col.get("operating_income")
            if da:
                tally["da_filled"] += 1
            if eb:
                tally["ebitda_filled"] += 1
            # 항등식
            if da and op is not None:
                tally["ebitda_ok" if eb == op + da else "ebitda_BAD"] += 1

            v2 = session.execute(
                V2_SQL, {"corp": corp, "fy": args.year, "fp": "FY", "st": st}
            ).scalar()
            if v2 and da:
                tally["v2_both"] += 1
                scale = max(abs(v2), abs(da))
                if abs(v2 - da) <= max(scale * 1e-6, 1000):
                    tally["v2_match"] += 1
                else:
                    ratio = da / v2 if v2 else 0
                    tally["v2_diff"] += 1
                    if len(diffs) < 8:
                        diffs.append(f"{corp} v3={da:,} v2={v2:,} (v3/v2={ratio:.3f})")
            elif v2 and not da:
                tally["v2_only"] += 1
            elif da and not v2:
                tally["v3_only"] += 1

    n = max(tally["total"], 1)
    print(f"=== std_v3 D&A enrichment 표본 · FY{args.year} · {args.basis} (n={n}) ===")
    print(f"  da_total 채움   {tally['da_filled']:>4} ({tally['da_filled']/n*100:5.1f}%)")
    print(f"  ebitda 채움     {tally['ebitda_filled']:>4} ({tally['ebitda_filled']/n*100:5.1f}%)")
    print(f"  ebitda 항등식   OK {tally['ebitda_ok']} / BAD {tally['ebitda_BAD']}")
    print(f"\n  v2 대조: 양쪽보유 {tally['v2_both']} → 일치 {tally['v2_match']} · 불일치 {tally['v2_diff']}")
    print(f"           v3만 {tally['v3_only']} (v2 가 못 채운 것) · v2만 {tally['v2_only']}")
    if tally["ERROR"]:
        print(f"  combine 오류 {tally['ERROR']}")
    if diffs:
        print("\n--- v2 불일치 (V2 는 정답 아님 — 조사 단서) ---")
        for d in diffs:
            print(f"  {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
