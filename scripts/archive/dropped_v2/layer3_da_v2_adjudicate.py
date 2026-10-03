"""v2 불일치 건 전수 원문 대조 (READ-ONLY).

목적
----
std_v3 의 da_total 이 v2 와 다른 건들에 대해 **어느 쪽이 원문에 맞는지** 판정한다.
표본 1건만 보고 "v3 가 맞다"고 일반화하지 않기 위해 전수로 돌린다.

방법
----
계층2 note_lines 는 원문 충실 전사이므로(검증됨), 소스 주석의 **당기 D&A 후보 행을
전부** 나열해 기준 합계를 만들고 v3·v2 와 대조한다. 이렇게 하면 세 가지가 갈린다:

  V3_FAITHFUL   v3 == 후보 전량 합 → v3 가 원문대로. v2 가 다른 것.
  V3_MISSING    v3 <  후보 전량 합 → **내 추출 체인의 누락**(라벨 변종 등). 진짜 결함.
  V3_EXCESS     v3 >  후보 전량 합 → 과다 계상(이중 합산 등). 진짜 결함.
  BODY_SOURCED  v3 값이 본문 CF 에서 온 것 → 주석 기준으로는 판정 불가(별도 분류).

또한 v2 가 후보 중 어떤 부분집합과 맞는지도 본다(예: ROU 제외분과 일치 → v2 가 ROU 누락).

Usage
-----
    python scripts/layer3_da_v2_adjudicate.py --year 2024 --limit 200
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
from fin2.layer3.combine import (build_merged_lines, _map_rows, _resolve,
                                 select_canonical_rcept)
from fin2.layer3.note_da import _ROWS_SQL, _Row
from parser.common.note_labels import classify_da_label
from parser.common.note_periods import resolve_periods
from parser.common.note_topics import DA_SOURCE_PRIORITY, map_topic

_BODY_DA = ("cf.depreciation", "cf.amortization", "cf.da_total",
            "cf.rou_depreciation", "is.depreciation", "is.amortization")

# v3 와 v2 가 모두 있는 FY 행 중 값이 다른 것.
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


def note_candidates(session, rcept, basis):
    """소스 주석의 당기 D&A 후보 행 전량 → (topic, [(label, bucket, value)])."""
    rows = session.execute(_ROWS_SQL, {"rcept": rcept, "basis": basis}).fetchall()
    if not rows:
        return None, []
    by_topic = {}
    for r in rows:
        t = map_topic(r.section_path)
        if t in DA_SOURCE_PRIORITY:
            by_topic.setdefault(t, {}).setdefault(r.section_path, []).append(_Row(r))
    for topic in DA_SOURCE_PRIORITY:
        for _sec, srows in by_topic.get(topic, {}).items():
            per_table = {}
            for cell in resolve_periods(srows):
                if cell.period_rank != 0:
                    continue
                b = classify_da_label(cell.label_raw)
                if b is None:
                    continue
                per_table.setdefault(cell.table_seq, []).append(
                    (cell.label_raw.strip(), b, abs(cell.value_won)))
            if per_table:
                best = max(per_table, key=lambda s: (len({x[1] for x in per_table[s]}), -s))
                return topic, per_table[best]
    return None, []


def v2_subset_match(cands, v2):
    """v2 가 후보들의 어떤 부분집합 합과 맞는가(최대 4개 조합까지 탐색)."""
    vals = [(lbl, v) for lbl, _b, v in cands]
    for k in range(1, min(len(vals), 4) + 1):
        for combo in combinations(range(len(vals)), k):
            if close(sum(vals[i][1] for i in combo), v2):
                return [vals[i][0] for i in combo]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--basis", default="consolidated")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--show", type=int, default=12)
    args = ap.parse_args()

    st = args.basis
    tally: Counter[str] = Counter()
    details: dict[str, list[str]] = {}

    with get_session() as session:
        rows = session.execute(
            MISMATCH_SQL, {"year": args.year, "st": st, "lim": args.limit}
        ).fetchall()
        print(f"v2 와 다른 FY{args.year} {st} 행: {len(rows)}건\n")

        for m in rows:
            corp = m.corp_code
            # v3 값의 출처가 본문인지 주석인지 먼저 가른다.
            try:
                merged = build_merged_lines(session, corp, args.year, "FY")
                basis = args.basis
                cands_map = _map_rows(merged, "FY", basis, ("BS", "IS", "CF"))
                if not cands_map:
                    other = "separate" if basis == "consolidated" else "consolidated"
                    if {r["basis"] for r in merged} == {other}:
                        cands_map = _map_rows(merged, "FY", other, ("BS", "IS", "CF"))
                        basis = other
                confirmed, _ = _resolve(cands_map)
            except Exception:  # noqa: BLE001
                tally["ERROR"] += 1
                continue

            if any(confirmed.get(c) for c in _BODY_DA):
                tally["BODY_SOURCED(주석기준 판정불가)"] += 1
                continue

            rcept = select_canonical_rcept(session, corp, args.year, "FY")
            topic, cands = note_candidates(session, rcept, basis) if rcept else (None, [])
            if not cands:
                tally["NO_NOTE_CANDIDATE"] += 1
                continue

            full = sum(v for _l, _b, v in cands)
            if close(m.v3_da, full):
                verdict = "V3_FAITHFUL(원문대로)"
            elif m.v3_da < full:
                verdict = "V3_MISSING(누락)"
            else:
                verdict = "V3_EXCESS(과다)"
            tally[verdict] += 1

            sub = v2_subset_match(cands, m.v2_da)
            tally["v2=후보부분집합" if sub else "v2=후보와무관"] += 1

            if len(details.setdefault(verdict, [])) < args.show:
                comp = " + ".join(f"{l}:{v:,}" for l, _b, v in cands)
                details[verdict].append(
                    f"{corp} [{topic}] v3={m.v3_da:,} v2={m.v2_da:,} 후보합={full:,}\n"
                    f"        구성: {comp[:150]}\n"
                    f"        v2설명: {'+'.join(sub) if sub else '후보 부분집합으로 설명 안 됨'}")

    print("=== 판정 ===")
    for k, v in tally.most_common():
        print(f"  {k:<32} {v:>5}")

    for verdict in ("V3_MISSING(누락)", "V3_EXCESS(과다)", "V3_FAITHFUL(원문대로)"):
        if details.get(verdict):
            print(f"\n=== {verdict} 상세 ===")
            for d in details[verdict]:
                print(f"  {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
