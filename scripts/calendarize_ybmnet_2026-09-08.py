"""calendar_v3 재동기화 — YBM넷(00307222) 수동입력(BS/IS 반영, CF 결측확정) 후
std_v3 재빌드 직후 (R69/R70/R71/R72와 같은 패턴: 스코프 재빌드 후 달력동기화 누락 방지).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from collector.db import get_session
from fin2.standardize.calendar_v3 import calendarize_corp_v3

CORP = "00307222"

if __name__ == "__main__":
    with get_session() as session:
        n = calendarize_corp_v3(session, CORP)
        print(f"calendarize_corp_v3({CORP}) -> {n} rows")
