"""Phase 2 safety check (read-only): for each of the 5 candidate is.cogs alias additions
found in scripts/probe_cogs_unmapped_labels_2026-08-15.py, check GLOBAL usage (every corp,
not just the 39-corp Phase 2 population) and specifically whether the label ever appears as
a SIBLING of an exact '매출원가' TOTAL line within the same table — that's the exact conflict
pattern that caused account_maps/is_accounts.py's 2026-07-18 removal of '제품매출원가'/
'상품매출원가' as separate is.cogs aliases (총계+세부 동시 alias -> value conflict/HELD).

Usage: python scripts/probe_cogs_alias_global_risk_2026-08-15.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session, init_db
from parser.common.amount_normalizer import normalize_account_name

CANDIDATES = {
    "상품및제품매출원가": ["상품 및 제품 매출원가", "상품 및 제품매출원가"],
    "임대매출원가/임대수익원가": ["임대매출원가/임대수익원가"],
    "제ㆍ상품매출원가": ["제ㆍ상품매출원가"],
    "제품및상품매출원가": ["2. 제품 및 상품매출원가"],
    "천연가스매출원가": ["천연가스매출원가"],
}


def main():
    init_db()
    with get_session() as s:
        for norm_key, raw_forms in CANDIDATES.items():
            print(f"\n=== {norm_key!r} (raw forms: {raw_forms}) ===")
            like_clauses = " OR ".join(["label_raw LIKE :l%d" % i for i in range(len(raw_forms))])
            params = {f"l{i}": f"%{f}%" for i, f in enumerate(raw_forms)}
            rows = s.execute(text(f"""
                SELECT DISTINCT corp_code, rcept_no, basis, table_seq
                FROM report_lines
                WHERE statement = 'IS' AND col_index = 0 AND ({like_clauses})
            """), params).fetchall()
            corps = sorted({r[0] for r in rows})
            print(f"  global usage: {len(rows)} (corp,rcept,basis,table) combos, {len(corps)} corps: {corps}")

            # for each combo, check whether an exact '매출원가' TOTAL sibling exists in the
            # SAME table (any depth) — the conflict-risk signal.
            conflict_combos = []
            for corp, rcept, basis, tseq in rows:
                total_rows = s.execute(text("""
                    SELECT label_raw, value_won, depth FROM report_lines
                    WHERE corp_code=:c AND rcept_no=:r AND basis=:b AND statement='IS'
                      AND table_seq=:t AND col_index=0
                """), {"c": corp, "r": rcept, "b": basis, "t": tseq}).fetchall()
                totals = [row for row in total_rows if normalize_account_name(row[0]) == "매출원가"]
                if totals:
                    conflict_combos.append((corp, rcept, basis, tseq, totals))
            print(f"  co-occurs with an exact '매출원가' total sibling in same table: "
                  f"{len(conflict_combos)} combos")
            for corp, rcept, basis, tseq, totals in conflict_combos[:10]:
                print(f"    {corp} {rcept} {basis} tseq={tseq} totals={totals}")

    print("\n=== DONE (read-only, no writes) ===")


if __name__ == "__main__":
    main()
