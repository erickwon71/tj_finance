"""
standard_financials 핵심 지표를 JSON 스냅샷으로 저장.

코드 수정 전에 실행해 before.json 저장 → 수정 후 after.json 저장
→ compare_snapshots.py로 비교.

사용:
    python scripts/snapshot_metrics.py --output before.json
    python scripts/snapshot_metrics.py --output after.json
    python scripts/snapshot_metrics.py --corp 00126380 --output samsung.json
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent.parent))

from collector.db import get_session
from sqlalchemy import text


_SNAPSHOT_FIELDS = [
    "fiscal_year", "fiscal_period", "statement_type",
    "revenue", "operating_income", "net_income", "controlling_ni",
    "total_assets", "total_liabilities", "total_equity",
    "cfo", "cfi", "cff", "capex",
    "da_total", "ebitda", "fcf", "net_debt",
    "dividends_paid", "shares_out", "data_quality",
]


def take_snapshot(corp_code=None, since_year=2018, output_path="snapshot.json"):
    """standard_financials 핵심 지표 스냅샷 저장."""
    sql = """
        SELECT
            sf.corp_code,
            c.corp_name,
            sf.fiscal_year,
            sf.fiscal_period,
            sf.statement_type,
            sf.revenue,
            sf.operating_income,
            sf.net_income,
            sf.controlling_ni,
            sf.total_assets,
            sf.total_liabilities,
            sf.total_equity,
            sf.cfo,
            sf.cfi,
            sf.cff,
            sf.capex,
            sf.da_total,
            sf.ebitda,
            sf.fcf,
            sf.net_debt,
            sf.dividends_paid,
            sf.shares_out,
            sf.data_quality
        FROM standard_financials sf
        JOIN corporations c ON c.corp_code = sf.corp_code
        WHERE sf.fiscal_year >= :since_year
          AND sf.version = 1
          AND sf.fiscal_period = 'FY'
    """
    params = {"since_year": since_year}
    if corp_code:
        sql += " AND sf.corp_code = :cc"
        params["cc"] = corp_code

    sql += " ORDER BY sf.corp_code, sf.fiscal_year DESC, sf.statement_type"

    with get_session() as session:
        rows = session.execute(text(sql), params).fetchall()

    snapshot = {
        "created_at": str(date.today()),
        "corp_code_filter": corp_code or "ALL",
        "since_year": since_year,
        "count": len(rows),
        "data": {},
    }

    for row in rows:
        cc = row[0]
        name = row[1]
        fy = row[2]
        fp = row[3]
        st = row[4]
        key = f"{cc}|{fy}|{fp}|{st}"
        snapshot["data"][key] = {
            "corp_code":     cc,
            "corp_name":     name,
            "fiscal_year":   fy,
            "fiscal_period": fp,
            "statement_type": st,
            "revenue":           row[5],
            "operating_income":  row[6],
            "net_income":        row[7],
            "controlling_ni":    row[8],
            "total_assets":      row[9],
            "total_liabilities": row[10],
            "total_equity":      row[11],
            "cfo":               row[12],
            "cfi":               row[13],
            "cff":               row[14],
            "capex":             row[15],
            "da_total":          row[16],
            "ebitda":            row[17],
            "fcf":               row[18],
            "net_debt":          row[19],
            "dividends_paid":    row[20],
            "shares_out":        row[21],
            "data_quality":      row[22],
        }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    print(f"스냅샷 저장: {output_path}  ({len(rows)}건, {len(set(r[0] for r in rows))}개 기업)")


def main():
    parser = argparse.ArgumentParser(description="standard_financials 스냅샷 저장")
    parser.add_argument("--output", "-o", default="snapshot.json", help="출력 JSON 파일 경로")
    parser.add_argument("--corp",   default=None, help="특정 기업 DART 코드 (없으면 전체)")
    parser.add_argument("--since",  type=int, default=2018, help="집계 시작 연도 (기본 2018)")
    args = parser.parse_args()

    take_snapshot(
        corp_code=args.corp,
        since_year=args.since,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
