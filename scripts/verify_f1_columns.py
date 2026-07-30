"""F1 검증 — 추출기가 **열마다** 무엇을 채웠는지 원문과 나란히 본다 (READ-ONLY).

집계로 끝내지 않기 위한 도구다. 한 filing 을 실제 추출 경로(`extract_report_lines`)로 돌려
표별·열별로 다음을 보여준다:

    col_label(원문 열 헤더) · unit_source(근거) · value_won(적재값) · value_raw(원문 문자열)

확인 항목:
  · 비금액 열(이자율(%)·지분율(%)·주식수)에 value_won 이 **없어야** 한다 → 오염 제거 확인
  · 그 칸에 value_raw 가 **있어야** 한다               → 정보 손실 없음 확인
  · 금액 열은 value_won 이 채워지고 value_raw 는 NULL   → 중복 저장 없음 확인

Usage
-----
    python scripts/verify_f1_columns.py --rcept 20150817000851
    python scripts/verify_f1_columns.py --rcept 20250317001028 --grep 이자율
    python scripts/verify_f1_columns.py --rcept 20150817000851 --only-unfilled
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import extract_report_lines

PATH_SQL = text("""
    SELECT d.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
    FROM download_tasks d JOIN filings f USING (rcept_no)
    WHERE d.rcept_no = :r AND d.file_type='xml' AND d.file_path IS NOT NULL LIMIT 1
""")


def dump_raw_table(path: Path, spec: str) -> int:
    """주석 표 하나의 **원문 셀**을 그대로 출력한다(basis:table_seq).

    구형 EUC-KR 보고서는 grep 으로 못 열기 때문에(바이트가 UTF-8 이 아니다) 원문 확인은
    반드시 추출기와 같은 파싱 경로로 해야 한다 — 이 함수가 그 창구다.
    """
    from parser.xml.dart_xml_parser import _parse_xml_file
    from parser.xml.section_detector import (SEC_CONSOL_NOTE, SEC_SEP_NOTE,
                                             assign_note_tables_with_titles,
                                             table_direct_rows)
    from parser.xml.table_extractor import _get_cells
    from fin2.extract.report_lines import _build_col_labels
    from fin2.extract.text import declaration_text

    basis, seq = spec.split(":")
    kind = SEC_CONSOL_NOTE if basis.startswith("con") else SEC_SEP_NOTE
    root = _parse_xml_file(path)
    tables = assign_note_tables_with_titles(root).get(kind, [])
    idx = int(seq)
    if idx >= len(tables):
        print(f"{basis} 주석 표 {len(tables)} 개뿐 — seq={idx} 없음")
        return 1
    table, title = tables[idx]
    print(f"=== {basis} table_seq={idx} · 표제 {(title or '')[:80]}")
    print(f"  단위 선언 원문: {declaration_text(table)!r}")
    print(f"  복원된 열 라벨 : {_build_col_labels(table)}")
    for i, tr in enumerate(table_direct_rows(table)):
        print(f"  TR{i:<3} " + " | ".join(c.strip() for c in _get_cells(tr)))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rcept", required=True)
    ap.add_argument("--grep", help="label_raw·col_label·table_title 부분일치 필터")
    ap.add_argument("--only-unfilled", action="store_true",
                    help="value_won 이 비어 있는 행만(원문 보존 확인용)")
    ap.add_argument("--max-tables", type=int, default=12)
    ap.add_argument("--dump", metavar="BASIS:SEQ",
                    help="그 주석 표의 **원문 셀**을 그대로 찍는다(예 separate:1) — 열 귀속이 "
                         "맞는지는 원문 표를 봐야 판정할 수 있다")
    args = ap.parse_args()

    with get_session() as s:
        row = s.execute(PATH_SQL, {"r": args.rcept}).fetchone()
    if not row:
        print(f"filing {args.rcept} 없음(다운로드 안 됨)")
        return 1

    if args.dump:
        return dump_raw_table(Path(row.file_path), args.dump)

    lines = [l for l in extract_report_lines(
        Path(row.file_path), rcept_no=args.rcept, corp_code=row.corp_code,
        report_fiscal_year=row.fiscal_year, report_fiscal_period=row.fiscal_period,
        include_notes=True) if l.statement == "note"]

    print(f"filing {args.rcept} · note 행 {len(lines):,}\n")

    hints = Counter(l.header_hint for l in lines if l.header_hint)
    if hints:
        print("--- header_hint 분포 (F2 — 종전에는 이 행들이 통째로 삭제됐다) ---")
        for k, v in hints.most_common():
            print(f"  {k:<12}{v:>8,}")
        print()

    src = Counter(l.unit_source for l in lines)
    filled = sum(1 for l in lines if l.value_won is not None)
    print("--- unit_source 분포 ---")
    for k, v in src.most_common():
        print(f"  {str(k):<14}{v:>8,}")
    print(f"  value_won 채움 {filled:,} / 원문만 {len(lines)-filled:,}")
    bad = [l for l in lines if l.value_won is None and not l.value_raw]
    print(f"  ★값도 원문도 없는 행: {len(bad)}   ← 0 이어야 한다(정보 손실)")
    dup = [l for l in lines if l.value_won is not None and l.value_raw]
    print(f"  ★값과 원문을 둘 다 저장한 행: {len(dup)}   ← 0 이어야 한다(중복 저장)")

    by_table: dict[tuple, list] = defaultdict(list)
    for l in lines:
        by_table[(l.basis, l.table_seq, l.table_title)].append(l)

    shown = 0
    for (basis, seq, title), rows in sorted(by_table.items(), key=lambda x: (x[0][0] or "", x[0][1])):
        if args.grep and not any(
                args.grep in (getattr(l, f) or "") for l in rows
                for f in ("label_raw", "col_label", "table_title")):
            continue
        if args.only_unfilled and all(l.value_won is not None for l in rows):
            continue
        if shown >= args.max_tables:
            break
        shown += 1
        print(f"\n=== {basis} table_seq={seq} · {(title or '')[:70]}")
        print(f"  {'label':<26}{'col':>4} {'col_label':<26}{'unit_source':<13}"
              f"{'value_won':>20} value_raw")
        for l in rows[:24]:
            if args.only_unfilled and l.value_won is not None:
                continue
            print(f"  {l.label_raw[:25]:<26}{l.col_index:>4} "
                  f"{(l.col_label or '')[:25]:<26}{str(l.unit_source):<13}"
                  f"{(f'{l.value_won:,}' if l.value_won is not None else '—'):>20} "
                  f"{l.value_raw or ''}")
        if len(rows) > 24:
            print(f"  … 그 외 {len(rows)-24} 행")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
