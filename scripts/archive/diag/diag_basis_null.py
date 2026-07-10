"""
OWNREPORT_BASIS_NULL 원인 진단: basis=NULL 로 추출된 자체보고서 fact 표본의
source_format / context_parsed / acontext_raw 를 본다.

대상: 00100601 의 2025 H1 보고서(앞서 (2025,'H1',None) 565행 확인).
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from collector.db import get_session

with get_session() as s:
    # 해당 보고서 rcept 식별
    rs = s.execute(text("""
        SELECT rcept_no, count(*) n,
               count(*) FILTER (WHERE basis IS NULL) n_null,
               count(*) FILTER (WHERE context_parsed) n_parsed,
               count(DISTINCT source_format) ,
               min(source_format), max(source_format)
        FROM fact_v2
        WHERE corp_code='00100601' AND report_fiscal_year=2025 AND report_fiscal_period='H1'
        GROUP BY rcept_no ORDER BY n DESC
    """)).fetchall()
    print("=== 2025 H1 보고서 fact 요약 (rcept, n, n_null, n_parsed, fmt_cnt, fmt_min, fmt_max) ===")
    for r in rs:
        print("  ", tuple(r))

    print("\n=== basis 분포 ===")
    for r in s.execute(text("""
        SELECT basis, context_parsed, source_format, count(*)
        FROM fact_v2
        WHERE corp_code='00100601' AND report_fiscal_year=2025 AND report_fiscal_period='H1'
        GROUP BY 1,2,3 ORDER BY 4 DESC
    """)).fetchall():
        print("  ", tuple(r))

    print("\n=== acontext_raw 표본 12 (basis, context_fy, acontext_raw) ===")
    for r in s.execute(text("""
        SELECT basis, context_fiscal_year, acontext_raw, acode
        FROM fact_v2
        WHERE corp_code='00100601' AND report_fiscal_year=2025 AND report_fiscal_period='H1'
        ORDER BY id LIMIT 12
    """)).fetchall():
        print("   basis=%r cfy=%r acode=%r\n     ac=%r" % (r[0], r[1], r[3], r[2]))

    # 대조: 2024 H1 은 정상 basis 였음
    print("\n=== 대조: 2024 H1 acontext_raw 표본 6 ===")
    for r in s.execute(text("""
        SELECT basis, context_fiscal_year, acontext_raw
        FROM fact_v2
        WHERE corp_code='00100601' AND report_fiscal_year=2024 AND report_fiscal_period='H1'
        ORDER BY id LIMIT 6
    """)).fetchall():
        print("   basis=%r cfy=%r\n     ac=%r" % (r[0], r[1], r[2]))
