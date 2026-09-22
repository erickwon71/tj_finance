#!/usr/bin/env python
"""R162 백필 — SCE 부호가 빠진 필링을 재추출해 재적재한다.

## 대상 선정과 그 한계

후보 = `scripts/scan_sce_sign_loss.py` 와 같은 프록시(BS/IS 에 같은 라벨·같은 절대값이
음수로 있는 SCE 양수 셀). 이 집합은 **앵커가 있는 필링**을 고른다 — R162 는 부호
방향을 BS/IS 로 확정하므로, 앵커가 하나도 없는 필링은 애초에 복원하지 않는다.

★**한계(알고 남긴다)**: 앵커가 되는 셀이 `col_label` 쪽에만 있는 필링(잔액행만 깨진
경우)은 이 프록시에 안 잡힌다 — 프록시는 `label_raw` 로만 매칭하기 때문이다. 그런
필링은 캠페인/데일리 재적재가 돌 때 자동으로 교정된다(수정이 `extract_report_lines`
안에 있으므로 재추출만으로 반영된다). 여기서 굳이 전수 재추출(10만 필링)을 돌리지
않는 이유다.

## --apply 없이는 DB 를 건드리지 않는다

`store_report_lines()` 의 수동입력 보호(R139 원문대조-pass 보호 포함)는 **끄지 않는다**
— 보호된 건은 덮지 않고 목록으로 남겨 캠페인 세션이 재검토하게 한다.

## 사용법

    python scripts/backfill_r162_sce_sign.py
    python scripts/backfill_r162_sce_sign.py --limit 30
    python scripts/backfill_r162_sce_sign.py --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import extract_report_lines, store_report_lines
from fin2.extract.sce_sign_repair import repair_sce_sign_loss

_L2R = Path(__file__).resolve().parent / "layer2_review.py"

_CANDIDATES_SQL = """
WITH neg AS (
    SELECT rcept_no, basis, label_raw, value_won
    FROM report_lines
    WHERE statement IN ('IS', 'BS') AND col_index = 0
      AND value_won < 0 AND report_fiscal_year >= 2015
), pos AS (
    SELECT rcept_no, basis, label_raw, value_won
    FROM report_lines
    WHERE statement = 'SCE' AND value_won > 0 AND report_fiscal_year >= 2015
)
SELECT n.rcept_no, min(r.corp_code) AS corp_code,
       min(c.corp_name) AS corp_name, count(*) AS proxy_cells
FROM neg n
JOIN pos p ON p.rcept_no = n.rcept_no AND p.basis = n.basis
          AND p.label_raw = n.label_raw AND p.value_won = -n.value_won
JOIN report_lines r ON r.rcept_no = n.rcept_no
LEFT JOIN corporations c ON c.corp_code = r.corp_code
GROUP BY n.rcept_no
ORDER BY n.rcept_no
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
    ap.add_argument("--limit", type=int, default=0, help="앞 N건만 처리")
    args = ap.parse_args()

    resolve_source = _resolve_source_fn()
    n_fixed = n_applied = n_blocked = n_none = 0
    total_cells = 0

    with get_session() as s:
        sql = _CANDIDATES_SQL + (f" LIMIT {int(args.limit)}" if args.limit else "")
        rows = s.execute(text(sql)).mappings().all()
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

            # extract_report_lines 안에서 이미 복원됐다. 몇 셀이 바뀌었는지 보고하려고
            # 같은 판정을 한 번 더 돌린다 — 이미 복원된 상태라 두 번째 호출은 0건이다
            # (멱등성 확인도 겸한다).
            again = repair_sce_sign_loss(lines)
            assert not again, f"{rcept}: 복원이 멱등적이지 않다({len(again)}셀)"

            negatives = sum(1 for l in lines
                            if l.statement == "SCE" and (l.value_won or 0) < 0)
            current_neg = s.execute(text("""
                SELECT count(*) FROM report_lines
                WHERE rcept_no = :r AND statement = 'SCE' AND value_won < 0"""),
                {"r": rcept}).scalar_one()
            delta = negatives - current_neg
            if delta <= 0:
                n_none += 1
                continue

            n_fixed += 1
            total_cells += delta
            print(f"  {rcept}  {(r['corp_name'] or '')[:16]:18} "
                  f"SCE 음수 {current_neg} → {negatives} (+{delta}) "
                  f"status={it['status']}")

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
    print(f"\n[{mode}] 부호복원 {n_fixed}필링 / {total_cells}셀 · "
          f"변화없음 {n_none}필링 · 적재 {n_applied}건 · 보호됨 {n_blocked}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
