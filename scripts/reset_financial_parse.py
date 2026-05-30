"""
Re-parse reset for financial industry IS fix.

Resets parse_status=NULL for XML filings that have:
  (a) is.revenue with is_subtotal=False and account_name_raw='영업수익'
      → these need is_subtotal recalculated as True after _SUBTOTAL_KEYWORDS fix
  (b) is.revenue at col_index=0 with note-ref bug amount (수수료수익 < 5억)
      → these need note-ref skip fix to apply

After running this script, execute:
    python3 run.py parse --workers 4
    python3 run.py aggregate --since 1999
"""
import argparse
import psycopg2

DB_DSN = "dbname=tj_finance user=taejin"


FIND_SQL = """
    SELECT DISTINCT ff.rcept_no
    FROM financial_facts ff
    JOIN download_tasks dt ON dt.rcept_no = ff.rcept_no
    WHERE dt.file_type = 'xml'
      AND dt.parse_status IN ('success', 'partial')
      AND NOT ff.is_superseded
      AND (
        (ff.account_code = 'is.revenue'
         AND ff.is_subtotal = FALSE
         AND ff.account_name_raw = '영업수익')
        OR
        (ff.account_code = 'is.revenue'
         AND ff.col_index = 0
         AND ff.account_name_raw LIKE '%수수료수익%'
         AND ff.amount IS NOT NULL
         AND ff.amount > 0
         AND ff.amount < 500000000)
      )
"""


def main():
    ap = argparse.ArgumentParser(description='Reset parse_status for financial IS fix')
    ap.add_argument('--dry-run', action='store_true', help='Show count only, no DB changes')
    args = ap.parse_args()

    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute(FIND_SQL)
    rcept_nos = [r[0] for r in cur.fetchall()]
    print(f'Affected filings: {len(rcept_nos)} rcept_no values')

    if args.dry_run:
        print('Dry-run: no changes made.')
        cur.close()
        conn.close()
        return

    # Reset parse_status to NULL in batches
    batch_size = 500
    total_reset = 0
    for i in range(0, len(rcept_nos), batch_size):
        batch = rcept_nos[i:i + batch_size]
        cur.execute(
            "UPDATE download_tasks SET parse_status = NULL WHERE rcept_no = ANY(%s)",
            (batch,)
        )
        total_reset += cur.rowcount
        conn.commit()
        print(f'  Reset {total_reset}/{len(rcept_nos)}...', end='\r')

    print(f'\nDone: {total_reset} download_tasks rows reset to parse_status=NULL')
    cur.close()
    conn.close()
    print('Next steps:')
    print('  python3 run.py parse --workers 4')
    print('  python3 run.py aggregate --since 1999')


if __name__ == '__main__':
    main()
