"""L3-3 std_v3 builder driver.

Creates std_financials_v3 (if missing) and builds rows from report_lines via
fin2.layer3.build. Default = sample corps; --all = every corp with report_lines.

Each rebuilt corp is also recalendarized (std_financials_calendar, calendar_v3) in the
same transaction, unless --no-calendar. Until 2026-11-17 this was a separate manual step
(runbook B5) and a rebuild that skipped it left calendar quarters pointing at std_v3 rows
that no longer exist: dq_assertions.py::calendar_orphan_cq ERROR on 2026-11-16 (00323868,
00442455 rebuilt by hand, calendar left from 10-05).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from collector.db import get_session, engine
from collector.models import Base, StdFinancialV3, ExtendedFactV3
from fin2.layer3.build import build_corp
from fin2.standardize.calendar_v3 import calendarize_corp_v3


def _ensure_table():
    StdFinancialV3.__table__.create(bind=engine, checkfirst=True)
    # extended_financials v3 (2026-09-01, docs/plans/extended_financials_v3_label_based_
    # design_2026-09-01.md) — build_corp() now upserts this table alongside std_v3.
    ExtendedFactV3.__table__.create(bind=engine, checkfirst=True)


def _corps(session, args):
    if args.corp:
        return args.corp.split(",")
    rows = session.execute(text("""
        SELECT DISTINCT corp_code FROM report_lines
        WHERE report_fiscal_year >= :ym ORDER BY corp_code
    """), {"ym": args.year_min}).fetchall()
    corps = [r[0] for r in rows]
    if args.shard:
        a, n = (int(x) for x in args.shard.split("/"))
        corps = [c for i, c in enumerate(corps) if i % n == a]
    if args.limit:
        corps = corps[: args.limit]
    return corps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corp", help="쉼표구분 corp_code (지정 시 그것만)")
    ap.add_argument("--all", action="store_true", help="report_lines 보유 전 corp")
    ap.add_argument("--year-min", type=int, default=2015)
    ap.add_argument("--shard", help="a/n 분할")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-calendar", action="store_true",
                    help="달력(std_financials_calendar) 재동기화 생략 — 따로 calendarize_corps.py 를 돌릴 때만")
    args = ap.parse_args()

    _ensure_table()
    with get_session() as s:
        corps = _corps(s, args)
    print(f"[build-std-v3] 대상 corp {len(corps):,}")

    t0 = time.time()
    n_rows = n_corp = n_cal = 0
    with get_session() as session:
        for i, corp in enumerate(corps, 1):
            try:
                # A savepoint per corp: a failure rolls back only this corp's std and
                # calendar rows, never a half-written pair or the other corps of the batch.
                with session.begin_nested():
                    n_rows += build_corp(session, corp, year_min=args.year_min)
                    if not args.no_calendar:
                        n_cal += calendarize_corp_v3(session, corp)
                n_corp += 1
            except Exception as e:  # noqa: BLE001
                print(f"  ! {corp}: {type(e).__name__}: {e}")
            if i % 200 == 0:
                session.commit()
                print(f"  … {i}/{len(corps)} corp · {n_rows:,} rows · {time.time()-t0:.0f}s")
        session.commit()
    cal = "달력 생략(--no-calendar)" if args.no_calendar else f"달력 {n_cal:,} rows"
    print(f"[build-std-v3] 완료 — {n_corp} corp · {n_rows:,} rows · {cal} · {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
