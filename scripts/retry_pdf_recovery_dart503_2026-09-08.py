"""v2 DROP 잔여 항목2(e) — DART 503로 막혀있던 4개사 PDF 복구 재시도 (2026-09-08, 1회성).

배경: `factv2_stdv2_gc_backfill_backlog_2026-09-01.md` §3 Category C PDF 복구 트랙에서
00122825(인스코비)/00124799(사조산업)/00125488(삼륭물산)/00133618(세기상사) 4개사는
당시 DART 웹뷰어(`LegacyDartScraper`) 요청이 503으로 실패해 report_lines 미충원 상태로
남았다(`v2-drop-remaining-backlog-2026-09-03.md` 항목2). 503이 풀렸는지 재시도한다.

`collector/pdf_lines_sync.py::sync_pdf_recovery()` 재사용(멱등: rcept 단위
delete-then-insert). 성공한 corp만 std_v3 재빌드 + calendarize_corp_v3 재동기화.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector.pdf_lines_sync import sync_pdf_recovery

CORPS = ["00122825", "00124799", "00125488", "00133618"]


def main() -> None:
    print(f"[retry-503] 대상: {CORPS}")
    out = sync_pdf_recovery(CORPS)
    print(f"[retry-503] 결과: {out}")

    if out["rows"] == 0:
        print("[retry-503] report_lines 신규 적재 0건 — std_v3 재빌드 스킵.")
        return

    from collector.db import get_session
    from fin2.layer3.build import build_corp
    from fin2.standardize.calendar_v3 import calendarize_corp_v3

    with get_session() as session:
        for corp in CORPS:
            n = build_corp(session, corp, year_min=1999)
            print(f"[retry-503] build_corp({corp}) -> {n} rows")
        session.commit()

    with get_session() as session:
        for corp in CORPS:
            n = calendarize_corp_v3(session, corp)
            print(f"[retry-503] calendarize_corp_v3({corp}) -> {n} rows")
        session.commit()


if __name__ == "__main__":
    main()
