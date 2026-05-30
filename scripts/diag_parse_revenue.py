"""
단일 XML 파싱 후 특정 계정(기본 is.revenue)의 fact를 출력 — 단위 탐지 검증용.

사용:
    python3 scripts/diag_parse_revenue.py <file.xml> --corp 00162416 \
        --year 2012 --period FY --type annual [--code is.revenue]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parser.xml.dart_xml_parser import parse_dart_xml


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file_path")
    ap.add_argument("--corp", default="TEST")
    ap.add_argument("--year", type=int, default=2000)
    ap.add_argument("--period", default="FY")
    ap.add_argument("--type", default="annual", dest="report_type")
    ap.add_argument("--code", default="is.revenue")
    args = ap.parse_args()

    result = parse_dart_xml(
        file_path=Path(args.file_path),
        rcept_no="DIAG",
        corp_code=args.corp,
        fiscal_year=args.year,
        fiscal_period=args.period,
        report_type=args.report_type,
    )
    print(f"parse_status={result.parse_status}  track={result.parser_track}  facts={len(result.facts)}")
    print(f"대상 계정: {args.code}")
    print(f"  {'fs_type':<8} {'col':>3} {'unit_mult':>9} {'amount_억':>16}  account_name_raw")
    hits = [f for f in result.facts if f.account_code == args.code]
    if not hits:
        print("  (해당 계정 fact 없음)")
    for f in sorted(hits, key=lambda x: (x.fs_type, x.col_index)):
        awk = (f.amount / 1e8) if f.amount is not None else None
        awk_s = f"{awk:,.1f}" if awk is not None else "None"
        print(f"  {f.fs_type:<8} {f.col_index:>3} {f.unit_multiplier:>9} {awk_s:>16}  {f.account_name_raw}")


if __name__ == "__main__":
    main()
