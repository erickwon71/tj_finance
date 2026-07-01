"""
스크리너 데이터 로더.

Phase 3(단일패스): 최신 FY 기준 전체 모집단을 한 번 로드한다. 모집단 행은
`analyzer.screener.screen` 이 만드는 행과 **완전히 동일**(같은 compute_ratios·
멀티플·Piotroski 산식) — 필터를 비우고 한도를 해제해 전수를 받아온 뒤, 페이지에서
`analyzer.screener._check` 로 메모리 필터·정렬을 적용한다. 따라서 결과·정렬이
`python run.py screen ...` CLI 와 일치한다.

Phase 4 에서 `load_screening_window(n_years, fiscal_year)`(rn 캡 확장 + 윈도우 집계)
가 여기 추가된다.
"""
from __future__ import annotations

from typing import Optional

# 사실상 무한 한도 — 전수 모집단을 받기 위함(전체 활성 보통주 ~2.5천)
_NO_LIMIT = 1_000_000

# 윈도우 로드 시 받아올 행에 포함할 컬럼(= compute_ratios 입력 + 식별/시총)
_WINDOW_COLS = """
    sf.corp_code, sf.fiscal_year, sf.fiscal_period,
    sf.statement_type, sf.period_end, sf.data_quality,
    sf.total_assets, sf.current_assets, sf.cash,
    sf.receivables, sf.inventory, sf.ppe,
    sf.total_liabilities, sf.current_liabilities,
    sf.short_term_debt, sf.long_term_debt,
    sf.total_equity, sf.controlling_equity, sf.retained_earnings,
    sf.trade_payables,
    sf.revenue, sf.cogs, sf.gross_profit, sf.sga, sf.rd_expense,
    sf.operating_income, sf.interest_expense, sf.ebt,
    sf.tax_expense, sf.net_income, sf.controlling_ni,
    sf.cfo, sf.cfi, sf.cff, sf.capex, sf.dividends_paid,
    sf.depreciation, sf.amortization, sf.da_total,
    sf.ebitda, sf.fcf, sf.net_debt, sf.shares_out
"""


def load_population(fiscal_year: Optional[int] = None) -> list[dict]:
    """
    필터 없는 전체 모집단(최신 FY, 연결, data_quality<3).

    반환 행 = `analyzer.screener.screen` 의 행 스키마와 동일:
      corp_code, corp_name, stock_code, market, fiscal_year, market_cap_jo,
      roe/roa/roic/op_margin/net_margin/ebitda_margin,
      per/pbr/ev_ebitda/pcr/psr,
      revenue_growth/op_growth/ni_growth,
      debt_ratio/current_ratio/interest_coverage, ccc,
      fcf_quality/accrual_ratio, piotroski
    """
    from analyzer.screener import screen

    return screen(
        filters={},
        market=None,
        sort_by="roe",
        sort_asc=False,
        limit=_NO_LIMIT,
        fiscal_year=fiscal_year,
    )


def load_screening_window(
    n_periods: int,
    fiscal_year: Optional[int] = None,
    statement_type: str = "consolidated",
    grain: str = "annual",
) -> dict[str, dict]:
    """
    전체 활성 보통주의 최근 `n_periods` 기간 시계열 + 최신 시총을 한 번에 로드.

    grain="annual": standard_financials FY (연간).
    grain="quarter": calendar_financials 달력분기 CQ1~CQ4 이산(분기).

    반환: {corp_code: {
        "corp_code","corp_name","stock_code","market","market_cap","close_price",
        "used_stmt",              # 실제 사용 basis (요청 basis 없어 폴백했으면 반대값)
        "rows": [행 dict, ...]   # 최신→과거
    }}

    statement_type 은 요청 basis(기본 consolidated). **corp별 연결→별도 폴백** — 요청 basis
    FY 행이 없는 기업은 반대 basis 로 대체(회사페이지 series 폴백과 동일 철학, 단 basis 는
    corp 단위로 고정해 한 기업의 시계열이 basis 혼합되지 않게 함).
    """
    if grain == "quarter":
        return _load_quarter_window(n_periods, statement_type)

    from collector.db import get_session
    from sqlalchemy import text

    n_rows = max(1, n_periods) + 1  # 오래된 기간 ratio prev 용 +1
    other = "separate" if statement_type == "consolidated" else "consolidated"
    year_filter = f"AND sf.fiscal_year = {int(fiscal_year)}" if fiscal_year else ""

    # avail: corp 별로 요청 basis FY 행 존재 여부. has_req=False 인 기업만 반대 basis 채택.
    sql = f"""
        WITH avail AS (
            SELECT sf.corp_code,
                   BOOL_OR(sf.statement_type = :stmt) AS has_req
            FROM standard_financials sf
            WHERE sf.fiscal_period    = 'FY'
              AND sf.statement_type   IN (:stmt, :other)
              AND sf.data_quality     < 3
              {year_filter}
            GROUP BY sf.corp_code
        ),
        ranked AS (
            SELECT
                {_WINDOW_COLS},
                c.corp_name, c.stock_code, c.market,
                sp.close_price, sp.market_cap,
                ROW_NUMBER() OVER (
                    PARTITION BY sf.corp_code
                    ORDER BY sf.fiscal_year DESC
                ) AS rn
            FROM standard_financials sf
            JOIN avail a ON a.corp_code = sf.corp_code
            JOIN corporations c ON c.corp_code = sf.corp_code
            LEFT JOIN LATERAL (
                SELECT close_price, market_cap
                FROM stock_prices
                WHERE stock_code = c.stock_code
                  AND market_cap IS NOT NULL
                ORDER BY trade_date DESC
                LIMIT 1
            ) sp ON TRUE
            WHERE sf.fiscal_period    = 'FY'
              AND sf.statement_type   = CASE WHEN a.has_req THEN :stmt ELSE :other END
              AND sf.data_quality     < 3
              AND c.stock_code        IS NOT NULL
              {year_filter}
        )
        SELECT * FROM ranked WHERE rn <= :n_rows
        ORDER BY corp_code, rn
    """

    with get_session() as session:
        rows = session.execute(
            text(sql), {"stmt": statement_type, "other": other, "n_rows": n_rows}
        ).mappings().fetchall()

    window: dict[str, dict] = {}
    for row in rows:
        cc = row["corp_code"]
        if cc not in window:
            window[cc] = {
                "corp_code":   cc,
                "corp_name":   row["corp_name"],
                "stock_code":  row["stock_code"],
                "market":      row["market"],
                "market_cap":  row["market_cap"],
                "close_price": row["close_price"],
                "used_stmt":   row["statement_type"],
                "rows":        [],
            }
        window[cc]["rows"].append(dict(row))  # rn 오름차순 = 최신→과거

    return window


