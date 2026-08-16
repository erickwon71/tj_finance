"""T2 — note_lines 'header_hint=기수' 오분류 재백필 (2026-08-16).

R28(commit f019cd9)에서 공용함수 `table_extractor.py::_header_rule_name`의 "기수" 규칙
부분일치 버그를 수정했다(원/% 유무로 판별). 그 수정은 report_lines(본문) 소급백필까지는
됐지만(R28 286개사), `reload_report_lines_corp.py`가 `include_notes=False`라서 note_lines
는 전혀 재추출되지 않았다 — 그래서 49개사·501행·250필링이 여전히 옛 버그로 오분류된
채 DB에 남아 있었다(T2 측정, [[eps-r28-followup-tracks-design-2026-08-16]]).

새 코드를 만들지 않고 기존 `collector/note_lines_sync.py::sync_layer2_lines(recheck=True)`
를 재사용한다 — docstring에 "파서 개선 소급 반영용"이라 명시된 바로 그 용도.
(reload_report_lines_corp.py에 --include-notes 플래그를 신설하는 대신 이 함수 재사용으로
결정 — 사용자 승인 2026-08-16.)

Usage: python scripts/backfill_t2_note_header_hint_2026-08-16.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from collector.note_lines_sync import sync_layer2_lines

_TARGET_SQL = """
    SELECT DISTINCT corp_code
    FROM note_lines
    WHERE header_hint = '기수' AND label_raw ~ '원|%'
    ORDER BY corp_code
"""

_MEASURE_SQL = """
    SELECT count(*) n, count(DISTINCT corp_code) corps, count(DISTINCT rcept_no) filings
    FROM note_lines
    WHERE header_hint = '기수' AND label_raw ~ '원|%'
"""


def measure():
    with get_session() as s:
        r = s.execute(text(_MEASURE_SQL)).fetchone()
        return {"rows": r.n, "corps": r.corps, "filings": r.filings}


def main():
    with get_session() as s:
        corps = [r.corp_code for r in s.execute(text(_TARGET_SQL)).fetchall()]
    print(f"대상 = {len(corps)}개사")

    before = measure()
    print(f"백필 전: {before}")

    t0 = time.time()
    out = sync_layer2_lines(corps, year_min=2015, recheck=True)
    elapsed = time.time() - t0
    print(f"sync_layer2_lines 결과: {out} ({elapsed:.0f}초)")

    after = measure()
    print(f"백필 후: {after}")
    print(f"해소: {before['rows']} → {after['rows']} 행 "
          f"({before['rows'] - after['rows']}건 해소, "
          f"{(before['rows'] - after['rows']) / before['rows'] * 100:.1f}%)")

    snapshot = {"before": before, "after": after, "sync_result": out,
                "elapsed_sec": elapsed, "target_corps": corps}
    out_path = Path(__file__).resolve().parent / "t2_note_header_hint_backfill_2026-08-16.json"
    out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    print(f"스냅샷 저장: {out_path}")


if __name__ == "__main__":
    main()
