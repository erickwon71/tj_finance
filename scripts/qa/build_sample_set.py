"""Build the stratified edge-case sample for the QA pilot (docs/qa/01_test_direction.md §7).

Selects ~25-30 companies covering the axes listed in §7 (fiscal-month, market,
market-cap, consolidated-vs-separate-only, market-action/amendment history,
newly-listed, longest/shortest coverage span, dividend/no-dividend, capital
events, and the named Samsung/SK affiliates). Writes
docs/qa/results/sample_set.csv with one row per company and an `axis` column
recording which axis it represents and how it was picked.

A company can legitimately satisfy more than one axis; we keep the first axis
that selected it and de-duplicate by corp_code so the final list stays in the
~25-30 range.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text
from collector.db import get_session

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COVERAGE_CSV = os.path.join(ROOT, "docs", "qa", "results", "expected_coverage.csv")
OUT_PATH = os.path.join(ROOT, "docs", "qa", "results", "sample_set.csv")

N_PER_AXIS = 2


def q(session, sql, **params):
    return session.execute(text(sql), params).fetchall()


def main():
    picks = []  # list of (corp_code, corp_name, stock_code, market, fiscal_month, axis, method)
    seen = set()

    def add(rows, axis, method, limit=N_PER_AXIS):
        n = 0
        for r in rows:
            cc = r[0]
            if cc in seen:
                continue
            seen.add(cc)
            picks.append({
                "corp_code": cc, "corp_name": r[1], "stock_code": r[2],
                "market": r[3], "fiscal_month": r[4],
                "axis": axis, "method": method,
            })
            n += 1
            if n >= limit:
                break

    with get_session() as s:
        # 1. Non-December fiscal year end (주1)
        rows = q(s, """
            SELECT corp_code, corp_name, stock_code, market, fiscal_month
            FROM corporations
            WHERE is_active=TRUE AND fiscal_month IS NOT NULL AND fiscal_month <> 12
            ORDER BY corp_code LIMIT 10
        """)
        add(rows, "fiscal_month_non_dec", "corporations.fiscal_month <> 12")

        # December fiscal year end control group
        rows = q(s, """
            SELECT corp_code, corp_name, stock_code, market, fiscal_month
            FROM corporations
            WHERE is_active=TRUE AND fiscal_month = 12 AND stock_code IN ('005930','000660')
            ORDER BY corp_code
        """)
        add(rows, "fiscal_month_dec_and_flagship", "explicit 005930/000660")

        # 2. Market KOSPI / KOSDAQ (fill any gaps)
        rows = q(s, """
            SELECT corp_code, corp_name, stock_code, market, fiscal_month
            FROM corporations
            WHERE is_active=TRUE AND market='KOSPI'
            ORDER BY corp_code LIMIT 10
        """)
        add(rows, "market_kospi", "corporations.market='KOSPI'")
        rows = q(s, """
            SELECT corp_code, corp_name, stock_code, market, fiscal_month
            FROM corporations
            WHERE is_active=TRUE AND market='KOSDAQ'
            ORDER BY corp_code LIMIT 10
        """)
        add(rows, "market_kosdaq", "corporations.market='KOSDAQ'")

        # 3. Market cap large / small (valuation_daily latest snapshot)
        rows = q(s, """
            SELECT c.corp_code, c.corp_name, c.stock_code, c.market, c.fiscal_month
            FROM valuation_daily v
            JOIN corporations c ON c.corp_code=v.corp_code
            WHERE v.trade_date = (SELECT MAX(trade_date) FROM valuation_daily)
              AND c.is_active=TRUE
            ORDER BY v.market_cap DESC NULLS LAST LIMIT 10
        """)
        add(rows, "market_cap_large", "valuation_daily latest snapshot, top market_cap")
        rows = q(s, """
            SELECT c.corp_code, c.corp_name, c.stock_code, c.market, c.fiscal_month
            FROM valuation_daily v
            JOIN corporations c ON c.corp_code=v.corp_code
            WHERE v.trade_date = (SELECT MAX(trade_date) FROM valuation_daily)
              AND c.is_active=TRUE AND v.market_cap > 0
            ORDER BY v.market_cap ASC LIMIT 10
        """)
        add(rows, "market_cap_small", "valuation_daily latest snapshot, bottom market_cap>0")

        # 4. Separate-only (no consolidated rows ever)
        rows = q(s, """
            SELECT c.corp_code, c.corp_name, c.stock_code, c.market, c.fiscal_month
            FROM corporations c
            WHERE c.is_active=TRUE
              AND EXISTS (SELECT 1 FROM std_financials_v2 s WHERE s.corp_code=c.corp_code AND s.statement_type='separate')
              AND NOT EXISTS (SELECT 1 FROM std_financials_v2 s WHERE s.corp_code=c.corp_code AND s.statement_type='consolidated')
            ORDER BY c.corp_code LIMIT 10
        """)
        add(rows, "separate_only", "no consolidated rows in std_financials_v2, separate rows exist")

        # 5. Market-action history (주3) — active vs lifted-only
        rows = q(s, """
            SELECT c.corp_code, c.corp_name, c.stock_code, c.market, c.fiscal_month
            FROM corporations c
            WHERE c.is_active=TRUE AND EXISTS (
                SELECT 1 FROM regulatory_events r WHERE r.corp_code=c.corp_code AND r.is_lift=false
                AND NOT EXISTS (
                    SELECT 1 FROM regulatory_events r2 WHERE r2.corp_code=r.corp_code
                    AND r2.event_type=r.event_type AND r2.is_lift=true AND r2.filed_at > r.filed_at
                )
            )
            ORDER BY c.corp_code LIMIT 10
        """)
        add(rows, "market_action_active", "regulatory_events: latest event for a type is not lifted")
        rows = q(s, """
            SELECT c.corp_code, c.corp_name, c.stock_code, c.market, c.fiscal_month
            FROM corporations c
            WHERE c.is_active=TRUE AND EXISTS (SELECT 1 FROM regulatory_events r WHERE r.corp_code=c.corp_code)
            ORDER BY c.corp_code LIMIT 10
        """)
        add(rows, "market_action_history", "regulatory_events exists (any, incl. lifted-only)")

        # 6. Amendment history — DB reflects vs original-kept
        rows = q(s, """
            SELECT c.corp_code, c.corp_name, c.stock_code, c.market, c.fiscal_month
            FROM corporations c
            WHERE c.is_active=TRUE AND EXISTS (
                SELECT 1 FROM filings f WHERE f.corp_code=c.corp_code AND f.is_amendment=true
            )
            ORDER BY c.corp_code LIMIT 15
        """)
        add(rows, "amendment_history", "filings.is_amendment=true exists for corp")

        # 7. Newly listed — earliest_fy at or near latest_fy (from expected_coverage.csv, loaded below)

        # 8. Dividend vs no-dividend
        rows = q(s, """
            SELECT c.corp_code, c.corp_name, c.stock_code, c.market, c.fiscal_month
            FROM corporations c
            WHERE c.is_active=TRUE AND EXISTS (
                SELECT 1 FROM std_financials_v2 s WHERE s.corp_code=c.corp_code AND s.dividends_paid IS NOT NULL AND s.dividends_paid <> 0
            )
            ORDER BY c.corp_code LIMIT 10
        """)
        add(rows, "dividend_yes", "std_financials_v2.dividends_paid non-null/non-zero exists")
        rows = q(s, """
            SELECT c.corp_code, c.corp_name, c.stock_code, c.market, c.fiscal_month
            FROM corporations c
            WHERE c.is_active=TRUE AND NOT EXISTS (
                SELECT 1 FROM std_financials_v2 s WHERE s.corp_code=c.corp_code AND s.dividends_paid IS NOT NULL AND s.dividends_paid <> 0
            )
            ORDER BY c.corp_code LIMIT 10
        """)
        add(rows, "dividend_no", "std_financials_v2.dividends_paid always null/zero")

        # 9. Capital events present (증자/CB/BW/EB)
        rows = q(s, """
            SELECT c.corp_code, c.corp_name, c.stock_code, c.market, c.fiscal_month
            FROM corporations c
            WHERE c.is_active=TRUE AND EXISTS (
                SELECT 1 FROM capital_events e WHERE e.corp_code=c.corp_code
                AND e.event_type IN ('cb_issue', 'bw_issue', 'eb_issue')
            )
            ORDER BY c.corp_code LIMIT 10
        """)
        add(rows, "capital_event_cb_bw_eb", "capital_events.event_type in (CB,BW,EB)")

        # 10. Production/order-backlog present vs absent (biz_metrics / order_backlog)
        rows = q(s, """
            SELECT c.corp_code, c.corp_name, c.stock_code, c.market, c.fiscal_month
            FROM corporations c
            WHERE c.is_active=TRUE AND EXISTS (SELECT 1 FROM order_backlog o WHERE o.corp_code=c.corp_code)
            ORDER BY c.corp_code LIMIT 6
        """)
        add(rows, "order_backlog_present", "order_backlog rows exist")

        # 11. No market cap (price-based metrics restricted) — no valuation_daily row ever
        rows = q(s, """
            SELECT c.corp_code, c.corp_name, c.stock_code, c.market, c.fiscal_month
            FROM corporations c
            WHERE c.is_active=TRUE AND c.stock_code IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM valuation_daily v WHERE v.corp_code=c.corp_code)
            ORDER BY c.corp_code LIMIT 6
        """)
        add(rows, "no_market_cap", "no valuation_daily rows for corp despite having stock_code")

        # 12. Flagship companies explicitly requested
        rows = q(s, """
            SELECT corp_code, corp_name, stock_code, market, fiscal_month
            FROM corporations WHERE stock_code IN ('005930','000660','034730')
            ORDER BY stock_code
        """)
        add(rows, "flagship_samsung_sk", "explicit stock_code IN (005930 Samsung Elec, 000660 SK hynix, 034730 SK Inc)", limit=3)

    # 7 + longest/shortest span — from expected_coverage.csv (ground truth already built)
    with open(COVERAGE_CSV, encoding="utf-8-sig") as f:
        cov_rows = list(csv.DictReader(f))
    cov_rows_sorted_span = sorted(cov_rows, key=lambda r: int(r["distinct_fy_count"]), reverse=True)
    longest = cov_rows_sorted_span[:2]
    shortest = sorted(cov_rows, key=lambda r: int(r["distinct_fy_count"]))[:2]
    newly_listed = sorted(cov_rows, key=lambda r: (int(r["latest_fy"]) - int(r["earliest_fy"])))[:3]

    def add_from_cov(rows, axis, method, limit=2):
        n = 0
        for r in rows:
            cc = r["corp_code"]
            if cc in seen:
                continue
            seen.add(cc)
            picks.append({
                "corp_code": cc, "corp_name": r["corp_name"], "stock_code": r["stock_code"],
                "market": r["market"], "fiscal_month": r["fiscal_month"],
                "axis": axis, "method": method,
            })
            n += 1
            if n >= limit:
                break

    add_from_cov(longest, "coverage_span_longest", "expected_coverage.csv distinct_fy_count max")
    add_from_cov(shortest, "coverage_span_shortest", "expected_coverage.csv distinct_fy_count min")
    add_from_cov(newly_listed, "newly_listed", "expected_coverage.csv (latest_fy - earliest_fy) min", limit=3)

    # 2026 Q1 synthetic/seed holders (Samsung/SK) already covered by flagship axis; note explicitly.
    for p in picks:
        if p["stock_code"] in ("005930", "000660"):
            p["axis"] = p["axis"] + "+synthetic_2026Q1_seed"

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "corp_code", "corp_name", "stock_code", "market", "fiscal_month", "axis", "method",
        ])
        writer.writeheader()
        for p in picks:
            writer.writerow(p)

    print(f"sample size: {len(picks)}")
    from collections import Counter
    axis_counts = Counter(p["axis"].split("+")[0] for p in picks)
    for axis, n in axis_counts.items():
        print(f"  {axis}: {n}")
    print(f"wrote: {OUT_PATH}")


if __name__ == "__main__":
    main()
