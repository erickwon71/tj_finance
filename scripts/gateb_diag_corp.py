"""한양증권 등 단일 corp 의 Gate B 불일치 근본원인 진단.
std_v2 의 source rcept 와, 그 파일에서 핵심 acode 의 모든 col0 셀(ACONTEXT/값)을 덤프."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from fin2.extract.acontext import parse_acontext
from fin2.audit.face_audit import parse_displayed, _cell_text

CORP = sys.argv[1] if len(sys.argv) > 1 else "00162416"
PROBE_ACODES = {"ifrs-full_Assets", "ifrs-full_Liabilities", "ifrs-full_Equity",
                "ifrs-full_Revenue", "ifrs-full_ProfitLoss",
                "ifrs-full_CashFlowsFromUsedInOperatingActivities"}

with get_session() as s:
    rows = s.execute(text("""
        SELECT fiscal_year, statement_type, total_assets, revenue, net_income, cfo,
               bs_rcept, is_rcept, cf_rcept, applied_rules
        FROM std_financials_v2
        WHERE corp_code=:c AND version=1 AND fiscal_period='FY' AND NOT COALESCE(is_stub,false)
        ORDER BY fiscal_year DESC LIMIT 4
    """), {"c": CORP}).fetchall()
    for r in rows:
        print(f"\n### FY{r.fiscal_year} {r.statement_type}: assets={r.total_assets} rev={r.revenue} "
              f"ni={r.net_income} cfo={r.cfo}")
        print(f"    bs_rcept={r.bs_rcept} is_rcept={r.is_rcept} cf_rcept={r.cf_rcept}")
        print(f"    applied_rules={r.applied_rules}")

    # 최근 FY 의 source 파일들에서 PROBE acode 셀 전수 덤프
    top = rows[0]
    for label, rcept in [("BS", top.bs_rcept), ("IS", top.is_rcept), ("CF", top.cf_rcept)]:
        if not rcept:
            continue
        fp = s.execute(text("SELECT file_path FROM download_tasks WHERE rcept_no=:r AND file_type='xml' LIMIT 1"),
                       {"r": rcept}).scalar()
        print(f"\n--- {label} source r{rcept} file={Path(fp).name if fp else None} ---")
        root = _parse_xml_file(Path(fp)) if fp else None
        if root is None:
            print("  (root 없음)"); continue
        seen = 0
        for te in root.findall(".//TE[@ACODE]"):
            ac = te.get("ACODE", "")
            if ac not in PROBE_ACODES:
                continue
            ctx = parse_acontext(te.get("ACONTEXT", ""))
            disp = parse_displayed(_cell_text(te))
            ade = te.get("ADECIMAL", "")
            if ctx.col_index == 0 and not ctx.is_dimensional:
                print(f"  {ac:55s} basis={ctx.basis} ade={ade} disp={disp} ctx={te.get('ACONTEXT','')[:70]}")
                seen += 1
        print(f"  (col0 비차원 PROBE 셀 {seen}개)")
