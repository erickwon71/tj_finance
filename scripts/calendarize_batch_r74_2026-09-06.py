"""calendar_v3 재동기화 배치 — 2026-09-06 R74(sanemax-reject 컬럼밀림) 백필분,
66개사 (`scratch_census_sanemax_shift_triaged.csv` high_confidence)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from collector.db import get_session
from fin2.standardize.calendar_v3 import calendarize_corp_v3

CORPS = ["00101220","00103130","00104388","00105271","00105961","00106669","00109037",
         "00109693","00110875","00110893","00111704","00112332","00113191","00115065",
         "00115676","00116949","00117212","00120021","00124799","00126256","00126487",
         "00130383","00133876","00138516","00139205","00144720","00152880","00155276",
         "00156691","00159616","00162911","00171265","00174527","00176835","00204226",
         "00219848","00231831","00249982","00255619","00258801","00261285","00296078",
         "00299002","00309503","00330424","00336817","00360142","00364467","00378363",
         "00503668","00526696","00578538","00877059","00888347","00904672","00937324",
         "00989619","01010110","01098792","01137383","01160363","01205329","01219155",
         "01335930","01416572","01437858"]

if __name__ == "__main__":
    with get_session() as session:
        total = 0
        for corp in CORPS:
            n = calendarize_corp_v3(session, corp)
            total += n
            print(f"calendarize_corp_v3({corp}) -> {n} rows")
        print(f"total: {total} rows across {len(CORPS)} corps")
