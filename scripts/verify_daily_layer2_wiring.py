"""F4 배선 확인 — 데일리 경로가 **본문까지** 적재하는지 실제로 적재해 본다.

왜 필요한가: 승인된 계획의 P0 는 "신규 보고서 본문이 데일리 경로에 없다"였다. 배선을 고쳤다는
말은 코드를 읽어서가 아니라 **행이 실제로 들어갔는지**로 확인해야 한다
(memory: 파이프라인 전체 고려 — '실제 적재 확인').

    python scripts/verify_daily_layer2_wiring.py --corp 01802928

한 기업의 계층2 행을 지운 뒤 데일리와 **같은 진입점**(`sync_layer2_lines`)으로 다시 채우고,
행 수·`unit_source` 분포를 앞뒤로 비교한다. 대상 기업은 Phase 4 전량 재적재에서 어차피 다시
쓰이므로 부작용이 없다. `--dry` 면 현재 상태만 본다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from collector.note_lines_sync import sync_layer2_lines

COUNT_SQL = text("""
    SELECT (SELECT count(*) FROM report_lines WHERE corp_code=:c) AS body,
           (SELECT count(*) FROM note_lines   WHERE corp_code=:c) AS note,
           (SELECT count(*) FROM note_lines   WHERE corp_code=:c AND value_raw IS NOT NULL) AS raw,
           (SELECT count(*) FROM note_lines   WHERE corp_code=:c AND header_hint IS NOT NULL) AS hint
""")


def snapshot(s, corp: str) -> dict:
    r = s.execute(COUNT_SQL, {"c": corp}).fetchone()
    return {"body": r.body, "note": r.note, "value_raw": r.raw, "header_hint": r.hint}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corp", required=True)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    with get_session() as s:
        before = snapshot(s, args.corp)
    print(f"적재 전 : {before}")
    if args.dry:
        return 0

    with get_session() as s:
        s.execute(text("DELETE FROM report_lines WHERE corp_code=:c"), {"c": args.corp})
        s.execute(text("DELETE FROM note_lines   WHERE corp_code=:c"), {"c": args.corp})
        s.commit()
    with get_session() as s:
        print(f"지운 뒤 : {snapshot(s, args.corp)}")

    res = sync_layer2_lines(corps=[args.corp])
    print(f"sync 결과: {res}")

    with get_session() as s:
        after = snapshot(s, args.corp)
        dist = s.execute(text(
            "SELECT unit_source, count(*) FROM note_lines WHERE corp_code=:c "
            "GROUP BY 1 ORDER BY 2 DESC"), {"c": args.corp}).fetchall()
    print(f"적재 후 : {after}")
    print("unit_source: " + ", ".join(f"{k}={v:,}" for k, v in dist))

    ok = after["body"] > 0 and after["note"] > 0
    print(f"\n{'PASS' if ok else 'FAIL'} — 데일리 진입점이 본문 {after['body']:,}행 · "
          f"주석 {after['note']:,}행을 적재했다 (본문 배선 전에는 본문 0)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
