"""삼성전자 shares_out 현황 확인"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from collector.db import get_session
from sqlalchemy import text

CORP = "00126380"  # 삼성전자

with get_session() as s:
    # 1. standard_financials의 shares_out
    print("=== standard_financials.shares_out (삼성전자 연결 FY) ===")
    rows = s.execute(text("""
        SELECT fiscal_year, fiscal_period, statement_type, shares_out, period_end
        FROM standard_financials
        WHERE corp_code = :cc
          AND fiscal_period = 'FY'
          AND statement_type = 'consolidated'
        ORDER BY fiscal_year DESC LIMIT 8
    """), {"cc": CORP}).fetchall()
    for r in rows:
        so = f"{r.shares_out:,}" if r.shares_out else "NULL"
        print(f"  {r.fiscal_year} {r.fiscal_period} {r.statement_type}: shares_out={so}  period_end={r.period_end}")

    # 2. stock_prices의 shares_out
    print("\n=== stock_prices.shares_out (삼성전자) ===")
    stock_code_row = s.execute(text(
        "SELECT stock_code FROM corporations WHERE corp_code = :cc"
    ), {"cc": CORP}).fetchone()
    sc = stock_code_row[0] if stock_code_row else None
    print(f"  stock_code: {sc}")

    if sc:
        rows2 = s.execute(text("""
            SELECT trade_date, shares_out, close_price
            FROM stock_prices
            WHERE stock_code = :sc AND shares_out IS NOT NULL
            ORDER BY trade_date DESC LIMIT 5
        """), {"sc": sc}).fetchall()
        for r in rows2:
            print(f"  {r.trade_date}: shares_out={r.shares_out:,}  close={r.close_price:,}")
        if not rows2:
            print("  stock_prices에 shares_out 데이터 없음")
