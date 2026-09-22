#!/usr/bin/env python
"""R161 백필 — 각주-앞-표제 오분류로 재무제표가 뒤바뀐 필링을 재적재한다.

## 대상 선정

프록시: **연결 CF 는 있는데 별도 CF 가 0행**인 필링(2015+). 별도 CF 가 다른 라벨로
오분류되면 그 scope 가 0행이 된다. 진짜 "별도 CF 미제출"도 섞이므로 **재추출해서
실제로 scope 구성이 바뀌는 건만** 적재한다.

★실측(2026-09-22): 후보는 10건/9개사뿐이고, 그중 SCE 가 부풀어 오분류 신호가 강한
건은 2건이었다. 두산밥캣 20170331005642 은 표 분류가 전부 정상이었고(SCE 201행도
50행 × 4열이라 정상) 별도 CF 0행은 **다른 원인**이다 — 미조사.

## --apply 없이는 DB 를 건드리지 않는다

`store_report_lines()` 의 수동입력 보호와 R139 원문대조-pass 보호는 **끄지 않는다** —
보호된 건은 덮지 않고 목록으로 남겨 캠페인 세션이 재검토하게 한다.

## 사용법

    python scripts/backfill_r161_note_title.py            # 검사만
    python scripts/backfill_r161_note_title.py --apply    # 적재
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import (extract_report_lines, store_report_lines,
                                       _is_loadable)

_L2R = Path(__file__).resolve().parent / "layer2_review.py"

_CANDIDATES_SQL = """
WITH per_filing AS (
    SELECT rcept_no, corp_code,
           count(*) FILTER (WHERE statement='CF'  AND basis='consolidated') AS cf_c,
           count(*) FILTER (WHERE statement='CF'  AND basis='separate')     AS cf_s,
           count(*) FILTER (WHERE statement='BS'  AND basis='separate')     AS bs_s
    FROM report_lines
    WHERE report_fiscal_year >= 2015
    GROUP BY rcept_no, corp_code
)
SELECT p.rcept_no, p.corp_code, c.corp_name
FROM per_filing p LEFT JOIN corporations c ON c.corp_code = p.corp_code
WHERE p.cf_c > 0 AND p.cf_s = 0 AND p.bs_s > 0
ORDER BY p.rcept_no;
"""


def _resolve_source_fn():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_l2r", _L2R)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._resolve_source


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="DB 에 실제로 적재")
    args = ap.parse_args()

    resolve_source = _resolve_source_fn()
    n_changed = n_applied = n_blocked = 0

    with get_session() as s:
        rows = s.execute(text(_CANDIDATES_SQL)).mappings().all()
        print(f"후보 {len(rows)}건\n")
        for r in rows:
            rcept = r["rcept_no"]
            it = s.execute(text("""
                SELECT fiscal_year, fiscal_period, status
                FROM layer2_review_queue WHERE rcept_no = :r"""),
                {"r": rcept}).mappings().first()
            if not it:
                print(f"  {rcept}  {r['corp_name']}  (큐에 없음 — 건너뜀)")
                continue
            try:
                _kind, path = resolve_source(s, rcept)
                lines = extract_report_lines(
                    path, rcept_no=rcept, corp_code=r["corp_code"],
                    report_fiscal_year=it["fiscal_year"],
                    report_fiscal_period=it["fiscal_period"])
            except Exception as exc:                              # noqa: BLE001
                print(f"  {rcept}  {r['corp_name']}  ERROR "
                      f"{type(exc).__name__}: {exc}")
                continue

            cur = {(x["statement"], x["basis"]): x["n"] for x in s.execute(text(
                "SELECT statement, basis, count(*) n FROM report_lines "
                "WHERE rcept_no=:r GROUP BY 1,2"), {"r": rcept}).mappings()}
            new = Counter((l.statement, l.basis) for l in lines if _is_loadable(l))
            diff = {k: (cur.get(k, 0), new.get(k, 0))
                    for k in set(cur) | set(new) if cur.get(k, 0) != new.get(k, 0)}

            if not diff:
                print(f"  {rcept}  {r['corp_name']:16} 변화 없음")
                continue
            n_changed += 1
            print(f"  {rcept}  {r['corp_name']:16} scope 변경 "
                  f"(status={it['status']})")
            for k in sorted(diff):
                a, b = diff[k]
                print(f"       {k[0]:4}/{k[1][:3]}  {a:>5} → {b:>5}")

            if args.apply:
                try:
                    store_report_lines(s, rcept, lines)
                    s.commit()
                    n_applied += 1
                except ValueError as guard:
                    s.rollback()
                    n_blocked += 1
                    print(f"       ⚠ 보호됨(덮지 않음): {str(guard)[:110]}")

    mode = "적재" if args.apply else "검사만(DB 미변경)"
    print(f"\n[{mode}] scope 변경 {n_changed}건 · 적재 {n_applied}건 · "
          f"보호됨 {n_blocked}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
