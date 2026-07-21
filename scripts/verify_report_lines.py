"""계층2 검증 러너 — report_lines(추출) ↔ 원문 face 표 1:1 대조.

원문 정의·방법론은 `fin2/audit/report_line_audit.py` 참고. 기본은 **FY(연간)** 보고서 대조
(interim 은 report_lines 가 YTD 컬럼만 채택해 3개월 컬럼이 MISSING 으로 잡히므로 참고용).

사용:
    python scripts/verify_report_lines.py --corp 00101220            # 한 기업 전 FY
    python scripts/verify_report_lines.py --rcept 20240321001911     # 한 보고서
    python scripts/verify_report_lines.py --sample 200               # 무작위 200 FY 보고서
    python scripts/verify_report_lines.py --sample 200 --period all   # interim 포함
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import extract_report_lines
from fin2.audit.report_line_audit import read_face_amounts, audit_report_lines


def _verify_one(rcept_no, file_path, corp_code, fy, period):
    lines = extract_report_lines(
        file_path, rcept_no=rcept_no, corp_code=corp_code,
        report_fiscal_year=fy, report_fiscal_period=period,
    )
    face = read_face_amounts(file_path)
    return audit_report_lines(rcept_no, face, lines), len(lines)


def _fetch(session, args):
    if args.rcept:
        sql = """SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
                 FROM download_tasks dt JOIN filings f USING(rcept_no)
                 WHERE dt.rcept_no=:r AND dt.file_type='xml' AND dt.status='completed'"""
        return session.execute(text(sql), {"r": args.rcept}).fetchall()
    where = ["dt.status='completed'", "dt.file_type='xml'", "dt.file_path IS NOT NULL",
             "f.fiscal_period IS NOT NULL", "f.report_nm NOT LIKE '%정정%'"]
    params = {}
    if args.corp:
        where.append("f.corp_code=:c"); params["c"] = args.corp
    if args.period == "fy":
        where.append("f.fiscal_period='FY'")
    if args.year:
        where.append("f.fiscal_year=:y"); params["y"] = args.year
    sql = f"""SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
              FROM download_tasks dt JOIN filings f USING(rcept_no)
              WHERE {' AND '.join(where)}"""
    rows = session.execute(text(sql), params).fetchall()
    if args.sample and len(rows) > args.sample:
        rows = random.Random(42).sample(rows, args.sample)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corp")
    ap.add_argument("--rcept")
    ap.add_argument("--year", type=int)
    ap.add_argument("--sample", type=int)
    ap.add_argument("--period", choices=["fy", "all"], default="fy")
    ap.add_argument("--show", type=int, default=10, help="상세 출력할 실패 보고서 수")
    args = ap.parse_args()

    with get_session() as session:
        rows = _fetch(session, args)
    if not rows:
        print("대상 없음"); return

    n = passed = held_only = 0
    fails = []
    for r in rows:
        if not Path(r.file_path).exists():
            continue
        try:
            res, n_lines = _verify_one(r.rcept_no, r.file_path, r.corp_code,
                                       r.fiscal_year, r.fiscal_period)
        except Exception as e:
            fails.append((r, None, f"ERR {type(e).__name__}: {e}"))
            n += 1
            continue
        n += 1
        # FY(연간): 양방향 완전일치. interim(H1/Q1/Q3): report_lines 는 IS/CF 에서 YTD(누적)
        # 컬럼만 채택하므로 원문의 3개월 컬럼이 MISSING 으로 남는 게 정상 → **EXTRA=0(=DB가
        # 원문의 부분집합, 날조/오파싱 없음)**을 통과 기준으로 삼는다.
        is_interim = r.fiscal_period != "FY"
        ok = (not res.extra) if is_interim else res.passed
        if ok:
            passed += 1
        else:
            fails.append((r, res, None))

    gate = "EXTRA=0(부분집합)" if args.period != "fy" else "원문↔DB 완전일치"
    print(f"\n=== 계층2 검증: {n}개 보고서 (period={args.period}) ===")
    print(f"PASS({gate}) {passed}/{n} ({100*passed//max(n,1)}%)")
    print(f"불일치 {len(fails)}건")
    for r, res, err in fails[: args.show]:
        tag = f"{r.corp_code} r{r.rcept_no} {r.fiscal_year}{r.fiscal_period}"
        if err:
            print(f"  ✗ {tag}: {err}"); continue
        print(f"  ✗ {tag}: match={res.match_rate:.1%} "
              f"missing={len(res.missing)} extra={len(res.extra)} "
              f"held_tables={res.held_tables}")
        for v in sorted(res.missing, key=lambda x: -abs(x))[:5]:
            print(f"      MISSING(원문에만) {v:>18,}")
        for v in sorted(res.extra, key=lambda x: -abs(x))[:5]:
            print(f"      EXTRA(DB에만)     {v:>18,}")


if __name__ == "__main__":
    main()
