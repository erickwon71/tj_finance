"""
§3-4-3 재설계안 최종형 영향범위 실측 — for
docs/plans/gateb_bugA_col_misselect_optionA_rootfix_plan_2026-08-24.md §3-4-3/§3-5.

§3-4의 offset 설계(표당 상수 col_offset)는 코드로 구현해 재검증하다 두 가지 실측으로
반증됐다(§3-4-1/3-4-2) — 코드는 전부 되돌렸다. 이 스크립트는 그 뒤 도출한 **더 단순하고
검증된 재설계**를 다시 실측한다:

  ①(진짜 근본원인) `parser/xml/table_extractor.py::_split_label_amounts()`가
    `table_has_note_column=True`인 표에서 i==1 칸을 주석으로 인식하는 조건이
    `_NOTE_REF_PATTERN`(콤마 다중참조/콤마없는 단일숫자)에만 걸려 있어 **빈 주석칸**을
    못 걸러낸다 — 빈칸이면 콤마 유무·단일숫자 여부와 무관하게 그 표가 주석컬럼을 쓴다고
    이미 확정됐으므로(table_has_note_column) 항상 소비해야 한다.
  ②①을 고치면 amount_cells 폭이 표 전체에서 균일해져(콤마 있는 주석행/빈 주석행 모두
    이미 note 칸이 빠진 상태) **소비 측(cum_map)에 offset 보정이 전혀 필요 없어진다** —
    §1의 원래 1줄 스케치(`preserve_col_positions=(cum_map is not None)`, offset 없이
    그대로 `row.amounts[pos]`)로 충분하다.

수동검증(원문대조, 이 세션에서 실행·확인 완료, 계획서 §3-5 참고):
  - 코리안리 20211115001569(주석컬럼 있음): ①+②로 '법인세비용차감전순이익'
    당기누적=199,537,863,402/전기누적=171,530,344,675 재현(기존 우연정답과 일치).
  - 국일제지 00104573 20251113000801(주석컬럼 없음): ②만으로 '법인세비용(수익)'
    당기누적=-2,310,052,284 재현 — **2026-08-23 세션에서 DB 실측 확정한 정답과 일치**
    (당시는 overlay_tax_expense_value 옵션 B로 고쳤던 바로 그 값, 이번엔 근본수정
    경로로 독립 재현).

Method: `_split_label_amounts()`를 몽키패치(①의 로컬 사본)하고 `preserve_col_positions=
True`로 `extract_rows()`를 호출(②) → cum_map 기반 pairs를 현재 프로덕션(old, patch 없음,
preserve=False)과 비교. 두 함수 모두 실제 프로덕션 코드(table_extractor.extract_rows)이고
①만 로컬 사본(아직 프로덕션에 없는 동작이라 토글 불가 — census_optionA_cum_map_impact와
동일 사유).
"""
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/Users/taejin/Project/tj_finance")

from collector.db import engine
from sqlalchemy import text

from parser.xml.dart_xml_parser import _parse_xml_file
import parser.xml.table_extractor as te
from fin2.extract.report_lines import _detect_body_statement_tables, _detect_fin_type
from fin2.extract.text import _interim_cumulative_cols

_orig_split = te._split_label_amounts


def _split_label_amounts_proposed(cells, table_has_note_column=False):
    label = ""
    amount_cells: list[str] = []
    for i, cell in enumerate(cells):
        if i == 0:
            label = cell
        else:
            cell_nospace = cell.replace(' ', '')
            cell_nospace = te._TRAIL_DECOR_RE.sub('', cell_nospace)
            cell_stripped = cell_nospace.replace(',', '')
            if (i == 1 and not amount_cells and table_has_note_column
                    and cell_nospace == ''):
                continue  # ★제안된 변경(§3-4-3①): 빈 주석칸도 항상 소비
            if (i == 1
                    and not amount_cells
                    and te._NOTE_REF_PATTERN.match(cell_nospace)
                    and not te._AMOUNT_GROUPED_PATTERN.match(cell_nospace)
                    and (',' in cell_nospace or table_has_note_column)):
                continue
            if te._NUMBER_PATTERN.match(cell_stripped) or cell_stripped in ('-', '—', ''):
                amount_cells.append(cell)
    return label, amount_cells


