"""(가+라) 원문대조 세션용 — 지정 corp/fy/period의 report_lines 전체를 덤프해
교차검증 단서(다른 표의 같은 값, 라벨에 박힌 실제 금액 등)를 찾는다.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from collector.db import get_session


def main(corp, fy, period):
    with get_session() as session:
        rows = session.execute(text("""
            SELECT rcept_no, statement, basis, label_raw, value_won, adecimal,
                   unit_source, col_index, table_seq
            FROM report_lines
            WHERE corp_code=:c AND report_fiscal_year=:y AND report_fiscal_period=:p
            ORDER BY statement, basis, table_seq, col_index
        """), {"c": corp, "y": fy, "p": period}).fetchall()
        for r in rows:
            print(r)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), sys.argv[3])
