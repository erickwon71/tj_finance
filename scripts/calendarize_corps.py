"""calendar_v3 resync for an arbitrary set of corps.

Run this after ANY change to `std_financials_v3` for a corp set (a backfill, a
targeted `build_std_v3.py --corp ...` rebuild). Skipping it leaves calendar rows
pointing at std_v3 rows that no longer exist -- `dq_assertions.py::
calendar_orphan_cq` reports those as ERROR. Same reasoning as
`layer2_review.py::cmd_finish_corp`, which pairs the two for a single corp.

This replaces the dated one-off `calendarize_*_<date>.py` scripts (six of them
by 2026-09-19) that each hardcoded their corp list.

Usage:
    python scripts/calendarize_corps.py --corp-file logs/std_v3_stale_corps.txt
    python scripts/calendarize_corps.py --corp 00126380,00164779
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402
from fin2.standardize.calendar_v3 import calendarize_corp_v3  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Reuse the gate's own orphan predicate -- defining a second one here would let
# this script report 0 while the gate still reports ERROR.
from diag_calendar_orphans import _ORPHAN_PRED  # noqa: E402


def _parse_corps(args) -> list[str]:
    raw = (Path(args.corp_file).read_text(encoding="utf-8")
           if args.corp_file else args.corp)
    return [c for c in (x.strip() for x in raw.replace("\n", ",").split(","))
            if c]


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--corp", help="comma-separated corp_code list")
    g.add_argument("--corp-file", help="file holding corp codes (comma/newline)")
    ap.add_argument("--commit-every", type=int, default=50,
                    help="commit cadence, in corps (default 50)")
    args = ap.parse_args()

    corps = _parse_corps(args)
    print(f"calendarize 대상 {len(corps)}개사", flush=True)

    total = 0
    with get_session() as session:
        for i, corp in enumerate(corps, 1):
            total += calendarize_corp_v3(session, corp)
            if i % args.commit_every == 0:
                session.commit()
                print(f"  {i}/{len(corps)} — 누적 {total:,}행", flush=True)
        session.commit()
        print(f"calendarize 완료 — {total:,}행 / {len(corps)}개사")

        orphans = session.execute(
            text(f"""SELECT count(*) FROM std_financials_calendar cf
                     WHERE cf.corp_code = ANY(:c) AND {_ORPHAN_PRED}"""),
            {"c": corps}).scalar_one()
    print(f"calendar_orphan_cq = {orphans}건"
          + ("  ✅" if orphans == 0 else "  ⚠ 조사 필요"))


if __name__ == "__main__":
    main()
