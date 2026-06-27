"""
Phase 3 스크리너 검증 — app 경로(모집단 캐시 + 메모리 필터) == CLI screen().

DoD: `python run.py screen --roe ">15%" --per "<12"` 와 결과·정렬이 일치.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analyzer.screener import _check, _parse_condition, screen
from app.data.screen_window import load_population


def app_path(filters: dict, market=None, sort_by="roe", sort_asc=False, limit=30):
    """screener_page._apply 와 동일한 메모리 로직."""
    pop = load_population()
    parsed = {k: _parse_condition(v) for k, v in filters.items()}
    out = []
    for r in pop:
        if market and (r.get("market") or "").upper() != market.upper():
            continue
        ok = all(_check(r.get(k), op, thr) for k, (op, thr) in parsed.items())
        if ok:
            out.append(r)
    out.sort(key=lambda r: (1, 0) if r.get(sort_by) is None else (0, r.get(sort_by)),
             reverse=not sort_asc)
    return out[:limit]


def main():
    cases = [
        ({"roe": ">15%", "per": "<12"}, None, "roe", False, 30),
        ({"roe": ">20%"}, "KOSPI", "roe", False, 20),
        ({"per": "<10", "pbr": "<1"}, None, "per", True, 25),
        ({"debt_ratio": "<1", "roic": ">10%"}, None, "roic", False, 30),
    ]
    all_ok = True
    for filters, market, sort_by, asc, limit in cases:
        cli = screen(filters=filters, market=market, sort_by=sort_by,
                     sort_asc=asc, limit=limit)
        app = app_path(filters, market, sort_by, asc, limit)
        cli_keys = [(r["corp_code"], round(r.get(sort_by) or -9e9, 9)) for r in cli]
        app_keys = [(r["corp_code"], round(r.get(sort_by) or -9e9, 9)) for r in app]
        ok = cli_keys == app_keys
        all_ok &= ok
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {filters} market={market} sort={sort_by} asc={asc} "
              f"-> CLI {len(cli)} / APP {len(app)}")
        if not ok:
            print("  CLI:", cli_keys[:10])
            print("  APP:", app_keys[:10])

    print("\n=== ALL PASS ===" if all_ok else "\n=== FAIL ===")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
