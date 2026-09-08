"""is_ifrs 판정 근거(2026-09-08) 소급 백필 — §6-5, CLAUDE.md 필수 절차 ② (자동 아님, 별도 실행).

docs/plans/is_ifrs_v3_design_2026-09-08.md 확정 설계: filings.ifrs_evidence 를
fin2/extract/ifrs_evidence.py 로 판정해 채운다. 스코프(사용자 결정, §5) — pre-2015
std_financials_v3 132,026행이 실제로 참조하는 source_rcepts 전체(66,814건, 실측
2026-09-08). 2015+ 필링은 원 가정("전량 IFRS")이 이미 맞았던 구간이라 이번엔 스코프 밖
(후속 세션에 원하면 낮은 우선순위로 진행 — 이 스크립트에 --year-min 을 낮춰 재실행하면 됨).

★ NAS(raw_report 심링크) 대신 SD 카드(dart_data) 경로로 치환해서 읽는다
([[feedback-bulk-read-use-sdcard]] — 대량 read 시 NAS SMB 는 느림).

멱등: filings.ifrs_evidence 가 이미 있는 행은 기본적으로 건너뛴다(--recheck 로 재판정).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from collector.db import get_session
from fin2.extract.ifrs_evidence import store_filing_ifrs_evidence

_NAS_PREFIX = "/Users/taejin/Project/tj_finance/raw_report"
_SD_PREFIX = "/Volumes/dart_data/raw_report"

_TARGETS_SQL = text(
    """
    WITH rc AS (
        SELECT DISTINCT (jsonb_each_text(source_rcepts)).value AS rcept_no
        FROM std_financials_v3
        WHERE fiscal_year < :year_max AND source_rcepts IS NOT NULL
    )
    SELECT f.rcept_no, dt.file_path, dt.file_type, dt.parser_track
    FROM rc
    JOIN filings f ON f.rcept_no = rc.rcept_no
    LEFT JOIN download_tasks dt ON dt.rcept_no = rc.rcept_no
    WHERE (:recheck OR f.ifrs_evidence IS NULL)
    ORDER BY f.rcept_no
    """
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year-max", type=int, default=2015,
                     help="이 회계연도 미만 std_v3 행이 참조하는 rcept만 대상(기본 2015, §5 결정)")
    ap.add_argument("--recheck", action="store_true", help="이미 판정된 rcept도 재판정")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    t0 = time.time()
    with get_session() as session:
        targets = session.execute(_TARGETS_SQL, {"year_max": args.year_max, "recheck": args.recheck}).fetchall()
    if args.limit:
        targets = targets[: args.limit]
    print(f"[backfill-ifrs-evidence] 대상 rcept {len(targets):,}")

    tally: dict[str | None, int] = {}
    no_file = 0
    with get_session() as session:
        for i, t in enumerate(targets, 1):
            file_path = None
            if t.parser_track != "XBRL_INSTANCE" and t.file_path:
                p = t.file_path.replace(_NAS_PREFIX, _SD_PREFIX) if t.file_path.startswith(_NAS_PREFIX) else t.file_path
                if Path(p).exists():
                    file_path = p
                else:
                    no_file += 1
            try:
                evidence = store_filing_ifrs_evidence(session, t.rcept_no, file_path=file_path)
            except Exception as exc:  # noqa: BLE001 — 한 건 실패가 전체를 막으면 안 됨
                print(f"  ! {t.rcept_no}: {type(exc).__name__}: {exc}")
                session.rollback()
                continue
            tally[evidence] = tally.get(evidence, 0) + 1
            if i % 2000 == 0:
                session.commit()
                print(f"  … {i}/{len(targets)} · {time.time()-t0:.0f}s · {tally}")
        session.commit()

    print(f"[backfill-ifrs-evidence] 완료 — {len(targets):,}건 · 파일없음 {no_file:,} · {time.time()-t0:.0f}s")
    print(f"  최종 분포: {tally}")


if __name__ == "__main__":
    main()
