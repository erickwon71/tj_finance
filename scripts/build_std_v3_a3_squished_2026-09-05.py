"""(A-3) 통짜-셀 BS total_assets 복구분 std_v3 반영 — report_lines 백필(재실행,
`unit_source='squished_total'` 신규행)로 새로 채워진 104개사를 `build_corp()`로
재빌드해 `standard_financials`(v3)에 반영한다.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector.db import get_session
from fin2.layer3.build import build_corp

with open("/tmp/a3_squished_touched_corps.txt") as f:
    corps = [line.strip() for line in f if line.strip()]
print(f"[A3-build] 대상 {len(corps):,}개사")

n_rows = n_corp = n_err = 0
t0 = time.time()
with get_session() as session:
    for i, corp in enumerate(corps, 1):
        try:
            n_rows += build_corp(session, corp, year_min=1999)
            n_corp += 1
        except Exception as e:  # noqa: BLE001
            n_err += 1
            print(f"  ! build_corp({corp}): {type(e).__name__}: {e}")
        if i % 50 == 0:
            session.commit()
            print(f"  … {i}/{len(corps)} corp · {n_rows:,} rows · {time.time()-t0:.0f}s")
    session.commit()
print(f"[A3-build] 완료 — {n_corp} corp(실패 {n_err}) · {n_rows:,} rows · {time.time()-t0:.0f}s")
