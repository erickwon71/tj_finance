"""Is an amendment a COMPLETE document, or only the corrected fragment? (READ-ONLY)

This decides the design for R2-1. If amendments re-file the whole document, then resolving a
period to "the newest filing that actually has a body" (a chain walk, exactly what
`fin2/layer3/combine.py::select_canonical_rcepts` already does per statement) is sufficient and
no table-level delta merge is needed. If amendments are fragments, the untouched base must be
merged in.

Measures, per original<->amendment pair, the table count of the '사업의 내용' section on both
sides. A fragment would show a large drop.

  python scripts/probe_amendment_completeness.py --groups 80
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
from fin2.extract.biz_section import parse_biz_metrics

GROUPS_SQL = """
    SELECT f.corp_code, c.corp_name, f.fiscal_year,
           array_agg(f.rcept_no  ORDER BY f.filed_at ASC NULLS FIRST, f.rcept_no ASC) AS rcepts,
           array_agg(f.report_nm ORDER BY f.filed_at ASC NULLS FIRST, f.rcept_no ASC) AS names,
           array_agg(d.file_path ORDER BY f.filed_at ASC NULLS FIRST, f.rcept_no ASC) AS paths
    FROM filings f
    JOIN download_tasks d ON d.rcept_no = f.rcept_no
    JOIN corporations c ON c.corp_code = f.corp_code
    WHERE f.report_type = 'annual' AND c.is_active AND c.stock_code IS NOT NULL
      AND d.file_type = 'xml' AND d.status = 'completed' AND d.file_path IS NOT NULL
      AND f.fiscal_year >= 2015
    GROUP BY 1, 2, 3
    HAVING count(*) >= 2
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups", type=int, default=80)
    ap.add_argument("--seed", type=int, default=5)
    args = ap.parse_args()

    with get_session() as s:
        groups = [dict(r._mapping) for r in s.execute(text(GROUPS_SQL)).fetchall()]
    random.Random(args.seed).shuffle(groups)

    verdict: Counter = Counter()
    worst: list[tuple[float, str]] = []
    pairs = 0

    for g in groups[: args.groups]:
        parsed = []
        for rcept, nm, path in zip(g["rcepts"], g["names"], g["paths"]):
            p = Path(path)
            if not p.exists():
                continue
            try:
                sec, met = parse_biz_metrics(p, g["corp_code"], g["fiscal_year"])
            except Exception:                                      # noqa: BLE001
                continue
            parsed.append((rcept, nm, len(sec), len(met)))
        if len(parsed) < 2:
            continue

        for i in range(len(parsed) - 1):
            (ra, na, ta, ma), (rb, nb, tb, mb) = parsed[i], parsed[i + 1]
            pairs += 1
            if ta == 0:
                verdict["원본이 0표(비교불가)"] += 1
                continue
            ratio = tb / ta
            if ratio >= 0.9:
                verdict["정정본이 사실상 완전(≥90%)"] += 1
            elif ratio >= 0.5:
                verdict["정정본이 절반~90%"] += 1
            else:
                verdict["정정본이 절반 미만(단편 의심)"] += 1
            if ratio < 0.9:
                worst.append((ratio, f"{g['corp_name']} FY{g['fiscal_year']} "
                                     f"{na[:18]}({ta}표/{ma}행) -> {nb[:18]}({tb}표/{mb}행) "
                                     f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rb}"))

    print(f"원본↔정정본 {pairs}쌍 (사업의 내용 표 수 비교)\n")
    for k, v in verdict.most_common():
        print(f"  {k:<30} {v:>4}쌍  ({v/max(pairs,1)*100:.1f}%)")
    if worst:
        print(f"\n표가 줄어든 쌍 {len(worst)}건 (적은 순):")
        for r, msg in sorted(worst)[:8]:
            print(f"  {r*100:5.0f}%  {msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
