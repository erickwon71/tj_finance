"""Read-only triage of the REMAINING note-scope missing_row issues, one at a time.

    python scripts/note_remaining_triage.py                     # category counts
    python scripts/note_remaining_triage.py --cat total -n 10   # 10 random issues of a category
    python scripts/note_remaining_triage.py --show 123456       # one issue: source table vs DB rows

Categories (same as docs/qa/handoff_2026-10-29_note_remaining_missing.md):
    other, total, unlabeled, shares_or_price, currency_code

`--show` prints what the machine saw: the source table rows around the missing amount (the DART XML,
spans expanded, printed text) next to the note_lines rows of the paired DB table, plus the DART link
and the XML path. Nothing is written. Issue ids come from `verification.issues` (scope='note').
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from collector.db import engine  # noqa: E402

CATEGORY_SQL = """
    CASE WHEN account_label ~ '^(USD|EUR|JPY|CNY|GBP|CHF|HKD|TWD|PHP|VND|IDR|THB|SGD|AUD|CAD|INR|MYR|RUB|BRL|MXN)$'
              THEN 'currency_code'
         WHEN account_label ~ '합계|소계|총계|^계$' THEN 'total'
         WHEN account_label ~ '^(열|행) [0-9]+$' THEN 'unlabeled'
         WHEN account_label ~ '보통주|우선주|행사가격|주식수|주당' THEN 'shares_or_price'
         ELSE 'other' END"""
OPEN = "status IN ('open', 'reopened')"
DART = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"


def counts() -> None:
    with engine.connect() as c:
        rows = c.execute(text(f"""
            SELECT {CATEGORY_SQL} AS cat, error_type, count(*) n, count(DISTINCT rcept_no) filings
            FROM verification.issues WHERE scope = 'note' AND {OPEN}
            GROUP BY 1, 2 ORDER BY 2, 3 DESC""")).fetchall()
    print(f"{'error_type':14s} {'category':16s} {'issues':>9s} {'filings':>8s}")
    for cat, et, n, f in rows:
        print(f"{et:14s} {cat:16s} {n:9d} {f:8d}")


def sample(cat: str, n: int) -> None:
    with engine.connect() as c:
        rows = c.execute(text(f"""
            SELECT issue_id, rcept_no, basis, table_ref, account_label, column_label,
                   source_value_raw, status
            FROM verification.issues
            WHERE scope = 'note' AND {OPEN} AND error_type = 'missing_row' AND ({CATEGORY_SQL}) = :c
            ORDER BY md5(issue_id::text) LIMIT :n"""), {"c": cat, "n": n}).fetchall()
    for r in rows:
        print(f"#{r.issue_id} [{r.status}] {r.rcept_no} {r.basis} 표{r.table_ref} "
              f"'{r.account_label[:24]}' {r.column_label[:40]}  원문값={r.source_value_raw}")
        print(f"      → python scripts/note_remaining_triage.py --show {r.issue_id}")


def show(issue_id: int) -> None:
    from fin2.verification import machine_biz as mb
    from fin2.verification import machine_note as mn
    from fin2.verification.machine_pass_scope import _source_path

    with engine.connect() as c:
        i = c.execute(text("""SELECT * FROM verification.issues WHERE issue_id = :i AND scope = 'note'"""),
                      {"i": issue_id}).mappings().fetchone()
        if i is None:
            raise SystemExit(f"note 이슈 #{issue_id} 없음")
        path = _source_path(c, i["rcept_no"])
        meta = c.execute(text("""SELECT c.corp_name, f.fiscal_year, f.fiscal_period, f.report_nm
                                 FROM filings f JOIN corporations c USING (corp_code) WHERE f.rcept_no = :r"""),
                         {"r": i["rcept_no"]}).fetchone()
        tab = c.execute(text("""SELECT table_title, section_path, declared_unit, unit_kind FROM report_tables
                                WHERE rcept_no = :r AND statement = 'note' AND basis = :b AND table_seq = :s"""),
                        {"r": i["rcept_no"], "b": i["basis"], "s": int(i["table_ref"])}).fetchone()
        db_rows = c.execute(text("""
            SELECT row_order, left(label_raw, 22) lbl, col_index, left(col_label, 34) col, value_won,
                   adecimal, left(value_raw, 16) raw, unit_source
            FROM note_lines WHERE rcept_no = :r AND basis = :b AND table_seq = :s
            ORDER BY row_order, col_index LIMIT 30"""),
                           {"r": i["rcept_no"], "b": i["basis"], "s": int(i["table_ref"])}).fetchall()
    print(f"#{issue_id} [{i['status']}] {i['error_type']}  {meta.corp_name} {meta.fiscal_year}{meta.fiscal_period}  {meta.report_nm}")
    print(f"  DART : {DART.format(i['rcept_no'])}")
    print(f"  XML  : {path}")
    print(f"  표   : {i['basis']} table_seq {i['table_ref']}  제목={ (tab.table_title or '')[:60] if tab else '-'}  "
          f"단위={tab.declared_unit if tab else '-'}/{tab.unit_kind if tab else '-'}")
    print(f"  이슈 : 라벨 '{i['account_label']}'  열 {i['column_label']}  원문값 {i['source_value_raw']}")
    print(f"  근거 : {i['evidence']}")
    print("\n  ── DB note_lines (이 표, 앞 30행) ──")
    for r in db_rows:
        print(f"   r{r.row_order:<3d} c{r.col_index:<2d} {r.lbl:22s} {r.col or '':34s} "
              f"{r.value_won if r.value_won is not None else 'NULL':>16} /{r.adecimal} raw={r.raw} {r.unit_source}")
    if not path:
        return
    print("\n  ── 원문 표 (DB 표와 금액이 가장 많이 겹치는 표; 값이 든 행 + 앞 3행) ──")
    needle = i["source_value_raw"]
    with engine.connect() as c:
        dbt = {(t.basis, t.seq): t for t in mn.load_db_tables(c, i["rcept_no"])}.get(
            (i["basis"], int(i["table_ref"])))
    dbvals = set(dbt.values) if dbt else set()
    root = mb.parse_source_root(path)
    best, best_score = None, -1
    for must_have_value in (True, False):          # 2nd pass: the printed text may differ (line breaks)
        for tb in root.iter("table"):
            g = mb._own_grid(tb, clean=mn._clean, copies=False)
            if must_have_value and not (needle and any(needle in x for r in g for x in r)):
                continue
            vals = {mn._read_source_cell(x) for r in g for x in r} - {None}
            score = len(vals & dbvals)
            if score > best_score:
                best, best_score = g, score
        if best is not None:
            break
    if best is None or best_score <= 0:
        print("   (DB 표와 겹치는 원문 표를 찾지 못함)")
        return
    print(f"   (DB 표와 겹치는 금액 {best_score}개 / DB 표 금액 {len(dbvals)}개)")
    for k, r in enumerate(best):
        if k < 3 or (needle and any(needle in x for x in r)) or (not needle and k < 40):
            print(f"   s{k:<3d} " + " | ".join(x[:16].replace('\n', '/') for x in r))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat", choices=["other", "total", "unlabeled", "shares_or_price", "currency_code"])
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("--show", type=int, help="note issue_id")
    a = ap.parse_args()
    if a.show:
        show(a.show)
    elif a.cat:
        sample(a.cat, a.n)
    else:
        counts()


if __name__ == "__main__":
    main()
