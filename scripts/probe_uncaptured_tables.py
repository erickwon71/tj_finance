"""What tables in '사업의 내용' does NO parser capture? (READ-ONLY)

R0's first watch item is **false absence**: content that exists in the document but never
reaches the DB. Listing "captions the catalog didn't classify" is not the same thing — many of
those are handled by biz_section / sales_section / rd_note / order_backlog instead.

So this walks every table in the section, subtracts the ones actually captured by
`parse_biz_metrics` (grid-hash identity, the same guarantee used to prevent double capture),
and reports what is left, grouped by caption. That remainder is the real gap.

  python scripts/probe_uncaptured_tables.py --corps 150 --workers 8
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from collector.filing_select import period_groups
from fin2.extract.biz_catalog import classify_caption, grid_key, walk_captioned_tables
from fin2.extract.biz_section import _load_root, is_merged_column_table, parse_biz_metrics


def work(job: tuple[str, str, int]) -> list[tuple[str, str, int, str]]:
    """→ [(caption, corp, numeric_cells, sample_raw_caption)] for uncaptured tables."""
    corp, path, fy = job
    p = Path(path)
    if not p.exists():
        return []
    try:
        sec_rows, _ = parse_biz_metrics(p, corp, fy)
        root = _load_root(p)
    except Exception:                                              # noqa: BLE001
        return []
    if root is None:
        return []
    captured = {grid_key(s["grid"]) for s in sec_rows if s.get("grid")}

    out = []
    for ct in walk_captioned_tables(root):
        if grid_key(ct.grid) in captured:
            continue
        if is_merged_column_table(ct.grid):
            continue                       # 병합열 표는 의도적으로 건너뛴 것(사용자 결정)
        n_num = sum(1 for row in ct.grid for c in row
                    if c and c.strip().replace(",", "").replace(".", "").replace("%", "").isdigit())
        if n_num < 3:
            continue                       # 수치가 거의 없는 표는 적재 대상이 아니다
        cap = ct.caption or "(캡션없음)"
        out.append((cap, corp, n_num, ct.caption_raw[:50]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corps", type=int, default=150)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=23)
    ap.add_argument("--show", type=int, default=35)
    args = ap.parse_args()

    with get_session() as s:
        corps = [r[0] for r in s.execute(text(
            "SELECT corp_code FROM corporations WHERE is_active AND stock_code IS NOT NULL "
            "ORDER BY corp_code")).fetchall()]
        random.Random(args.seed).shuffle(corps)
        corps = corps[: args.corps]
        jobs = []
        for c in corps:
            groups = period_groups(s, c, "annual", latest_only=True)
            if groups:
                f = groups[0][-1]          # 그 기간의 가장 최신 보고서 1건
                jobs.append((c, f.file_path, f.fiscal_year))

    print(f"기업 {len(jobs)}개 · 워커 {args.workers} — 파싱 중…", flush=True)
    with Pool(args.workers) as pool:
        chunks = pool.map(work, jobs)

    cap_corps: dict[str, set] = defaultdict(set)
    cap_num: Counter = Counter()
    cap_tab: Counter = Counter()
    example: dict[str, str] = {}
    for c in chunks:
        for cap, corp, n_num, raw in c:
            cap_corps[cap].add(corp)
            cap_num[cap] += n_num
            cap_tab[cap] += 1
            example.setdefault(cap, raw)

    n = len(jobs)
    print(f"\n어떤 파서도 안 잡은 표 — 캡션별 (기업 {n}개 기준)\n")
    print(f"{'캡션':<40} {'기업':>5} {'커버':>6} {'표':>5} {'숫자셀':>7}  예시")
    print("-" * 116)
    for cap, corps_ in sorted(cap_corps.items(), key=lambda x: -len(x[1]))[: args.show]:
        print(f"{cap[:39]:<40} {len(corps_):>5} {len(corps_)/n*100:>5.1f}% "
              f"{cap_tab[cap]:>5} {cap_num[cap]:>7,}  {example[cap][:34]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
