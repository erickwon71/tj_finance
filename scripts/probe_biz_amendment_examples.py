"""R2-1 illustration — find original<->amendment pairs where the SET OF TABLES differs.

These are the cases that decide the design: if an amendment re-files only some tables, then
"pick one version" silently drops the tables it did not re-file, while a table-level delta
keeps them. Prints DART links so a human can open both filings and compare.

READ-ONLY.

  python scripts/probe_biz_amendment_examples.py --groups 60 --show 6
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.biz_section import parse_biz_metrics

DART = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="

GROUPS_SQL = """
    SELECT f.corp_code, c.corp_name, f.fiscal_year,
           array_agg(f.rcept_no ORDER BY f.filed_at ASC NULLS FIRST, f.rcept_no ASC) AS rcepts,
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


def caption_of(sec: dict) -> str:
    """Human-facing table label: '[subsection] caption' head of the stored narrative."""
    return re.sub(r"\s+", " ", (sec.get("narrative") or "")).strip()[:70]


def tkey(sec: dict) -> tuple:
    cap = re.sub(r"\s+", "", (sec.get("narrative") or ""))[:40]
    grid = sec.get("grid") or []
    return (sec.get("metric"), cap, (len(grid), max((len(r) for r in grid), default=0)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups", type=int, default=60)
    ap.add_argument("--show", type=int, default=6)
    ap.add_argument("--seed", type=int, default=5)
    args = ap.parse_args()

    with get_session() as s:
        groups = [dict(r._mapping) for r in s.execute(text(GROUPS_SQL)).fetchall()]
    random.Random(args.seed).shuffle(groups)

    shown = 0
    for g in groups[: args.groups]:
        parsed = []
        for rcept, nm, path in zip(g["rcepts"], g["names"], g["paths"]):
            p = Path(path)
            if not p.exists():
                continue
            try:
                sec, _ = parse_biz_metrics(p, g["corp_code"], g["fiscal_year"])
            except Exception:                                      # noqa: BLE001
                continue
            if sec:
                parsed.append((rcept, nm, sec))
        if len(parsed) < 2:
            continue

        for i in range(len(parsed) - 1):
            (ra, na, sa), (rb, nb, sb) = parsed[i], parsed[i + 1]
            ka = {tkey(x): x for x in sa}
            kb = {tkey(x): x for x in sb}
            only_a = [ka[k] for k in ka if k not in kb]
            only_b = [kb[k] for k in kb if k not in ka]
            if not only_a and not only_b:
                continue
            shown += 1
            print(f"\n{'='*100}")
            print(f"{g['corp_name']}  FY{g['fiscal_year']}")
            print(f"  원본   {na[:34]:<36} {DART}{ra}")
            print(f"  다음   {nb[:34]:<36} {DART}{rb}")
            print(f"  표 수: 원본 {len(sa)} → 다음 {len(sb)}")
            if only_a:
                print(f"  ▼ 원본에만 있는 표 {len(only_a)}개 "
                      f"(‘최신본만 쓰기’ 를 하면 이것들이 사라진다)")
                for x in only_a[:4]:
                    print(f"      [{x['metric']}] {caption_of(x)}")
            if only_b:
                print(f"  ▲ 다음 보고서에만 있는 표 {len(only_b)}개")
                for x in only_b[:4]:
                    print(f"      [{x['metric']}] {caption_of(x)}")
            if shown >= args.show:
                return 0
    print(f"\n(표 구성이 갈리는 쌍 {shown}건)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
