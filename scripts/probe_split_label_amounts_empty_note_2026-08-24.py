"""
§3-4-3 재설계안 ① 영향범위 실측 — for
docs/plans/gateb_bugA_col_misselect_optionA_rootfix_plan_2026-08-24.md §3-4-3.

가설: `parser/xml/table_extractor.py::_split_label_amounts()`(R19)가 `table_has_note_
column=True`인 표에서 라벨 바로 다음 칸(i==1)을 주석으로 인식하는 조건이 `_NOTE_REF_
PATTERN`(콤마 다중참조, 또는 콤마없는 단일숫자+table_has_note_column)에만 걸려 있어
**빈 칸(주석 없음)**을 못 걸러낸다 — 그 결과 그 칸이 amount_cells 첫 칸(빈칸→None)으로
새는데, 이게 §3-1/§3-4가 추적한 col-misselect 버그의 진짜 근원(주석컬럼이 있는 표에서
"당기3개월 누락"과 증상이 같은 선행 None을 만듦)이다.

이 스크립트는 그 가설의 **적용범위**(빈 칸을 항상 주석으로 소비하도록 고치면 몇 건이
바뀌는지, 반례가 있는지)를 실측한다 — `_split_label_amounts()`를 직접 고치기 전에.

Method: `_split_label_amounts()`(실제 프로덕션 함수, 안 건드림)와 그 옆에 **제안된 수정만
반영한 로컬 사본**(scripts/census_body_span_impact.py 와 같은 패턴 — 아직 존재하지 않는
동작이라 프로덕션에 토글이 없으므로 비교하려면 사본이 불가피)을 나란히 돌려 amount_cells
결과를 diff한다. BS/IS/CF **전체**(FY 포함, interim 한정 아님) 대상 — `_split_label_
amounts` 가 이 버그(interim cum_map)와 무관한 표에도 공유되는 함수라 부작용 범위를
넓게 봐야 한다(계획서 §3-4-3 리스크 노트).

Read-only, DB 값은 참조만(표본 선정용) — 결과 truth 아님. 원문대조는 사람이 examples로.
"""
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/Users/taejin/Project/tj_finance")

from collector.db import engine
from sqlalchemy import text

from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.table_extractor import (
    _get_cells, _split_label_amounts, _table_has_comma_note_column,
    _header_rule_name, _is_fs_title_row,
    _NOTE_REF_PATTERN, _AMOUNT_GROUPED_PATTERN, _TRAIL_DECOR_RE, _NUMBER_PATTERN,
)
from fin2.extract.text import _detect_body_statement_tables, _detect_fin_type, _interim_cumulative_cols


