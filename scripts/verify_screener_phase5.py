"""
Phase 5 검증 — 대가지표(master_metrics) 수기 대조 + 마법공식 종합랭크 산식.

DCF/배당/Compare 는 엔진(run_dcf/analyze_dividend/compare) 직접 재사용이라
캐시 래퍼가 같은 함수를 호출 → 별도 수치검증 불필요(스모크에서 호출 확인).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from app.compute import screen_eval as se
from app.compute.master_metrics import compute_master
from app.data.screen_window import load_screening_window

STOCK = "005930"  # 삼성전자


def approx(a, b, tol=1e-6):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol + 1e-6 * max(abs(a), abs(b))


def main():
    ok = True
    win = load_screening_window(5, statement_type="consolidated")
    cc = next((k for k, c in win.items() if c["stock_code"] == STOCK), None)
    assert cc, f"{STOCK} 없음"
    c = win[cc]
    rows = c["rows"]
    mc = c["market_cap"]
    price = c["close_price"]

    mm = compute_master(rows, mc, price)
    curr = rows[0]

    # ── Graham Number 수기 ──
    shares = curr["shares_out"]
    eps = (curr.get("controlling_ni") or curr.get("net_income")) / shares
    bps = (curr.get("controlling_equity") or curr.get("total_equity")) / shares
    exp_graham = math.sqrt(22.5 * eps * bps) if eps > 0 and bps > 0 else None
    g_ok = approx(mm.graham_number, exp_graham, tol=1.0)
    ok &= g_ok
    print(f"[{'PASS' if g_ok else 'FAIL'}] Graham Number exp={exp_graham} got={mm.graham_number}")

    # ── EY 수기 ──
    ev = mc + (curr.get("net_debt") or 0)
    exp_ey = curr["operating_income"] / ev
    ey_ok = approx(mm.earnings_yield, exp_ey)
    ok &= ey_ok
    print(f"[{'PASS' if ey_ok else 'FAIL'}] Earnings Yield exp={exp_ey} got={mm.earnings_yield}")

    # ── ROC 수기 ──
    invested = (curr["current_assets"] - curr["current_liabilities"]) + curr["ppe"]
    exp_roc = curr["operating_income"] / invested
    roc_ok = approx(mm.return_on_capital, exp_roc)
    ok &= roc_ok
    print(f"[{'PASS' if roc_ok else 'FAIL'}] ROC exp={exp_roc} got={mm.return_on_capital}")

    # ── 마법공식 종합랭크 산식 ──
    base = se.build_base_frame(win, se.AVERAGE, 5)
    assert se.MAGIC_RANK_ID in base.columns
    valid = base["earnings_yield"].notna() & base["return_on_capital"].notna()
    ey_rank = base["earnings_yield"].rank(ascending=False, method="min")
    roc_rank = base["return_on_capital"].rank(ascending=False, method="min")
    combined = (ey_rank + roc_rank).where(valid)
    exp_magic = combined.rank(ascending=True, method="min")
    # NaN 위치/값 일치 확인
    got = base[se.MAGIC_RANK_ID]
    same = ((got.isna() & exp_magic.isna()) | (got == exp_magic)).all()
    # 최우수(랭크1) 기업이 실제로 EY+ROC 합산 최소인지
    top = base.loc[got.idxmin()] if got.notna().any() else None
    ok &= bool(same)
    print(f"[{'PASS' if same else 'FAIL'}] 마법공식 랭크 산식 일치 · "
          f"유효 {int(valid.sum())}개 · 1위={top['corp_name'] if top is not None else '—'} "
          f"(EY={top['earnings_yield']:.3f} ROC={top['return_on_capital']:.3f})")

    print("\n=== ALL PASS ===" if ok else "\n=== FAIL ===")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
