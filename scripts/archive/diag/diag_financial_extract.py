"""
item 4 진단 — 금융업 XBRL 추출 0행 원인 규명용 표본 수집.

동양생명/하나금융지주 등 금융사의 최근 정기보고서 중 fact_v2=0 인 XML 파일 경로를
찾아 출력한다. 이후 해당 XML 을 직접 열어 TE[@ACODE]/ACONTEXT 태깅 구조를 진단.

읽기 전용. 사용:
    PYTHONPATH=. .venv_tj_finance/bin/python scripts/diag_financial_extract.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from collector.db import get_session

# 메모리 item 4 에서 지목된 금융사 후보
NAME_PATTERNS = ["동양생명", "하나금융지주", "삼성화재", "부국증권", "삼성카드", "LS증권"]


def main() -> None:
    with get_session() as session:
        for nm in NAME_PATTERNS:
            rows = session.execute(text("""
                SELECT c.corp_code, c.corp_name, c.coverage_class,
                       dt.rcept_no, f.fiscal_year, f.fiscal_period, f.report_type,
                       dt.file_path, dt.gate_a_status, dt.gate_a_reason,
                       (SELECT COUNT(*) FROM fact_v2 fv WHERE fv.rcept_no = dt.rcept_no) AS facts
                FROM corporations c
                JOIN filings f ON f.corp_code = c.corp_code
                JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
                WHERE c.corp_name = :nm
                  AND f.is_final = TRUE
                  AND f.fiscal_year >= 2022
                  AND dt.file_path IS NOT NULL
                ORDER BY f.fiscal_year DESC, f.fiscal_period
                LIMIT 6
            """), {"nm": nm}).fetchall()

            if not rows:
                print(f"\n=== {nm}: (정기보고 filing 없음) ===")
                continue

            print(f"\n=== {nm} (corp={rows[0].corp_code}, coverage={rows[0].coverage_class}) ===")
            for r in rows:
                ext = Path(r.file_path).suffix.lower() if r.file_path else "?"
                exists = Path(r.file_path).exists() if r.file_path else False
                print(f"  {r.fiscal_year} {r.fiscal_period:3} {r.report_type:8} "
                      f"facts={r.facts:5d} gate={r.gate_a_reason or r.gate_a_status or '-':14} "
                      f"{ext} exists={exists}")
                print(f"        rcept={r.rcept_no}  {r.file_path}")


if __name__ == "__main__":
    main()
