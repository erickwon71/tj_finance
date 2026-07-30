"""D4 검증 — `_table_has_data_rows` 게이트를 **완화하면 무엇이 들어오는가** (READ-ONLY).

배경: F1 후 census 에서 '금액을 선언했는데 폐기된 표' 의 **100%가 단위 문제가 아니라 이
게이트**임이 드러났다(전수 2,199,735 표 / 9,501,682 셀). 게이트는 "콤마 3자리 금액을 가진
직접 데이터행이 **2 개 이상**"을 요구한다 — 표제표·stub 을 거르려는 장치인데, 작지만 진짜인
표('16. 결손금' 2셀 등)까지 걸린다.

사용자 결정(2026-07-31) = **완화한 상태로 표본을 원문 대조한 뒤 채택 여부를 정한다.**
이 스크립트가 그 표본을 만든다 — `minimum=1` 로 낮췄을 때 **새로 들어오는 표만** 골라
원문 그리드를 그대로 출력한다. 판정은 사람이 한다(도구가 '진짜 데이터'라고 주장하지 않는다).

    python scripts/probe_data_row_gate.py --limit 120 --show 30
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
from fin2.extract.report_lines import _build_col_labels
from fin2.extract.text import (_table_has_data_rows, declaration_text,
                               inherited_declaration_text)
from fin2.extract.units import ColumnUnits
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (SEC_CONSOL_NOTE, SEC_SEP_NOTE,
                                         assign_note_tables_with_titles,
                                         table_direct_rows)
from parser.xml.table_extractor import _get_cells

TARGETS_SQL = """
    SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period, d.file_path
    FROM filings f JOIN download_tasks d USING (rcept_no)
    WHERE d.status='completed' AND d.file_type='xml' AND d.file_path IS NOT NULL
      AND f.fiscal_year >= 2015
    ORDER BY f.rcept_no
"""


def grid(tbl, max_rows: int = 6, max_cols: int = 7) -> list[str]:
    out = []
    for tr in list(table_direct_rows(tbl))[:max_rows]:
        out.append(" | ".join(c.strip().replace("\n", " ")[:18]
                              for c in _get_cells(tr)[:max_cols]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--seed", type=int, default=20260731)
    ap.add_argument("--show", type=int, default=30)
    args = ap.parse_args()

    with get_session() as s:
        rows = list(s.execute(text(TARGETS_SQL)).fetchall())
    random.Random(args.seed).shuffle(rows)
    rows = rows[: args.limit]
    print(f"대상 {len(rows)} filing · 게이트 minimum 2 → 1 로 낮췄을 때의 증분만 본다\n", flush=True)

    t: Counter[str] = Counter()
    samples: list = []
    t0 = time.time()
    for i, f in enumerate(rows, 1):
        if i % 20 == 0:
            print(f"  … {i}/{len(rows)}", flush=True)
        p = Path(f.file_path)
        if not p.exists():
            continue
        try:
            root = _parse_xml_file(p)
            if root is None:
                continue
        except Exception:  # noqa: BLE001
            continue
        t["filing"] += 1
        sec = assign_note_tables_with_titles(root)
        for kind in (SEC_CONSOL_NOTE, SEC_SEP_NOTE):
            for tb, title in sec.get(kind, []):
                if _table_has_data_rows(tb):
                    t["현행 적재"] += 1
                    continue
                if not _table_has_data_rows(tb, minimum=1):
                    t["완화해도 제외"] += 1
                    continue
                # ── 여기부터가 '완화하면 새로 들어오는 표'
                t["★신규 편입 표"] += 1
                own = declaration_text(tb)
                decl = own or inherited_declaration_text(tb)
                cu = ColumnUnits.from_declaration(decl, _build_col_labels(tb, all_cells=True),
                                                  inherited=bool(decl and not own))
                cells = sum(1 for tr in table_direct_rows(tb) for c in _get_cells(tr)
                            if any(ch.isdigit() for ch in c))
                t["★신규 편입 숫자셀"] += cells
                t[f"선언:{cu.kind}"] += 1
                if len(samples) < 200:
                    samples.append((f.rcept_no, (title or "")[:40], cu.kind,
                                    (decl or "")[:50], cells, grid(tb)))

    n = max(t["filing"], 1)
    print(f"\n=== 게이트 완화 증분 (filing {n}, {time.time()-t0:.0f}s) ===")
    for k in ("현행 적재", "★신규 편입 표", "★신규 편입 숫자셀", "완화해도 제외"):
        print(f"  {k:<18}{t[k]:>10,}")
    print(f"  filing 당 신규 편입 표 {t['★신규 편입 표']/n:.1f} · 셀 {t['★신규 편입 숫자셀']/n:.1f}")
    print("\n  신규 편입 표의 선언 분류: " +
          " ".join(f"{k.split(':')[1]}={v:,}" for k, v in t.items() if k.startswith("선언:")))

    print(f"\n--- 원문 그리드 표본 {min(args.show, len(samples))} (사람이 판정할 것) ---")
    for rc, title, kind, decl, cells, g in samples[: args.show]:
        print(f"\n  [{rc}] {title} · 선언={kind} {decl!r} · 숫자셀 {cells}")
        for line in g:
            print(f"    | {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
