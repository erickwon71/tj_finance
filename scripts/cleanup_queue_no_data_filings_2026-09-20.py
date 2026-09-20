#!/usr/bin/env python
"""계층2 캠페인 큐에서 '검토해도 볼 게 없는' 필링을 걷어낸다 (2026-09-20).

근거: `docs/qa/layer2_blocked_filings_investigation_2026-09-20.md` §②·§③
(사용자 결정 2026-09-20 — 두 갈래 다 `skipped` 로 정리)

`cleanup_queue_non_report_filings_2026-09-20.py` 가 '서류 종류 자체가 정기보고서가
아닌 것'(제출기한연장신고서)을 걷어냈다면, 이 스크립트는 **정기보고서가 맞지만 그
rcept 본문에는 재무제표가 없는 것**을 걷어낸다. 두 갈래다:

  A. `source_kind IN ('pdf', 'xbrl_zip')` 로 blocked 된 51건
     이 CLI 가 자동 재적재하지 않는 소스다. 전수 조사 결과 진짜 결측 0건이고,
     `xbrl_zip` 7건은 이미 report_lines 가 131~1,109행 적재돼 있다.

  B. 첨부정정인데 본문 0행인 것 (2015+ 530건, 전 구간 538건)
     `[첨부정정]사업보고서` 의 본문 XML 이 실제로는 **연결감사보고서**(ACODE 00761)라
     정기보고서 섹션 구조가 없다 → 0행이 정상 동작. 실데이터는 형제 필링에 있다.
     (실측: 현대글로비스 `20250318000748` 의 본문은 `20250317001025` 에 있다.)

## 안전장치
- 기본이 **dry-run** 이다. 실제로 쓰려면 `--apply` 를 붙인다.
- `status='pending'`/`'blocked'` 인 행만 건드린다 — 사람이 이미 `pass`/`fail` 판단을
  남긴 행은 절대 손대지 않는다(ReconCandidate 관례).
- ★**결측 아님을 행마다 증명한 것만** 내린다: 그 rcept 에 report_lines 가 있거나,
  같은 `(corp_code, fiscal_year, fiscal_period)` 형제 필링에 실데이터가 있어야 한다.
  증명 안 되는 행은 `[보류]` 로 찍어 사람이 보게 남긴다.
  ★형제 판정에 `is_final` 을 **쓰지 않는다** — 첨부정정 쪽이 is_final=True 인데
  데이터를 든 원본 본문이 is_final=False 인 배치가 흔해서(조사문서 §② 참고)
  is_final 만 보면 거짓 결측이 난다.
- `note` 에 조사문서 경로를 남겨 나중에 왜 내렸는지 추적할 수 있게 한다.

## 사용법
    python scripts/cleanup_queue_no_data_filings_2026-09-20.py
    python scripts/cleanup_queue_no_data_filings_2026-09-20.py --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session

_DOC = "docs/qa/layer2_blocked_filings_investigation_2026-09-20.md"

# 본인 rcept 에 실데이터가 있거나, 형제 필링에 있으면 '결측 아님' 으로 본다.
_HAS_DATA = """
    (EXISTS (SELECT 1 FROM report_lines rl WHERE rl.rcept_no = q.rcept_no)
     OR EXISTS (
         SELECT 1
         FROM filings sf
         JOIN report_lines srl ON srl.rcept_no = sf.rcept_no
         WHERE sf.corp_code = f.corp_code
           AND sf.fiscal_year = f.fiscal_year
           AND sf.fiscal_period = f.fiscal_period
           AND sf.rcept_no <> f.rcept_no
     ))
"""

_SELECT = """
    SELECT q.rcept_no, q.corp_name, q.fiscal_year, q.fiscal_period,
           q.status, q.source_kind, q.report_nm,
           {has_data} AS has_data
    FROM layer2_review_queue q
    JOIN filings f ON f.rcept_no = q.rcept_no
    WHERE q.status IN ('pending', 'blocked')
      AND ({cond})
    ORDER BY q.fiscal_year DESC, q.rcept_no
"""

# A: 재적재 불가 소스로 blocked — 조사문서 §③
_COND_A = "q.status = 'blocked' AND q.source_kind IN ('pdf', 'xbrl_zip')"
_NOTE_A = ("재적재 불가 소스(pdf/xbrl_zip)이며 결측 아님이 확인됨 — "
           f"{_DOC} §③")

# B: 첨부정정인데 본문 0행 — 조사문서 §②
_COND_B = ("q.is_attachment_amendment"
           " AND NOT EXISTS (SELECT 1 FROM report_lines rl"
           "                 WHERE rl.rcept_no = q.rcept_no)")
_NOTE_B = ("첨부정정 본문이 감사보고서라 0행(실데이터는 형제 필링에 있음) — "
           f"{_DOC} §②")

_SKIP = text(
    """
    UPDATE layer2_review_queue
       SET status = 'skipped', note = :note, reviewed_at = now()
     WHERE rcept_no = :r
    """
)


def _run(session, label: str, cond: str, note: str, apply: bool) -> int:
    sql = text(_SELECT.format(has_data=_HAS_DATA, cond=cond))
    rows = session.execute(sql).fetchall()
    ok = [r for r in rows if r.has_data]
    held = [r for r in rows if not r.has_data]

    by_status: dict[str, int] = {}
    for r in ok:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    logger.info(f"[{label}] 대상 {len(rows):,}건 — 정리 {len(ok):,}건 {by_status}, "
                f"결측 미증명 보류 {len(held):,}건")
    for r in held:
        logger.warning(f"  [보류] {r.rcept_no} {r.corp_name} "
                       f"FY{r.fiscal_year}{r.fiscal_period} "
                       f"src={r.source_kind} {r.report_nm!r}")

    if not apply:
        for r in ok[:5]:
            logger.info(f"  예시: {r.rcept_no} {r.corp_name} "
                        f"FY{r.fiscal_year}{r.fiscal_period} src={r.source_kind}")
        return 0

    for r in ok:
        session.execute(_SKIP, {"r": r.rcept_no, "note": note})
    return len(ok)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="실제로 status='skipped' 로 바꾼다(기본은 dry-run)")
    args = ap.parse_args()

    with get_session() as session:
        # A 를 먼저 내려야 B 에서 같은 행(첨부정정이면서 pdf-blocked)을 다시 세지 않는다.
        n_a = _run(session, "A 재적재불가", _COND_A, _NOTE_A, args.apply)
        n_b = _run(session, "B 첨부정정0행", _COND_B, _NOTE_B, args.apply)

        if not args.apply:
            logger.info("dry-run — 쓰지 않았다. 실행하려면 --apply")
            return
        session.commit()
        logger.success(f"[cleanup] A {n_a:,}건 + B {n_b:,}건 → status='skipped'")


if __name__ == "__main__":
    main()
