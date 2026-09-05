"""(C)+(A-1)+(A-2) std_v3 반영 — report_lines 백필(`backfill_a1_a2_c_2026-09-05.py`)로
새로 채워진 114개사를 `build_corp()`로 재빌드해 `standard_financials`(v3)에 반영한다.

report_lines 는 이미 백필 스크립트가 직접 채웠으므로(`store_report_lines` 등) 여기선
`sync_layer2_lines` 재실행 불요 — `build_corp` 만 돌린다.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector.db import get_session
from fin2.layer3.build import build_corp

with open("/tmp/a1a2c_backfill_touched_corps.txt") as f:
    corps = [line.strip() for line in f if line.strip()]
print(f"[A1A2C-build] 대상 {len(corps):,}개사")

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
print(f"[A1A2C-build] 완료 — {n_corp} corp(실패 {n_err}) · {n_rows:,} rows · {time.time()-t0:.0f}s")
