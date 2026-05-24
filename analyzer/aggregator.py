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
    "is.rd_expense":        "rd_expense",
    "is.operating_income":  "operating_income",
    "is.interest_expense":  "interest_expense",
    "is.finance_cost":      "interest_expense",   # 대체 코드
    "is.ebt":               "ebt",
    "is.tax_expense":       "tax_expense",
    "is.net_income":        "net_income",
    "is.controlling_ni":    "controlling_ni",
}

_CF_MAP: dict[str, str] = {
    "cf.operating":            "cfo",
    "cf.investing":            "cfi",
    "cf.financing":            "cff",
    "cf.capex":                "capex",
    "cf.capex_intangible":     "capex",    # 무형자산취득 → CAPEX에 합산
    "cf.dividends_paid":       "dividends_paid",
    "cf.depreciation":         "depreciation",
    "cf.amortization":         "amortization",
    "cf.da_total":             "da_total",
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
    # note.rou_depreciation / is.rou_depreciation (Right-Of-Use asset depreciation):
    # 사용권자산상각비 — standard_financials 컬럼 없음, depreciation에 합산
    "note.rou_depreciation": "depreciation",
    "note.roa_depreciation": "depreciation",   # legacy typo 호환
    "is.rou_depreciation":   "depreciation",
    "is.roa_depreciation":   "depreciation",   # legacy typo 호환
    "cf.rou_depreciation":   "depreciation",
    "cf.roa_depreciation":   "depreciation",   # legacy typo 호환
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


def _validate_cross_year(
    session,
    corp_code: str,
    statement_type: str,
    sf_values: dict,
) -> int:
    """
    이미 저장된 연도 데이터와 교차 검증해 이상값 탐지.

    임계값 설계:
      - ratio > 200x  : 파싱 오류로 간주 (DQ=3)
        → 예: 경농 2024 343조 vs 정상 3,400억 (1000x)
        → 예: 농심 2018 226,941조 vs 정상 3조 (75,000x)
      - ratio > 30x   : 경고 표시 (DQ=2)
        → 예: M&A로 급성장 → 사람이 검토
      - else          : 정상 (DQ=1)

    절대 최솟값 조건: 중앙값이 너무 작으면 (< 10억) 비율 검증 생략
    → 소규모 기업의 정상적 변동을 오탐 방지

    Returns:
        data_quality 레벨 (1=정상, 2=경고, 3=오류)
    """
    # 기준 컬럼: revenue 또는 total_assets
    check_cols = [("revenue", 200, 30), ("total_assets", 200, 30)]
    _MIN_MEDIAN = 1_000_000_000   # 중앙값 10억 미만은 검증 생략 (소기업)

    dq = 1
    for col, limit_err, limit_warn in check_cols:
        new_val = sf_values.get(col)
        if not new_val or new_val <= 0:
            continue   # 0 또는 음수 매출/자산은 검증 대상 아님 (정상 범위로 간주)

        # 같은 기업 같은 statement_type의 다른 연도 중앙값 조회
        result = session.execute(text(f"""
            SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {col})
            FROM standard_financials
            WHERE corp_code      = :corp_code
              AND statement_type = :stmt_type
              AND fiscal_period  = 'FY'
              AND {col}          > 0
              AND version        = 1
              AND data_quality   < 3
        """), {"corp_code": corp_code, "stmt_type": statement_type}).scalar()

        if result and result >= _MIN_MEDIAN:
            ratio = new_val / result
            if ratio > limit_err or ratio < (1.0 / limit_err):
                logger.warning(
                    f"[이상값-오류] {corp_code} {statement_type} {col}: "
                    f"신규={new_val/1e8:.0f}억 vs 중앙값={result/1e8:.0f}억 "
                    f"(비율={ratio:.1f}x) → DQ=3"
                )
                return 3  # 오류 (비율 200x 초과)
            elif ratio > limit_warn or ratio < (1.0 / limit_warn):
                logger.warning(
                    f"[이상값-경고] {corp_code} {statement_type} {col}: "
                    f"신규={new_val/1e8:.0f}억 vs 중앙값={result/1e8:.0f}억 "
                    f"(비율={ratio:.1f}x) → DQ=2"
                )
                dq = max(dq, 2)  # 경고

    return dq


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
            -- col_index=0 우선, 없으면 col_index>0, 최후 수단으로 NOTE 섹션 rcept 사용
            -- NOTE 폴백: NOTE만 존재하는 경우에도 upsert를 진행해 기존 잘못된 값을 NULL로 초기화
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
                ),
                (
                    SELECT ff4.rcept_no
                    FROM financial_facts ff4
                    WHERE ff4.corp_code      = ff.corp_code
                      AND ff4.fiscal_year    = ff.fiscal_year
                      AND ff4.fiscal_period  = ff.fiscal_period
                      AND ff4.statement_type = ff.statement_type
                      AND NOT ff4.is_superseded
                    GROUP BY ff4.rcept_no
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
        ORDER BY
            col_index ASC,
            -- NOTE 섹션은 보조 출처: IS/BS/CF가 항상 NOTE보다 먼저 (is_subtotal보다 우선)
            -- 이유: NOTE의 is_subtotal=True가 IS_C보다 먼저 정렬되는 버그 방지
            CASE WHEN fs_type LIKE 'NOTE%' THEN 1 ELSE 0 END ASC,
            is_subtotal DESC,
            extraction_confidence DESC
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

    # 합산 방식으로 집계할 계정 코드 (sub-items → 합계)
    _ADDITIVE_CODES = {
        "depreciation", "amortization",  # D&A
        "capex",                          # CAPEX 세부항목 합산 (K-GAAP 개별 자산)
    }
    # CF/IS에서 D&A 합산 (개별 자산별 감가상각, ROU 포함)
    # NOTE도 허용: note_extractor가 CF 주석에서 추출한 감가상각비
    _ADDITIVE_DA_FS_TYPES = {"CF_C", "CF_S", "IS_C", "IS_S", "NOTE_C", "NOTE_S"}
    # CAPEX 합산은 CF 섹션만 (NOTE 섹션의 자산취득 = 유형자산 주석, 현금흐름 아님)
    _ADDITIVE_CAPEX_FS_TYPES = {"CF_C", "CF_S"}

    sf_values: dict[str, Optional[int]] = {}
    _accumulator: dict[str, int] = {}   # 합산 대상 계정 누계
    # NOTE vs CF 소스 추적 (CF 소스가 있으면 NOTE로 덮지 않기 위해)
    _da_source: str = ""  # "" / "cf" / "note"

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

        # 합산 방식 처리 (D&A + CAPEX 세부항목)
        if col_name in _ADDITIVE_CODES:
            is_note = fs_type.startswith("NOTE")
            if col_name in ("depreciation", "amortization"):
                # D&A: CF/IS/NOTE 모두 합산 허용.
                # 단, CF 소스가 이미 있으면 NOTE 소스로 덮지 않음
                # (CF 간접법에서 직접 추출 > 주석 추출)
                if not is_note and fs_type in _ADDITIVE_DA_FS_TYPES:
                    _accumulator[col_name] = _accumulator.get(col_name, 0) + abs(v)
                    _da_source = "cf"
                elif is_note and _da_source != "cf":
                    # CF에 D&A가 없을 때만 NOTE 소스 사용
                    _accumulator[col_name] = _accumulator.get(col_name, 0) + abs(v)
                    _da_source = "note"
            elif col_name == "capex":
                if fs_type in _ADDITIVE_CAPEX_FS_TYPES:
                    _accumulator["capex"] = _accumulator.get("capex", 0) + abs(v)
        elif col_name not in sf_values:
            sf_values[col_name] = v

    # 합산 결과 반영
    for col, total in _accumulator.items():
        if total > 0:
            if col == "capex":
                # CAPEX는 음수로 저장 (현금 유출이므로)
                sf_values[col] = -total
            else:
                sf_values[col] = total

    # sf_values가 비어있어도 upsert는 진행:
    # 이미 standard_financials에 잘못된 값(NOTE_C 오탐 등)이 있을 경우
    # NULL로 덮어씌워 정리해야 함
    # (rows가 있었지만 모든 값이 5,000조 캡에 걸려 무효화된 경우)
    # rows 자체가 없으면 _aggregate_one이 rows==[] 체크에서 이미 return 0

    # ── 파생 지표 계산 ────────────────────────────────────────────────
    # net_income 보완: controlling_ni + noncontrolling_ni로 합산
    # 일부 K-IFRS IS에서 "당기순이익" 합계 행 없이 지배/비지배 귀속만 표시하는 경우
    if sf_values.get("net_income") is None:
        cni  = sf_values.get("controlling_ni")
        ncni = sf_values.get("noncontrolling_ni")
        if cni is not None or ncni is not None:
            sf_values["net_income"] = (cni or 0) + (ncni or 0)

    # controlling_ni 보완: 별도재무제표는 비지배지분 없음 → net_income = controlling_ni
    if sf_values.get("controlling_ni") is None:
        ni = sf_values.get("net_income")
        if ni is not None and statement_type == "separate":
            sf_values["controlling_ni"] = ni

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

    with get_session() as session:
        # 교차 연도 이상값 검증 (FY 레코드만)
        dq = 1
        if fiscal_period == "FY":
            dq = _validate_cross_year(session, corp_code, statement_type, sf_values)

        # 모든 _SF_COLS 컬럼을 항상 포함 (sf_values에 없으면 None → 기존 잘못된 값 덮어씌움)
        # _DERIVED_COLS (ebitda, fcf, net_debt)는 _ALL_MAP에 없어 _SF_COLS에 미포함 →
        # 명시적으로 추가해야 파생 지표가 DB에 저장됨
        # shares_out: stock_prices에서 period_end 기준 30일 내 최근 값 조회
        shares_out = None
        if period_end:
            from sqlalchemy import text as _text
            from datetime import timedelta
            row_so = session.execute(_text("""
                SELECT shares_out FROM stock_prices
                WHERE stock_code = (
                    SELECT stock_code FROM corporations WHERE corp_code = :cc
                )
                  AND shares_out IS NOT NULL
                  AND trade_date BETWEEN :d1 AND :d2
                ORDER BY trade_date DESC LIMIT 1
            """), {
                "cc": corp_code,
                "d1": period_end - timedelta(days=30),
                "d2": period_end,
            }).fetchone()
            if row_so:
                shares_out = row_so[0]

        record = {
            "corp_code":      corp_code,
            "fiscal_year":    fiscal_year,
            "fiscal_period":  fiscal_period,
            "statement_type": statement_type,
            "version":        1,
            "period_end":     period_end,
            "is_ifrs":        is_ifrs,
            "rcept_no":       rcept_no,
            "data_quality":   dq,
            "calculated_at":  datetime.utcnow(),
            # 표준화 컬럼 (_ALL_MAP에서 파생된 것들)
            **{col: sf_values.get(col) for col in _SF_COLS},
            # 파생 지표 컬럼 (_ALL_MAP에 없지만 계산되어 sf_values에 담긴 것들)
            "ebitda":      sf_values.get("ebitda"),
            "fcf":         sf_values.get("fcf"),
            "net_debt":    sf_values.get("net_debt"),
            "shares_out":  shares_out,
        }

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
