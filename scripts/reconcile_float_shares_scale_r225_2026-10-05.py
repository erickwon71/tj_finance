#!/usr/bin/env python
"""R225 후속 — report_shares_outstanding 에서 Ⅳ(shares_out)와 Ⅴ/Ⅵ(treasury/float)의 배수가 어긋난 행 정리.

R225 소급(`backfill_float_shares_r225_2026-10-05.py`)은 원문을 다시 읽어 Ⅴ/Ⅵ 만 채우고 shares_out 은
두었다. 그런데 440행에서 둘의 배수가 정확히 1,000배 어긋났다(float+treasury = shares_out×1000 409행):
  · 캡션이 '(단위 : 천주)' 인데 실제 숫자는 '주'인 원문(R90 이 기록한 함정, 일승·한일철강 유형)을
    재추출이 ×1000 했고, 저장된 shares_out(R90 이전 적재)은 배수 없이 맞았던 경우 — 340행
  · 반대로 저장된 shares_out 이 R90 이전 값이라 ×1000 이 빠져 있던 경우 — 25행
대상은 float+treasury 와 shares_out 이 **정확히 1,000배** 관계인 행뿐이다(그 밖의 작은 차이는 원문에
인쇄된 Ⅵ 가 Ⅳ−Ⅴ 와 다른 것이라 원문 그대로 둔다). 판정 근거, 순서대로:
  ① 같은 사업연도 FY 의 지배순이익 ÷ 기본EPS = 암시 주식수 — 후보 Ⅳ 가 그 3배 이내인 쪽(문서 안의
     독립 증거). 회사 이력 전체가 배수 누락으로 적재된 경우(00302926: 저장 109,142 vs 암시 ≈9,520만)는
     중앙값이 오염돼 ②로는 못 잡는다.
  ② 같은 회사의 전 기간 shares_out 중앙값(±20%).
어느 쪽도 한 후보만 지지하지 않으면 건드리지 않고 출력만 한다(추측 금지).

    python scripts/reconcile_float_shares_scale_r225_2026-10-05.py            # dry-run
    python scripts/reconcile_float_shares_scale_r225_2026-10-05.py --apply
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

_IMPLIED_SQL = """
SELECT e.corp_code, e.fiscal_year,
       percentile_cont(0.5) WITHIN GROUP (
           ORDER BY coalesce(s.controlling_ni, s.net_income)::float / e.amount_won) AS implied
FROM extended_facts_v3 e
JOIN std_financials_v3 s USING (corp_code, fiscal_year, fiscal_period, statement_type)
WHERE e.fiscal_period = 'FY' AND e.canonical_account = 'is.eps_basic'
  AND e.amount_won <> 0 AND coalesce(s.controlling_ni, s.net_income) IS NOT NULL
  AND (coalesce(s.controlling_ni, s.net_income) > 0) = (e.amount_won > 0)
GROUP BY e.corp_code, e.fiscal_year
"""

_SQL = """
WITH med AS (
    SELECT corp_code, percentile_cont(0.5) WITHIN GROUP (ORDER BY shares_out) AS m
    FROM report_shares_outstanding GROUP BY corp_code
)
SELECT r.rcept_no, r.corp_code, r.fiscal_year, r.fiscal_period, r.shares_out,
       r.treasury_shares, r.float_shares, med.m
FROM report_shares_outstanding r JOIN med USING (corp_code)
WHERE r.float_shares IS NOT NULL
  AND r.float_shares + coalesce(r.treasury_shares, 0) <> r.shares_out
"""


def _near(x: float, m: float) -> bool:
    return m > 0 and abs(x - m) <= 0.2 * m


def _within3x(x: float, implied: float | None) -> bool:
    return bool(implied) and implied > 0 and x > 0 and 1 / 3 <= x / implied <= 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    agg = Counter()
    unresolved = []
    with get_session() as s:
        rows = s.execute(text(_SQL)).mappings().all()
        implied = {(c, y): v for c, y, v in s.execute(text(_IMPLIED_SQL))}
        for r in rows:
            issued_new = r["float_shares"] + (r["treasury_shares"] or 0)
            old, m = r["shares_out"], float(r["m"])
            if issued_new != old * 1000:
                agg["not_x1000_kept"] += 1      # source-printed Ⅵ ≠ Ⅳ−Ⅴ — keep as printed
                continue
            imp = implied.get((r["corp_code"], r["fiscal_year"]))
            old_ok, new_ok = _within3x(old, imp), _within3x(issued_new, imp)
            if old_ok != new_ok:
                basis = "eps"
            else:
                old_ok, new_ok = _near(old, m), _near(issued_new, m)
                basis = "median"
            if old_ok and not new_ok:
                # re-extraction applied a false 천주 caption → scale Ⅴ/Ⅵ back to Ⅳ's scale
                upd = {"t": None if r["treasury_shares"] is None else r["treasury_shares"] // 1000,
                       "f": r["float_shares"] // 1000, "s": old}
                agg[f"scale_float_down_{basis}"] += 1
            elif new_ok and not old_ok:
                # stored Ⅳ predates the 천주 multiplier → take the re-extracted Ⅳ
                upd = {"t": r["treasury_shares"], "f": r["float_shares"], "s": issued_new}
                agg[f"fix_stale_issued_{basis}"] += 1
            else:
                agg["unresolved"] += 1
                unresolved.append({**dict(r), "implied": imp})
                continue
            if args.apply:
                s.execute(text("""UPDATE report_shares_outstanding
                    SET shares_out = :s, treasury_shares = :t, float_shares = :f
                    WHERE rcept_no = :r"""), {**upd, "r": r["rcept_no"]})
        if args.apply:
            s.commit()
    print(f"rows {len(rows)} {dict(agg)} (apply={args.apply})")
    for u in unresolved[:40]:
        print("  unresolved", u)
    return 0


if __name__ == "__main__":
    sys.exit(main())
