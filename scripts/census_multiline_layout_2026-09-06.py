"""전수 census — 00163691류 "다줄(라벨/숫자/영문 3줄)" PDF 레이아웃이 실제로 몇 건/
몇 개사에 영향을 주는지 스코프 확인 (2026-09-06, 트랙①-b 후속).

시그니처: Track C(PDF-only, unit_source='pdf')로 적재된 필링 중, 같은 rcept_no·basis
에서 BS 행수가 극소(<=2)인데 CF 행수는 정상(>=8)인 경우 — `_iter_data_lines()`가
"라벨+숫자가 한 줄"을 요구하므로, 라벨/숫자/영문이 3줄로 쪼개진 표에서는 BS/IS가
거의 통째로 유실되고(라벨과 우연히 숫자가 같은 줄에 걸리는 헤더 정도만 1~2건 남음)
CF만(이 시대 문서에서 종종 다른 2단 레이아웃이라 우연히 한 줄 포맷) 멀쩡히 남는
비대칭이 재현된다 — 00163691 실측으로 확정된 패턴.

로컬 재조회만 사용(원문 재수집 없음) — 이미 report_lines에 적재된 결과의 행수
비대칭만으로 스크리닝하는 저비용 census.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from collector.db import get_session

Q = """
WITH pdf_filings AS (
    SELECT DISTINCT rcept_no, corp_code, report_fiscal_year, report_fiscal_period
    FROM report_lines WHERE unit_source = 'pdf'
),
counts AS (
    SELECT pf.rcept_no, pf.corp_code, pf.report_fiscal_year, pf.report_fiscal_period,
           rl.basis,
           COUNT(*) FILTER (WHERE rl.statement = 'BS') AS bs_n,
           COUNT(*) FILTER (WHERE rl.statement = 'IS') AS is_n,
           COUNT(*) FILTER (WHERE rl.statement = 'CF') AS cf_n
    FROM pdf_filings pf
    JOIN report_lines rl ON rl.rcept_no = pf.rcept_no
    GROUP BY pf.rcept_no, pf.corp_code, pf.report_fiscal_year, pf.report_fiscal_period, rl.basis
)
SELECT * FROM counts
WHERE bs_n <= 2 AND cf_n >= 8
ORDER BY corp_code, report_fiscal_year, report_fiscal_period, basis
"""

if __name__ == "__main__":
    with get_session() as session:
        rows = session.execute(text(Q)).fetchall()
        print(f"suspected multiline-layout rows: {len(rows)}")
        corps = sorted(set(r.corp_code for r in rows))
        filings = sorted(set(r.rcept_no for r in rows))
        print(f"distinct corps: {len(corps)}  distinct rcepts: {len(filings)}")
        for r in rows:
            print(r)
