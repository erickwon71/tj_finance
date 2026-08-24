"""
Gate B 버그① 옵션 A 근본수정(커밋 이후) — 소급 백필 대상 filing 목록 산출.

`gateb_bugA_col_misselect_optionA_rootfix_plan_2026-08-24.md` §7: 이번 근본수정은
tax_expense 오버레이(옵션 B, fy>=2024 스코프)와 달리 **전 연도**에 걸쳐 영향(§3-1/§3-4-3
실측)이 있어 `--fy-min` 하나로 스코프를 좁힐 수 없다. `load_report_lines.py --recheck`
전량 재처리는 인터림(H1/Q1/Q3) 필링만 122,949건이라 너무 크다(전량 재처리 근거 없음 —
영향은 그중 cum_map 표가 있는 일부 행뿐).

이 스크립트는 "DB에 이미 적재된 값(=이 커밋 전 코드로 만들어진 값)"과 "지금 코드로 다시
추출했을 때의 값"을 실제로 비교해(추측 아님) **진짜 바뀌는 filing만** 골라
`--rcept-file`용 목록으로 뽑는다. 읽기전용(DB 쓰기 없음) — census_optionA_final_
design_2026-08-24.py 와 같은 비교 방법(구코드는 커밋 전 `_split_label_amounts()`를
로컬에 그대로 복제해 몽키패치, 신코드는 지금 커밋된 실제 프로덕션)이지만 표본이 아니라
**전수** + rcept_no 출력이 다르다.

사용법(샤딩 권장 — 인터림 IS/CF filing 전체 122,949건):
    python scripts/find_optionA_affected_filings_2026-08-24.py --shard 0/4
    python scripts/find_optionA_affected_filings_2026-08-24.py --shard 1/4
    ...
출력: scripts/optionA_affected_rcepts_2026-08-24.txt 에 rcept_no 한 줄씩 append
      (여러 샤드가 같은 파일에 안전하게 append — 각자 자기 결과만 씀, 파일 락 불요:
      각 프로세스가 자신의 shard 결과를 다 모은 뒤 한 번에 파일을 연다).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, "/Users/taejin/Project/tj_finance")

from collector.db import engine
from sqlalchemy import text

from parser.xml.dart_xml_parser import _parse_xml_file
import parser.xml.table_extractor as te
from fin2.extract.report_lines import _detect_body_statement_tables, _detect_fin_type
from fin2.extract.text import _interim_cumulative_cols

_OUT = Path(__file__).resolve().parent / "optionA_affected_rcepts_2026-08-24.txt"


# ── 커밋 전(이 세션 시작 시점) _split_label_amounts() 그대로 복제 — "구코드" 재현용.
# 지금 실제 함수(te._split_label_amounts)는 이미 고쳐진 버전이라 이걸로 대체할 수 없다.
def _split_label_amounts_pre_fix(cells, table_has_note_column=False):
    label = ""
    amount_cells: list[str] = []
    for i, cell in enumerate(cells):
        if i == 0:
            label = cell
        else:
            cell_nospace = cell.replace(' ', '')
            cell_nospace = te._TRAIL_DECOR_RE.sub('', cell_nospace)
            cell_stripped = cell_nospace.replace(',', '')
            if (i == 1
                    and not amount_cells
                    and te._NOTE_REF_PATTERN.match(cell_nospace)
                    and not te._AMOUNT_GROUPED_PATTERN.match(cell_nospace)
                    and (',' in cell_nospace or table_has_note_column)):
                continue
            if te._NUMBER_PATTERN.match(cell_stripped) or cell_stripped in ('-', '—', ''):
                amount_cells.append(cell)
    return label, amount_cells


_fixed_split = te._split_label_amounts  # 지금 커밋된(고쳐진) 실제 함수, 원본 저장


def _pairs_old(table, cum_map):
    """DB에 이미 적재돼 있는 값 재현 — 구코드(패치 전) + preserve_col_positions=False."""
    n_cols = max(cum_map) + 1
    te._split_label_amounts = _split_label_amounts_pre_fix
    try:
        rows = list(te.extract_rows(table, multiplier=1, num_cols=n_cols,
                                     direct_only=True, skip_junk=False,
                                     preserve_col_positions=False))
    finally:
        te._split_label_amounts = _fixed_split
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
    """지금 코드(이번 커밋 반영) 그대로."""
    n_cols = max(cum_map) + 1
    rows = list(te.extract_rows(table, multiplier=1, num_cols=n_cols,
                                 direct_only=True, skip_junk=False,
                                 preserve_col_positions=True))
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", default=None, help="a/n (예: 0/4) — 정렬 후 i%%n==a")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT DISTINCT rcept_no, corp_code, report_fiscal_year, report_fiscal_period "
            "FROM report_lines WHERE statement IN ('IS','CF') "
            "AND report_fiscal_period IN ('H1','Q1','Q3')"
        )).fetchall()
        meta = {r[0]: (r[1], r[2], r[3]) for r in rows}
        rcepts = sorted(meta)
        paths = dict(conn.execute(text(
            "SELECT rcept_no, file_path FROM download_tasks WHERE rcept_no = ANY(:r)"
        ), {"r": rcepts}).fetchall())

    if args.shard:
        a, n = (int(x) for x in args.shard.split("/"))
        rcepts = [r for i, r in enumerate(rcepts) if i % n == a]
    if args.limit:
        rcepts = rcepts[:args.limit]

    pool = [(r, paths[r]) for r in rcepts if paths.get(r)]
    print(f"scanning {len(pool):,} filings (shard={args.shard})", flush=True)

    affected: list[tuple[str, str]] = []
    err = 0
    for i, (rcept, fp) in enumerate(pool, 1):
        if i % 500 == 0:
            print(f"... {i}/{len(pool)}  affected so far: {len(affected)}  err: {err}", flush=True)
        try:
            root = _parse_xml_file(Path(fp))
            if root is None:
                err += 1
                continue
            fin_type = _detect_fin_type(root)
            groups = _detect_body_statement_tables(root, fin_type, include_sce=True)
        except Exception:
            err += 1
            continue

        changed = False
        for section_code, tables_with_unit in groups.items():
            if changed:
                break
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
                    old = _pairs_old(table, cum_map)
                    new = _pairs_new(table, cum_map)
                except Exception:
                    continue
                if len(old) != len(new):
                    changed = True
                    break
                if any(po != pn for (_, po), (_, pn) in zip(old, new)):
                    changed = True
                    break

        if changed:
            corp_code = meta[rcept][0]
            affected.append((rcept, corp_code))

    print(f"DONE shard={args.shard}: scanned {len(pool):,}, affected {len(affected):,}, err {err}")
    with open(_OUT, "a") as f:
        for rcept, corp_code in affected:
            f.write(f"{rcept}\t{corp_code}\n")
    print(f"appended {len(affected)} rows to {_OUT}")


if __name__ == "__main__":
    main()
