"""fact_v2/std_v2 GC 트랙 §6-3, category C 백필 (2026-09-01, 1회성).

`docs/plans/factv2_stdv2_gc_scoping_2026-09-01.md` §5-1 설계대로 실행한다.

배경: std_financials_v2 에는 있고 std_financials_v3 에는 없는 (corp,fy,fp,basis)
16,617건(fy>=1999) 중, 73%(12,149건)는 report_lines 의 "당기만 적재" 정책(2026-07-30
결정)의 의도된 결과라 영구 갭이고, 26%(4,366건, 922개사·4,799 rcept, 전부 fy<=2017)만
"필링은 다운로드됐는데 계층2 추출이 한 번도 안 돈" 진짜 백로그다. 이 스크립트는 후자만
채운다.

멱등: `sync_layer2_lines`(rcept 단위 delete-then-insert) + `build_corp`(corp,fy,fp,basis
단위 delete-then-insert) 둘 다 재실행 안전.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

# category C 정의 SQL — docs/plans/factv2_stdv2_gc_scoping_2026-09-01.md §5-1 그대로.
_CATEGORY_C_CORPS_SQL = text(
    """
    WITH gap AS (
        SELECT s.corp_code, s.fiscal_year, s.fiscal_period, s.statement_type
        FROM std_financials_v2 s
        WHERE s.version = 1 AND NOT COALESCE(s.is_stub, false)
          AND NOT COALESCE(s.is_discrete, false)
          AND s.fiscal_year >= 1999
          AND NOT EXISTS (
              SELECT 1 FROM std_financials_v3 v3b
              WHERE v3b.corp_code = s.corp_code AND v3b.fiscal_year = s.fiscal_year
                AND v3b.fiscal_period = s.fiscal_period
                AND v3b.statement_type = s.statement_type)
          AND NOT EXISTS (
              SELECT 1 FROM report_lines rl
              WHERE rl.corp_code = s.corp_code AND rl.report_fiscal_year = s.fiscal_year
                AND rl.report_fiscal_period = s.fiscal_period
                AND rl.basis = s.statement_type)
    )
    SELECT DISTINCT gap.corp_code
    FROM gap
    WHERE EXISTS (SELECT 1 FROM filings f WHERE f.corp_code = gap.corp_code
                    AND f.fiscal_year = gap.fiscal_year
                    AND f.fiscal_period = gap.fiscal_period)
      AND NOT EXISTS (SELECT 1 FROM report_lines rl WHERE rl.corp_code = gap.corp_code
                    AND rl.report_fiscal_year = gap.fiscal_year
                    AND rl.report_fiscal_period = gap.fiscal_period)
    ORDER BY 1
    """
)


def main() -> None:
    with get_session() as s:
        corps = [r[0] for r in s.execute(_CATEGORY_C_CORPS_SQL).fetchall()]
    print(f"[backfill-C] 대상 {len(corps):,}개사")
    if not corps:
        return

    from collector.note_lines_sync import sync_layer2_lines

    t0 = time.time()
    res = sync_layer2_lines(corps=corps, year_min=1999)
    print(f"[backfill-C] ④-3 계층2 전사 — 기업 {res['corps']} · 보고서 {res['filings']:,} · "
          f"주석 {res['rows']:,}행 · 본문 {res['body_rows']:,}행 (실패 {res['errors']}) · "
          f"{time.time()-t0:.0f}s")

    from fin2.layer3.build import build_corp

    t1 = time.time()
    n_rows = n_corp = n_err = 0
    with get_session() as session:
        for i, corp in enumerate(corps, 1):
            try:
                n_rows += build_corp(session, corp, year_min=1999)
                n_corp += 1
            except Exception as e:  # noqa: BLE001 — 한 건 실패가 전체를 막으면 안 됨
                n_err += 1
                print(f"  ! build_corp({corp}): {type(e).__name__}: {e}")
            if i % 200 == 0:
                session.commit()
                print(f"  … {i}/{len(corps)} corp · {n_rows:,} rows · {time.time()-t1:.0f}s")
        session.commit()
    print(f"[backfill-C] std_v3 build 완료 — {n_corp} corp(실패 {n_err}) · "
          f"{n_rows:,} rows · {time.time()-t1:.0f}s")

    with open("/tmp/backfill_c_corps_2026-09-01.txt", "w") as f:
        f.write("\n".join(corps))
    print(f"[backfill-C] corp 목록 저장: /tmp/backfill_c_corps_2026-09-01.txt")


if __name__ == "__main__":
    main()
