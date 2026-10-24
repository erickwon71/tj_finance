"""C10 · Failure notification — macOS 알림 + 텔레그램.

W7(전문가 리뷰): dqcheck/backup 실패가 로그 파일에만 남아 아무도 매일 읽지 않는다 — 그래서
백업이 며칠간 미실행이었던 것도 모르고 지나갔다. `osascript`로 macOS 알림센터에 띄워
launchd LaunchAgent(GUI 세션에서 실행됨)에서 바로 눈에 띄게 한다.

2026-10-24 — **텔레그램 경로** (이메일 대체):
  macOS 알림은 그 Mac 앞에 있어야 보인다. KRX/DART 인증키 만료처럼 "며칠 안에 조치하지 않으면
  수집이 멈추는" 사건은 자리를 비워도 알아야 하므로 텔레그램으로도 보낸다.

  발송은 사용자 홈의 `~/.claude/notify/telegram.sh` (환경변수 TJ_TELEGRAM_SH 로 경로 변경 가능)를
  그대로 호출한다. 봇 토큰은 그쪽 telegram.env 에만 있고 이 저장소에는 두지 않는다.
  야간(22:00-08:00)에는 그 스크립트가 큐에 쌓았다가 08:00 다이제스트로 보낸다(exit 3).
  메시지는 한 줄·마크다운 없이·200자 이내로 줄여 보낸다.

  스크립트가 없거나 실패해도 **호출자를 막지 않는다** — 알림은 부가 기능이지 게이트가 아니다.

usage:
    from scripts.notify import notify_failure
    notify_failure("KRX 인증 실패", "유가증권 활용기간 만료 — 재신청 필요")

standalone test:
    python scripts/notify.py "제목" "본문"
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:  # .env 로드(collector.config 가 담당). 단독 실행에서도 설정이 보이도록.
    import collector.config  # noqa: F401
except Exception:  # noqa: BLE001
    pass

from loguru import logger


def _suppressed() -> str | None:
    """테스트 환경이면 억제 사유를, 아니면 None.

    2026-07-31 사고 — `tests/test_corp_universe_guard.py` 는 `krx_client.fetch_all` 만
    가짜로 바꾸고 **진짜** `_get_krx_universe()` 를 부른다. 그 안의 `notify_failure` 도
    진짜라서 스위트 1회 실행마다 실제 Gmail SMTP 로 7통(KRX 인증 실패 6 + 소스 불일치 1)이
    나갔다. 하루 7회 돌려 49통이 발송됐고, 본문의 `(주입)` 이 유일한 단서였다.

    그래서 억제는 **호출자가 아니라 여기**에 둔다 — 앞으로 추가될 테스트도 자동 보호된다.
    `PYTEST_CURRENT_TEST` 는 pytest 가 심어주고, 자체 러너(tests/run_all.py·tests/_util.py)
    는 `TJ_NOTIFY_DISABLE=1` 을 심는다. 운영 경로에는 둘 다 없으므로 영향이 없다.
    """
    if os.getenv("TJ_NOTIFY_DISABLE", "").strip() not in ("", "0"):
        return "TJ_NOTIFY_DISABLE"
    if os.getenv("PYTEST_CURRENT_TEST"):
        return "pytest"
    return None


def notify_macos(title: str, message: str) -> None:
    """macOS 알림센터. 실패해도 조용히 넘어간다(headless SSH 등)."""
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    safe_message = message.replace("\\", "\\\\").replace('"', '\\"')[:500]
    script = (f'display notification "{safe_message}" with title "TJ Finance" '
              f'subtitle "{safe_title}" sound name "Basso"')
    try:
        subprocess.run(["osascript", "-e", script],
                       capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001
        pass


TELEGRAM_MAX_CHARS = 200


def _one_line(title: str, message: str) -> str:
    """Telegram text: one line, no markdown, at most TELEGRAM_MAX_CHARS characters."""
    text = f"[TJ Finance] {title} — {message}"
    text = " ".join(text.replace("*", "").replace("`", "").replace("_", " ").split())
    return text if len(text) <= TELEGRAM_MAX_CHARS else text[:TELEGRAM_MAX_CHARS - 1] + "…"


def notify_telegram(title: str, message: str) -> bool:
    """텔레그램 발송. 즉시 전달되면 True, 야간 큐 보관(exit 3)·스크립트 없음·실패면 False."""
    script = Path(os.getenv("TJ_TELEGRAM_SH") or Path.home() / ".claude" / "notify" / "telegram.sh")
    if not script.exists():
        logger.warning(f"[notify] 텔레그램 스크립트가 없어 건너뛴다: {script}")
        return False
    try:
        r = subprocess.run([str(script), _one_line(title, message)],
                           capture_output=True, text=True, timeout=30)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[notify] 텔레그램 발송 실패({type(exc).__name__}: {exc}) — 알림만 남긴다")
        return False
    if r.returncode == 0:
        logger.info(f"[notify] 텔레그램 발송 — {title}")
        return True
    if r.returncode == 3:
        logger.info(f"[notify] 텔레그램 보류(야간 큐 또는 전송 실패, 08:00 다이제스트로 재전송) — {title}")
    else:
        logger.warning(f"[notify] 텔레그램 스크립트 종료코드 {r.returncode} — {title}")
    return False


def notify_failure(title: str, message: str, telegram: bool = True) -> None:
    """실패 알림 — macOS 알림센터 + 텔레그램.

    Args:
        telegram: 텔레그램까지 보낼지. 소음이 큰 경고는 False 로 알림센터만.
    """
    logger.error(f"[notify] {title} — {message}")
    if (why := _suppressed()) is not None:
        logger.info(f"[notify] 발송 생략({why}) — 테스트 환경")
        return
    notify_macos(title, message)
    if telegram:
        notify_telegram(title, message)


if __name__ == "__main__":
    notify_failure(sys.argv[1] if len(sys.argv) > 1 else "테스트",
                   sys.argv[2] if len(sys.argv) > 2 else "notify.py 직접 실행 테스트")
