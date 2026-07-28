"""본문 D&A 충돌-누락 전수 규모 측정 (READ-ONLY).

문제
----
본문 CF 에서 여러 행이 **같은 D&A canonical** 로 매핑되면(예: '감가상각비' 와
'투자부동산감가상각비' 가 둘 다 note.depreciation) `_resolve` 가 이를 단일값 canonical 의
충돌로 보고 **통째로 버린다**. D&A 는 합산해야 하는 가산 계열인데 단일값 취급을 받는 것.
실측 00105855: 원문 합 113,769,202,462 중 감가상각비 77,024,987,253 이 사라졌다.

측정
----
기업마다 본문(CF/IS) 당기 D&A 후보 행을 전부 뽑아 기준 합을 만들고, 현재 std_v3.da_total 과
비교한다. v2 불일치 여부와 무관하게 **전수**로 본다(v2 와 우연히 같은 건에도 결함이 있을 수 있음).

  MISSING   std_v3 < 후보합 (누락)   ← 이 결함
  MATCH     같음
  OVER      std_v3 > 후보합
  NOTE_SRC  본문에 D&A 가 없어 주석에서 온 건 → 대상 아님

Usage
-----
    python scripts/layer3_da_conflict_scale.py --year 2024
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.layer3.combine import build_merged_lines, _map_rows, _resolve
from parser.common.note_labels import classify_da_label

_BODY_DA = ("cf.depreciation", "cf.amortization", "cf.da_total",
            "cf.rou_depreciation", "is.depreciation", "is.amortization",
            "note.depreciation", "note.amortization", "note.rou_depreciation",
            "note.da_total")

V3_SQL = text(
    """
    SELECT corp_code, da_total FROM std_financials_v3
    WHERE fiscal_year = :year AND fiscal_period = 'FY' AND statement_type = :st
    """
)


def close(a, b, rel=1e-6):
    if a is None or b is None:
        return False
    s = max(abs(a), abs(b))
    return abs(a - b) <= max(s * rel, 1000)


def body_candidates(merged, basis):
    """본문(CF/IS) 당기 D&A 후보 행 전량."""
    out = []
    for r in merged:
        if r.get("basis") != basis:
            continue
        if r.get("statement") not in ("CF", "IS"):
            continue
        if (r.get("col_index") or 0) != 0:
            continue
        v = r.get("value_won")
        if v is None:
            continue
        if classify_da_label(r.get("label_raw") or "") is None:
            continue
        out.append(((r.get("label_raw") or "").strip(), abs(v)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--basis", default="consolidated")
    ap.add_argument("--limit", type=int, default=0, help="0 = 전수")
    args = ap.parse_args()

    tally: Counter[str] = Counter()
    lost_total = 0
    worst: list[tuple[int, str]] = []

    with get_session() as session:
        v3 = {r.corp_code: r.da_total for r in session.execute(
            V3_SQL, {"year": args.year, "st": args.basis}).fetchall()}
        corps = sorted(v3)
        if args.limit:
            corps = corps[: args.limit]
        print(f"대상 {len(corps)}개 corp (FY{args.year} {args.basis})", flush=True)

        for i, corp in enumerate(corps, 1):
            if i % 400 == 0:
                print(f"  … {i}/{len(corps)}", flush=True)
            try:
                merged = build_merged_lines(session, corp, args.year, "FY")
                if not merged:
                    continue
                basis = args.basis
                cmap = _map_rows(merged, "FY", basis, ("BS", "IS", "CF"))
                if not cmap:
                    other = "separate" if basis == "consolidated" else "consolidated"
                    if {r["basis"] for r in merged} == {other}:
                        cmap = _map_rows(merged, "FY", other, ("BS", "IS", "CF"))
                        basis = other
                    else:
                        continue
                confirmed, _ = _resolve(cmap)
            except Exception:  # noqa: BLE001
                tally["ERROR"] += 1
                continue

            cands = body_candidates(merged, basis)
            if not cands:
                tally["NOTE_SRC(본문 D&A 없음)"] += 1
                continue

            # 본문에 후보가 있는데 confirmed 에 D&A canonical 이 하나도 없으면
            # 충돌로 전량 버려진 경우다.
            if not any(confirmed.get(c) for c in _BODY_DA):
                tally["ALL_DROPPED(충돌 전량폐기)"] += 1

            full = sum(v for _l, v in cands)
            cur = v3.get(corp)
            if cur is None:
                tally["V3_NULL"] += 1
                continue
            if close(cur, full):
                tally["MATCH"] += 1
            elif cur < full:
                tally["MISSING(누락)"] += 1
                lost = full - cur
                lost_total += lost
                worst.append((lost, f"{corp} v3={cur:,} 후보합={full:,} 누락={lost:,}"))
            else:
                tally["OVER(과다)"] += 1

    n = sum(v for k, v in tally.items() if k in ("MATCH", "MISSING(누락)", "OVER(과다)"))
    print(f"\n=== 본문 D&A 전수 대조 · FY{args.year} · {args.basis} ===")
    for k, v in tally.most_common():
        print(f"  {k:<28} {v:>5}")
    if n:
        miss = tally["MISSING(누락)"]
        print(f"\n  판정대상 {n} 중 누락 {miss} = {miss / n * 100:.1f}%")
        print(f"  누락 총액 {lost_total:,}원")
    worst.sort(reverse=True)
    print("\n--- 누락 상위 8 ---")
    for _l, s in worst[:8]:
        print(f"  {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
