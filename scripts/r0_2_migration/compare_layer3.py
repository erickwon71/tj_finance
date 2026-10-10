"""Layer-3 before/after comparison for a set of corps (R0-2 follow-ups, 2026-10-10).

  snapshot <tag> <corps.txt> <periods.tsv>
      copy std_financials_v3 rows of the corps (fiscal_year >= 2015) and extended_facts_v3 rows of
      the corp-years in periods.tsv into r02_<tag>_std_before / r02_<tag>_ext_before
  compare  <tag> <corps.txt> <periods.tsv>
      compare the current tables with the snapshot; periods.tsv lines
      "corp_code<TAB>fiscal_year<TAB>fiscal_period" mark the periods whose source filing was
      reloaded (counted separately from the rest)

Usage (cwd = repo root, DATABASE_URL set):
  python scripts/r0_2_migration/compare_layer3.py snapshot viewer logs/r0_2/viewer_corps.txt logs/r0_2/viewer_periods.tsv
  python scripts/r0_2_migration/compare_layer3.py compare viewer logs/r0_2/viewer_corps.txt logs/r0_2/viewer_periods.tsv
"""
import os
import sys
from collections import Counter

STD_COLS = ("total_assets,current_assets,cash,receivables,inventory,ppe,intangibles,total_liabilities,"
            "current_liabilities,short_term_debt,long_term_debt,total_equity,controlling_equity,"
            "retained_earnings,trade_payables,revenue,cogs,gross_profit,sga,rd_expense,operating_income,"
            "interest_expense,ebt,tax_expense,net_income,controlling_ni,cfo,cfi,cff,dividends_paid,capex,"
            "depreciation,amortization,da_total,ebitda,fcf,net_debt,lease_liability,borrowings_proceeds,"
            "borrowings_repaid").split(",")


def main():
    mode, tag, corps_file = sys.argv[1], sys.argv[2], sys.argv[3]
    corps = [l.strip() for l in open(corps_file) if l.strip()]
    import psycopg2
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    std_b, ext_b = f"r02_{tag}_std_before", f"r02_{tag}_ext_before"
    periods = set()
    for l in open(sys.argv[4]):
        c, y, p = l.rstrip("\n").split("\t")
        periods.add((c, int(y), p))
    # extended facts are large: only the corp-years of the reloaded periods
    pairs = sorted({(c, y) for c, y, _ in periods})
    ext_corps, ext_years = [c for c, _ in pairs], [y for _, y in pairs]
    ext_where = ("(corp_code, fiscal_year) IN (SELECT * FROM unnest(%s::text[], %s::int[]))")
    if mode == "snapshot":
        cur.execute(f"DROP TABLE IF EXISTS {std_b}")
        cur.execute(f"CREATE TABLE {std_b} AS SELECT * FROM std_financials_v3 "
                    "WHERE corp_code = ANY(%s) AND fiscal_year >= 2015", (corps,))
        cur.execute(f"DROP TABLE IF EXISTS {ext_b}")
        cur.execute(f"CREATE TABLE {ext_b} AS SELECT * FROM extended_facts_v3 WHERE {ext_where}",
                    (ext_corps, ext_years))
        for name in (std_b, ext_b):
            cur.execute(f"SELECT count(*) FROM {name}")
            print(name, cur.fetchone()[0])
        conn.commit()
        return

    def bucket(c, y, p):
        return "reloaded" if (c, y, p) in periods else "other"

    # std: per row, which value columns changed
    sel = ",".join(STD_COLS)
    cur.execute(f"SELECT corp_code, fiscal_year, fiscal_period, statement_type, {sel} FROM {std_b}")
    before = {r[:4]: r[4:] for r in cur.fetchall()}
    cur.execute(f"SELECT corp_code, fiscal_year, fiscal_period, statement_type, {sel} FROM std_financials_v3 "
                "WHERE corp_code = ANY(%s) AND fiscal_year >= 2015", (corps,))
    after = {r[:4]: r[4:] for r in cur.fetchall()}
    tally, cols = Counter(), Counter()
    for k in before.keys() | after.keys():
        b, a = before.get(k), after.get(k)
        bk = bucket(*k[:3])
        if b is None:
            tally[(bk, "new")] += 1
        elif a is None:
            tally[(bk, "removed")] += 1
        else:
            diff = [STD_COLS[i] for i in range(len(STD_COLS)) if b[i] != a[i]]
            tally[(bk, "changed" if diff else "same")] += 1
            for c in diff:
                cols[(bk, c, "filled" if b[STD_COLS.index(c)] is None else
                      "nulled" if a[STD_COLS.index(c)] is None else
                      "sign" if b[STD_COLS.index(c)] == -a[STD_COLS.index(c)] else "value")] += 1
    print("std_financials_v3 rows:", dict(sorted(tally.items())))
    print("std changed columns (bucket, column, kind) top 40:")
    for k, n in cols.most_common(40):
        print("  ", k, n)

    # extended facts: per cell
    cur.execute(f"SELECT corp_code, fiscal_year, fiscal_period, statement_type, canonical_account, amount_won "
                f"FROM {ext_b}")
    before = {r[:5]: r[5] for r in cur.fetchall()}
    cur.execute("SELECT corp_code, fiscal_year, fiscal_period, statement_type, canonical_account, amount_won "
                f"FROM extended_facts_v3 WHERE {ext_where}", (ext_corps, ext_years))
    after = {r[:5]: r[5] for r in cur.fetchall()}
    tally = Counter()
    for k in before.keys() | after.keys():
        b, a = before.get(k), after.get(k)
        bk = bucket(*k[:3])
        kind = ("new" if b is None else "removed" if a is None else "same" if a == b
                else "sign" if a == -b else "value")
        tally[(bk, kind)] += 1
    print("extended_facts_v3 cells:", dict(sorted(tally.items())))
    conn.close()


if __name__ == "__main__":
    main()
