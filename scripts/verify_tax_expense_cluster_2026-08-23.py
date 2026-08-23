"""
Sample-verify the tax_expense fail_a cluster (fy>=2024, 1-field-only fails)
against raw XBRL source, to check whether db_won matches a prior-year
non-cumulative (P..Q) ACONTEXT and report_won matches the current-year
cumulative (C..A) ACONTEXT -- the column-mis-selection hypothesis found in
01201970/00104573.

Reads the pre-dumped TSV (corp_code, fiscal_year, fiscal_period,
statement_type, db_won, report_won), looks up the raw report file for each
row via the DB, and greps the XML for the exact value strings (comma
formatted) together with their ACONTEXT attribute.
"""
from __future__ import annotations

import re
import subprocess
import sys

TSV = "/private/tmp/claude-501/-Users-taejin-Project-tj-finance/bd47d7c2-036f-41ac-8eaf-1f31eadcc307/scratchpad/tax_expense_fails.tsv"

PERIOD_TO_DIRKIND = {"Q1": "quarter", "Q3": "quarter", "H1": "half", "FY": "annual"}


def comma(n: str) -> str:
    neg = n.startswith("-")
    n = n.lstrip("-")
    s = f"{int(n):,}"
    return ("(" + s + ")") if neg else s  # DART renders negatives in parens


def psql(sql: str) -> list[str]:
    out = subprocess.run(
        ["psql", "-d", "tj_finance", "-t", "-A", "-F", "\t", "-c", sql],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return [l for l in out.splitlines() if l]


def find_file(corp_code: str, fy: str, fp: str) -> str | None:
    sql = f"""
    select dt.file_path from download_tasks dt
    join filings f on f.rcept_no = dt.rcept_no
    where f.corp_code='{corp_code}' and f.fiscal_year={fy} and f.fiscal_period='{fp}'
      and dt.status='completed' and dt.file_type='xml'
    order by f.filed_at desc limit 1;
    """
    rows = psql(sql)
    return rows[0] if rows else None


ACONTEXT_RE = re.compile(r'ACONTEXT="([^"]+)"')


def classify(file_path: str, db_won: str, report_won: str) -> str:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except FileNotFoundError:
        return "FILE_NOT_FOUND"

    db_str = comma(db_won)
    rep_str = comma(report_won)

    def contexts_for(value_str: str) -> list[str]:
        ctxs = []
        # search each occurrence of value_str, walk backward to nearest ACONTEXT= on same TE tag
        for m in re.finditer(re.escape(">" + value_str + "<"), text):
            # look back up to 400 chars for the ACONTEXT attribute of this TE
            window = text[max(0, m.start() - 400):m.start()]
            am = list(ACONTEXT_RE.finditer(window))
            if am:
                ctxs.append(am[-1].group(1))
        return ctxs

    db_ctxs = contexts_for(db_str) if db_str != "0" else []
    rep_ctxs = contexts_for(rep_str) if rep_str != "0" else []

    def tag(ctxs, want_rel, want_accum):
        for c in ctxs:
            m = re.match(r"^(BP|C|P)FY(\d{4})([de])(FY|FQ|HY|TQ)([AQ]?)", c)
            if m and m.group(1) == want_rel and m.group(5) == want_accum:
                return True
        return False

    db_is_PQ = tag(db_ctxs, "P", "Q")
    rep_is_CA = tag(rep_ctxs, "C", "A")
    db_is_CA = tag(db_ctxs, "C", "A")

    parts = []
    parts.append(f"db_ctxs={db_ctxs[:4]}")
    parts.append(f"rep_ctxs={rep_ctxs[:4]}")
    if db_is_PQ and rep_is_CA:
        verdict = "MATCH(col-misselect: db=PFY..Q, report=CFY..A)"
    elif db_is_CA:
        verdict = "NOMATCH(db already CFY..A -- different cause)"
    elif not db_ctxs and not rep_ctxs:
        verdict = "NOT_FOUND(value string not located verbatim)"
    else:
        verdict = "UNCLEAR"
    return verdict + " | " + " ".join(parts)


def main():
    lines = open(TSV, encoding="utf-8").read().splitlines()
    rows = [l.split("\t") for l in lines]
    # sample: take every ~7th row plus a few known landmark rows
    idxs = sorted(set(list(range(0, len(rows), 6)) + [i for i, r in enumerate(rows) if r[0] == "00874803"]))
    for i in idxs:
        corp, fy, fp, stype, db_won, report_won = rows[i]
        fpath = find_file(corp, fy, fp)
        if not fpath:
            print(f"{corp} {fy} {fp} {stype}: NO_FILE")
            continue
        verdict = classify(fpath, db_won, report_won)
        print(f"{corp} {fy} {fp} {stype} db={db_won} report={report_won} -> {verdict}")


if __name__ == "__main__":
    main()
