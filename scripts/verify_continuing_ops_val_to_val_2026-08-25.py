"""
'계속영업' 귀속 가드 확장 드라이런에서 나온 값->다른값(val->val) 2건 원문대조 검증.

대상: 00204262(2014 H1 consolidated), 00377610(2011 FY consolidated).
항등식 controlling_ni + noncontrolling_ni = net_income 이 실제 std_v3(net_income은
가드와 무관하게 불변)과 일치하는지, 그리고 after_controlling_ni 값이 report_lines
원문(계속+중단 합산 헤드라인 라인)과 일치하는지 확인한다.

실행: python scripts/verify_continuing_ops_val_to_val_2026-08-25.py
"""
import sys
sys.path.insert(0, "/Users/taejin/Project/tj_finance")

from sqlalchemy import text
from collector.db import SessionLocal

TARGETS = [
    ("00204262", 2014, "H1"),
    ("00377610", 2011, "FY"),
]


def main():
    session = SessionLocal()
    try:
        for corp, fy, period in TARGETS:
            name = session.execute(text(
                "SELECT corp_name FROM corporations WHERE corp_code=:c"
            ), {"c": corp}).scalar()
            print(f"\n=== {corp} {name} FY{fy} {period} ===")

            rows = session.execute(text("""
                SELECT rcept_no, statement, label_raw, context_fiscal_year, period_kind,
                       is_cumulative, value_won, col_label, col_index, row_order,
                       table_seq, context_raw
                FROM report_lines
                WHERE corp_code = :corp AND report_fiscal_year = :fy
                  AND report_fiscal_period = :period
                  AND statement = 'IS'
                  AND (label_raw LIKE '%지배%' OR label_raw LIKE '%순이익%'
                       OR label_raw LIKE '%당기순%')
                ORDER BY rcept_no, table_seq, row_order, col_index
            """), {"corp": corp, "fy": fy, "period": period}).fetchall()

            for r in rows:
                print(f"  rcept={r.rcept_no} table_seq={r.table_seq} row={r.row_order} "
                      f"col_idx={r.col_index} label={r.label_raw!r} "
                      f"ctx_fy={r.context_fiscal_year} period_kind={r.period_kind} "
                      f"cum={r.is_cumulative} col={r.col_label!r} value_won={r.value_won} "
                      f"ctx_raw={r.context_raw!r}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
