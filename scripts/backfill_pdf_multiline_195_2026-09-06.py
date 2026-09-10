"""R75(3줄 이중언어 PDF 레이아웃) census 195건(72개사) 소급 백필.

`docs/PARSING_RULES.md` R75 "아직 안 한 것"의 ② 실행: report_lines 재수집·재파싱
(`collector/pdf_lines_sync.py::recover_one()` — 오늘 갱신된 `fin2/extract/pdf.py`
3줄 파서를 그대로 재사용) → 영향받는 72개사만 std_v3 재빌드+calendarize → 항등식
(자산총계=부채총계+자본총계) before/after 전이표로 회귀 확인.

`recover_one()`은 이미 report_lines 가 존재하는 rcept 도 재처리하도록 직접 호출한다
(`collector/pdf_lines_sync.py::sync_pdf_recovery()`의 기본 후보 SQL은 `NOT EXISTS
report_lines`만 잡는 순수 갭필용이라 이번 대상엔 안 맞음 — 이번 195건은 이미
report_lines가 존재함, 다만 근접손실 상태). `store_report_lines()`가 rcept 단위
delete-then-insert라 재실행 안전.

실행: python scripts/backfill_pdf_multiline_195_2026-09-06.py
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
ORDER BY corp_code, rcept_no
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
    out = {}
    for r in rows:
        key = (r.corp_code, r.fiscal_year, r.fiscal_period, r.statement_type)
        out[key] = identity_status(r.total_assets, r.total_liabilities, r.total_equity)
    return out


def main() -> None:
    with get_session() as session:
        targets = session.execute(text(CENSUS_SQL)).fetchall()
    print(f"대상 필링: {len(targets)}건")
    corps = sorted({t.corp_code for t in targets})
    print(f"대상 회사: {len(corps)}개사")

    # ── BEFORE 스냅샷 ────────────────────────────────────────────
    with get_session() as session:
        before = snapshot_identity(session, corps)

    # ── 1) report_lines 재수집·재파싱(오늘 갱신된 3줄 파서) ─────────
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
                except Exception as exc:  # noqa: BLE001 — 한 건 실패가 전체를 막지 않음
                    stats["errors"] += 1
                    session.rollback()
                    logger.warning(f"[backfill195] {t.rcept_no} 실패: {type(exc).__name__}: {exc}")
                    continue
                if i % 20 == 0:
                    session.commit()
                    print(f"  … report_lines {i}/{len(targets)}")
            session.commit()
    finally:
        scraper.close()

    print(f"report_lines 재수집 결과: {stats}")

    # ── 2) 영향받는 72개사만 std_v3 재빌드 + calendarize ────────────
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
    if build_errors:
        print(f"std_v3 재빌드 오류 {len(build_errors)}건: {build_errors}")
    else:
        print(f"std_v3 재빌드 + calendarize 완료 ({len(corps)}개사, 오류 0)")

    # ── AFTER 스냅샷 + 전이표 ────────────────────────────────────
    with get_session() as session:
        after = snapshot_identity(session, corps)

    keys = sorted(set(before) | set(after))
    from collections import Counter
    transitions = Counter()
    regressions = []
    for k in keys:
        b = before.get(k, "absent")
        a = after.get(k, "absent")
        transitions[(b, a)] += 1
        if b == "ok" and a != "ok":
            regressions.append((k, b, a))

    print("\n항등식(자산총계=부채총계+자본총계) 전이표 (before -> after : 건수)")
    for (b, a), n in sorted(transitions.items(), key=lambda x: -x[1]):
        print(f"  {b:>7} -> {a:<7} : {n}")

    if regressions:
        print(f"\n⚠ 회귀(이전엔 ok였는데 after에 ok가 아님) {len(regressions)}건:")
        for k, b, a in regressions[:20]:
            print(f"   {k} {b} -> {a}")
    else:
        print("\n✅ 회귀 0건 (이전 ok였던 키가 전부 after에도 ok)")


if __name__ == "__main__":
    main()
