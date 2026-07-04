"""C10 · Failure notification — macOS notification on nonzero exit / assertion failure.

W7(전문가 리뷰): dqcheck/backup 실패가 로그 파일에만 남아 아무도 매일 읽지 않는다 — 그래서
백업이 며칠간 미실행이었던 것도 모르고 지나갔다. `osascript`로 macOS 알림센터에 띄워
launchd LaunchAgent(GUI 세션에서 실행됨)에서 바로 눈에 띄게 한다.

usage (다른 스크립트에서 import):
    from scripts.notify import notify_failure
    notify_failure("백업 실패", "pg_dump rc=1: ...")

standalone test:
    python scripts/notify.py "제목" "본문"
"""
from __future__ import annotations

import subprocess
import sys


def notify_failure(title: str, message: str) -> None:
    """macOS 알림센터에 실패 알림을 띄운다. 알림 전송 자체가 실패해도(예: headless SSH 세션)
    호출자를 막지 않는다 — 알림은 부가 기능이지 게이트가 아니다."""
    # AppleScript 문자열 리터럴 이스케이프(따옴표·백슬래시)
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    safe_message = message.replace("\\", "\\\\").replace('"', '\\"')[:500]
    script = f'display notification "{safe_message}" with title "TJ Finance" subtitle "{safe_title}" sound name "Basso"'
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001
        pass  # GUI 세션이 없는 환경(예: headless) — 로그만으로 충분, 알림은 best-effort


if __name__ == "__main__":
    notify_failure(sys.argv[1] if len(sys.argv) > 1 else "테스트",
                    sys.argv[2] if len(sys.argv) > 2 else "notify.py 직접 실행 테스트")
