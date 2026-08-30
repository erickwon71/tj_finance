"""
Blast-radius census for the §5.4 fix design in
docs/plans/gateb_trade_payables_classB_stale_column_investigation_2026-08-29.md
(trade_payables 클래스B 유형1 — Track B `_emit_section` 선두 None 절삭 재설계).

측정 대상: `fin2/extract/text.py::_emit_section()`(및 report_lines.py 동형 else 분기)의
non-cum_map(else) 경로에서, 현재 **무조건 절삭**되는 선두 None 컬럼 중 그 원본 셀이
실제로는 `<TE ACODE=... >`(XBRL 태그 있음)인데 `ACONTEXT` 속성이 없는(=원문이 명시적으로
"이 기간 미공시"라고 밝힌) 경우가 전체 corpus에서 얼마나 되는지 센다.

Method: 실제 프로덕션 함수(`_detect_fin_type`, `_detect_body_statement_tables`,
`_interim_cumulative_cols`, `extract_rows`, `_split_label_amounts`,
`_table_has_comma_note_column`)를 그대로 재사용한다. `_split_label_amounts`의 셀
선택 로직만 **판독용으로 그대로 복제**(count_cell_flags)해 amount_cells 와 나란히
"이 칸의 원본 엘리먼트가 TE+ACODE 있고 ACONTEXT 없는지" 불리언 배열을 만든다
(table_extractor.py 자체는 건드리지 않음 — read-only 계측).

카운트 정의:
  - `leading_none_rows`      : 현재 로직이 선두 None 을 1칸 이상 절삭하는 행 총수
  - `would_keep_rows`        : 그 절삭된 선두 None 중 **첫 번째 절삭 칸**이
                               TE+ACODE 있고 ACONTEXT 없는(=진짜 미공시) 행 —
                               §5.4 새 로직이면 절삭하지 않았을 행(=현재 오염 후보)
  - `would_strip_still_rows` : 나머지(§5.4 로직도 그대로 절삭 — 회귀 없음 확인용)
  - acode 별/재무제표유형별/연도별 분포
"""
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/Users/taejin/Project/tj_finance")

from lxml import etree
from sqlalchemy import text

from collector.db import engine
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.table_extractor import (
    extract_rows, _table_has_comma_note_column,
    _NOTE_REF_PATTERN, _AMOUNT_GROUPED_PATTERN, _NUMBER_PATTERN,
)
from fin2.extract.text import (
    _detect_fin_type, _detect_body_statement_tables, _interim_cumulative_cols,
)

# table_extractor.py 의 _split_label_amounts 내부 정규식과 동일해야 함(트레일 데코 제거).
_TRAIL_DECOR_RE = __import__("parser.xml.table_extractor", fromlist=["_TRAIL_DECOR_RE"])._TRAIL_DECOR_RE


def _cell_elements(tr) -> list:
    """`_get_cells`(table_extractor.py)와 동일한 태그 필터·순서로 **엘리먼트 자체**를 반환."""
    out = []
    for child in tr:
        tag = child.tag.upper() if isinstance(child.tag, str) else ""
        if tag in ("TD", "TH", "TE", "TU"):
            out.append(child)
    return out


def _acontext_missing(el) -> bool:
    """True: TE 이고 ACODE 는 있는데 ACONTEXT 속성이 없음(원문이 명시한 '이 기간 미공시')."""
    tag = el.tag.upper() if isinstance(el.tag, str) else ""
    if tag != "TE":
        return False
    if not el.get("ACODE"):
        return False
    return el.get("ACONTEXT") is None


