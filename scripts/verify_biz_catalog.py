"""B5 caption catalog verification — sample parsing + source-comparison drill.

READ-ONLY: never writes to the DB.

Two modes
---------
  --sample N   parse N companies and aggregate per-metric output, company coverage, outliers
  --rcept R    single-filing drill — prints the caption->metric decision and **the generated
               rows side by side with the original grid** so a human can compare against the
               source (aggregates alone are not accepted as verification here)

Usage:
    python scripts/verify_biz_catalog.py --sample 120
    python scripts/verify_biz_catalog.py --rcept 20250311001085 --metric product_status
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.biz_catalog import (CATALOG, classify_caption, extract_catalog_from_root,
                                      grid_key, map_catalog_table, walk_captioned_tables)
from fin2.extract.biz_section import _load_root, parse_biz_metrics

TARGETS_SQL = """
    SELECT DISTINCT ON (f.corp_code)
           f.corp_code, c.corp_name, c.market, c.induty_code,
           f.fiscal_year, f.rcept_no, d.file_path
    FROM filings f
    JOIN download_tasks d USING (rcept_no)
    JOIN corporations c ON c.corp_code = f.corp_code
    WHERE d.status = 'completed' AND d.file_type = 'xml' AND d.file_path IS NOT NULL
      AND f.fiscal_period = 'FY' AND c.is_active AND c.stock_code IS NOT NULL
      AND f.fiscal_year >= :min_year
    ORDER BY f.corp_code, f.fiscal_year DESC
"""


def drill(rcept_no: str, only_metric: str | None) -> int:
    with get_session() as s:
        row = s.execute(text(
            "SELECT d.file_path, f.corp_code, f.fiscal_year FROM download_tasks d "
            "JOIN filings f USING (rcept_no) WHERE d.rcept_no=:r AND d.file_type='xml' "
            "AND d.file_path IS NOT NULL LIMIT 1"), {"r": rcept_no}).fetchone()
    if not row:
        print(f"{rcept_no}: 원본 없음")
        return 1
    root = _load_root(Path(row.file_path))
    if root is None:
        print(f"{rcept_no}: 파싱 실패")
        return 1

    for ct in walk_captioned_tables(root):
        metric = classify_caption(ct.caption)
        if metric is None or (only_metric and metric != only_metric):
            continue
        rows = map_catalog_table(ct, metric, row.fiscal_year)
        tag = " (연속표·캡션상속)" if ct.inherited else ""
        print(f"\n{'='*100}\n[{ct.subsection}] {ct.caption_raw[:60]}{tag}")
        print(f"  → metric={metric}  grid {len(ct.grid)}x{max(len(r) for r in ct.grid)}  "
              f"행 {len(rows)}개")
        print("  ── 원본 grid ──")
        for r in ct.grid[:12]:
            print("    | " + " | ".join(c.strip()[:16] for c in r[:9]))
        if len(ct.grid) > 12:
            print(f"    … ({len(ct.grid)-12}행 더)")
        print("  ── 생성된 행 ──")
        for m in rows[:14]:
            print(f"    seg={str(m.segment)[:20]:<22} item={str(m.item)[:20]:<22} "
                  f"per={str(m.period_label)[:14]:<16} y={m.period_year} "
                  f"val={m.value:>16,.2f} {m.unit or ''}")
        if len(rows) > 14:
            print(f"    … ({len(rows)-14}행 더)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--min-year", type=int, default=2023)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--rcept")
    ap.add_argument("--metric")
    args = ap.parse_args()

    if args.rcept:
        return drill(args.rcept, args.metric)

    with get_session() as s:
        rows = [dict(r._mapping) for r in s.execute(text(TARGETS_SQL),
                                                    {"min_year": args.min_year}).fetchall()]
    random.Random(args.seed).shuffle(rows)
    rows = rows[: args.sample or 100]

    t0 = time.time()
    corps: dict[str, set] = defaultdict(set)
    nrows: Counter = Counter()
    ntab: Counter = Counter()
    unclassified: Counter = Counter()
    dup_blocked = 0
    err = 0
    ex: dict[str, str] = {}
    for i, r in enumerate(rows, 1):
        p = Path(r["file_path"])
        if not p.exists():
            continue
        try:
            root = _load_root(p)
            if root is None:
                continue
            # Reproduce what the production/sales parsers already took, to measure how many
            # tables the duplicate guard blocks.
            sec, met = parse_biz_metrics(p, r["corp_code"], r["fiscal_year"])
            cat_sec, cat_met = extract_catalog_from_root(root, r["corp_code"], r["fiscal_year"])
            base = {grid_key(s["grid"]) for s in sec if s.get("metric") and
                    s["metric"] in ("capacity", "output", "utilization", "sales")}
            dup_blocked += sum(1 for s in cat_sec if grid_key(s["grid"]) in base)
        except Exception as exc:                                   # noqa: BLE001
            err += 1
            print(f"  ! {r['corp_name']}: {type(exc).__name__}: {exc}")
            continue
        for m in cat_met:
            corps[m["metric"]].add(r["corp_code"])
            nrows[m["metric"]] += 1
            ex.setdefault(m["metric"],
                          f"{r['corp_name']} seg={m['segment']} item={m['item']} "
                          f"y={m['period_year']} val={m['value']:,.0f}{m['unit'] or ''}")
        for s_ in cat_sec:
            ntab[s_["metric"]] += 1
        for ct in walk_captioned_tables(root):
            if classify_caption(ct.caption) is None and ct.caption:
                unclassified[ct.caption] += 1
        if i % 25 == 0:
            print(f"  {i}/{len(rows)} ({time.time()-t0:.0f}s)", flush=True)

    n = len(rows)
    print(f"\n표본 {n}사 · {time.time()-t0:.0f}s · 파싱오류 {err} · 중복차단 {dup_blocked}표\n")
    print(f"{'metric':<16} {'기업':>5} {'커버':>6} {'표':>7} {'행':>9}  예시")
    print("-" * 118)
    declared = list(dict.fromkeys(m for m, _, _ in CATALOG))
    for m in sorted(declared, key=lambda x: -len(corps[x])):
        print(f"{m:<16} {len(corps[m]):>5} {len(corps[m])/n*100:>5.1f}% {ntab[m]:>7,} "
              f"{nrows[m]:>9,}  {ex.get(m,'—')[:56]}")
    print(f"\n미분류 캡션 상위 30 (카탈로그 확장 후보):")
    for c, k in unclassified.most_common(30):
        print(f"  {k:>4}  {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
