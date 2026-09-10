"""3줄 이중언어 레이아웃(R75) 표본 dry-run 검증 — DB 미기록, 원문 재수집+파싱만.

census(scripts/census_multiline_layout_2026-09-06.py) 195건/72개사 중 회사당 1건씩
(연도·분기 다양성 확보를 위해 census SQL의 ORDER BY corp,year,period 순 첫 필링을
채택) 골라 실제 DART 웹뷰어에서 재수집 → fin2/extract/pdf.py::extract_pdf_facts()로
파싱 → 회계항등식(자산=부채+자본)·예외·0건 여부만 점검한다. **DB에는 아무것도 쓰지
않는다** — 설계문서 "검증 계획: dry-run 먼저, 절대 바로 backfill 하지 않는다" 준수.

실행: python scripts/dryrun_multiline_sample_2026-09-06.py [--limit N]
"""
import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from collector.db import get_session
from collector.legacy_downloader import LegacyDartScraper
from fin2.extract.pdf import extract_pdf_facts

CENSUS_SQL = """
WITH pdf_filings AS (
    SELECT DISTINCT rcept_no, corp_code, report_fiscal_year, report_fiscal_period
    FROM report_lines WHERE unit_source = 'pdf'
),
counts AS (
    SELECT pf.rcept_no, pf.corp_code, pf.report_fiscal_year, pf.report_fiscal_period,
           rl.basis,
           COUNT(*) FILTER (WHERE rl.statement = 'BS') AS bs_n,
           COUNT(*) FILTER (WHERE rl.statement = 'CF') AS cf_n
    FROM pdf_filings pf
    JOIN report_lines rl ON rl.rcept_no = pf.rcept_no
    GROUP BY pf.rcept_no, pf.corp_code, pf.report_fiscal_year, pf.report_fiscal_period, rl.basis
)
SELECT DISTINCT rcept_no, corp_code, report_fiscal_year, report_fiscal_period
FROM counts
WHERE bs_n <= 2 AND cf_n >= 8
ORDER BY corp_code, report_fiscal_year, report_fiscal_period
"""


def select_sample(one_per_corp: bool) -> list[tuple]:
    with get_session() as session:
        rows = session.execute(text(CENSUS_SQL)).fetchall()
    if not one_per_corp:
        return [tuple(r) for r in rows]
    seen = set()
    out = []
    for r in rows:
        if r.corp_code in seen:
            continue
        seen.add(r.corp_code)
        out.append(tuple(r))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--all-filings", action="store_true",
                     help="회사당 1건이 아니라 전체 필링을 순회")
    args = ap.parse_args()

    sample = select_sample(one_per_corp=not args.all_filings)
    if args.limit:
        sample = sample[: args.limit]
    print(f"sample size: {len(sample)}")

    scraper = LegacyDartScraper()
    results = {"pdf_ok": 0, "html_fallback": 0, "no_content": 0, "exception": 0,
               "zero_facts": 0, "identity_ok": 0, "identity_fail": 0, "no_identity_data": 0}
    identity_oks = []
    identity_fails = []
    no_data = []
    exceptions = []
    zero_facts = []
    t0 = time.monotonic()
    try:
        for i, (rcept, corp, fy, period) in enumerate(sample, 1):
            try:
                content, fmt = scraper.fetch(rcept)
            except Exception as exc:  # noqa: BLE001
                results["exception"] += 1
                exceptions.append((corp, rcept, f"fetch: {type(exc).__name__}: {exc}"))
                continue
            if not content:
                results["no_content"] += 1
                continue
            if fmt != "pdf":
                results["html_fallback"] += 1
                continue
            results["pdf_ok"] += 1
            try:
                with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
                    tmp.write(content)
                    tmp.flush()
                    facts = extract_pdf_facts(
                        tmp.name, corp_code=corp, rcept_no=rcept,
                        report_fiscal_year=fy, report_fiscal_period=period)
            except Exception as exc:  # noqa: BLE001
                results["exception"] += 1
                exceptions.append((corp, rcept, f"parse: {type(exc).__name__}: {exc}"))
                continue

            if not facts:
                results["zero_facts"] += 1
                zero_facts.append((corp, rcept, fy, period))
                continue

            by = {}
            for f in facts:
                by.setdefault((f.basis, f.canonical_account), []).append(f.amount_won)
            for basis in ("separate", "consolidated"):
                # ★2026-09-06 — 같은 canonical(예: bs.total_liabilities)에 후보가 둘 이상
                # 살아남는 경우가 있다(예: "부채"(bare 헤더 잔재)와 "부채총계"(진짜 합계) —
                # acode 가 달라 seen dedup 을 안 탄다). "마지막 후보가 항상 맞다"는 가정은
                # 반증됨(00148276: "(부채총계)"가 먼저, "부채총계"가 나중인데 실제로는
                # **먼저 것**이 맞음) — 실제 파이프라인은 Layer3 `_reduce_conflict()`가
                # 정교하게 고르지만 이 dry-run 스크립트는 그 로직이 없다. 대신 "후보 조합 중
                # 항등식이 성립하는 조합이 존재하는가"로 완화해서 판정한다 — 이건 Layer3가
                # 원리적으로 도달 가능한 정답이 있는지를 보는 것이지, Layer3가 실제로 그
                # 조합을 고를지 보장하진 않는다(별개 검증 필요, 이 스크립트의 한계로 기록).
                A_cands = by.get((basis, "bs.total_assets"), [])
                L_cands = by.get((basis, "bs.total_liabilities"), [])
                E_cands = by.get((basis, "bs.total_equity"), [])
                if not A_cands and not L_cands and not E_cands:
                    continue
                found = False
                for a in A_cands:
                    for l in L_cands:
                        for e in E_cands:
                            if a == l + e:
                                found = True
                                break
                        if found:
                            break
                    if found:
                        break
                if found:
                    results["identity_ok"] += 1
                    identity_oks.append((corp, rcept, fy, period, basis,
                                          A_cands, L_cands, E_cands))
                elif A_cands and L_cands and E_cands:
                    results["identity_fail"] += 1
                    identity_fails.append((corp, rcept, fy, period, basis,
                                            A_cands, L_cands, E_cands))
                else:
                    results["no_identity_data"] += 1
                    no_data.append((corp, rcept, fy, period, basis,
                                     A_cands, L_cands, E_cands))

            if i % 10 == 0 or i == len(sample):
                elapsed = time.monotonic() - t0
                print(f"... {i}/{len(sample)} done ({elapsed:.0f}s elapsed)")
    finally:
        scraper.close()

    print("\n=== summary ===")
    for k, v in results.items():
        print(f"  {k}: {v}")

    dart_url = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"

    def _dump(title, rows):
        print(f"\n=== {title} ({len(rows)}) ===")
        for corp, rcept, fy, period, basis, A, L, E in rows:
            print(f"  {corp} {rcept} {fy} {period} {basis} A={A} L={L} E={E}")
            print(f"    {dart_url.format(rcept)}")

    _dump("identity_ok", identity_oks)
    _dump("identity_fail", identity_fails)
    _dump("no_identity_data", no_data)

    print(f"\n=== exceptions ({len(exceptions)}) ===")
    for row in exceptions:
        print(" ", row)

    print(f"\n=== zero_facts ({len(zero_facts)}) ===")
    for row in zero_facts:
        print(" ", row)


if __name__ == "__main__":
    main()
