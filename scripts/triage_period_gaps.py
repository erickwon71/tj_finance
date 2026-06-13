"""
Period-gap triage
=================
check_period_completeness.py 가 NOFIL/NODL 로 표시한 셀을 *왜* 비었는지 분류한다.
다운로드 완전성(PRD 01/02) 착수 1단계: 1,783 NOFIL 이 진짜 누락인지, 라벨 artifact 인지,
구조적(특정 기간 미제출 업종/펀드)인지 가른다.

분류 (NOFIL 셀 기준):
  MISLABEL_SAMEYEAR   — 같은 fiscal_year 에 다른 period 의 filing 이 grid 기대보다 많음
                        (= 기간 라벨이 잘못 붙어 한 칸이 비고 다른 칸이 중복) 의심
  EARLY_PREcov        — fiscal_year <= 2003 (분기보고서 의무화 초기, 구조적 희소)
  Q_ONLY              — 비는 게 Q1/Q3(분기)뿐이고 H1/FY 는 있음 (분기 미제출 업종 의심: 금융/펀드)
  GENUINE             — 위 어디에도 안 들어가는, 같은 해 어떤 filing 도 없음 (진짜 누락 → 재싱크 후보)

출력: stdout 요약 + (옵션) CSV.

사용:
    python3 scripts/triage_period_gaps.py [--since 2000] [--csv /tmp/period_gaps.csv]
"""
import argparse
import csv as _csv
from collections import Counter, defaultdict
from datetime import date

from check_period_completeness import (  # 같은 scripts/ 디렉터리
    PERIODS,
    build_expected_grid,
    cell_status,
    fetch_corp_first_period,
    fetch_corps,
    fetch_filings,
)


def classify(corp_filings_by_fy: dict, fy: int, period: str) -> str:
    """단일 NOFIL 셀 분류. corp_filings_by_fy: {fy: set(periods present)}."""
    present = corp_filings_by_fy.get(fy, set())
    if fy <= 2003:
        return "EARLY_PREcov"
    if not present:
        return "GENUINE"
    # 같은 해에 다른 기간 filing 은 있는데 이 period 만 빔
    if period in ("Q1", "Q3") and ("H1" in present or "FY" in present):
        return "Q_ONLY"
    # 같은 해에 뭔가 있으나 패턴이 분기-only 아님
    return "MISLABEL_SAMEYEAR"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=int, default=2000)
    ap.add_argument("--market", choices=["KOSPI", "KOSDAQ"], default=None)
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()

    today = date.today()
    corps = fetch_corps(args.market, None)
    raw_filings = fetch_filings(args.since, args.market, None)
    first_periods = fetch_corp_first_period(args.since, args.market, None)

    by_class = Counter()
    by_period = Counter()
    by_year = Counter()
    by_class_corps = defaultdict(set)
    rows = []

    for corp in corps:
        code = corp["corp_code"]
        fm = corp["fiscal_month"]
        first_fy, first_period = first_periods.get(code, (today.year, "Q1"))
        grid = build_expected_grid(first_fy, first_period, fm, today, args.since)
        if not grid:
            continue

        corp_rows = raw_filings.get(code, [])
        filings_map = defaultdict(list)
        present_by_fy = defaultdict(set)
        for fy, period, is_final, dl in corp_rows:
            if period in PERIODS:
                filings_map[(fy, period)].append((is_final, dl))
                present_by_fy[fy].add(period)

        for fy, p in grid:
            st = cell_status(fy, p, filings_map)
            if st == "OK":
                continue
            if st == "NODL":
                cls = "NODL"
            else:  # NOFIL
                cls = classify(present_by_fy, fy, p)
            by_class[cls] += 1
            by_period[p] += 1
            by_year[fy] += 1
            by_class_corps[cls].add(code)
            rows.append((code, corp["corp_name"], corp["market"], fm, fy, p, st, cls))

    total = sum(by_class.values())
    print(f"총 갭 셀: {total:,}")
    print("\n── 분류별 ──")
    for cls, n in by_class.most_common():
        print(f"  {cls:18s} {n:>6,}  ({len(by_class_corps[cls])} corps)")
    print("\n── period 별 ──")
    for p in PERIODS:
        print(f"  {p:4s} {by_period.get(p,0):>6,}")
    print("\n── fiscal_year 별 (상위 15) ──")
    for fy, n in sorted(by_year.items(), key=lambda x: -x[1])[:15]:
        print(f"  {fy}: {n:>5,}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["corp_code", "corp_name", "market", "fiscal_month",
                        "fiscal_year", "period", "status", "class"])
            w.writerows(rows)
        print(f"\nCSV: {args.csv}  ({len(rows):,} rows)")


if __name__ == "__main__":
    main()
