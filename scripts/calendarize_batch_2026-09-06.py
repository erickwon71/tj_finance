"""calendar_v3 재동기화 배치 — 2026-09-06 (가+라) unit_override 백필분."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from collector.db import get_session
from fin2.standardize.calendar_v3 import calendarize_corp_v3

CORPS = ["00102858", "00113207", "00117601", "00138701", "00143226",
         "00163673", "00260958", "00366942", "00400121", "00487546"]

if __name__ == "__main__":
    with get_session() as session:
        for corp in CORPS:
            n = calendarize_corp_v3(session, corp)
            print(f"calendarize_corp_v3({corp}) -> {n} rows")
