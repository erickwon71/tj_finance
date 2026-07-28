"""std_v3 D&A 의 v2 불일치 성격 규명 (READ-ONLY).

앞선 표본에서 v2 대비 불일치가 65/81 나왔다. 첫 가설(사용권자산 ROU 합산 차이)은
실측에서 기각됐다(rou=0). 그래서 **출처를 구분해** 다시 분류한다:

  · BODY  — v3 값이 본문 CF/IS canonical 에서 나옴(주석 주입 안 됨)
  · NOTE  — 본문에 D&A 가 없어 주석 체인이 공급

v2(cf_da/expense_nature 백필)와 v3 의 차이가 어느 출처에서 생기는지 갈라야
"내 주석 체인의 문제"와 "기존 본문 매핑의 문제"를 구분할 수 있다.
★대전제: V2 는 정답이 아니다 — DART 원문이 기준. 여기서는 원인 분류만 한다.

Usage
-----
    python scripts/layer3_da_v2_diff_probe.py --corps 150
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
from fin2.layer3.combine import (build_merged_lines, _map_rows, _resolve,
                                 select_canonical_rcept)
from fin2.layer3.note_da import note_da_canonicals

_BODY_DA = ("cf.depreciation", "cf.amortization", "cf.da_total",
            "cf.rou_depreciation", "is.depreciation", "is.amortization")

V2_SQL = text(
    """
    SELECT da_total FROM std_financials_v2
    WHERE corp_code=:corp AND fiscal_year=:fy AND fiscal_period='FY'
      AND statement_type=:st AND NOT is_stub AND NOT is_discrete
    ORDER BY version DESC LIMIT 1
    """
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corps", type=int, default=150)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--basis", default="consolidated")
    ap.add_argument("--seed", type=int, default=20260728)
    args = ap.parse_args()

    tally: Counter[str] = Counter()
    samples: dict[str, list[str]] = {"BODY": [], "NOTE": []}

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
                merged = build_merged_lines(session, corp, args.year, "FY")
                if not merged:
                    continue
                basis = args.basis
                cands = _map_rows(merged, "FY", basis, ("BS", "IS", "CF"))
                if not cands:
                    other = "separate" if basis == "consolidated" else "consolidated"
                    if {r["basis"] for r in merged} == {other}:
                        cands = _map_rows(merged, "FY", other, ("BS", "IS", "CF"))
                        basis = other
                confirmed, _ = _resolve(cands)
            except Exception:  # noqa: BLE001
                tally["ERROR"] += 1
                continue

            body = {c: confirmed[c] for c in _BODY_DA if confirmed.get(c)}
            if body:
                source = "BODY"
                da = (abs(body.get("cf.da_total"))
                      if body.get("cf.da_total") else
                      sum(abs(v) for k, v in body.items()))
            else:
                rcept = select_canonical_rcept(session, corp, args.year, "FY")
                nc = note_da_canonicals(session, rcept, basis) if rcept else {}
                if not nc:
                    tally["NO_DA"] += 1
                    continue
                source = "NOTE"
                da = (nc.get("note.da_total")
                      or sum(v for k, v in nc.items()))

            st = "consolidated" if args.basis == "consolidated" else "separate"
            v2 = session.execute(
                V2_SQL, {"corp": corp, "fy": args.year, "st": st}
            ).scalar()
            if not v2:
                tally[f"{source}_v2없음"] += 1
                continue

            scale = max(abs(v2), abs(da))
            if abs(da - v2) <= max(scale * 1e-6, 1000):
                tally[f"{source}_일치"] += 1
            else:
                tally[f"{source}_불일치"] += 1
                if len(samples[source]) < 6:
                    samples[source].append(
                        f"{corp} v3={da:,} v2={v2:,} 비율={da / v2:.3f}")

    print(f"=== v3 D&A vs v2 · 출처별 · FY{args.year} · {args.basis} ===")
    for k, v in sorted(tally.items()):
        print(f"  {k:<16} {v:>5}")

    for src in ("BODY", "NOTE"):
        m, t = tally[f"{src}_불일치"], tally[f"{src}_일치"] + tally[f"{src}_불일치"]
        if t:
            print(f"\n  {src}: 불일치 {m}/{t} = {m / t * 100:.1f}%")
        for s in samples[src]:
            print(f"    {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
