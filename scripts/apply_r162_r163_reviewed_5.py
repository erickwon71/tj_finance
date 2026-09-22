#!/usr/bin/env python
"""R162/R163 — 원문대조 pass 로 보호된 5건에 **명시 승인**으로 부호 교정을 적재한다.

## 왜 별도 스크립트인가

`store_report_lines()` 의 R139 가드는 사람이 원문대조한 필링(`layer2_review_queue.
status='pass'`)을 **자동 백필이 조용히 덮는 것**을 막는 장치다. 그 목적은 유효하므로
일반 백필 스크립트(`backfill_r162_sce_sign.py`·`backfill_r163_cf_cash_sign.py`)는
가드를 끄지 않는다 — 대신 이 스크립트가 **rcept 를 하드코딩**해 딱 그 5건만 넘긴다.

## 승인 경로 (중요)

사용자가 2026-09-22 에 이 5건에 대해 명시적으로 승인했다("이 5건만 가드 넘기기").
★캠페인 세션(peer)의 요청이 아니라 **사용자 본인의 결정**이다 — peer 가 자기 세션에서
막힌 동작을 대신 해 달라고 한 것을 그대로 수행하는 것은 금지(permission laundering)이고,
이 건은 그것이 아니다.

## 대상이 왜 이 5건인가

R162(SCE)·R163(CF) 부호 복원 백필이 이 5건에서만 가드에 막혀 적재되지 않았다. 값이
틀린 채 DB 에 남아 있고, 캠페인 세션이 DART 원문으로 재확인한 건들이다.

    python scripts/apply_r162_r163_reviewed_5.py            # 검사만
    python scripts/apply_r162_r163_reviewed_5.py --apply     # 적재
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import extract_report_lines, store_report_lines

_L2R = Path(__file__).resolve().parent / "layer2_review.py"

# rcept -> (회사, 기대 CF 음수(col0), 기대 SCE 음수). None = 검증 생략.
_TARGETS = {
    "20190515002585": ("효성중공업", None, 8),
    "20191114002661": ("SK하이닉스", None, 36),
    "20180330001629": ("한화오션", 15, 99),
    "20180403001678": ("한화오션(정정)", 15, 99),
    "20180523000409": ("한화오션(정정)", 15, 99),
}

_COUNT_SQL = """
SELECT
  count(*) FILTER (WHERE statement='CF'  AND col_index=0 AND value_won < 0) AS cf_neg,
  count(*) FILTER (WHERE statement='SCE' AND value_won < 0)                 AS sce_neg
FROM report_lines WHERE rcept_no = :r
"""


def _resolve_source_fn():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_l2r", _L2R)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._resolve_source


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    resolve_source = _resolve_source_fn()
    n_ok = n_fail = 0

    with get_session() as s:
        for rcept, (name, exp_cf, exp_sce) in _TARGETS.items():
            it = s.execute(text("""
                SELECT corp_code, fiscal_year, fiscal_period, status
                FROM layer2_review_queue WHERE rcept_no = :r"""),
                {"r": rcept}).mappings().first()
            if not it:
                print(f"  {rcept} {name}: 큐에 없음 — 건너뜀")
                continue

            before = s.execute(text(_COUNT_SQL), {"r": rcept}).mappings().first()
            try:
                _kind, path = resolve_source(s, rcept)
                lines = extract_report_lines(
                    path, rcept_no=rcept, corp_code=it["corp_code"],
                    report_fiscal_year=it["fiscal_year"],
                    report_fiscal_period=it["fiscal_period"])
            except Exception as exc:                              # noqa: BLE001
                print(f"  {rcept} {name}: 추출 실패 {type(exc).__name__}: {exc}")
                n_fail += 1
                continue

            if args.apply:
                # ★가드를 넘기는 **유일한** 지점. 위 docstring 의 승인 경로 참고.
                store_report_lines(s, rcept, lines, overwrite_reviewed=True)
                s.commit()

            after = s.execute(text(_COUNT_SQL), {"r": rcept}).mappings().first()
            checks = []
            good = True
            if exp_cf is not None:
                hit = after["cf_neg"] == exp_cf
                good &= hit
                checks.append(f"CF {before['cf_neg']}→{after['cf_neg']}"
                              f"/{exp_cf}{'✔' if hit else '✘'}")
            hit = after["sce_neg"] == exp_sce
            good &= hit
            checks.append(f"SCE {before['sce_neg']}→{after['sce_neg']}"
                          f"/{exp_sce}{'✔' if hit else '✘'}")
            print(f"  {rcept} {name[:14]:16} {' · '.join(checks):38} "
                  f"status={it['status']}")
            n_ok, n_fail = (n_ok + 1, n_fail) if good else (n_ok, n_fail + 1)

    mode = "적재" if args.apply else "검사만(DB 미변경)"
    print(f"\n[{mode}] 기대값 일치 {n_ok} · 불일치 {n_fail}")
    if not args.apply:
        print("※ --apply 없이는 값이 안 바뀌므로 불일치가 정상이다.")
    return 0 if (args.apply and n_fail == 0) or not args.apply else 1


if __name__ == "__main__":
    raise SystemExit(main())
