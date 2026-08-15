"""Follow-up probe (2026-08-11, same day as Phase 1) — 50건 파일럿에서 xbrl_zip **다운로드는
성공했지만 report_lines 추출은 0건**이었던 문제의 범위 확인.

원인 1건 확정됨: 파일럿(rcept_no 오름차순 50건)이 전부 2015-01-09~2015-05-13 필링에
쏠려 있었고, 이 시기 XBRL은 `extract_report_lines_xbrl()`이 기대하는 'ifrs-full' 네임스페이스
접두사가 없는 구형 DART taxonomy(entry_point_2011-05-02.xsd 계열)를 씀 — 38/44는 이걸로
스킵, 6/44는 zip 내 presentation linkbase(_pre.xml) 부재로 실패.

이 스크립트는: 이게 "2015년 초 한정" 문제인지 "2015+ 전체에 만연"한 문제인지 판정하기 위해
연도를 고르게 층화한 표본(2015~2020, 연 4건)으로 다운로드 없이(ifrs.do에서 zip을 메모리로만
받아 임시파일에 저장) `extract_report_lines_xbrl()`을 직접 호출해 실제 라인 추출 성공률을
확인한다. DB에는 아무것도 쓰지 않는다(download_tasks 미변경).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from collector.legacy_downloader import LegacyDartScraper
from fin2.extract.report_lines_xbrl import extract_report_lines_xbrl

SEED = "extraction-rate-2026-08-11"
N_PER_YEAR = 5
YEARS = [2015, 2016, 2017, 2018, 2019, 2020]


def sample(session) -> list[dict]:
    rows = []
    for year in YEARS:
        q = text("""
            WITH filing_types AS (
              SELECT f.rcept_no, f.corp_code, f.corp_name, f.fiscal_year, f.filed_at,
                     f.report_type, f.fiscal_period, f.period_end_date,
                     bool_or(dt.file_type IN ('xml','xbrl_zip')) AS has_xml
              FROM filings f
              JOIN download_tasks dt ON dt.rcept_no = f.rcept_no AND dt.status = 'completed'
              JOIN corporations c ON c.corp_code = f.corp_code AND c.is_active = true
              WHERE f.filed_at >= :y_start AND f.filed_at < :y_end
              GROUP BY f.rcept_no, f.corp_code, f.corp_name, f.fiscal_year, f.filed_at,
                       f.report_type, f.fiscal_period, f.period_end_date
            )
            SELECT ft.* FROM filing_types ft
            WHERE NOT ft.has_xml
              AND EXISTS (
                SELECT 1 FROM download_tasks dt2
                WHERE dt2.rcept_no = ft.rcept_no AND dt2.file_type='pdf' AND dt2.status='completed'
              )
            ORDER BY md5(ft.rcept_no || :seed)
            LIMIT :n
        """)
        res = session.execute(q, {
            "y_start": f"{year}-01-01", "y_end": f"{year+1}-01-01",
            "seed": SEED, "n": N_PER_YEAR,
        }).mappings().all()
        rows.extend(dict(r) for r in res)
    return rows


def main() -> None:
    with get_session() as session:
        samples = sample(session)
    print(f"sampled {len(samples)} filings across {YEARS}")

    scraper = LegacyDartScraper()
    results = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for s in samples:
            rec = {**s}
            try:
                zip_bytes, dcm_no = scraper.fetch_xbrl_zip(s["rcept_no"])
            except Exception as e:
                rec["xbrl_recoverable"] = None
                rec["extract_result"] = f"fetch_exc:{type(e).__name__}"
                results.append(rec)
                continue
            if not zip_bytes:
                rec["xbrl_recoverable"] = False
                rec["extract_result"] = "not_recoverable"
                results.append(rec)
                continue
            rec["xbrl_recoverable"] = True
            tmp_path = Path(tmpdir) / f"{s['rcept_no']}.zip"
            tmp_path.write_bytes(zip_bytes)
            try:
                lines = extract_report_lines_xbrl(
                    tmp_path,
                    rcept_no=s["rcept_no"],
                    corp_code=s["corp_code"],
                    report_fiscal_year=s["fiscal_year"],
                    report_fiscal_period=s["fiscal_period"],
                    period_end_date=s["period_end_date"],
                )
                rec["extract_result"] = f"rows={len(lines)}"
            except Exception as e:
                rec["extract_result"] = f"extract_exc:{type(e).__name__}:{e}"
            results.append(rec)
            print(f"  {s['fiscal_year']} {s['filed_at']} {s['rcept_no']} {s['corp_name']} "
                  f"-> xbrl={rec['xbrl_recoverable']} extract={rec['extract_result']}")
    scraper.close()

    write_report(results)


def write_report(results: list[dict]) -> None:
    out_path = Path("docs/qa/pdf_only_xbrl_extraction_rate_probe_2026-08-11.md")
    lines = []
    lines.append("# 후속 — XBRL 회수 후 report_lines 추출 성공률 실측 (2026-08-11)")
    lines.append("")
    lines.append(
        "> 50건 파일럿(2015-01~05 쏠림)에서 다운로드 성공 44건 전부 추출 0행이었던 문제의 "
        "범위 확인. 스크립트 = `scripts/probe_xbrl_recovery_extraction_rate.py`(읽기 전용, "
        "DB 미기록, 메모리에서만 zip 받아 즉시 폐기)."
    )
    lines.append("")
    lines.append("| year | rcept_no | corp_name | filed_at | xbrl_recoverable | extract_result |")
    lines.append("|---|---|---|---|---|---|")
    for r in results:
        lines.append(
            f"| {r['fiscal_year']} | {r['rcept_no']} | {r['corp_name']} | {r['filed_at']} | "
            f"{r.get('xbrl_recoverable')} | {r.get('extract_result')} |"
        )
    lines.append("")

    from collections import defaultdict
    by_year = defaultdict(list)
    for r in results:
        by_year[r["fiscal_year"]].append(r)
    lines.append("## 연도별 요약")
    lines.append("")
    lines.append("| year | 표본 | xbrl회수가능 | rows>0(진짜성공) | rows=0(스킵/실패) |")
    lines.append("|---|---|---|---|---|")
    for year in YEARS:
        rs = by_year.get(year, [])
        if not rs:
            continue
        rec_n = sum(1 for r in rs if r.get("xbrl_recoverable"))
        success = sum(1 for r in rs if str(r.get("extract_result", "")).startswith("rows=")
                      and r["extract_result"] != "rows=0")
        zero = sum(1 for r in rs if r.get("extract_result") == "rows=0")
        lines.append(f"| {year} | {len(rs)} | {rec_n} | {success} | {zero} |")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
