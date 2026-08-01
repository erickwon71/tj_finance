"""Find 'merged column' tables — a whole column stacked into ONE cell (READ-ONLY).

Root cause (measured 2026-08-01, 일양약품 20260318000595 지적재산권 보유현황):
the filer put an entire column into a single <TD HEIGHT="1794"> with **no separator of any
kind** — no <P>, no <BR>, no newline:

    <TR HEIGHT="1801">
      <TD WIDTH="68" ...>20252024202320222021...19641962</TD>   <- 44 years
      <TD WIDTH="67" ...>상표권특허권특허권상표권...</TD>          <- 68 tokens
      <TD WIDTH="438" ...>용비산 등 22건클로피도그렐 ...</TD>       <- 56+ entries
    </TR>

DART's web viewer only *looks* right because the fixed-width cell wraps the text; the row
structure is a rendering artifact, not data. 44 / 68 / 56 do not line up, so which 구분 belongs
to which 년도 is not recoverable — reconstructing it would be guessing (PARSING_RULES.md R6).

The damage is real: parsing such a cell yields a fabricated number (44 years concatenated =
2.025e+175). This scans stored grids to size the problem and to check the detector for false
positives before wiring it in.

  python scripts/probe_merged_column_tables.py
  python scripts/probe_merged_column_tables.py --show 15
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.biz_section import merged_cell_reason


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0, help="검사할 표 수(0=전수)")
    args = ap.parse_args()

    sql = """
        SELECT t.rcept_no, t.table_ord, t.corp_code, t.fiscal_year, t.metric,
               left(t.narrative, 50) AS cap, t.grid
        FROM biz_section_tables t
    """
    if args.limit:
        sql += f" LIMIT {args.limit}"

    flagged: list[tuple] = []
    n_tables = 0
    with get_session() as s:
        for r in s.execute(text(sql)).yield_per(2000):
            n_tables += 1
            grid = r.grid or []
            hit = None
            for row in grid:
                for cell in row:
                    why = merged_cell_reason(cell or "")
                    if why:
                        hit = (why, (cell or "")[:70])
                        break
                if hit:
                    break
            if hit:
                flagged.append((r.rcept_no, r.table_ord, r.corp_code, r.fiscal_year,
                                r.metric, r.cap, hit[0], hit[1]))

    print(f"검사한 표 {n_tables:,}개 · 병합열 판정 {len(flagged):,}개 "
          f"({len(flagged)/max(n_tables,1)*100:.3f}%)\n")

    if flagged:
        with get_session() as s:
            keys = [(f[0], f[1]) for f in flagged]
            rows = s.execute(text("""
                SELECT rcept_no, table_ord, count(*) n
                FROM biz_metrics
                WHERE (rcept_no, table_ord) IN :keys
                GROUP BY 1,2
            """).bindparams(keys=tuple(keys))).fetchall() if keys else []
        affected = sum(r.n for r in rows)
        print(f"이 표들이 만들어 낸 biz_metrics 행: {affected:,}\n")

        print(f"{'기업':<10} {'FY':>5} {'metric':<15} {'사유':<22} 셀 앞부분")
        print("-" * 110)
        for f in flagged[: args.show]:
            print(f"{f[2]:<10} {f[3]:>5} {str(f[4])[:14]:<15} {f[6]:<22} {f[7][:44]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
