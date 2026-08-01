"""Diagnose the cell-merge defect: a whole column collapsing into one cell (READ-ONLY).

Symptom (measured): biz_metrics rows with |value| > 1e18 — e.g. 일양약품 ip_right holding
'20252024202320222021...' , i.e. every year of a column concatenated into a single value.
docs/PARSING_RULES.md 부록 C.

This dumps the RAW XML structure of the offending table (TR/TD counts, tag names, rowspan /
colspan attributes) next to what expand_table_grid produced, so the cause can be identified
instead of guessed.

  python scripts/diag_cell_merge_defect.py --rcept 20260318000595 --table-ord 43
  python scripts/diag_cell_merge_defect.py --scan 30      # find more instances
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lxml import etree
from sqlalchemy import text

from collector.db import get_session
from fin2.extract.biz_section import _load_root, _tag, _text, expand_table_grid


def dump_table(el, label: str) -> None:
    print(f"\n── {label} ──")
    trs = [c for c in el.iter() if _tag(c) == "TR"]
    print(f"  이 TABLE 하위 TR 총 {len(trs)}개 (중첩 포함)")
    direct = [c for c in el if _tag(c) == "TR"]
    print(f"  직계 자식 TR {len(direct)}개")
    kids = {}
    for c in el:
        kids[_tag(c)] = kids.get(_tag(c), 0) + 1
    print(f"  TABLE 직계 자식 태그: {kids}")

    for i, tr in enumerate(trs[:4]):
        cells = [c for c in tr if _tag(c) in ("TD", "TH", "TE", "TU")]
        print(f"  TR[{i}] 셀 {len(cells)}개")
        for j, c in enumerate(cells[:4]):
            span = {k: v for k, v in c.attrib.items() if "SPAN" in k.upper()}
            txt = _text(c).replace("\n", " ")[:60]
            print(f"      [{j}] {_tag(c)} {span} · len={len(_text(c))} · {txt!r}")
    if len(trs) > 4:
        print(f"  … TR {len(trs)-4}개 더")


def drill(rcept: str, table_ord: int | None) -> int:
    with get_session() as s:
        path = s.execute(text(
            "SELECT file_path FROM download_tasks WHERE rcept_no=:r AND file_type='xml'"),
            {"r": rcept}).scalar()
        stored = s.execute(text(
            "SELECT narrative, grid FROM biz_section_tables WHERE rcept_no=:r AND table_ord=:o"),
            {"r": rcept, "o": table_ord}).fetchone() if table_ord is not None else None
    if not path:
        print("원본 없음")
        return 1
    root = _load_root(Path(path))
    if root is None:
        print("파싱 실패")
        return 1

    if stored:
        g = stored.grid
        print(f"저장된 grid: {len(g)}행 x {max((len(r) for r in g), default=0)}열")
        print(f"캡션: {(stored.narrative or '')[:90]}")
        for r in g[:3]:
            print("  | " + " | ".join((c or "")[:45].replace("\n", " ") for c in r))

    # 저장된 grid 와 같은 모양을 내는 표를 원문에서 찾는다.
    target = None
    for el in root.iter():
        if _tag(el) != "TABLE":
            continue
        try:
            grid = expand_table_grid(el)
        except Exception:                                          # noqa: BLE001
            continue
        if stored and grid and len(grid) == len(stored.grid) and grid and stored.grid \
                and grid[0] == stored.grid[0]:
            target = el
            break
    if target is None:
        print("\n원문에서 같은 표를 못 찾음 — 첫 번째로 '한 셀에 4자리 연도가 3개 이상' 인 표를 찾는다")
        for el in root.iter():
            if _tag(el) != "TABLE":
                continue
            for c in el.iter():
                if _tag(c) in ("TD", "TH", "TE", "TU") and len(_text(c)) > 60 \
                        and _text(c).count("20") > 5:
                    target = el
                    break
            if target is not None:
                break
    if target is None:
        print("해당 표를 찾지 못함")
        return 1

    dump_table(target, "원문 XML 구조")
    print("\n── expand_table_grid 결과 ──")
    g = expand_table_grid(target)
    print(f"  {len(g)}행 x {max((len(r) for r in g), default=0)}열")
    return 0


def scan(limit: int) -> int:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT c.corp_name, b.metric, b.rcept_no, b.table_ord, count(*) n
            FROM biz_metrics b JOIN corporations c USING(corp_code)
            WHERE abs(b.value) > 1e18
            GROUP BY 1,2,3,4 ORDER BY n DESC LIMIT :l
        """), {"l": limit}).fetchall()
    print(f"{'기업':<16} {'metric':<16} {'rcept':<16} {'ord':>4} {'행':>5}")
    for r in rows:
        print(f"{r.corp_name[:15]:<16} {r.metric:<16} {r.rcept_no:<16} {r.table_ord:>4} {r.n:>5}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rcept")
    ap.add_argument("--table-ord", type=int)
    ap.add_argument("--scan", type=int)
    args = ap.parse_args()
    if args.scan:
        return scan(args.scan)
    if args.rcept:
        return drill(args.rcept, args.table_ord)
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
