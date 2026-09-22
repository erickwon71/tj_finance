#!/usr/bin/env python
"""R162 규모 스캐너 — SCE 표에서 음수 괄호가 빠진 셀을 프록시로 센다.

## 판정 근거(프록시)

같은 필링·같은 basis 에서 **같은 라벨**이 IS(또는 BS)에는 음수로, SCE 에는 **같은
절대값의 양수**로 들어 있으면 SCE 쪽 셀이 마이너스를 잃은 것이다. DART 원문이
BS/IS 는 괄호로 음수를 찍는데 같은 필링의 SCE 표에서는 괄호를 빼먹는다(효성중공업
`20190515002585` 원문 실측 — R162 참고).

★프록시라는 점을 잊지 말 것. 절대값이 우연히 같은 무관한 개념이 섞일 수 있으므로
이 숫자는 **규모 추정**이고, 셀 하나하나의 참값은 열 롤포워드 항등식으로 따로
증명해야 한다(R6: 증명되지 않으면 손대지 않는다).

## 사용법

    python scripts/scan_sce_sign_loss.py
    python scripts/scan_sce_sign_loss.py --list 40      # 필링 목록도 출력
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

# IS/BS 는 col_index=0 만 저장된다(_PERIOD_AXIS_STATEMENTS). SCE 는 열 축이 기간이
# 아니라 자본 구성요소라 여러 col_index 가 남으므로 col_index 를 걸지 않는다.
_PAIRS_CTE = """
WITH neg AS (
    SELECT rcept_no, corp_code, basis, label_raw, value_won
    FROM report_lines
    WHERE statement IN ('IS', 'BS') AND col_index = 0
      AND value_won < 0 AND report_fiscal_year >= 2015
), pos AS (
    SELECT rcept_no, basis, label_raw, value_won
    FROM report_lines
    WHERE statement = 'SCE' AND value_won > 0
      AND report_fiscal_year >= 2015
)
"""

_TOTALS = _PAIRS_CTE + """
SELECT count(*) AS cells, count(DISTINCT n.rcept_no) AS filings,
       count(DISTINCT n.corp_code) AS corps
FROM neg n JOIN pos p
  ON p.rcept_no = n.rcept_no AND p.basis = n.basis
 AND p.label_raw = n.label_raw AND p.value_won = -n.value_won;
"""

_BY_LABEL = _PAIRS_CTE + """
SELECT n.label_raw, count(*) AS n_cells,
       count(DISTINCT n.rcept_no) AS n_filings
FROM neg n JOIN pos p
  ON p.rcept_no = n.rcept_no AND p.basis = n.basis
 AND p.label_raw = n.label_raw AND p.value_won = -n.value_won
GROUP BY 1 ORDER BY n_filings DESC, n_cells DESC LIMIT 20;
"""

_BY_FILING = _PAIRS_CTE + """
SELECT n.rcept_no, n.corp_code, c.corp_name, count(*) AS n_cells
FROM neg n JOIN pos p
  ON p.rcept_no = n.rcept_no AND p.basis = n.basis
 AND p.label_raw = n.label_raw AND p.value_won = -n.value_won
LEFT JOIN corporations c ON c.corp_code = n.corp_code
GROUP BY 1, 2, 3 ORDER BY n_cells DESC, n.rcept_no LIMIT :lim;
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", type=int, default=0,
                    help="상위 N개 필링 목록도 출력")
    args = ap.parse_args()

    with get_session() as s:
        t = s.execute(text(_TOTALS)).mappings().first()
        print(f"프록시 적중(2015+): {t['cells']:,}셀 / {t['filings']:,}필링 / "
              f"{t['corps']:,}개사")

        print("\n라벨별 상위:")
        for r in s.execute(text(_BY_LABEL)).mappings():
            print(f"  {r['label_raw'][:44]:46} {r['n_filings']:>6}필링 "
                  f"{r['n_cells']:>7}셀")

        if args.list:
            print(f"\n필링별 상위 {args.list}건:")
            for r in s.execute(text(_BY_FILING),
                               {"lim": args.list}).mappings():
                name = r["corp_name"] or r["corp_code"]
                print(f"  {r['rcept_no']}  {name[:18]:20} {r['n_cells']:>4}셀")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
