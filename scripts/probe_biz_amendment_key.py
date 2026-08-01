"""R2-1 groundwork — pick the delta-patch cell key for biz_metrics (READ-ONLY, no DB writes).

Why
---
`fin2/layer3/combine.py` patches amendments onto the original using the cell key
(statement, basis, col_index, section_path, label_raw), measured at 90.9% SAME over 60
original<->amendment pairs. `biz_metrics` is long-format, so that key does not exist here and
a new one must be chosen **with the same kind of measurement**, not by guesswork
(docs/PARSING_RULES.md R2, R6, R9).

What it measures
----------------
For each (corp, fiscal_year) that has 2+ annual filings with a parsable XML body, it parses
them chronologically and compares consecutive pairs under several candidate keys:

  SAME        key present in both, value identical      -> patch is a no-op (good)
  CHANGED     key present in both, value differs        -> a genuine amendment edit
  ONLY_ORIG   key only in the earlier filing            -> base row the amendment omits (KEPT)
  ONLY_AMEND  key only in the later filing              -> row added by the amendment

A good key maximises SAME+CHANGED (rows that line up) and minimises ONLY_* churn. High
ONLY_* on both sides means the key is unstable and patching would double-count.

  python scripts/probe_biz_amendment_key.py --groups 40
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.biz_section import parse_biz_metrics

# Candidate keys. table_ord is deliberately absent — it is the extraction order within one
# filing and shifts whenever a table is added or removed, so it can never be a cross-filing key.
CANDIDATE_KEYS = {
    "K1 metric+segment+item+period_label": ("metric", "segment", "item", "period_label"),
    "K2 metric+segment+item+period_year": ("metric", "segment", "item", "period_year"),
    "K3 metric+segment+item+period_label+unit": ("metric", "segment", "item", "period_label", "unit"),
    "K4 metric+segment+period_label": ("metric", "segment", "period_label"),
}

# Table-level identity candidates. `narrative` starts with "[subsection] caption ..." for the
# catalog and holds the heading text for the production/sales parsers, so its head is the most
# stable human-meaningful table label available across filings.
TABLE_KEYS = {
    "T1 metric+caption(40자)": "cap40",
    "T2 metric+caption(40자)+표모양": "cap40shape",
    "T3 metric+표모양": "shape",
}


def table_key(sec: dict, kind: str) -> tuple:
    cap = re.sub(r"\s+", "", (sec.get("narrative") or ""))[:40]
    grid = sec.get("grid") or []
    shape = (len(grid), max((len(r) for r in grid), default=0))
    if kind == "cap40":
        return (sec.get("metric"), cap)
    if kind == "cap40shape":
        return (sec.get("metric"), cap, shape)
    return (sec.get("metric"), shape)


GROUPS_SQL = """
    SELECT f.corp_code, c.corp_name, f.fiscal_year,
           array_agg(f.rcept_no ORDER BY f.filed_at ASC NULLS FIRST, f.rcept_no ASC) AS rcepts,
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


