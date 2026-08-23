"""Phase 1 실측 검증 — overlay_tax_expense_value() 를 fy>=2024 tax_expense fail_a
89건 전수(scripts/verify_tax_expense_cluster_2026-08-23.py 가 쓰던 TSV 재사용)에
실제로 돌려, 적용 건수·전부 report_won 일치(오탐 0)·미적용 건 근거를 확인한다.

docs/plans/d_category_col_misselect_ni_label_dup_design_2026-08-23.md §1-6 항목 3.
"""
from __future__ import annotations

import subprocess
import sys

from fin2.extract.report_lines import extract_report_lines

TSV = "/private/tmp/claude-501/-Users-taejin-Project-tj-finance/bd47d7c2-036f-41ac-8eaf-1f31eadcc307/scratchpad/tax_expense_fails.tsv"


def psql(sql: str) -> list[str]:
    out = subprocess.run(
        ["psql", "-d", "tj_finance", "-t", "-A", "-F", "\t", "-c", sql],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return [l for l in out.splitlines() if l]


def find_file_and_rcept(corp_code: str, fy: str, fp: str) -> tuple[str, str] | None:
    sql = f"""
    select dt.file_path, f.rcept_no from download_tasks dt
    join filings f on f.rcept_no = dt.rcept_no
    where f.corp_code='{corp_code}' and f.fiscal_year={fy} and f.fiscal_period='{fp}'
      and dt.status='completed' and dt.file_type='xml'
    order by f.filed_at desc limit 1;
    """
    rows = psql(sql)
    if not rows:
        return None
    fpath, rcept = rows[0].split("\t")
    return fpath, rcept


def main():
    lines_in = open(TSV, encoding="utf-8").read().splitlines()
    rows = [l.split("\t") for l in lines_in]

    n_total = len(rows)
    n_no_file = 0
    n_applied_match = 0
    n_applied_mismatch = 0
    n_not_applied = 0
    mismatches = []
    not_applied_detail = []

    for corp, fy, fp, stype, db_won, report_won in rows:
        found = find_file_and_rcept(corp, fy, fp)
        if not found:
            n_no_file += 1
            continue
        fpath, rcept = found
        try:
            out_lines = extract_report_lines(
                fpath, rcept_no=rcept, corp_code=corp,
                report_fiscal_year=int(fy), report_fiscal_period=fp,
            )
        except Exception as exc:  # noqa: BLE001
            not_applied_detail.append(f"{corp} {fy}{fp}: EXTRACT_ERROR {exc}")
            n_not_applied += 1
            continue

        candidates = [
            l for l in out_lines
            if l.statement == "IS" and (l.col_index or 0) == 0
            and "법인세비용" in (l.label_raw or "") and "차감전" not in (l.label_raw or "")
            and (l.source_ref or "").endswith(";xbrl_inline_override")
        ]
        if not candidates:
            n_not_applied += 1
            not_applied_detail.append(f"{corp} {fy}{fp}: no overlay applied (db={db_won} report={report_won})")
            continue
        # multiple overlay rows possible (consolidated/separate) -- check any match report_won
        rw = int(report_won)
        matched = [c for c in candidates if c.value_won == rw]
        if matched:
            n_applied_match += 1
        else:
            n_applied_mismatch += 1
            mismatches.append(f"{corp} {fy}{fp}: applied but no candidate == report_won={rw}; "
                               f"got {[c.value_won for c in candidates]}")

    print(f"total={n_total} no_file={n_no_file} applied_match={n_applied_match} "
          f"applied_mismatch={n_applied_mismatch} not_applied={n_not_applied}")
    if mismatches:
        print("\n--- MISMATCHES (applied but wrong value) ---")
        for m in mismatches:
            print(" ", m)
    if not_applied_detail:
        print("\n--- NOT APPLIED (sample, first 20) ---")
        for m in not_applied_detail[:20]:
            print(" ", m)


if __name__ == "__main__":
    sys.exit(main())
