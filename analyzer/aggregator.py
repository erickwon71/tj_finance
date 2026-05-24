"""
financial_facts → standard_financials 집계 엔진

사용 예:
    from analyzer.aggregator import aggregate_corp, aggregate_all

    # 단일 기업 집계
    result = aggregate_corp("00126380")  # 삼성전자

    # 전체 기업 집계
    aggregate_all(since_fiscal_year=2020)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from loguru import logger
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from collector.db import get_session
from collector.models import StandardFinancial


# ── account_code → standard_financials 컬럼 매핑 ─────────────────────────
# col_index=0 (당기) 기준
# BS: point_in_time, IS/CF: annual/cumulative_ytd
_BS_MAP: dict[str, str] = {
    "bs.total_assets":         "total_assets",
    "bs.current_assets":       "current_assets",
    "bs.cash":                 "cash",
    "bs.trade_receivables":    "receivables",
    "bs.inventory":            "inventory",
    "bs.ppe":                  "ppe",
    "bs.intangibles":          "intangibles",
    "bs.total_liabilities":    "total_liabilities",
    "bs.current_liabilities":  "current_liabilities",
    "bs.short_term_debt":      "short_term_debt",
    "bs.long_term_debt":       "long_term_debt",
    "bs.total_equity":         "total_equity",
    "bs.controlling_equity":   "controlling_equity",
    "bs.retained_earnings":    "retained_earnings",
    "bs.trade_payables":       "trade_payables",
}

_IS_MAP: dict[str, str] = {
    "is.revenue":           "revenue",
    "is.cogs":              "cogs",
    "is.gross_profit":      "gross_profit",
    "is.sga":               "sga",
    "is.operating_income":  "operating_income",
    "is.interest_expense":  "interest_expense",
    "is.finance_cost":      "interest_expense",   # 대체 코드
    "is.ebt":               "ebt",
    "is.tax_expense":       "tax_expense",
    "is.net_income":        "net_income",
    "is.controlling_ni":    "controlling_ni",
}

_CF_MAP: dict[str, str] = {
    "cf.operating":        "cfo",
    "cf.investing":        "cfi",
    "cf.financing":        "cff",
    "cf.capex":            "capex",
    "cf.dividends_paid":   "dividends_paid",
    "cf.depreciation":     "depreciation",
    "cf.amortization":     "amortization",
    "cf.da_total":         "da_total",
}

# account_mapper가 섹션 무관하게 merged index를 사용해서
# CF 섹션의 감가상각비가 note.depreciation 또는 is.depreciation으로 코딩될 수 있음
# → 이 크로스-섹션 코드들도 동일 standard_financials 컬럼으로 집계
_CROSS_SECTION_MAP: dict[str, str] = {
    # account_mapper 섹션 혼용으로 인해 CF/NOTE/IS 섹션 데이터가
    # 다른 접두사로 코딩될 수 있음 → 동일 standard_financials 컬럼으로 수렴
    "note.depreciation":   "depreciation",
    "note.amortization":   "amortization",
    "note.da_total":       "da_total",
    "is.depreciation":     "depreciation",
    "is.amortization":     "amortization",
    # note.roa_depreciation / is.roa_depreciation:
    # 사용권자산상각비 — standard_financials 컬럼 없음, depreciation에 합산
    "note.roa_depreciation": "depreciation",
    "is.roa_depreciation":   "depreciation",
    "cf.roa_depreciation":   "depreciation",
}

_ALL_MAP = {**_BS_MAP, **_IS_MAP, **_CF_MAP, **_CROSS_SECTION_MAP}

# standard_financials 컬럼 이름 집합
_SF_COLS = set(_ALL_MAP.values())


def _amount_won(amount, unit_multiplier) -> Optional[int]:
    """
    원 단위 금액 반환.

    financial_facts.amount 는 parse_amount()가 이미 unit_multiplier를 곱해서
    원(KRW) 단위로 반환한 값이다. → 추가 곱셈 없이 그대로 반환.

    unit_multiplier=1 (원 단위) 이면 amount 자체가 원 단위.
    unit_multiplier=1000 (천원) 이면 amount = cell_value × 1000 이미 계산됨.
    """
    if amount is None:
        return None
    v = int(amount)
    # PostgreSQL BIGINT 범위: ±9,223,372,036,854,775,807 (약 ±9.2경)
    # 한국 상장사 최대 수준: 삼성전자 자산 566조 ≈ 5.66×10^14원
    # 5,000조 = 5×10^15 이상은 파싱 오류로 간주
    _MAX_KRW = 5_000_000_000_000_000   # 5,000조원
    if abs(v) > _MAX_KRW:
        return None
    return v


def aggregate_corp(
    corp_code: str,
    fiscal_year: Optional[int] = None,
    statement_type: str = "both",    # "consolidated" / "separate" / "both"
) -> int:
    """
    주어진 기업의 financial_facts를 집계해 standard_financials에 저장.

    각 (fiscal_year, fiscal_period, statement_type) 조합에서
    가장 facts가 많은 공시(rcept_no) 1개만 선택 → 중복 공시 문제 방지.

    Returns:
        저장/갱신된 행 수
    """
    year_clause = "AND ff.fiscal_year = :fy" if fiscal_year else ""
    stmt_filter = {
        "consolidated": "AND ff.statement_type = 'consolidated'",
        "separate":     "AND ff.statement_type = 'separate'",
    }.get(statement_type, "")

    # 각 (fiscal_year, fiscal_period, statement_type) 별로 최다 BS/IS/CF facts를 가진 rcept_no 선택
    # col_index=0 (당기 직접 공시) 우선, 없으면 col_index>0 (이전 공시의 비교 컬럼) 폴백
    sql = f"""
        SELECT
            ff.corp_code,
            ff.fiscal_year,
            ff.fiscal_period,
            ff.statement_type,
            MAX(ff.period_end)      AS period_end,
            BOOL_OR(ff.is_ifrs)     AS is_ifrs,
            -- col_index=0 우선, 없으면 다른 col_index의 rcept_no 사용
            COALESCE(
                (
                    SELECT ff2.rcept_no
                    FROM financial_facts ff2
                    WHERE ff2.corp_code      = ff.corp_code
                      AND ff2.fiscal_year    = ff.fiscal_year
                      AND ff2.fiscal_period  = ff.fiscal_period
                      AND ff2.statement_type = ff.statement_type
                      AND ff2.col_index      = 0
                      AND ff2.fs_type        NOT LIKE 'NOTE%'
                      AND NOT ff2.is_superseded
                    GROUP BY ff2.rcept_no
                    ORDER BY COUNT(*) DESC
                    LIMIT 1
                ),
                (
                    SELECT ff3.rcept_no
                    FROM financial_facts ff3
                    WHERE ff3.corp_code      = ff.corp_code
                      AND ff3.fiscal_year    = ff.fiscal_year
                      AND ff3.fiscal_period  = ff.fiscal_period
                      AND ff3.statement_type = ff.statement_type
                      AND ff3.col_index      > 0
                      AND ff3.fs_type        NOT LIKE 'NOTE%'
                      AND NOT ff3.is_superseded
                    GROUP BY ff3.rcept_no
                    ORDER BY COUNT(*) DESC
                    LIMIT 1
                )
            ) AS best_rcept_no
        FROM financial_facts ff
        WHERE ff.corp_code = :corp_code
          AND NOT ff.is_superseded
          {year_clause}
          {stmt_filter}
        GROUP BY ff.corp_code, ff.fiscal_year, ff.fiscal_period, ff.statement_type
        ORDER BY ff.fiscal_year DESC, ff.fiscal_period, ff.statement_type
    """
    params = {"corp_code": corp_code}
    if fiscal_year:
        params["fy"] = fiscal_year

    with get_session() as session:
        combos = session.execute(text(sql), params).fetchall()

    if not combos:
        logger.debug(f"[집계] {corp_code} — 데이터 없음")
        return 0

    saved = 0
    for row in combos:
        corp_code_, fy, fp, stmt_type, period_end, is_ifrs, rcept_no = row
        if not rcept_no:
            continue
        n = _aggregate_one(corp_code_, fy, fp, stmt_type, period_end, is_ifrs, rcept_no)
        saved += n

    return saved


def _aggregate_one(
    corp_code: str,
    fiscal_year: int,
    fiscal_period: str,
    statement_type: str,
    period_end,
    is_ifrs: Optional[bool],
    rcept_no: Optional[str],
) -> int:
    """단일 (corp_code, fiscal_year, fiscal_period, statement_type) 집계."""

    # fs_type 필터: 연결/별도에 따라 BS_C, IS_C, CF_C / BS_S, IS_S, CF_S
    suffix = "_C" if statement_type == "consolidated" else "_S"
    fs_types = [f"BS{suffix}", f"IS{suffix}", f"CF{suffix}",
                f"NOTE{suffix}"]

    # rcept_no로 필터링해 단일 공시의 데이터만 사용
    # fs_type을 올바른 연결/별도 유형으로 제한 (IS_C/BS_C 혼합 방지)
    # fiscal_year에 맞는 col_index 선택:
    #   - col_index=0이 있으면 우선 사용
    #   - 없으면 해당 fiscal_year의 다른 col_index 사용
    sql = """
        SELECT account_code, amount, unit_multiplier, fs_type, col_index
        FROM financial_facts
        WHERE corp_code    = :corp_code
          AND rcept_no     = :rcept_no
          AND fiscal_year  = :fiscal_year
          AND fiscal_period = :fiscal_period
          AND fs_type       = ANY(:fs_types)
          AND NOT is_superseded
          AND (account_code NOT LIKE 'unknown.%'
               OR account_code IN ('unknown.지배주주순이익', 'unknown.지배주주 순이익',
                                   'unknown.비지배주주순이익', 'unknown.비지배주주 순이익'))
        ORDER BY col_index ASC, is_subtotal DESC, extraction_confidence DESC
    """
    with get_session() as session:
        rows = session.execute(text(sql), {
            "corp_code":    corp_code,
            "rcept_no":     rcept_no,
            "fiscal_year":  fiscal_year,
            "fiscal_period": fiscal_period,
            "fs_types":     fs_types,
        }).fetchall()

    if not rows:
        return 0

    # ── account_code → 컬럼값 매핑 (소계 우선, 중복 시 먼저 등장한 것 유지) ──
    # context-aware 오버라이드: IS 섹션에 잘못 코딩된 CF 코드 처리
    _IS_FS_TYPES = {"IS_C", "IS_S"}
    _CF_IN_IS_FIXUP = {
        # 계정과목명 "당기순이익"이 IS 섹션에서 cf.net_income_cf 로 오코딩될 수 있음
        "cf.net_income_cf": "net_income",
    }
    # BS 코드가 IS 섹션에 나타나는 경우의 재매핑
    # (예: 삼성전자 "지배기업 소유지분" → bs.controlling_equity로 오코딩)
    _BS_IN_IS_FIXUP: dict[str, Optional[str]] = {
        "bs.controlling_equity":      "controlling_ni",
        "bs.noncontrolling_interest": None,  # 비지배지분 귀속 NI — 표준 컬럼 없음
    }

    # unknown 계정명 → IS 컬럼 직접 매핑 (aggregator 레벨 fallback)
    # is_accounts.py 갱신 전에 파싱된 데이터 구제
    _UNKNOWN_IS_FIXUP: dict[str, str] = {
        "unknown.지배주주순이익":       "controlling_ni",
        "unknown.지배주주 순이익":      "controlling_ni",
        "unknown.비지배주주순이익":     None,  # 집계 불필요
        "unknown.비지배주주 순이익":    None,
    }

    # 감가상각비 합산용 별도 누계 (sub-item이 여러 개일 수 있음)
    # CF/IS 섹션에서만 D&A 추출 (NOTE 섹션은 누계액이나 다른 문맥일 수 있어 제외)
    _DA_ADDITIVE_CODES = {
        "depreciation", "amortization",
    }
    # NOTE 섹션의 감가상각은 누계액(accumulated)이 섞일 수 있어 D&A 집계에서 제외
    _DA_VALID_FS_TYPES = {"CF_C", "CF_S", "IS_C", "IS_S"}

    sf_values: dict[str, Optional[int]] = {}
    _da_accumulator: dict[str, int] = {}   # depreciation/amortization 누계

    for account_code, amount, unit_mult, fs_type, col_idx in rows:
        col_name = _ALL_MAP.get(account_code)

        if fs_type in _IS_FS_TYPES:
            # IS 섹션에 CF 코드가 있는 경우 → IS 컬럼으로 강제 매핑
            if col_name is None:
                col_name = _CF_IN_IS_FIXUP.get(account_code)
            # IS 섹션에 BS 코드가 있는 경우 → IS 컬럼으로 재매핑
            # (예: 지배기업 소유지분 → bs.controlling_equity → controlling_ni)
            if col_name is None or col_name in {"controlling_equity"}:
                fixup = _BS_IN_IS_FIXUP.get(account_code)
                if fixup is not None or account_code in _BS_IN_IS_FIXUP:
                    col_name = fixup  # None이면 이 계정 스킵
            # unknown.* 계정 중 알려진 IS 패턴 구제
            if col_name is None and account_code.startswith("unknown."):
                col_name = _UNKNOWN_IS_FIXUP.get(account_code)

        if not col_name:
            continue

        v = _amount_won(amount, unit_mult)
        if v is None:
            continue

        # D&A 합산: CF/IS 섹션에서만, abs 값 사용 (음수 표시 기업도 있음)
        if col_name in _DA_ADDITIVE_CODES:
            if fs_type in _DA_VALID_FS_TYPES:
                _da_accumulator[col_name] = _da_accumulator.get(col_name, 0) + abs(v)
            # NOTE 섹션 D&A는 무시 (누계액 혼용 방지)
        elif col_name not in sf_values:
            sf_values[col_name] = v

    # 합산된 감가상각 반영
    for da_col, total in _da_accumulator.items():
        if total > 0:
            sf_values[da_col] = total

    if not sf_values:
        return 0

    # ── 파생 지표 계산 ────────────────────────────────────────────────
    # EBITDA = operating_income + da_total (감가상각비 있을 때만)
    op_income = sf_values.get("operating_income")
    da = sf_values.get("da_total")
    if da is None:
        # cf.depreciation + cf.amortization 합산
        dep = sf_values.get("depreciation")
        amo = sf_values.get("amortization")
        if dep is not None or amo is not None:
            da = (dep or 0) + (amo or 0)
            if da:
                sf_values["da_total"] = da

    if op_income is not None and da is not None and da > 0:
        sf_values["ebitda"] = op_income + da

    # FCF = CFO - |CAPEX|
    cfo = sf_values.get("cfo")
    capex = sf_values.get("capex")
    if cfo is not None and capex is not None:
        sf_values["fcf"] = cfo - abs(capex)

    # Net Debt = (단기차입금 + 장기차입금) - 현금
    std = sf_values.get("short_term_debt")
    ltd = sf_values.get("long_term_debt")
    cash = sf_values.get("cash")
    if cash is not None and (std is not None or ltd is not None):
        sf_values["net_debt"] = (std or 0) + (ltd or 0) - cash

    # ── period_end 보정: NULL이면 fiscal_year + fiscal_period로 추정 ──
    if not period_end:
        from datetime import date as _date
        _fp_to_month_day = {
            "FY": (12, 31),
            "H1": (6, 30),
            "H2": (12, 31),
            "Q1": (3, 31),
            "Q2": (6, 30),
            "Q3": (9, 30),
            "Q4": (12, 31),
        }
        md = _fp_to_month_day.get(fiscal_period, (12, 31))
        try:
            period_end = _date(fiscal_year, md[0], md[1])
        except Exception:
            pass

    # ── standard_financials upsert ────────────────────────────────────
    # 항상 명시적으로 포함해야 하는 파생 컬럼들 (이전 잘못된 값을 NULL로 덮어씌움)
    _DERIVED_COLS = {"depreciation", "amortization", "da_total", "ebitda", "fcf", "net_debt"}

    record = {
        "corp_code":      corp_code,
        "fiscal_year":    fiscal_year,
        "fiscal_period":  fiscal_period,
        "statement_type": statement_type,
        "version":        1,
        "period_end":     period_end,
        "is_ifrs":        is_ifrs,
        "rcept_no":       rcept_no,
        "data_quality":   1,   # 정상 (자동 계산)
        "calculated_at":  datetime.utcnow(),
        # 파생 컬럼은 항상 명시 포함 (NULL이면 None으로 기존 값 덮어씌움)
        **{col: sf_values.get(col) for col in _DERIVED_COLS},
        # 나머지 계산된 값들
        **{k: v for k, v in sf_values.items()
           if k in _SF_COLS and k not in _DERIVED_COLS},
    }

    with get_session() as session:
        stmt = pg_insert(StandardFinancial.__table__).values([record])
        stmt = stmt.on_conflict_do_update(
            index_elements=["corp_code", "fiscal_year", "fiscal_period", "statement_type", "version"],
            set_={k: stmt.excluded[k]
                  for k in record if k not in
                  ("corp_code", "fiscal_year", "fiscal_period", "statement_type", "version")},
        )
        session.execute(stmt)

    return 1


def aggregate_all(
    since_fiscal_year: int = 2015,
    statement_type: str = "both",
    workers: int = 1,
) -> int:
    """
    전체 기업을 집계해 standard_financials 갱신.

    Returns:
        처리된 (corp_code, fiscal_year, fiscal_period, statement_type) 수
    """
    sql = """
        SELECT DISTINCT ff.corp_code
        FROM financial_facts ff
        WHERE ff.fiscal_year >= :since_fy
          AND ff.col_index = 0
          AND NOT ff.is_superseded
        ORDER BY ff.corp_code
    """
    with get_session() as session:
        corps = [r[0] for r in session.execute(text(sql), {"since_fy": since_fiscal_year}).fetchall()]

    logger.info(f"집계 대상: {len(corps)}개 기업 (FY≥{since_fiscal_year})")

    total_rows = 0
    for i, corp_code in enumerate(corps, 1):
        try:
            n = aggregate_corp(corp_code, statement_type=statement_type)
            total_rows += n
        except Exception as exc:
            logger.error(f"[집계] {corp_code} 오류: {exc}")

        if i % 50 == 0:
            logger.info(f"  집계 {i}/{len(corps)} — 누계 {total_rows}건")

    logger.success(f"집계 완료 — {len(corps)}개 기업, {total_rows}건 표준화")
    return total_rows
