"""Gate B 설계용 사전 조사 (read-only). 규모 + golden corp 의 std_v2→source→file 경로 검증."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from collector.db import get_session

GOLDEN = {
    "00162416": "한양증권", "01275665": "리메드", "01492651": "큐로셀",
    "00126186": "삼성전자", "01367586": "지아이텍",
}

with get_session() as s:
    # 1. 전체 규모
    n_std = s.execute(text("SELECT count(*) FROM std_financials_v2 WHERE version=1 AND NOT COALESCE(is_stub,false)")).scalar()
    n_corp = s.execute(text("SELECT count(DISTINCT corp_code) FROM std_financials_v2 WHERE version=1")).scalar()
    n_ss = s.execute(text("SELECT count(*) FROM statement_source")).scalar()
    print(f"std_v2 v1 (non-stub): {n_std:,} / corps {n_corp:,} / statement_source {n_ss:,}")

    # 2. source_format 분포(파일 추출 Track A vs B) — fact_v2 기준
    print("\n-- fact_v2 source_format 분포 --")
    for r in s.execute(text("SELECT source_format, count(*) c FROM fact_v2 GROUP BY 1 ORDER BY 2 DESC")):
        print(f"  {r.source_format:14s} {r.c:,}")

    # 3. golden corp 의 최근 FY std_v2 + 그 source rcept 의 file_path/format
    print("\n-- golden corp 최근 FY lineage --")
    for corp, name in GOLDEN.items():
        row = s.execute(text("""
            SELECT fiscal_year, statement_type, bs_rcept, is_rcept, cf_rcept, revenue, total_assets, net_income
            FROM std_financials_v2
            WHERE corp_code=:c AND version=1 AND fiscal_period='FY' AND NOT COALESCE(is_stub,false)
            ORDER BY fiscal_year DESC LIMIT 1
        """), {"c": corp}).fetchone()
        if not row:
            print(f"  {name}({corp}): std_v2 FY 없음")
            continue
        rcept = row.is_rcept or row.bs_rcept
        fmt = fp = None
        if rcept:
            fr = s.execute(text("""
                SELECT dt.file_path, dt.file_type, (SELECT source_format FROM fact_v2 WHERE rcept_no=:r LIMIT 1) sf
                FROM download_tasks dt WHERE dt.rcept_no=:r AND dt.file_type='xml' LIMIT 1
            """), {"r": rcept}).fetchone()
            if fr:
                fmt, fp = fr.sf, fr.file_path
        exists = Path(fp).exists() if fp else False
        print(f"  {name}({corp}) FY{row.fiscal_year}: rev={row.revenue} assets={row.total_assets} "
              f"src={rcept} fmt={fmt} file_exists={exists}")
