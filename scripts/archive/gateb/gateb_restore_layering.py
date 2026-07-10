"""
gateb_restandardize_fails 가 standardize_corp 만 돌려 clobber 한 comparative/kgaap 채움행 복원.
표준 후속 패스(comparative → kgaap_gap)를 face_audit fail corp 들에 재실행.

⚠ own-report 가 키를 점유하면 채움패스가 덮지 않음(설계: 기존행 불가침). optrontec 류
(IFRS 재작성 comparative 가 K-GAAP own-report 보다 우선이어야 하는 케이스)는 2008 own-report
행 purge 후 재채움이 필요 → --purge-corp 로 지정.
"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from collector.db import get_session
from fin2.standardize.build import standardize_comparative_corp, standardize_kgaap_gap_corp

ap = argparse.ArgumentParser()
ap.add_argument("--purge-corp", action="append", default=[],
                help="CORP:FY — 그 corp/연도의 비교/K-GAAP보다 낮은 own-report 행 purge 후 재채움")
args = ap.parse_args()

with get_session() as s:
    # purge 지정 corp/연도: own-report 가 clobber 한 행 삭제(채움패스가 IFRS 재작성값 재적재하도록)
    for spec in args.purge_corp:
        corp, fy = spec.split(":")
        n = s.execute(text("""
            DELETE FROM std_financials_v2 WHERE corp_code=:c AND fiscal_year=:y AND version=1
        """), {"c": corp, "y": int(fy)}).rowcount
        print(f"  purge {corp} FY{fy}: {n}행 삭제")
    s.commit()

    corps = [r.corp_code for r in s.execute(text(
        "SELECT DISTINCT corp_code FROM face_audit WHERE status='fail' ORDER BY corp_code"))]
    purge_corps = {spec.split(":")[0] for spec in args.purge_corp}
    corps = sorted(set(corps) | purge_corps)
    print(f"comparative+kgaap 후속패스 재실행 대상 {len(corps)}사")
    cw = kw = 0
    for c in corps:
        cw += standardize_comparative_corp(s, c)
        kw += standardize_kgaap_gap_corp(s, c)
        s.commit()
    print(f"comparative {cw}행 · kgaap_gap {kw}행 재적재")