def rows_by_key(rows: list[dict], key_fields: tuple[str, ...]) -> dict[tuple, float]:
    out: dict[tuple, float] = {}
    for r in rows:
        k = tuple(r.get(f) for f in key_fields)
        # Later duplicates within one filing are kept as-is; collisions are counted separately.
        out.setdefault(k, r["value"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups", type=int, default=40)
    ap.add_argument("--seed", type=int, default=5)
    args = ap.parse_args()

    with get_session() as s:
        groups = [dict(r._mapping) for r in s.execute(text(GROUPS_SQL)).fetchall()]
    random.Random(args.seed).shuffle(groups)
    groups = groups[: args.groups]
    print(f"원본↔정정본 쌍을 가진 (기업,연도) 그룹 {len(groups)}개 표본\n")

    stats: dict[str, Counter] = defaultdict(Counter)
    collisions: dict[str, int] = defaultdict(int)
    pairs = 0
    tbl_stats: dict[str, Counter] = defaultdict(Counter)
    tbl_collisions: dict[str, int] = defaultdict(int)
    tbl_pairs: list[int] = []
    examples: list[str] = []

    for g in groups:
        parsed: list[tuple[str, list[dict]]] = []
        for rcept, path in zip(g["rcepts"], g["paths"]):
            p = Path(path)
            if not p.exists():
                continue
            try:
                sec, met = parse_biz_metrics(p, g["corp_code"], g["fiscal_year"])
            except Exception:                                      # noqa: BLE001
                continue
            if met:
                parsed.append((rcept, met, sec))
        if len(parsed) < 2:
            continue

        for i in range(len(parsed) - 1):
            pairs += 1
            (r_a, rows_a, sec_a), (r_b, rows_b, sec_b) = parsed[i], parsed[i + 1]
            tbl_pairs.append(1)
            for tname, tkind in TABLE_KEYS.items():
                ta, tb = {}, {}
                for x in sec_a:
                    ta.setdefault(table_key(x, tkind), x)
                for x in sec_b:
                    tb.setdefault(table_key(x, tkind), x)
                tbl_collisions[tname] += (len(sec_a) - len(ta)) + (len(sec_b) - len(tb))
                for k in ta:
                    tbl_stats[tname]["BOTH" if k in tb else "ONLY_ORIG"] += 1
                for k in tb:
                    if k not in ta:
                        tbl_stats[tname]["ONLY_AMEND"] += 1
            for name, fields in CANDIDATE_KEYS.items():
                a = rows_by_key(rows_a, fields)
                b = rows_by_key(rows_b, fields)
                collisions[name] += (len(rows_a) - len(a)) + (len(rows_b) - len(b))
                for k, va in a.items():
                    if k in b:
                        stats[name]["SAME" if b[k] == va else "CHANGED"] += 1
                    else:
                        stats[name]["ONLY_ORIG"] += 1
                for k in b:
                    if k not in a:
                        stats[name]["ONLY_AMEND"] += 1
            if len(examples) < 5:
                a = rows_by_key(rows_a, CANDIDATE_KEYS["K1 metric+segment+item+period_label"])
                b = rows_by_key(rows_b, CANDIDATE_KEYS["K1 metric+segment+item+period_label"])
                diff = [(k, a[k], b[k]) for k in a if k in b and a[k] != b[k]]
                if diff:
                    k, va, vb = diff[0]
                    examples.append(f"{g['corp_name']} FY{g['fiscal_year']} {r_a}->{r_b}: "
                                    f"{k} {va:,.0f} -> {vb:,.0f}")

    print(f"비교한 원본↔정정본 쌍 {pairs}개\n")
    if tbl_pairs:
        print("── 표 단위 식별(행 키가 아니라 표를 맞추는 방식) ──")
        h2 = f"{'표 키':<40} {'양쪽':>7} {'원본만':>7} {'정정만':>7} {'정렬률':>7} {'키충돌':>7}"
        print(h2)
        print("-" * len(h2))
        for name in TABLE_KEYS:
            c = tbl_stats[name]
            tot = c["BOTH"] + c["ONLY_ORIG"] + c["ONLY_AMEND"]
            al = c["BOTH"] / tot * 100 if tot else 0
            print(f"{name:<40} {c['BOTH']:>7,} {c['ONLY_ORIG']:>7,} {c['ONLY_AMEND']:>7,} "
                  f"{al:>6.1f}% {tbl_collisions[name]:>7,}")
        print()
    hdr = f"{'키':<44} {'SAME':>8} {'CHANGED':>8} {'ONLY_ORIG':>10} {'ONLY_AMEND':>11} {'정렬률':>7} {'키충돌':>7}"
    print(hdr)
    print("-" * len(hdr))
    for name in CANDIDATE_KEYS:
        c = stats[name]
        tot = sum(c.values())
        aligned = (c["SAME"] + c["CHANGED"]) / tot * 100 if tot else 0
        print(f"{name:<44} {c['SAME']:>8,} {c['CHANGED']:>8,} {c['ONLY_ORIG']:>10,} "
              f"{c['ONLY_AMEND']:>11,} {aligned:>6.1f}% {collisions[name]:>7,}")

    if examples:
        print("\n정정으로 값이 바뀐 예:")
        for e in examples:
            print("  " + e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