def _load_quarter_window(n_periods: int, statement_type: str) -> dict[str, dict]:
    """
    분기(달력분기 CQ1~CQ4 이산) 윈도우 — calendar_financials.

    n_rows = max(n_periods+1, 8): TTM 멀티플/대가(현재 TTM=4분기 + 전년 TTM=직전 4분기)와
    YoY(4분기 전) 계산에 충분하도록 최소 8분기 확보.
    """
    from collector.db import get_session
    from sqlalchemy import text

    n_rows = max(int(n_periods) + 1, 8)
    other = "separate" if statement_type == "consolidated" else "consolidated"
    # avail: corp 별 요청 basis 달력분기 행 존재 여부 → 없으면 반대 basis 폴백(annual 과 동일).
    sql = """
        WITH avail AS (
            SELECT cf.corp_code,
                   BOOL_OR(cf.statement_type = :stmt) AS has_req
            FROM calendar_financials cf
            WHERE cf.calendar_period IN ('CQ1', 'CQ2', 'CQ3', 'CQ4')
              AND cf.statement_type IN (:stmt, :other)
              AND COALESCE(cf.data_quality, 1) < 3
            GROUP BY cf.corp_code
        ),
        ranked AS (
            SELECT
                cf.*,
                c.corp_name, c.stock_code, c.market,
                sp.close_price, sp.market_cap,
                ROW_NUMBER() OVER (
                    PARTITION BY cf.corp_code
                    ORDER BY cf.calendar_year DESC,
                        CASE cf.calendar_period
                            WHEN 'CQ4' THEN 4 WHEN 'CQ3' THEN 3
                            WHEN 'CQ2' THEN 2 ELSE 1 END DESC
                ) AS rn
            FROM calendar_financials cf
            JOIN avail a ON a.corp_code = cf.corp_code
            JOIN corporations c ON c.corp_code = cf.corp_code
            LEFT JOIN LATERAL (
                SELECT close_price, market_cap
                FROM stock_prices
                WHERE stock_code = c.stock_code AND market_cap IS NOT NULL
                ORDER BY trade_date DESC LIMIT 1
            ) sp ON TRUE
            WHERE cf.statement_type = CASE WHEN a.has_req THEN :stmt ELSE :other END
              AND cf.calendar_period IN ('CQ1', 'CQ2', 'CQ3', 'CQ4')
              AND COALESCE(cf.data_quality, 1) < 3
              AND c.stock_code IS NOT NULL
        )
        SELECT * FROM ranked WHERE rn <= :n_rows
        ORDER BY corp_code, rn
    """
    with get_session() as session:
        rows = session.execute(
            text(sql), {"stmt": statement_type, "other": other, "n_rows": n_rows}
        ).mappings().fetchall()

    window: dict[str, dict] = {}
    for row in rows:
        cc = row["corp_code"]
        if cc not in window:
            window[cc] = {
                "corp_code":   cc,
                "corp_name":   row["corp_name"],
                "stock_code":  row["stock_code"],
                "market":      row["market"],
                "market_cap":  row["market_cap"],
                "close_price": row["close_price"],
                "used_stmt":   row["statement_type"],
                "rows":        [],
            }
        window[cc]["rows"].append(dict(row))
    return window
