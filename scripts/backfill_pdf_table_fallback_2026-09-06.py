"""R78(표-격자 폴백, fin2/extract/pdf.py) 적용 후 잔여 결측 재백필.

`_region_has_anchor_labels()`가 텍스트 스트림에서 거부하는 리전(라벨이 숫자를 사이에
두고 줄바꿈되는 등)에 pdfplumber `extract_tables()` 폴백을 새로 추가한 직후 실행.
대상은 지금 std_financials_v3에 A/L/E 중 하나 이상이 NULL로 남은 census(195건) 필링
전체 — R75/R77 두 차례 백필 이후에도 남아있던 것들을 다시 재조회한다(00102432·
00115694·00116268는 이번 트랙 발견 과정에서 이미 수동 반영됨, 재실행해도 idempotent).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from loguru import logger

from collector.db import get_session
from collector.legacy_downloader import LegacyDartScraper
from collector.pdf_lines_sync import recover_one
from fin2.extract.report_lines import store_report_lines
from fin2.layer3.build import build_corp
from fin2.standardize.calendar_v3 import calendarize_corp_v3

RESIDUAL_MISSING_SQL = """
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
),
targets_raw AS (
    SELECT DISTINCT rcept_no, corp_code, report_fiscal_year, report_fiscal_period
    FROM counts
    WHERE bs_n <= 2 AND cf_n >= 8
),
targets AS (
    SELECT t.*, b.basis
    FROM targets_raw t
    CROSS JOIN (VALUES ('consolidated'),('separate')) AS b(basis)
)
SELECT DISTINCT t.rcept_no, t.corp_code, t.report_fiscal_year, t.report_fiscal_period
FROM targets t
LEFT JOIN std_financials_v3 s
  ON s.corp_code=t.corp_code AND s.fiscal_year=t.report_fiscal_year
 AND s.fiscal_period=t.report_fiscal_period AND s.statement_type=t.basis
WHERE s.total_assets IS NULL OR s.total_liabilities IS NULL OR s.total_equity IS NULL
ORDER BY t.corp_code, t.rcept_no
"""

IDENTITY_SQL = """
SELECT corp_code, fiscal_year, fiscal_period, statement_type,
       total_assets, total_liabilities, total_equity
FROM std_financials_v3
WHERE corp_code = ANY(:corps) AND fiscal_year BETWEEN 1999 AND 2003
"""


def identity_status(a, l, e) -> str:
    if a is None or l is None or e is None:
        return "missing"
    return "ok" if a == l + e else "fail"


def snapshot_identity(session, corps: list[str]) -> dict:
    rows = session.execute(text(IDENTITY_SQL), {"corps": corps}).fetchall()
    return {
        (r.corp_code, r.fiscal_year, r.fiscal_period, r.statement_type):
            identity_status(r.total_assets, r.total_liabilities, r.total_equity)
        for r in rows
    }


def main() -> None:
    with get_session() as session:
        targets = session.execute(text(RESIDUAL_MISSING_SQL)).fetchall()
    print(f"잔여 대상 필링: {len(targets)}건")
    corps = sorted({t.corp_code for t in targets})
    print(f"대상 회사: {len(corps)}개사")

    with get_session() as session:
        before = snapshot_identity(session, corps)

    stats = {"candidates": len(targets), "recovered_pdf": 0, "recovered_html_only": 0,
              "no_content": 0, "rows": 0, "errors": 0}
    scraper = LegacyDartScraper()
    try:
        with get_session() as session:
            for i, t in enumerate(targets, 1):
                try:
                    lines, raw_bytes, fmt = recover_one(
                        scraper, t.rcept_no, t.corp_code,
                        t.report_fiscal_year, t.report_fiscal_period)
                    if raw_bytes is None:
                        stats["no_content"] += 1
                        continue
                    if fmt != "pdf":
                        stats["recovered_html_only"] += 1
                        continue
                    stats["recovered_pdf"] += 1
                    if lines:
                        stats["rows"] += store_report_lines(session, t.rcept_no, lines)
                except Exception as exc:  # noqa: BLE001
                    stats["errors"] += 1
                    session.rollback()
                    logger.warning(f"[backfill_table] {t.rcept_no} 실패: {type(exc).__name__}: {exc}")
                    continue
                if i % 15 == 0:
                    session.commit()
                    print(f"  … report_lines {i}/{len(targets)}")
            session.commit()
    finally:
        scraper.close()

    print(f"report_lines 재수집 결과: {stats}")

    build_errors = []
    with get_session() as session:
        for corp in corps:
            try:
                build_corp(session, corp, year_min=1999)
                calendarize_corp_v3(session, corp)
            except Exception as exc:  # noqa: BLE001
                build_errors.append((corp, f"{type(exc).__name__}: {exc}"))
                session.rollback()
                continue
        session.commit()
    print(f"std_v3 재빌드 완료 ({len(corps)}개사, 오류 {len(build_errors)}건)")
    if build_errors:
        print(build_errors)

    with get_session() as session:
        after = snapshot_identity(session, corps)

    from collections import Counter
    keys = sorted(set(before) | set(after))
    transitions = Counter()
    regressions = []
    for k in keys:
        b = before.get(k, "absent")
        a = after.get(k, "absent")
        transitions[(b, a)] += 1
        if b == "ok" and a != "ok":
            regressions.append((k, b, a))

    print("\n전이표 (before -> after : 건수)")
    for (b, a), n in sorted(transitions.items(), key=lambda x: -x[1]):
        print(f"  {b:>7} -> {a:<7} : {n}")
    if regressions:
        print(f"\n⚠ 회귀 {len(regressions)}건: {regressions[:20]}")
    else:
        print("\n✅ 회귀 0건")


if __name__ == "__main__":
    main()