def _split_label_amounts_with_flags(cells_text: list[str], cells_el: list,
                                     table_has_note_column: bool):
    """table_extractor.py::_split_label_amounts() 의 셀 선택 로직을 **그대로 복제**하되,
    살아남은 금액 셀마다 그 원본 엘리먼트의 acontext_missing 플래그를 나란히 반환한다.
    (계측 전용 — 프로덕션 코드는 건드리지 않는다.)
    """
    amount_cells: list[str] = []
    flags: list[bool] = []
    for i, cell in enumerate(cells_text):
        if i == 0:
            continue
        cell_nospace = cell.replace(' ', '')
        cell_nospace = _TRAIL_DECOR_RE.sub('', cell_nospace)
        cell_stripped = cell_nospace.replace(',', '')
        if (i == 1 and not amount_cells and table_has_note_column
                and cell_nospace == ''):
            continue
        if (i == 1
                and not amount_cells
                and _NOTE_REF_PATTERN.match(cell_nospace)
                and not _AMOUNT_GROUPED_PATTERN.match(cell_nospace)
                and (',' in cell_nospace or table_has_note_column)):
            continue
        if _NUMBER_PATTERN.match(cell_stripped) or cell_stripped in ('-', '—', ''):
            amount_cells.append(cell)
            flags.append(_acontext_missing(cells_el[i]) if i < len(cells_el) else False)
    return amount_cells, flags


