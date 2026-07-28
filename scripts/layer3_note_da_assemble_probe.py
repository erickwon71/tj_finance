"""계층3 D&A 조립 end-to-end 검증 (READ-ONLY).

②주제(note_topics) → ③기간(note_periods) → ④라벨(note_labels) 체인을 실제로 태워
corp-fy-basis D&A 를 뽑고, **외부 정답 없이** 교차보고서 자기일관성으로 검증한다:

    report FY(Y)   당기 D&A  ==  report FY(Y+1) 전기 D&A

세 계층 중 하나라도 틀리면 이 항등식이 깨지므로 체인 전체의 회귀 테스트가 된다.
(재작성이 있는 기업은 값이 살짝 달라지므로 상대허용오차와 '전기 슬롯이 더 가까운가'를 함께 본다.)

소스 우선순위는 note_topics.DA_SOURCE_PRIORITY — 단일 1차 소스가 없다는 실측 반영.

Usage
-----
    python scripts/layer3_note_da_assemble_probe.py --corps 200
    python scripts/layer3_note_da_assemble_probe.py --corps 200 --by-topic
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.common.note_labels import (
    AMORTIZATION, DA_COMBINED, classify_da_label, is_depreciation,
)
from parser.common.note_periods import resolve_periods
from parser.common.note_topics import DA_SOURCE_PRIORITY, map_topic

ROWS_SQL = text(
    """
    SELECT section_path, table_seq, row_order, col_index, label_raw, value_won
    FROM note_lines
    WHERE corp_code = :corp
      AND rcept_no = :rcept
      AND basis = :basis
      AND statement = 'note'
      AND value_won IS NOT NULL
    """
)

FILINGS_SQL = text(
    """
    SELECT corp_code, max(rcept_no) AS rcept_no
    FROM filings
    WHERE fiscal_year = :year AND fiscal_period = 'FY'
      AND report_type = 'annual' AND is_final
    GROUP BY corp_code
    """
)


class _Row:
    """resolve_periods 가 기대하는 속성만 가진 경량 행."""
    __slots__ = ("table_seq", "col_index", "label_raw", "value_won", "row_order")

    def __init__(self, r):
        self.table_seq = r.table_seq
        self.col_index = r.col_index
        self.label_raw = r.label_raw
        self.value_won = r.value_won
        self.row_order = r.row_order


def extract_da(session, corp: str, rcept: str, basis: str) -> dict:
    """topic 우선순위를 따라가며 첫 번째로 성립하는 소스에서 당기 D&A 를 뽑는다."""
    rows = session.execute(
        ROWS_SQL, {"corp": corp, "rcept": rcept, "basis": basis}
    ).fetchall()
    if not rows:
        return {}

    by_topic: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        topic = map_topic(r.section_path)
        if topic in DA_SOURCE_PRIORITY:
            by_topic[topic][r.section_path].append(_Row(r))

    for topic in DA_SOURCE_PRIORITY:
        for section, srows in by_topic.get(topic, {}).items():
            dep = amort = combined = None
            rule_used = None
            for cell in resolve_periods(srows):
                if cell.period_rank != 0:
                    continue
                bucket = classify_da_label(cell.label_raw)
                if bucket is None:
                    continue
                rule_used = cell.rule
                if bucket == DA_COMBINED:
                    combined = (combined or 0) + cell.value_won
                elif is_depreciation(bucket):
                    dep = (dep or 0) + cell.value_won      # 사용권자산분 합산
                elif bucket == AMORTIZATION:
                    amort = (amort or 0) + cell.value_won
            if dep is not None or amort is not None or combined is not None:
                return {
                    "topic": topic, "section": section, "rule": rule_used,
                    "dep": dep, "amort": amort, "combined": combined,
                    "total": (combined if combined is not None
                              else (dep or 0) + (amort or 0)),
                }
    return {}


def close(a: Optional[int], b: Optional[int], rel: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    if a == b:
        return True
    scale = max(abs(a), abs(b))
    return scale > 0 and abs(a - b) <= max(scale * rel, 1_000)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corps", type=int, default=200)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--basis", default="consolidated")
    ap.add_argument("--seed", type=int, default=20260728)
    ap.add_argument("--by-topic", action="store_true")
    args = ap.parse_args()

    y0, y1 = args.year, args.year + 1
    verdicts: Counter[str] = Counter()
    topics: Counter[str] = Counter()
    rules: Counter[str] = Counter()
    examples: list[str] = []

    with get_session() as session:
        corps = [
            r[0] for r in session.execute(
                text("SELECT DISTINCT corp_code FROM std_financials_v3 ORDER BY corp_code")
            ).fetchall()
        ]
        random.Random(args.seed).shuffle(corps)
        corps = corps[: args.corps]

        latest = {}
        for y in (y0, y1):
            for r in session.execute(FILINGS_SQL, {"year": y}).fetchall():
                latest[(r.corp_code, y)] = r.rcept_no

        for corp in corps:
            r0, r1 = latest.get((corp, y0)), latest.get((corp, y1))
            if not r0:
                verdicts["NO_FILING"] += 1
                continue
            d0 = extract_da(session, corp, r0, args.basis)
            if not d0:
                verdicts["NO_SOURCE"] += 1
                continue
            topics[d0["topic"]] += 1
            rules[d0.get("rule") or "?"] += 1

            # FY(Y+1) 에서 '전기' 슬롯을 뽑아 대조한다.
            rows1 = session.execute(
                ROWS_SQL, {"corp": corp, "rcept": r1, "basis": args.basis}
            ).fetchall() if r1 else []
            prior_total = None
            cur1_total = None
            if rows1:
                same_section = [
                    _Row(r) for r in rows1 if r.section_path == d0["section"]
                ] or [
                    _Row(r) for r in rows1 if map_topic(r.section_path) == d0["topic"]
                ]
                if same_section:
                    acc = {0: {"dep": 0, "amort": 0, "comb": 0, "hit": False},
                           1: {"dep": 0, "amort": 0, "comb": 0, "hit": False}}
                    for cell in resolve_periods(same_section):
                        if cell.period_rank not in acc:
                            continue
                        b = classify_da_label(cell.label_raw)
                        if b is None:
                            continue
                        acc[cell.period_rank]["hit"] = True
                        if b == DA_COMBINED:
                            acc[cell.period_rank]["comb"] += cell.value_won
                        elif is_depreciation(b):
                            acc[cell.period_rank]["dep"] += cell.value_won
                        else:
                            acc[cell.period_rank]["amort"] += cell.value_won
                    if acc[1]["hit"]:
                        prior_total = (acc[1]["comb"] or
                                       acc[1]["dep"] + acc[1]["amort"])
                    if acc[0]["hit"]:
                        cur1_total = (acc[0]["comb"] or
                                      acc[0]["dep"] + acc[0]["amort"])

            if prior_total is None:
                verdicts["NO_NEXT_YEAR"] += 1
                continue

            if close(d0["total"], prior_total):
                verdicts["CONFIRMED"] += 1
            elif close(d0["total"], cur1_total):
                verdicts["SWAPPED(기간역전)"] += 1
                if len(examples) < 6:
                    examples.append(
                        f"{corp} topic={d0['topic']} rule={d0.get('rule')} "
                        f"FY{y0}.cur={d0['total']:,} FY{y1}.prior={prior_total:,}")
            else:
                # 재작성이면 '전기' 슬롯이 '당기' 슬롯보다 가깝다.
                gp = abs(d0["total"] - prior_total)
                gc = (abs(d0["total"] - cur1_total)
                      if cur1_total is not None else None)
                if gc is None or gp < gc:
                    verdicts["NEAR_PRIOR(재작성)"] += 1
                else:
                    verdicts["MISMATCH"] += 1
                    if len(examples) < 6:
                        examples.append(
                            f"{corp} topic={d0['topic']} rule={d0.get('rule')} "
                            f"FY{y0}.cur={d0['total']:,} FY{y1}.prior={prior_total:,} "
                            f"FY{y1}.cur={cur1_total}")

    total = sum(verdicts.values())
    print(f"=== D&A 조립 자기일관성 · FY{y0} vs FY{y1} · {args.basis} (n={total}) ===")
    for k, v in verdicts.most_common():
        print(f"  {k:<20} {v:>5}  {v / total * 100:5.1f}%")

    decided = (verdicts["CONFIRMED"] + verdicts["SWAPPED(기간역전)"]
               + verdicts["MISMATCH"] + verdicts["NEAR_PRIOR(재작성)"])
    if decided:
        ok = verdicts["CONFIRMED"] + verdicts["NEAR_PRIOR(재작성)"]
        print(f"\n  기간해석 정합: {ok}/{decided} = {ok / decided * 100:.1f}% "
              f"(기간역전 {verdicts['SWAPPED(기간역전)']})")

    print("\n=== 채택된 소스 topic ===")
    for k, v in topics.most_common():
        print(f"  {k:<28} {v:>5}")
    print("\n=== 기간 판정 근거 ===")
    for k, v in rules.most_common():
        print(f"  {k:<16} {v:>5}")
    if examples:
        print("\n--- 이상 사례 ---")
        for e in examples:
            print(f"  {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
