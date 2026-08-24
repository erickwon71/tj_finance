"""
Phase 0 / §3-3-5 impact measurement for
docs/plans/gateb_bugA_col_misselect_optionA_rootfix_plan_2026-08-24.md.

★ 2026-08-24 개정 — §3-1 실측으로 "narrow fix"(preserve_col_positions bool 하나)가
틀렸음이 드러난 뒤, §3-3 offset 보정 설계로 갱신된 버전(§3-3-5 step 2). 이제 raw
`.amounts` 배열 diff가 아니라 **실제로 emit되는 (period_offset -> amount) pairs**를
old(buggy)/new(offset-corrected) 두 로직으로 각각 시뮬레이션해 비교한다 — report_lines.py
/ text.py 가 실제로 하는 일과 동형이어야 "고쳐지는 게 맞는지" 판단할 수 있다(단순 배열
비교는 코리안리류 주석컬럼 표에서 오탐을 낸다, §3-1).

old(현재 프로덕션, 이 세션 패치 전):
    cum_map = _interim_cumulative_cols(table)  # offset 없음
    n_cols = max(cum_map) + 1
    rows = extract_rows(..., preserve_col_positions=False)
    pairs = [(off, row.amounts[pos]) for pos, off in cum_map.items()
             if pos < len(row.amounts) and row.amounts[pos] is not None]
    (비면 present 순서 폴백)

new(§3-3 offset 보정):
    col_offset, cum_map = _interim_cumulative_layout(table)
    n_cols = col_offset + max(cum_map) + 1
    rows = extract_rows(..., preserve_col_positions=True)
    pairs = [(off, row.amounts[col_offset + pos]) for pos, off in cum_map.items()
             if col_offset + pos < len(row.amounts)
             and row.amounts[col_offset + pos] is not None]
    (비면 present 순서 폴백 — old와 동일 폴백 로직)

Method: 실제 프로덕션 함수(`extract_rows()`, `_interim_cumulative_cols()`/
`_interim_cumulative_layout()`)를 그대로 호출한다 — 로직 재구현이 아니라 두 버전을
나란히 시뮬레이션. Read-only, DB 값은 truth로 안 씀(§3-3-5 step 3 원문대조가 별도).

기대: 코리안리류(주석컬럼 있는 표, offset=1)에서 old==new(둘 다 정답, §3-1에서 이미
확인) — "바뀌는 행"에 더 이상 안 잡혀야 한다. 00104573/00172291류(offset=0, 진짜
당기3개월 disclosure 누락)에서만 old!=new 로 남아야 한다.
"""
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/Users/taejin/Project/tj_finance")

from collector.db import engine
from sqlalchemy import text

from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.table_extractor import extract_rows
from fin2.extract.report_lines import _detect_body_statement_tables, _detect_fin_type
from fin2.extract.text import _interim_cumulative_cols, _interim_cumulative_layout


def _pairs_old(table, cum_map):
    n_cols = max(cum_map) + 1
    rows = list(extract_rows(table, multiplier=1, num_cols=n_cols,
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


def _pairs_new(table, col_offset, cum_map):
    n_cols = col_offset + max(cum_map) + 1
    rows = list(extract_rows(table, multiplier=1, num_cols=n_cols,
                              direct_only=True, skip_junk=False,
                              preserve_col_positions=True))
    out = []
    for row in rows:
        pairs = [(off, row.amounts[col_offset + pos]) for pos, off in cum_map.items()
                 if col_offset + pos < len(row.amounts)
                 and row.amounts[col_offset + pos] is not None]
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
    by_offset = Counter()
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
                    layout = _interim_cumulative_layout(table)
                except Exception:
                    continue
                if layout is None:
                    continue  # plan §1: fix is a no-op outside this path
                col_offset, cum_map = layout
                cnt["cum_map_tables"] += 1
                by_year[fy] += 1
                by_offset[col_offset] += 1

                try:
                    old = _pairs_old(table, cum_map)
                    new = _pairs_new(table, col_offset, cum_map)
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
                            examples.append((rcept, fy, fp_period, section_code,
                                              col_offset, label, p_old, p_new))

    print(f"filings sampled                         : {len(sample)}  "
          f"(parse err {cnt['parse_err']}, detect err {cnt['detect_err']}, "
          f"extract err {cnt['extract_err']}, row-count mismatch {cnt['row_count_mismatch']})")
    print(f"cum_map tables (interim, 2-tier header)  : {cnt['cum_map_tables']:,}")
    print(f"  by col_offset: {dict(sorted(by_offset.items()))}")
    print(f"rows checked                             : {cnt['rows_checked']:,}")
    print(f"rows changed by fix (old pairs != new)   : {cnt['rows_changed']:,} "
          f"({cnt['rows_changed'] / max(1, cnt['rows_checked']) * 100:.3f}%)")
    print()
    print("cum_map tables / changed rows by fiscal year:")
    for y in sorted(by_year):
        print(f"  {y}: tables={by_year[y]:5d}   rows_changed={by_year_changed.get(y, 0)}")
    print("=" * 70)
    for rcept, fy, fp_period, sec, col_offset, label, p_old, p_new in examples:
        print(f"\n{rcept} fy{fy}{fp_period} [{sec}] col_offset={col_offset} label={label!r}")
        print(f"  old (current, offset-blind) pairs: {p_old}")
        print(f"  new (§3-3 offset-corrected) pairs: {p_new}")


if __name__ == "__main__":
    main()
