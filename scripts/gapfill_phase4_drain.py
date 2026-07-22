"""Phase 4 (비용성격 D&A) 잔여를 0이 될 때까지 한 번에 완주 — 일회성 수동 드레인.

Phase 4 는 로컬 파일 파싱 + DB 재표준화만 하므로 DART API 쿼터와 무관하다.
nightly_gap_fill_backfill.run_phase4() 의 500사/회 상한(launchd 야간 무인실행 시간
제한용, 쿼터 때문 아님)은 그대로 두고, 이 스크립트가 잔여가 0 될 때까지 반복 호출한다.
기업단위 원자 commit + attempt-tracking 상태파일 체크포인트라 중간에 중단해도 안전.

사용 전: 다른 Phase4 실행(수동/launchd)이 동시에 돌고 있지 않은지 확인할 것
(상태파일 gap_fill_phase4_state.json 동시 쓰기 충돌 방지).

실행: .venv/bin/python scripts/gapfill_phase4_drain.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

from scripts.nightly_gap_fill_backfill import run_phase4


def main() -> None:
    round_no = 0
    while True:
        round_no += 1
        logger.info(f"[phase4-drain] ==== 라운드 {round_no} 시작 ====")
        remaining = run_phase4()
        logger.info(f"[phase4-drain] 라운드 {round_no} 완료 — 잔여 {remaining}")
        if remaining == 0:
            logger.success("[phase4-drain] Phase4 잔여 0 — 드레인 완료")
            break


if __name__ == "__main__":
    main()
