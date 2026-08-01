"""Does the merge key drop rows that the old per-filing load kept? (READ-ONLY)

`collector/biz_merge.merge_filings` keeps the FIRST row when the same item key appears twice
inside one filing. The old loader stored every row, so any such collision is a row the new
contract drops. This measures that rate before trusting the reload.

Compares, per (corp, year):
  old_style : total rows across the filings, as the per-filing loader would have stored them
  merged    : rows after chronological item-level merge
  collisions: rows dropped because their key repeated inside a single filing

  python scripts/probe_merge_collisions.py --corps 40
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.biz_merge import merge_filings
from collector.db import get_session
from collector.filing_select import period_groups
from fin2.extract.biz_section import parse_biz_metrics


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corps", type=int, default=40)
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args()

    with get_session() as s:
        corps = [r[0] for r in s.execute(text(
            "SELECT corp_code FROM corporations WHERE is_active AND stock_code IS NOT NULL "
            "ORDER BY corp_code")).fetchall()]
        random.Random(args.seed).shuffle(corps)
        corps = corps[: args.corps]

        tot = Counter()
        worst: list[tuple[float, str]] = []
        for corp in corps:
            for group in period_groups(s, corp, "annual"):
                parsed = []
                for f in group:
                    p = Path(f.file_path)
                    if not p.exists():
                        continue
                    try:
                        sec, met = parse_biz_metrics(p, corp, f.fiscal_year)
                    except Exception:                              # noqa: BLE001
                        continue
                    parsed.append((f.rcept_no, sec, met))
                if not parsed:
                    continue
                raw = sum(len(m) for _, _, m in parsed)
                _, merged, stats = merge_filings(parsed)
                tot["raw"] += raw
                tot["merged"] += len(merged)
                tot["collision"] += stats.get("collision_within_filing", 0)
                tot["overridden"] += stats.get("overridden", 0)
                tot["periods"] += 1
                tot["multi"] += 1 if len(parsed) > 1 else 0
                if raw and stats.get("collision_within_filing", 0) / raw > 0.05:
                    worst.append((stats["collision_within_filing"] / raw,
                                  f"{corp} FY{group[0].fiscal_year} "
                                  f"raw {raw} → merged {len(merged)} "
                                  f"(충돌 {stats['collision_within_filing']})"))

    print(f"기간 {tot['periods']}개 (정정본 있는 기간 {tot['multi']}개)\n")
    print(f"  파싱 원행 합계        {tot['raw']:>9,}")
    print(f"  병합 후               {tot['merged']:>9,}")
    print(f"  정정본이 덮어쓴 항목   {tot['overridden']:>9,}")
    print(f"  ★한 보고서 내 키 충돌 {tot['collision']:>9,}  "
          f"({tot['collision']/max(tot['raw'],1)*100:.2f}%) ← 구 방식 대비 유실분")
    if worst:
        print(f"\n충돌 5%↑ 기간 {len(worst)}개 (높은 순):")
        for r, msg in sorted(worst, reverse=True)[:8]:
            print(f"  {r*100:5.1f}%  {msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
