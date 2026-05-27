"""020 quota 오류로 인한 download_tasks 피해 확인"""
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가 (scripts/ 하위에서 실행해도 동작)
sys.path.insert(0, str(Path(__file__).parent.parent))

from collector.db import get_session
from sqlalchemy import text

with get_session() as s:
    # ① 020 오류로 기록된 태스크 (status/attempts 분포)
    r1 = s.execute(text("""
        SELECT status, attempts, COUNT(*) as cnt
        FROM download_tasks
        WHERE last_error LIKE '%사용한도%' OR last_error LIKE '%020%'
        GROUP BY status, attempts ORDER BY status, attempts
    """)).fetchall()
    print("=== 020 오류로 기록된 태스크 ===")
    for row in r1:
        print(f"  status={row.status}  attempts={row.attempts}  count={row.cnt}")

    # ② attempts >= 3 이면서 020 오류 → 영구 제외 위험
    r2 = s.execute(text("""
        SELECT COUNT(*) FROM download_tasks
        WHERE attempts >= 3
          AND (last_error LIKE '%사용한도%' OR last_error LIKE '%020%')
    """)).scalar()
    print(f"\n영구 제외 위험 (attempts>=3, 020오류): {r2}건")

    # ③ 현재 downloading 상태 (크래시 잔재)
    r3 = s.execute(text(
        "SELECT COUNT(*) FROM download_tasks WHERE status='downloading'"
    )).scalar()
    print(f"downloading 상태로 멈춘 태스크: {r3}건")
