"""face_audit.status='fail' corp 들을 재표준화(standardize_corp) 후 재감사.
interim cumulative 수정 검증용. 재추출 불요(fact_v2 에 누적/3개월 셀 이미 존재)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from collector.db import get_session
from fin2.standardize.build import standardize_corp

with get_session() as s:
    corps = [r.corp_code for r in s.execute(text(
        "SELECT DISTINCT corp_code FROM face_audit WHERE status='fail' ORDER BY corp_code"))]
    print(f"fail corp {len(corps)}사 재표준화")
    for i, c in enumerate(corps, 1):
        standardize_corp(s, c)
        s.commit()
        if i % 10 == 0:
            print(f"  ..{i}/{len(corps)}")
    print("재표준화 완료")