def _split_label_amounts_proposed(cells, table_has_note_column=False):
    """`_split_label_amounts()`와 동일하되, i==1 칸이 **빈칸**이고
    `table_has_note_column`이면(콤마참조·단일숫자와 마찬가지로) 주석칸으로 소비한다
    (기존은 이 경우만 못 걸러 amount_cells 첫 칸(None)으로 샘 — 계획서 §3-4-2).
    나머지 로직은 원본과 100% 동일(비교를 위해 그대로 복제)."""
    label = ""
    amount_cells: list[str] = []
    for i, cell in enumerate(cells):
        if i == 0:
            label = cell
        else:
            cell_nospace = cell.replace(' ', '')
            cell_nospace = _TRAIL_DECOR_RE.sub('', cell_nospace)
            cell_stripped = cell_nospace.replace(',', '')
            if (i == 1 and not amount_cells and table_has_note_column
                    and cell_nospace == ''):
                continue  # ★제안된 변경: 빈 주석칸도 항상 소비
            if (i == 1
                    and not amount_cells
                    and _NOTE_REF_PATTERN.match(cell_nospace)
                    and not _AMOUNT_GROUPED_PATTERN.match(cell_nospace)
                    and (',' in cell_nospace or table_has_note_column)):
                continue
            if _NUMBER_PATTERN.match(cell_stripped) or cell_stripped in ('-', '—', ''):
                amount_cells.append(cell)
    return label, amount_cells


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    random.seed(20260824)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT DISTINCT rcept_no, report_fiscal_year, report_fiscal_period "
            "FROM report_lines WHERE statement IN ('BS','IS','CF')"
        )).fetchall()
        meta = {r[0]: (r[1], r[2]) for r in rows}
        rcepts = list(meta)
        paths = dict(conn.execute(text(
            "SELECT rcept_no, file_path FROM download_tasks WHERE rcept_no = ANY(:r)"
        ), {"r": rcepts}).fetchall())
    pool = [(r, paths[r]) for r in rcepts if paths.get(r)]
    sample = random.sample(pool, min(n, len(pool)))

    cnt = Counter()
    by_year = Counter()
    by_year_changed = Counter()
    by_statement_changed = Counter()
    examples = []

    for i, (rcept, fp) in enumerate(sample, 1):
        if i == 1 or i % 20 == 0 or i == len(sample):
            print(f"... {i}/{len(sample)} filings  "
                  f"(note_col_tables so far: {cnt['note_col_tables']:,}, "
                  f"rows_changed so far: {cnt['rows_changed']:,})", flush=True)
        fy, fp_period = meta[rcept]
        try:
            root = _parse_xml_file(Path(fp))
        except Exception:
            cnt["parse_err"] += 1
            continue
        if root is None:
            cnt["parse_err"] += 1
            continue
        try:
            fin_type = _detect_fin_type(root)
            groups = _detect_body_statement_tables(root, fin_type, include_sce=True)
        except Exception:
            cnt["detect_err"] += 1
            continue

        for section_code, tables_with_unit in groups.items():
            statement = section_code.split("_")[0]
            if statement not in ("BS", "IS", "CF"):
                continue
            for table, _unit, _kind in tables_with_unit:
                try:
                    trs = table.findall(".//TR")
                    rows_cells = [_get_cells(tr) for tr in trs]
                except Exception:
                    continue
                table_has_note_column = _table_has_comma_note_column(rows_cells)
                if not table_has_note_column:
                    continue  # 가설이 적용 안 되는 표(기존 동작 무변화 보장 범위 밖)
                cnt["note_col_tables"] += 1
                by_year[fy] += 1

                # ★위험 경로 분류 — cum_map(절대위치 인덱싱) 경로만 진짜 위험하다(§1 기존
                # 확인: multicol/else 경로는 이미 자체 재압축이라 앞쪽 빈칸 1개 더 스치는 건
                # 결과에 영향 없음, lead-strip이 어차피 선행 None 전부를 건너뛰므로). 이 표가
                # 실제로 cum_map 경로를 타는지 계산해 "바뀌는 행" 중 몇 건이 진짜 위험 경로인지
                # 분리 집계한다.
                interim_flow = statement in ("IS", "CF") and fp_period in ("H1", "Q1", "Q3")
                cum_map = _interim_cumulative_cols(table) if interim_flow else None
                risky_path = cum_map is not None

                for cells in rows_cells:
                    if not cells:
                        continue
                    first_text = cells[0].strip()
                    if _header_rule_name(first_text) or _is_fs_title_row(cells):
                        continue
                    label_old, amt_old = _split_label_amounts(cells, table_has_note_column)
                    label_new, amt_new = _split_label_amounts_proposed(cells, table_has_note_column)
                    if not label_old:
                        continue
                    cnt["rows_checked"] += 1
                    if amt_old != amt_new:
                        cnt["rows_changed"] += 1
                        by_year_changed[fy] += 1
                        by_statement_changed[statement] += 1
                        cnt["rows_changed_risky_cum_map"] += int(risky_path)
                        cnt["rows_changed_safe_other"] += int(not risky_path)
                        if len(examples) < 40 and random.random() < 0.5:
                            examples.append((rcept, fy, fp_period, section_code, risky_path,
                                              label_old, cells[1] if len(cells) > 1 else "",
                                              amt_old, amt_new))

    print(f"filings sampled                         : {len(sample)}  "
          f"(parse err {cnt['parse_err']}, detect err {cnt['detect_err']})")
    print(f"note-column tables (table_has_note_col)  : {cnt['note_col_tables']:,}")
    print(f"rows checked (in note-column tables)     : {cnt['rows_checked']:,}")
    print(f"rows changed by proposed fix             : {cnt['rows_changed']:,} "
          f"({cnt['rows_changed'] / max(1, cnt['rows_checked']) * 100:.3f}%)")
    print(f"  of which risky path (cum_map, interim IS/CF, absolute-position): "
          f"{cnt['rows_changed_risky_cum_map']:,}")
    print(f"  of which safe path (BS / multicol / plain-FY lead-strip, self-correcting): "
          f"{cnt['rows_changed_safe_other']:,}")
    print()
    print("note-col tables / changed rows by fiscal year:")
    for y in sorted(by_year):
        print(f"  {y}: tables={by_year[y]:5d}   rows_changed={by_year_changed.get(y, 0)}")
    print()
    print("changed rows by statement:", dict(by_statement_changed))
    print("=" * 70)
    for rcept, fy, fp_period, sec, risky, label, note_cell, amt_old, amt_new in examples:
        print(f"\n{rcept} fy{fy}{fp_period} [{sec}] risky_path={risky} label={label!r} note_cell={note_cell!r}")
        print(f"  old (current) amount_cells: {amt_old}")
        print(f"  new (proposed) amount_cells: {amt_new}")


if __name__ == "__main__":
    main()
