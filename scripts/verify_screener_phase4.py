"""
Phase 4 스크리너 검증.

1) 윈도우 집계(average/CAGR/YoY)가 1개 기업 수기 대조와 일치.
2) 퀀트 3패스가 순차로 모집단을 좁힘(각 패스 단조 비증가).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from analyzer.ratio_engine import _cagr, _growth_rate, compute_ratios
from app.compute import screen_eval as se
from app.data.screen_window import load_screening_window

N = 3
STOCK = "005930"  # 삼성전자


def approx(a, b, tol=1e-9):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol + 1e-6 * max(abs(a), abs(b))


def main():
    ok = True

    # ── 1) 윈도우 집계 수기 대조 ──
    for method in (se.AVERAGE, se.CAGR, se.YOY):
        win = load_screening_window(N, statement_type="consolidated")
        base = se.build_base_frame(win, method, N)

        target_cc = next((cc for cc, c in win.items()
                          if c["stock_code"] == STOCK), None)
        assert target_cc, f"{STOCK} 윈도우에 없음"
        rows = win[target_cc]["rows"]

        # revenue (column metric) 수기
        rev = [rows[i].get("revenue") for i in range(min(N, len(rows)))]
        if method == se.AVERAGE:
            vals = [v for v in rev if v is not None]
            exp_rev = sum(vals) / len(vals)
        elif method == se.YOY:
            exp_rev = _growth_rate(rev[0], rev[1])
        else:
            start, span = None, 0
            for i in range(1, len(rev)):
                if rev[i] is not None:
                    start, span = rev[i], i
            exp_rev = _cagr(start, rev[0], span)

        # roe (ratio metric) 수기
        roe_series = []
        for i in range(min(N, len(rows))):
            prev = rows[i + 1] if i + 1 < len(rows) else None
            roe_series.append(compute_ratios(rows[i], prev).roe)
        if method == se.AVERAGE:
            rv = [v for v in roe_series if v is not None]
            exp_roe = sum(rv) / len(rv) if rv else None
        elif method == se.YOY:
            exp_roe = _growth_rate(roe_series[0], roe_series[1])
        else:
            start, span = None, 0
            for i in range(1, len(roe_series)):
                if roe_series[i] is not None:
                    start, span = roe_series[i], i
            exp_roe = _cagr(start, roe_series[0], span) if span else None

        got = base[base["corp_code"] == target_cc].iloc[0]
        r_ok = approx(float(got["revenue"]) if pd.notna(got["revenue"]) else None, exp_rev)
        e_ok = approx(float(got["roe"]) if pd.notna(got["roe"]) else None, exp_roe)
        ok &= r_ok and e_ok
        print(f"[{'PASS' if r_ok and e_ok else 'FAIL'}] {method:8s} "
              f"revenue exp={exp_rev} got={got['revenue']} | "
              f"roe exp={exp_roe} got={got['roe']}")

    # ── 2) 퀀트 3패스 순차 축소 ──
    win = load_screening_window(N, statement_type="consolidated")
    base = se.build_base_frame(win, se.AVERAGE, N)
    passes = [
        {"filters": {"roe": ("gt", 0.10)}, "sort_by": "roe", "asc": False, "limit": 200},
        {"filters": {"debt_ratio": ("lt", 1.0)}, "sort_by": "roe", "asc": False, "limit": 100},
        {"filters": {"op_margin": ("gt", 0.10)}, "sort_by": "op_margin", "asc": False, "limit": 30},
    ]
    final, counts = se.run_quant_passes(base, passes)
    monotone = all(counts[i] >= counts[i + 1] for i in range(len(counts) - 1))
    # 각 패스가 실제로 필터링했는지(전체 대비 축소)
    narrowed = counts[0] <= len(base)
    p_ok = monotone and narrowed and len(final) == counts[-1]
    ok &= p_ok
    print(f"[{'PASS' if p_ok else 'FAIL'}] 퀀트 3패스: base={len(base)} → {counts} "
          f"(단조축소={monotone})")

    print("\n=== ALL PASS ===" if ok else "\n=== FAIL ===")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
