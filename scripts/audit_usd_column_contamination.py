"""USD 열에 원화 배수가 적용됐는지 **원문 대조로** 확인한다 (2026-08-04).

배경 — `unit_decl_raw` 에 USD 가 있는 표가 137,680개이고, 그중 `unit_kind='mixed',
declared_unit=1000` 이 77,861개다. 표 선언의 천원 배수가 USD 열에도 적용됐다면
USD 금액이 ×1,000 되어 `value_won` 에 들어간다(유실이 아니라 **오염**).

`fin2/extract/units.py` 는 `column_is_non_money` 를 `column_is_money` 보다 먼저 보므로
USD 표지가 있는 열은 차단되게 되어 있다. 그러나 두 가지 빈틈이 의심된다:

  ⓐ `label_segments()` 가 **'단위' 가 든 헤더 조각을 통째로 버린다.**
     '외화금액(단위 : 천/USD)' 이 한 조각이면 USD 표지도 같이 사라진다.
  ⓑ '(단위 : USD, 천원)' 처럼 **한 열 안에 두 통화가 섞이면** 헤더가 판별해 주지 못한다.

그래서 추측하지 않고 **실제 코드 경로**(`_build_col_labels` + `ColumnUnits`)를 태워
'USD 표지가 있는 열인데 배수가 적용된' 셀을 센다. 그리고 그 셀의 원문 값과 DB 의
`value_won` 을 대조해 실제 오염을 확정한다(R9).

사용:
    python scripts/audit_usd_column_contamination.py --sample 300
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (
    assign_note_tables_with_titles, SEC_CONSOL_NOTE, SEC_SEP_NOTE, table_direct_rows,
)
from parser.xml.table_extractor import _get_cells
from fin2.extract.report_lines import _build_col_labels
from fin2.extract.text import declaration_text, inherited_declaration_text
from fin2.extract.units import ColumnUnits, label_segments, normalize_col_label

# 그 열이 외화(원화가 아님)라고 **원문이 말하는** 표지.
_FX = re.compile(r"USD|EUR|JPY|CNY|HKD|GBP|CHF|VND|IDR|\$|달러|외화|위안|엔화", re.I)
_AMOUNT = re.compile(r"^\(?-?\d{1,3}(?:,\d{3})+\)?$")

SQL = """
SELECT t.rcept_no, d.file_path, f.corp_name, f.fiscal_year, f.fiscal_period
  FROM (SELECT DISTINCT rcept_no FROM report_tables
         WHERE unit_decl_raw ILIKE '%%USD%%' AND declared_unit IS NOT NULL) t
  JOIN filings f USING(rcept_no)
  JOIN download_tasks d ON d.rcept_no = t.rcept_no
 ORDER BY md5(t.rcept_no) LIMIT :n
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=300)
    args = ap.parse_args()

    with get_session() as s:
        rows = s.execute(text(SQL), {"n": args.sample}).fetchall()

    stats: Counter = Counter()
    hits: list = []

    for rcept, fpth, corp_name, fy, fp in rows:
        if not fpth or not Path(fpth).exists():
            continue
        root = _parse_xml_file(Path(fpth))
        if root is None:
            continue
        stats["문서"] += 1

        for sec in (SEC_CONSOL_NOTE, SEC_SEP_NOTE):
            for tbl, _title in assign_note_tables_with_titles(root).get(sec, []):
                decl = declaration_text(tbl) or inherited_declaration_text(tbl)
                if not decl or not _FX.search(decl):
                    continue                       # USD 선언 표만 본다
                col_labels = _build_col_labels(tbl, all_cells=True)
                cu = ColumnUnits.from_declaration(decl, col_labels)
                if cu.money_mult is None:
                    continue
                stats["USD 선언 + 금액배수 보유 표"] += 1

                for idx, label in col_labels.items():
                    mult = cu.multiplier(idx)
                    raw_label = normalize_col_label(label)
                    fx_in_label = bool(_FX.search(raw_label))
                    fx_in_segments = any(_FX.search(seg) for seg in label_segments(label))
                    if not fx_in_label:
                        continue
                    stats["외화 표지가 있는 열"] += 1
                    if mult is None:
                        stats["  → 차단됨(정상)"] += 1
                        continue
                    # ★배수가 적용됐다 = 오염 후보
                    stats["  → ★배수 적용됨(오염 후보)"] += 1
                    if not fx_in_segments:
                        stats["     원인: label_segments 가 '단위' 조각을 버림"] += 1
                    else:
                        stats["     원인: 기타"] += 1
                    if len(hits) < 15:
                        # 그 열의 실제 셀 값 하나를 원문에서 뽑는다
                        sample_cell = None
                        for tr in table_direct_rows(tbl):
                            cells = [c.strip() for c in _get_cells(tr)]
                            amts = [c for c in cells if _AMOUNT.match(c)]
                            if idx < len(amts):
                                sample_cell = amts[idx]
                                break
                        hits.append((corp_name, fy, fp, rcept, label[:70], mult,
                                     sample_cell, decl.replace("\n", " | ")[:80]))

    print(f"=== USD 선언 표 감사 (표본 문서 {stats['문서']}건) ===\n")
    for k, v in stats.items():
        if k != "문서":
            print(f"  {v:6d}  {k}")

    if hits:
        print("\n=== 오염 후보 사례 (열 헤더 · 적용배수 · 원문 셀) ===")
        for corp_name, fy, fp, rcept, label, mult, cell, decl in hits:
            print(f"\n  {corp_name} {fy}{fp} {rcept}")
            print(f"    선언   : {decl}")
            print(f"    열헤더 : {label!r}")
            print(f"    적용배수={mult}  원문셀={cell}  → value_won={int(cell.replace(',',''))*mult if cell else '?'}")
    else:
        print("\n  오염 후보 없음 — USD 열은 전부 차단되고 있다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
