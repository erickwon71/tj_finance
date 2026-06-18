"""EBT 가드 수정 단일기업 검증: purge + E→R→S + comparative, tax_expense/ebt 확인.
usage: python scripts/gateb_validate_ebt_fix.py CORP [CORP2 ...]"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from collector.db import get_session
from fin2.reconcile import reconcile_corp
from fin2.standardize.build import standardize_corp, standardize_comparative_corp
from run import _extract2_corp

corps = sys.argv[1:] or ["00231105"]
for corp in corps:
    with get_session() as s:
        s.execute(text("DELETE FROM fact_v2 WHERE corp_code=:c"), {"c": corp})
        files, a, b, facts = _extract2_corp(s, corp, verbose=False)
        r = reconcile_corp(s, corp)
        sn = standardize_corp(s, corp)
        try:
            cmp = standardize_comparative_corp(s, corp)
        except Exception as e:
            cmp = f"skip({e})"
        s.commit()
    print(f"\n=== {corp}: files={files} facts={facts} (TrackB {b}) stmt_src={r} std={sn} comp={cmp} ===")
    with get_session() as s:
        rows = s.execute(text("""
            SELECT fiscal_year, fiscal_period, statement_type, tax_expense, ebt, net_income
            FROM std_financials_v2
            WHERE corp_code=:c AND version=1 AND NOT COALESCE(is_stub,false)
              AND fiscal_period='FY' AND fiscal_year BETWEEN 2015 AND 2018
            ORDER BY fiscal_year, statement_type
        """), {"c": corp}).fetchall()
        for x in rows:
            d = dict(x._mapping)
            print(f"  {d['fiscal_year']} {d['statement_type']:12s} "
                  f"tax={str(d['tax_expense']):>16} ebt={str(d['ebt']):>16} ni={str(d['net_income']):>16}")