def _rows_with_flags(table, num_cols: int):
    """extract_rows() 와 동일 필터(direct_only, skip_junk=False)로 순회하되, 각 행의
    amounts 와 같은 인덱스로 acontext_missing 플래그 배열도 함께 만든다."""
    from parser.xml.section_detector import table_direct_rows
    from parser.xml.table_extractor import _get_cells, _header_rule_name, _is_fs_title_row
    from parser.common.amount_normalizer import parse_amount

    trs = table_direct_rows(table)
    table_has_note_column = _table_has_comma_note_column([_get_cells(tr) for tr in trs])

    out = []
    for tr in trs:
        cells_text = _get_cells(tr)
        if not cells_text:
            continue
        first_text = cells_text[0].strip()
        if _header_rule_name(first_text) is not None:
            continue
        if _is_fs_title_row(cells_text):
            continue
        cells_el = _cell_elements(tr)
        label = cells_text[0]
        if not label:
            continue
        amount_cells, flags = _split_label_amounts_with_flags(
            cells_text, cells_el, table_has_note_column)
        all_parsed = [parse_amount(ac, 1) for ac in amount_cells]
        if len(all_parsed) >= 4:
            while all_parsed and all_parsed[0] is None:
                all_parsed.pop(0)
                flags.pop(0)
        amounts = [all_parsed[i] if i < len(all_parsed) else None for i in range(num_cols)]
        flags_padded = [flags[i] if i < len(flags) else False for i in range(num_cols)]
        out.append((label.strip(), amounts, flags_padded))
    return out


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    random.seed(20260829)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT d.rcept_no, d.file_path, f.fiscal_year, f.fiscal_period "
            "FROM download_tasks d JOIN filings f ON f.rcept_no = d.rcept_no "
            "WHERE d.parser_track = 'B' AND d.file_path IS NOT NULL"
        )).fetchall()
    pool = [(r[0], r[1], r[2], r[3]) for r in rows]
    print(f"Track B population: {len(pool):,} filings")
    sample = random.sample(pool, min(n, len(pool)))

    cnt = Counter()
    by_year = Counter()
    by_year_keep = Counter()
    by_stmt_keep = Counter()
    affected_rcepts = set()
    affected_rcepts_by_year = {}
    examples = []

    for i, (rcept, fp, fy, period) in enumerate(sample, 1):
        if i == 1 or i % 100 == 0 or i == len(sample):
            print(f"... {i}/{len(sample)} filings  "
                  f"(rows_checked={cnt['rows_checked']:,}, "
                  f"leading_none_rows={cnt['leading_none_rows']:,}, "
                  f"would_keep_rows={cnt['would_keep_rows']:,})", flush=True)
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
            groups = _detect_body_statement_tables(root, fin_type)
        except Exception:
            cnt["detect_err"] += 1
            continue

        for section_code, tables_with_unit in groups.items():
            fs_section = section_code.split("_")[0].lower()
            statement = section_code.split("_")[0]
            interim_flow = fs_section in ("is", "cf") and period in ("H1", "Q1", "Q3")
            tables = [t for t, _, _ in tables_with_unit]
            for table in tables:
                cum_map = _interim_cumulative_cols(table) if interim_flow else None
                if cum_map is not None:
                    continue  # 이 census 는 else(non-cum_map) 경로만 대상
                try:
                    rows_flags = _rows_with_flags(table, num_cols=3)
                except Exception:
                    cnt["extract_err"] += 1
                    continue

                for label, amounts, flags in rows_flags:
                    cnt["rows_checked"] += 1
                    # OLD(현재 프로덕션): 선두 None 무조건 절삭.
                    lead_old = 0
                    while lead_old < len(amounts) and amounts[lead_old] is None:
                        lead_old += 1
                    pairs_old = {i: a for i, a in enumerate(amounts[lead_old:]) if a is not None}
                    if lead_old == 0:
                        continue  # 절삭 자체가 없는 행 — 무영향(빠른 스킵)
                    cnt["leading_none_rows"] += 1
                    by_year[fy] += 1
                    # NEW(§5.4): acontext_missing=True 인 선두 None 앞에서 절삭 중단.
                    lead_new = 0
                    while (lead_new < len(amounts) and amounts[lead_new] is None
                           and not flags[lead_new]):
                        lead_new += 1
                    pairs_new = {i: a for i, a in enumerate(amounts[lead_new:]) if a is not None}
                    if pairs_old != pairs_new:
                        cnt["would_keep_rows"] += 1
                        by_year_keep[fy] += 1
                        by_stmt_keep[statement] += 1
                        affected_rcepts.add(rcept)
                        affected_rcepts_by_year.setdefault(fy, set()).add(rcept)
                        if len(examples) < 40 and random.random() < 0.5:
                            examples.append((rcept, fy, period, statement, section_code,
                                              label, amounts, flags, pairs_old, pairs_new))
                    else:
                        cnt["would_strip_still_rows"] += 1

    print()
    print(f"filings sampled                          : {len(sample)}  "
          f"(parse err {cnt['parse_err']}, detect err {cnt['detect_err']}, "
          f"extract err {cnt['extract_err']})")
    print(f"rows checked (non-cum_map else branch)    : {cnt['rows_checked']:,}")
    print(f"rows with leading-None strip (current)    : {cnt['leading_none_rows']:,}")
    print(f"  → would KEEP unstripped under §5.4       : {cnt['would_keep_rows']:,} "
          f"({cnt['would_keep_rows'] / max(1, cnt['leading_none_rows']) * 100:.2f}% of stripped rows)")
    print(f"  → would still strip (unchanged, safe net): {cnt['would_strip_still_rows']:,}")
    print()
    print(f"distinct AFFECTED filings (rcept_no)      : {len(affected_rcepts)} "
          f"/ {len(sample)} sampled ({len(affected_rcepts) / len(sample) * 100:.2f}%)")
    print("would-keep rows by fiscal year:")
    for y in sorted(by_year_keep):
        print(f"  {y}: rows={by_year_keep[y]}  distinct_filings={len(affected_rcepts_by_year.get(y, ()))}")
    print()
    print("would-keep rows by statement:")
    for s, c in by_stmt_keep.most_common():
        print(f"  {s}: {c}")
    print("=" * 70)
    for rcept, fy, period, stmt, sec, label, amounts, flags, pairs_old, pairs_new in examples:
        print(f"\n{rcept} fy{fy}{period} [{sec}] label={label!r}")
        print(f"  amounts={amounts}  acontext_missing_flags={flags}")
        print(f"  old pairs={pairs_old}  new pairs={pairs_new}")


if __name__ == "__main__":
    main()