def _pairs_old(table, cum_map):
    """현재 프로덕션 그대로(패치 없음, 6-column pop 압축 적용)."""
    n_cols = max(cum_map) + 1
    rows = list(te.extract_rows(table, multiplier=1, num_cols=n_cols,
                                 direct_only=True, skip_junk=False,
                                 preserve_col_positions=False))
    out = []
    for row in rows:
        pairs = [(off, row.amounts[pos]) for pos, off in cum_map.items()
                 if pos < len(row.amounts) and row.amounts[pos] is not None]
        if not pairs:
            present = [a for a in row.amounts if a is not None]
            pairs = list(enumerate(present))
        out.append((row.account_name, dict(pairs)))
    return out


def _pairs_new(table, cum_map):
    """①_split_label_amounts 패치 + ②preserve_col_positions=True, offset 없음."""
    n_cols = max(cum_map) + 1
    te._split_label_amounts = _split_label_amounts_proposed
    try:
        rows = list(te.extract_rows(table, multiplier=1, num_cols=n_cols,
                                     direct_only=True, skip_junk=False,
                                     preserve_col_positions=True))
    finally:
        te._split_label_amounts = _orig_split
    out = []
    for row in rows:
        pairs = [(off, row.amounts[pos]) for pos, off in cum_map.items()
                 if pos < len(row.amounts) and row.amounts[pos] is not None]
        if not pairs:
            present = [a for a in row.amounts if a is not None]
            pairs = list(enumerate(present))
        out.append((row.account_name, dict(pairs)))
    return out


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    random.seed(20260824)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT DISTINCT rcept_no, report_fiscal_year, report_fiscal_period "
            "FROM report_lines WHERE statement IN ('IS','CF') "
            "AND report_fiscal_period IN ('H1','Q1','Q3')"
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
    by_note_col = Counter()
    examples = []

    for i, (rcept, fp) in enumerate(sample, 1):
        if i == 1 or i % 20 == 0 or i == len(sample):
            print(f"... {i}/{len(sample)} filings  "
                  f"(cum_map_tables so far: {cnt['cum_map_tables']:,}, "
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
            if statement not in ("IS", "CF"):
                continue
            for table, _unit, _kind in tables_with_unit:
                try:
                    cum_map = _interim_cumulative_cols(table)
                except Exception:
                    continue
                if cum_map is None:
                    continue
                try:
                    trs = table.findall(".//TR")
                    rows_cells = [te._get_cells(tr) for tr in trs]
                    thnc = te._table_has_comma_note_column(rows_cells)
                except Exception:
                    continue
                cnt["cum_map_tables"] += 1
                by_year[fy] += 1
                by_note_col[thnc] += 1

                try:
                    old = _pairs_old(table, cum_map)
                    new = _pairs_new(table, cum_map)
                except Exception:
                    cnt["extract_err"] += 1
                    continue

                if len(old) != len(new):
                    cnt["row_count_mismatch"] += 1
                    continue
                for (label, p_old), (_label2, p_new) in zip(old, new):
                    cnt["rows_checked"] += 1
                    if p_old != p_new:
                        cnt["rows_changed"] += 1
                        by_year_changed[fy] += 1
                        if len(examples) < 30 and random.random() < 0.5:
                            examples.append((rcept, fy, fp_period, section_code, thnc,
                                              label, p_old, p_new))

    print(f"filings sampled                         : {len(sample)}  "
          f"(parse err {cnt['parse_err']}, detect err {cnt['detect_err']}, "
          f"extract err {cnt['extract_err']}, row-count mismatch {cnt['row_count_mismatch']})")
    print(f"cum_map tables (interim, 2-tier header)  : {cnt['cum_map_tables']:,}  "
          f"(has_note_column: {by_note_col.get(True, 0)}, no note col: {by_note_col.get(False, 0)})")
    print(f"rows checked                             : {cnt['rows_checked']:,}")
    print(f"rows changed by fix (old pairs != new)   : {cnt['rows_changed']:,} "
          f"({cnt['rows_changed'] / max(1, cnt['rows_checked']) * 100:.3f}%)")
    print()
    print("cum_map tables / changed rows by fiscal year:")
    for y in sorted(by_year):
        print(f"  {y}: tables={by_year[y]:5d}   rows_changed={by_year_changed.get(y, 0)}")
    print("=" * 70)
    for rcept, fy, fp_period, sec, thnc, label, p_old, p_new in examples:
        print(f"\n{rcept} fy{fy}{fp_period} [{sec}] has_note_col={thnc} label={label!r}")
        print(f"  old (current production)        pairs: {p_old}")
        print(f"  new (§3-4-3 final design)        pairs: {p_new}")


if __name__ == "__main__":
    main()
