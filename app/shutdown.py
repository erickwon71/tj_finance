"""
로컬 데스크톱 실행 전용 종료 헬퍼.

사이드바 "🛑 앱 종료" 버튼에서만 사용. Streamlit 서버 프로세스를 끝내면서, 이 앱을
띄운 iTerm2 창도 함께 닫는다. 어떤 창인지는 데스크톱 런처(TJ Finance 시각화.app)가
새 창을 만들 때 TJ_TERM_WINDOW_ID 환경변수로 그 창의 AppleScript id 를 넘겨 알려준다.
그 환경변수가 없으면(런처를 거치지 않고 직접 `streamlit run` 한 경우 등) 창 닫기는
건너뛰고 서버만 종료한다 — best-effort, 실패해도 에러 없이 서버 종료는 항상 보장.
"""
from __future__ import annotations

import os
import subprocess
import sys


def shutdown_app() -> None:
    """iTerm2 창을 닫도록 백그라운드로 예약(지연 실행)한 뒤, 서버 프로세스를 종료한다.

    순서가 중요: 이 프로세스가 먼저 죽어 쉘이 유휴 상태가 되어야, 뒤이어 도는 AppleScript 가
    "실행 중인 프로세스가 있습니다" 확인창 없이 창을 닫을 수 있다. 그래서 지연을 준 뒤
    별도 백그라운드 프로세스로 분리해 실행한다.
    """
    window_id = os.environ.get("TJ_TERM_WINDOW_ID")
    if window_id and sys.platform == "darwin":
        script = f'''
        delay 1.5
        tell application "iTerm2"
            repeat with w in windows
                if id of w is {window_id} then
                    try
                        close w
                    end try
                    exit repeat
                end if
            end repeat
        end tell
        '''
        try:
            subprocess.Popen(
                ["osascript", "-e", script],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            pass
    os._exit(0)
