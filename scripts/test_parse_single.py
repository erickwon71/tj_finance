"""
단일 파일(XML 또는 PDF)을 DB 저장 없이 파싱해 결과를 콘솔에 출력.

파서 코드 수정 시 단일 파일로 먼저 검증하는 용도.

사용:
    python scripts/test_parse_single.py /path/to/file.xml
    python scripts/test_parse_single.py /path/to/file.xml --corp 00126380 --year 2023 --period FY
    python scripts/test_parse_single.py /path/to/file.xml --verbose   # fact 목록 전체 출력
"""
import sys
import argparse
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))

from parser.xml.dart_xml_parser import parse_dart_xml
from parser.common.account_mapper import get_mapper


def _fmt_won(v):
    """원 단위 숫자 표시."""
    if v is None:
        return "—"
    if abs(v) >= 1e12:
        return f"{v/1e12:.2f}조"
    if abs(v) >= 1e8:
        return f"{v/1e8:.1f}억"
    return f"{v:,}"


def test_parse(file_path: str, corp_code: str, fiscal_year: int,
               fiscal_period: str, report_type: str,
               verbose: bool = False, rcept_no: str = "TEST"):
    """파싱 결과를 출력만 하고 DB에 저장하지 않음."""
    fp = Path(file_path)
    if not fp.exists():
        print(f"[오류] 파일 없음: {file_path}")
        sys.exit(1)

    ext = fp.suffix.lower()
    print(f"\n{'='*65}")
    print(f"파일: {fp.name}  ({fp.stat().st_size / 1024:.1f} KB)")
    print(f"옵션: corp={corp_code}  fy={fiscal_year}  period={fiscal_period}  type={report_type}")
    print(f"{'='*65}\n")

    if ext == ".xml":
        result = parse_dart_xml(
            file_path=fp,
            rcept_no=rcept_no,
            corp_code=corp_code,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            report_type=report_type,
        )
    elif ext == ".pdf":
        try:
            from parser.pdf.dart_pdf_parser import parse_dart_pdf
            result = parse_dart_pdf(
                file_path=fp,
                rcept_no=rcept_no,
                corp_code=corp_code,
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
                report_type=report_type,
            )
        except ImportError:
            print("[오류] PDF 파서 미구현 (parser/pdf/dart_pdf_parser.py 없음)")
            sys.exit(1)
    else:
        print(f"[오류] 지원하지 않는 파일 형식: {ext}")
        sys.exit(1)

    # ── 요약 출력 ──────────────────────────────────────────────────
    print(f"파싱 결과: {result.parse_status.upper()}  (Track {result.parser_track})")
    print(f"추출된 facts: {len(result.facts)}건")
    print(f"unknown accounts: {len(result.unknown_accounts_seen)}종\n")

    # fact 통계 — 섹션별 카운트
    fs_counter = Counter(f.fs_type for f in result.facts)
    print("섹션별 facts 수:")
    for k, v in sorted(fs_counter.items()):
        print(f"  {k:<10}: {v}건")

    # 매핑된 표준 계정 목록 요약
    mapper = get_mapper()
    mapped_cols: dict[str, int] = {}  # standard column → amount
    for fact in result.facts:
        col = mapper.map(fact.account_code, fact.fs_type[:4], fact.fs_type)
        if col and not col.startswith("unknown"):
            val = int(fact.amount) if fact.amount is not None else None
            mapped_cols[col] = val

    if mapped_cols:
        print(f"\n매핑된 표준 컬럼 ({len(mapped_cols)}개):")
        priority = [
            "revenue", "operating_income", "net_income", "total_assets",
            "total_liabilities", "total_equity", "cfo", "cfi", "cff",
            "ebitda", "fcf", "capex", "da_total", "dividends_paid",
        ]
        shown = set()
        for col in priority:
            if col in mapped_cols:
                print(f"  {col:<22}: {_fmt_won(mapped_cols[col])}")
                shown.add(col)
        rest = [c for c in mapped_cols if c not in shown]
        if rest:
            print(f"  ... 외 {len(rest)}개 컬럼")

    # unknown accounts
    if result.unknown_accounts_seen:
        print(f"\n미매핑 계정 top 10:")
        for acc, info in sorted(
            result.unknown_accounts_seen.items(),
            key=lambda x: x[1]["count"], reverse=True
        )[:10]:
            print(f"  [{info['fs_type']:<8}] {acc[:50]:<50}  {info['count']}건")

    # verbose: 전체 fact 목록
    if verbose:
        print(f"\n전체 facts ({len(result.facts)}건):")
        print(f"  {'fs_type':<10} {'account_code':<35} {'account_name':<40} {'amount':>18}  conf")
        print(f"  {'-'*108}")
        for f in sorted(result.facts, key=lambda x: (x.fs_type, x.row_order)):
            amt_str = _fmt_won(int(f.amount)) if f.amount is not None else "—"
            print(
                f"  {f.fs_type:<10} {f.account_code[:34]:<35} "
                f"{f.account_name_raw[:39]:<40} {amt_str:>18}  {f.extraction_confidence:.2f}"
            )

    print()


def main():
    parser = argparse.ArgumentParser(description="단일 파일 파싱 테스트 (DB 저장 없음)")
    parser.add_argument("file_path",   help="파싱할 XML 또는 PDF 파일 경로")
    parser.add_argument("--corp",      default="00000000",  help="DART 기업코드 (기본 00000000)")
    parser.add_argument("--year",      type=int, default=2024, help="회계연도 (기본 2024)")
    parser.add_argument("--period",    default="FY",
                        choices=["FY", "H1", "H2", "Q1", "Q3"],
                        help="회계기간 (기본 FY)")
    parser.add_argument("--type",      default="annual", dest="report_type",
                        choices=["annual", "semi-annual", "quarterly"],
                        help="보고서 종류 (기본 annual)")
    parser.add_argument("--rcept-no",  default="TEST", dest="rcept_no",
                        help="공시번호 (기본 TEST)")
    parser.add_argument("--verbose",   action="store_true",
                        help="전체 fact 목록 출력")
    args = parser.parse_args()

    test_parse(
        file_path=args.file_path,
        corp_code=args.corp,
        fiscal_year=args.year,
        fiscal_period=args.period,
        report_type=args.report_type,
        verbose=args.verbose,
        rcept_no=args.rcept_no,
    )


if __name__ == "__main__":
    main()
