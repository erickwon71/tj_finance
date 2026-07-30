"""주석·SCE 표의 **실제 금액 열 수 분포** 측정 — `_NOTE_MAX_COLS`/`_SCE_MAX_COLS` 상한 결정용.

배경: 전수 정방향 조사(2026-07-30)에서 `extract_rows(num_cols=N)` 의 `range(num_cols)` 가
N 번째 이후 셀을 조용히 버리는 것이 확인됐다 — 주석 3,592,401 셀(주석 원문의 1.62%),
SCE 30,285 셀. 주석 열은 자산분류·만기구간이라 **전부 실데이터**이고 `note_da.py` 가
col 필터 없이 전부 읽으므로 유실이 그대로 계층3 에 영향한다.

상한을 얼마로 올릴지는 추측이 아니라 **원문 열 수 분포**로 정해야 한다. 이 스크립트는
적재 대상 표마다 '값이 있는 최대 열 위치+1' 을 세어 분포와 필요 상한을 낸다.

Usage
-----
    python scripts/qa_column_width_dist.py --limit 800
    python scripts/qa_column_width_dist.py --shard 0/10      # 전수
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.text import (_SECTION_META, _detect_body_statement_tables,
                               _detect_fin_type, _table_has_data_rows,
                               declared_unit)
from parser.common.amount_normalizer import parse_amount
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (SEC_CONSOL_NOTE, SEC_SEP_NOTE,
                                         assign_note_tables_with_titles,
                                         table_direct_rows)
from parser.xml.table_extractor import (_get_cells, _is_fs_title_row,
                                        _is_header_cell, _split_label_amounts)

TARGETS_SQL = """
    SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period, d.file_path
    FROM filings f JOIN download_tasks d USING (rcept_no)
    WHERE d.status='completed' AND d.file_type='xml' AND d.file_path IS NOT NULL
      AND f.fiscal_year >= 2015
    ORDER BY f.rcept_no
"""


def table_width(table, unit: int, *, date_labels_ok: bool, preserve: bool) -> int:
    """이 표에서 **값이 실제로 있는 최대 열 위치 + 1**. `extract_rows` 의 행 필터와
    선행 None pop 을 그대로 재현한다(그래야 num_cols 와 같은 좌표계가 된다)."""
    width = 0
    for tr in table_direct_rows(table):
        cells = _get_cells(tr)
        if not cells:
            continue
        if _is_header_cell(cells[0].strip(), allow_date_label=date_labels_ok) \
                or _is_fs_title_row(cells):
            continue
        label, amt_cells = _split_label_amounts(cells)
        if not label:
            continue
        parsed = [parse_amount(c, unit) for c in amt_cells]
        if len(parsed) >= 4 and not preserve:
            while parsed and parsed[0] is None:
                parsed.pop(0)
        last = max((i for i, v in enumerate(parsed) if v is not None), default=-1)
        width = max(width, last + 1)
    return width


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=800, help="0 = 전수")
    ap.add_argument("--shard", help="a/n")
    ap.add_argument("--seed", type=int, default=20260730)
    args = ap.parse_args()

    with get_session() as session:
        rows = list(session.execute(text(TARGETS_SQL)).fetchall())
    if args.shard:
        a, n = (int(x) for x in args.shard.split("/"))
        rows = [r for i, r in enumerate(rows) if i % n == a]
    elif args.limit:
        random.Random(args.seed).shuffle(rows)
        rows = rows[: args.limit]
    print(f"대상 {len(rows)} filing", flush=True)

    dist: dict[str, Counter[int]] = {"note": Counter(), "SCE": Counter()}
    t0 = time.time()
    n_filing = 0

    for i, f in enumerate(rows, 1):
        if i % 200 == 0:
            print(f"  … {i}/{len(rows)} ({(time.time()-t0)/i:.2f}s/filing)", flush=True)
        p = Path(f.file_path)
        if not p.exists():
            continue
        try:
            root = _parse_xml_file(p)
        except Exception:  # noqa: BLE001
            continue
        if root is None:
            continue
        n_filing += 1

        for code, tw in _detect_body_statement_tables(
                root, _detect_fin_type(root), include_sce=True).items():
            if not code.startswith("SCE"):
                continue
            for tb, unit, _ in tw:
                if unit is None:
                    continue
                dist["SCE"][table_width(tb, unit, date_labels_ok=True, preserve=True)] += 1

        sec = assign_note_tables_with_titles(root)
        for kind in (SEC_CONSOL_NOTE, SEC_SEP_NOTE):
            for tb, _title in sec.get(kind, []):
                unit = declared_unit(tb)
                if unit is None or not _table_has_data_rows(tb):
                    continue
                dist["note"][table_width(tb, unit, date_labels_ok=False, preserve=False)] += 1

    print(f"\n=== 금액 열 수 분포 (filing {n_filing:,}, {time.time()-t0:.0f}s) ===")
    for kind, cap in (("note", 8), ("SCE", 12)):
        c = dist[kind]
        total = sum(c.values())
        if not total:
            continue
        print(f"\n── {kind} (현재 상한 {cap}) · 표 {total:,}")
        over = sum(v for w, v in c.items() if w > cap)
        print(f"   상한 초과 표 {over:,} ({over/total*100:.3f}%) · 최대 열수 {max(c):,}")
        run = 0
        for w in sorted(c):
            run += c[w]
            mark = "  ← 현재 상한" if w == cap else ""
            if w <= 3 and kind == "note":
                continue
            print(f"     열수 {w:>3} : 표 {c[w]:>9,}  누적 {run/total*100:7.3f}%{mark}")
        # 커버리지 목표별 필요 상한
        for target in (99.0, 99.9, 99.99, 100.0):
            need, run2 = None, 0
            for w in sorted(c):
                run2 += c[w]
                if run2 / total * 100 >= target:
                    need = w
                    break
            print(f"   {target:6.2f}% 커버 → 상한 {need}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
