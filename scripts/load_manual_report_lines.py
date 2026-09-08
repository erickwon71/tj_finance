"""사용자가 CSV에 직접 타이핑한 재무제표 항목을 report_lines에 적재한다(최후 수단 경로,
2026-09-07). 형식·설계 근거: fin2/extract/manual_report_lines.py 모듈 docstring 참고.

사용법:
    python scripts/load_manual_report_lines.py <csv_path>              # 적재
    python scripts/load_manual_report_lines.py <csv_path> --dry-run    # 파싱만, DB 안 건드림
    python scripts/load_manual_report_lines.py <csv_path> --overwrite  # 자동추출 산출물 있어도 교체

CSV 컬럼: rcept_no,statement,basis,label_raw,value_raw[,unit][,depth]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.manual_report_lines import (
    FilingMeta, ManualCsvError, build_manual_report_lines, read_manual_csv,
    store_manual_report_lines, unwrap_excel_text,
)


def _load_filing_meta(session, rcept_nos: set[str]) -> dict[str, FilingMeta]:
    if not rcept_nos:
        return {}
    rows = session.execute(
        text("SELECT rcept_no, corp_code, fiscal_year, fiscal_period FROM filings WHERE rcept_no = ANY(:rs)"),
        {"rs": list(rcept_nos)},
    ).fetchall()
    return {r.rcept_no: FilingMeta(r.corp_code, r.fiscal_year, r.fiscal_period) for r in rows}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_path")
    ap.add_argument("--dry-run", action="store_true", help="파싱·검증만 하고 DB에 쓰지 않는다")
    ap.add_argument("--overwrite", action="store_true", help="같은 (rcept_no,statement,basis)에 자동추출 산출물이 있어도 교체")
    args = ap.parse_args()

    try:
        csv_rows = read_manual_csv(args.csv_path)
    except ManualCsvError as e:
        print(f"CSV error: {e}", file=sys.stderr)
        raise SystemExit(1)

    if not csv_rows:
        print("CSV has no data rows — nothing to do.")
        return

    # ★엑셀이 rcept_no를 지수표기(2.00208E+13)로 바꾸는 걸 막으려고 review CSV는 그 컬럼을
    #   ="20020814000872" 형태로 감싸 둔다 — filings 조회 전에 풀어야 실제 접수번호로 찾는다.
    rcept_nos = {unwrap_excel_text((row.get("rcept_no") or "").strip()) for row in csv_rows}
    rcept_nos.discard("")

    with get_session() as session:
        filing_lookup = _load_filing_meta(session, rcept_nos)
        try:
            rows = build_manual_report_lines(csv_rows, filing_lookup)
        except ManualCsvError as e:
            print(f"CSV error: {e}", file=sys.stderr)
            raise SystemExit(1)

        scopes = sorted({(r.rcept_no, r.statement, r.basis) for r in rows})
        print(f"parsed {len(rows)} row(s) across {len(scopes)} scope(s):")
        for rcept_no, statement, basis in scopes:
            n = sum(1 for r in rows if (r.rcept_no, r.statement, r.basis) == (rcept_no, statement, basis))
            n_blank = sum(1 for r in rows if (r.rcept_no, r.statement, r.basis) == (rcept_no, statement, basis) and r.value_won is None)
            print(f"  {rcept_no} {statement}/{basis}: {n} line(s), {n_blank} blank/unparsed")

        if args.dry_run:
            print("dry-run — nothing written.")
            return

        try:
            result = store_manual_report_lines(session, rows, overwrite=args.overwrite)
        except ValueError as e:
            print(f"refused: {e}", file=sys.stderr)
            print("(재확인 후 --overwrite 로 다시 실행)", file=sys.stderr)
            raise SystemExit(1)
        print(f"stored: {result}")


if __name__ == "__main__":
    main()
