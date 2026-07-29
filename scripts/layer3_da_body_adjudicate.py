"""BODY_SOURCED D&A 건 원문 대조 (READ-ONLY).

layer3_da_v2_adjudicate.py 는 v3 값이 **주석**에서 온 건만 판정할 수 있었고, 본문 CF 에서
온 125건은 비교 기준이 없어 '판정 불가'로 남겼다. 여기서 같은 방법을 본문에 적용한다.

기준선(원문)
-----------
계층2 report_lines 의 CF 섹션에서 **당기(col_index=0) 상각 관련 행 전량**을 뽑아
후보 합계를 만든다. report_lines 는 원문 충실 전사이므로 이게 원문 기준선이다.

판정
----
  V3_FAITHFUL  v3 == 후보 전량 합        → v3 가 원문대로. v2 가 다른 것.
  V3_MISSING   v3 <  후보 전량 합        → 본문 canonical 매핑 누락
  V3_EXCESS    v3 >  후보 전량 합        → 이중 계상
  v2 가 후보의 어떤 부분집합과 맞는지도 함께 본다(v2 가 무엇을 빠뜨렸는지 파악용).

Usage
-----
    python scripts/layer3_da_body_adjudicate.py --year 2024 --limit 400
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.layer3.combine import build_merged_lines, _map_rows, _resolve
from parser.common.note_labels import classify_da_label

_BODY_DA = ("cf.depreciation", "cf.amortization", "cf.da_total",
            "cf.rou_depreciation", "is.depreciation", "is.amortization")

MISMATCH_SQL = text(
    """
    SELECT v3.corp_code, v3.da_total AS v3_da, v2.da_total AS v2_da
    FROM std_financials_v3 v3
    JOIN LATERAL (
        SELECT da_total FROM std_financials_v2 s
        WHERE s.corp_code = v3.corp_code AND s.fiscal_year = v3.fiscal_year
          AND s.fiscal_period = 'FY' AND s.statement_type = v3.statement_type
          AND NOT s.is_stub AND NOT s.is_discrete
        ORDER BY s.version DESC LIMIT 1
    ) v2 ON TRUE
    WHERE v3.fiscal_period = 'FY' AND v3.fiscal_year = :year
      AND v3.statement_type = :st
      AND v3.da_total IS NOT NULL AND v2.da_total IS NOT NULL
      AND v3.da_total <> v2.da_total
    ORDER BY v3.corp_code
    LIMIT :lim
    """
)


def close(a, b, rel=1e-6):
    if a is None or b is None:
        return False
    s = max(abs(a), abs(b))
    return abs(a - b) <= max(s * rel, 1000)


def body_candidates(merged, basis: str):
    """본문 CF 의 당기 상각 후보 행 전량 → [(label, bucket, value)]."""
    out = []
    for r in merged:
        # ★기준선은 CF+IS 둘 다 봐야 한다. CF 만 보면 IS 출처 D&A 가 빠져
        #   v3 가 과다한 것처럼 보인다(허위 EXCESS).
        if r.get("basis") != basis or r.get("statement") not in ("CF", "IS"):
            continue
        if (r.get("col_index") or 0) != 0:      # 본문은 col_index 0 = 당기
            continue
        v = r.get("value_won")
        if v is None:
            continue
        b = classify_da_label(r.get("label_raw") or "")
        if b is None:
            continue
        out.append(((r.get("label_raw") or "").strip(), b, abs(v)))
    return out


def subset_match(cands, target):
    vals = [(l, v) for l, _b, v in cands]
    for k in range(1, min(len(vals), 4) + 1):
        for combo in combinations(range(len(vals)), k):
            if close(sum(vals[i][1] for i in combo), target):
                return [vals[i][0] for i in combo]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--basis", default="consolidated")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--show", type=int, default=6)
    args = ap.parse_args()

    tally: Counter[str] = Counter()
    details: dict[str, list[str]] = {}

    with get_session() as session:
        rows = session.execute(
            MISMATCH_SQL, {"year": args.year, "st": args.basis, "lim": args.limit}
        ).fetchall()

        for m in rows:
            corp = m.corp_code
            try:
                merged = build_merged_lines(session, corp, args.year, "FY")
                basis = args.basis
                cmap = _map_rows(merged, "FY", basis, ("BS", "IS", "CF"))
                if not cmap:
                    other = "separate" if basis == "consolidated" else "consolidated"
                    if {r["basis"] for r in merged} == {other}:
                        cmap = _map_rows(merged, "FY", other, ("BS", "IS", "CF"))
                        basis = other
                confirmed, _ = _resolve(cmap)
            except Exception:  # noqa: BLE001
                tally["ERROR"] += 1
                continue

            if not any(confirmed.get(c) for c in _BODY_DA):
                continue                       # 주석 출처 → 다른 스크립트 소관
            tally["BODY 총건"] += 1

            cands = body_candidates(merged, basis)
            if not cands:
                tally["후보없음(라벨 미분류)"] += 1
                continue
            full = sum(v for _l, _b, v in cands)

            if close(m.v3_da, full):
                verdict = "V3_FAITHFUL(원문대로)"
            elif m.v3_da < full:
                verdict = "V3_MISSING(누락)"
            else:
                verdict = "V3_EXCESS(과다)"
            tally[verdict] += 1

            sub = subset_match(cands, m.v2_da)
            tally["v2=후보부분집합" if sub else "v2=후보와무관"] += 1

            if len(details.setdefault(verdict, [])) < args.show:
                comp = " + ".join(f"{l}:{v:,}" for l, _b, v in cands)
                details[verdict].append(
                    f"{corp} v3={m.v3_da:,} v2={m.v2_da:,} 후보합={full:,}\n"
                    f"        구성: {comp[:150]}\n"
                    f"        v2설명: {'+'.join(sub) if sub else '설명 안 됨'}")

    print(f"=== BODY_SOURCED 원문 대조 · FY{args.year} · {args.basis} ===")
    for k, v in tally.most_common():
        print(f"  {k:<28} {v:>5}")
    for verdict in ("V3_MISSING(누락)", "V3_EXCESS(과다)", "V3_FAITHFUL(원문대로)"):
        if details.get(verdict):
            print(f"\n=== {verdict} ===")
            for d in details[verdict]:
                print(f"  {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
