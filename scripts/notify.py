"""C10 · Failure notification — macOS 알림 + 이메일.

W7(전문가 리뷰): dqcheck/backup 실패가 로그 파일에만 남아 아무도 매일 읽지 않는다 — 그래서
백업이 며칠간 미실행이었던 것도 모르고 지나갔다. `osascript`로 macOS 알림센터에 띄워
launchd LaunchAgent(GUI 세션에서 실행됨)에서 바로 눈에 띄게 한다.

2026-07-31 추가 — **이메일 경로**:
  macOS 알림은 그 Mac 앞에 있어야 보인다. KRX/DART 인증키 만료처럼 "며칠 안에 조치하지 않으면
  수집이 멈추는" 사건은 자리를 비워도 알아야 하므로 메일로도 보낸다.

  설정(.env):
      ALERT_EMAIL_TO    수신 주소 (없으면 이메일 생략, 알림만)
      SMTP_HOST         기본 smtp.gmail.com
      SMTP_PORT         기본 587 (STARTTLS)
      SMTP_USER         발신 계정
      SMTP_PASSWORD     ※ Gmail 은 **앱 비밀번호**여야 한다(2단계 인증 계정의 일반 비밀번호 불가)
                          https://myaccount.google.com/apppasswords

  SMTP 설정이 없거나 실패해도 **호출자를 막지 않는다** — 알림은 부가 기능이지 게이트가 아니다.

usage:
    from scripts.notify import notify_failure
    notify_failure("KRX 인증 실패", "유가증권 활용기간 만료 — 재신청 필요")

standalone test:
    python scripts/notify.py "제목" "본문"
"""
from __future__ import annotations

import os
import smtplib
import subprocess
import sys
from email.message import EmailMessage
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


def notify_email(subject: str, body: str) -> bool:
    """이메일 발송. 설정이 없으면 False(경고 없이 스킵), 실패하면 로그만 남기고 False."""
    to_addr = os.getenv("ALERT_EMAIL_TO", "").strip()
    if not to_addr:
        return False

    host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    if not user or not password:
        logger.warning(
            "[notify] ALERT_EMAIL_TO 는 있는데 SMTP_USER/SMTP_PASSWORD 가 없어 이메일을 건너뛴다. "
            "Gmail 은 앱 비밀번호가 필요하다: https://myaccount.google.com/apppasswords")
        return False

    msg = EmailMessage()
    msg["Subject"] = f"[TJ Finance] {subject}"
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
        logger.info(f"[notify] 이메일 발송: {to_addr} — {subject}")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[notify] 이메일 발송 실패({type(exc).__name__}: {exc}) — 알림만 남긴다")
        return False


def notify_failure(title: str, message: str, email: bool = True) -> None:
    """실패 알림 — macOS 알림센터 + (설정돼 있으면) 이메일.

    Args:
        email: 이메일까지 보낼지. 소음이 큰 경고는 False 로 알림만.
    """
    logger.error(f"[notify] {title} — {message}")
    if (why := _suppressed()) is not None:
        logger.info(f"[notify] 발송 생략({why}) — 테스트 환경")
        return
    notify_macos(title, message)
    if email:
        notify_email(title, message)


if __name__ == "__main__":
    notify_failure(sys.argv[1] if len(sys.argv) > 1 else "테스트",
                   sys.argv[2] if len(sys.argv) > 2 else "notify.py 직접 실행 테스트")
