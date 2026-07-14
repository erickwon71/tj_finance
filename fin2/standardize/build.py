"""
fin2 S-레이어 조립: statement_source 선택 → fact_v2 수집 → 규칙엔진 → std_financials_v2.

(corp, fy, period, basis) 마다:
  1) statement_source 에서 BS/IS/CF source filing 조회.
  2) 각 statement source 에서 해당 접두어 canonical 의 col0 값 수집(중복 max-abs).
     + D&A 보조: 선택 source 들의 note./is./cf. 감가상각 canonical 합산용 수집.
  3) rules.run_rules 로 std 컬럼 산출.
  4) period_end 추정 · shares_out 조회 · DQ(항등식+교차연도) · std_financials_v2 upsert.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from loguru import logger
from sqlalchemy import text, bindparam
from sqlalchemy.dialects.postgresql import insert

from collector.models import StdFinancialV2
from fin2.standardize.rules import (
    StdContext, run_rules, validate_equations, VALUE_COLS,
    _DEP_CANON, _AMORT_CANON, _DA_TOTAL_CANON,
)

_PREFIX = {"BS": "bs.", "IS": "is.", "CF": "cf."}
_FP_MONTH_DAY = {"FY": (12, 31), "H1": (6, 30), "Q1": (3, 31), "Q3": (9, 30), "Q2": (6, 30), "Q4": (12, 31)}
# 실제 재무제표 행이면 최소 하나는 있어야 하는 BS/IS 핵심 헤드라인(전무=빈/phantom 행).
_HEADLINE_COLS = ("total_assets", "total_equity", "current_assets",
                  "revenue", "net_income", "operating_income", "gross_profit")
# D&A 보조 + R&D 주석(note.rd_expense): build 단계에서 union source 들로부터 수집 →
# rules 의 rule_additive_da / rule_rd_fallback 가 조립.
_DA_SUPP = set(_DEP_CANON) | set(_AMORT_CANON) | set(_DA_TOTAL_CANON) | {"note.rd_expense"}


def _collect(session, basis: str, sources: dict[str, str],
             fiscal_period: str | None = None) -> dict[str, int]:
    """
    선택 source 들에서 canonical→value(원) 수집.

    중복 셀 해소:
      - 기본: max-abs(중복 컬럼은 절대값 큰 쪽).
      - **반기/3분기(H1/Q3) flow(IS/CF)**: Track A 보고서는 같은 acode 에 누적(YTD)·3개월 셀이
        둘 다 col_index=0 으로 존재한다. std_v2 는 누적값을 저장해야 하므로 max-abs 가 아니라
        **누적 셀(is_cumulative)을 권위**로 채택한다(누적 셀이 없을 때만 3개월로 폴백).
        (max-abs 는 Q1 세액공제 등으로 3개월 절대값이 누적을 넘으면 오선택 — tax_expense 등.)
        BS(instant)·FY·Q1 은 영향 없음.
    """
    interim = fiscal_period in ("H1", "Q3")
    canon: dict[str, int] = {}
    cum_locked: set[str] = set()  # interim flow 에서 누적 셀로 확정된 canonical

    def _merge(c, v, is_cum):
        if v is None:
            return
        if interim and (c.startswith("is.") or c.startswith("cf.")):
            if is_cum:
                if c not in cum_locked or abs(v) > abs(canon[c]):
                    canon[c] = v
                    cum_locked.add(c)
            elif c not in cum_locked:  # 3개월 폴백(누적 미확정인 경우만)
                if c not in canon or abs(v) > abs(canon[c]):
                    canon[c] = v
        else:
            if c not in canon or abs(v) > abs(canon[c]):
                canon[c] = v

    for stmt, rcept in sources.items():
        rows = session.execute(text("""
            SELECT canonical_account, amount_won, COALESCE(is_cumulative, false) AS is_cum
            FROM fact_v2
            WHERE rcept_no = :r AND basis = :b AND col_index = 0
              AND NOT is_dimensional AND canonical_account LIKE :p
        """), {"r": rcept, "b": basis, "p": _PREFIX[stmt] + "%"}).fetchall()
        for c, v, is_cum in rows:
            _merge(c, v, is_cum)

    # D&A 보조: note./is./cf. 감가상각 — 선택 source 들의 union 에서
    union = list({r for r in sources.values()})
    if union:
        rows = session.execute(text("""
            SELECT canonical_account, amount_won, COALESCE(is_cumulative, false) AS is_cum
            FROM fact_v2
            WHERE rcept_no = ANY(:rs) AND basis = :b AND col_index = 0
              AND NOT is_dimensional AND canonical_account = ANY(:cs)
        """), {"rs": union, "b": basis, "cs": list(_DA_SUPP)}).fetchall()
        for c, v, is_cum in rows:
            _merge(c, v, is_cum)

    # 영업이익 오선택 교정: operating_income 이 net_income 과 원 단위 정확 일치하면 Track B 가
    # 순이익 라인을 is.operating_income canonical 로 오매핑 + max-abs 로 그 값을 오선택한 신호다
    # (정상적으로 영업이익==순이익 이 원단위까지 같을 확률은 사실상 0). 순이익과 다른 비영(非0)
    # 영업이익 후보가 있으면 그중 max-abs 를 채택한다. FY/Q1(비interim) 에만 적용(interim 은
    # 누적/3개월 구분이 있어 별도) — 후보가 없으면 그대로 두고 DQ/어서션이 잡도록 남긴다.
    op, ni = canon.get("is.operating_income"), canon.get("is.net_income")
    if op is not None and ni is not None and op == ni:
        # interim(H1/Q3)은 누적셀만 후보로(3개월셀 오선택 방지). FY/Q1 은 전체 col0 후보.
        cum_filter = "AND COALESCE(is_cumulative, false)" if interim else ""
        alt = session.execute(text(f"""
            SELECT amount_won FROM fact_v2
            WHERE rcept_no = ANY(:rs) AND basis = :b AND col_index = 0
              AND NOT is_dimensional AND canonical_account = 'is.operating_income'
              AND amount_won IS NOT NULL AND amount_won <> :ni AND amount_won <> 0
              {cum_filter}
        """), {"rs": list({r for r in sources.values()}), "b": basis, "ni": ni}).fetchall()
        cands = [r[0] for r in alt]
        if cands:
            canon["is.operating_income"] = max(cands, key=abs)

    # 지배주주 귀속 순이익 총포괄 오염 교정: Track B(텍스트) 보고서는 손익계산서의
    # '지배기업 소유주 귀속 당기순이익'과 포괄손익계산서의 '지배기업 소유주 귀속 총포괄손익'을
    # 회사마다 '지배기업소유주지분' 같은 동일 축약 라벨로 표기해 둘 다 is.controlling_ni 로
    # 매핑된다(account_maps/is_accounts.py alias). max-abs 는 OCI 를 포함한 총포괄분(더 큼)을
    # 오선택 → controlling_ni > net_income 항등식 위반(삼성전자 2023: 17.85조 채택, 정답 14.47조).
    # 회계 항등식 controlling_ni + noncontrolling_ni = net_income 을 이용해, 후보가 여럿일 때
    # (net_income - noncontrolling_ni)=기대 지배분에 가장 가까운 값을 채택한다. 후보가 하나뿐인
    # 기업(정당하게 이 라벨로만 순이익 귀속분을 보고)은 그대로 유지되어 안전.
    cni, ni2 = canon.get("is.controlling_ni"), canon.get("is.net_income")
    if cni is not None and ni2 is not None:
        nci = canon.get("is.noncontrolling_ni") or 0
        expected = ni2 - nci
        # 현재 선택값이 기대 지배분에서 유의미하게 벗어나면(총포괄 오염 의심) 후보 재선택.
        if abs(cni - expected) > abs(expected) * 0.02 + 1_000_000:
            cum_filter = "AND COALESCE(is_cumulative, false)" if interim else ""
            alt = session.execute(text(f"""
                SELECT DISTINCT amount_won FROM fact_v2
                WHERE rcept_no = ANY(:rs) AND basis = :b AND col_index = 0
                  AND NOT is_dimensional AND canonical_account = 'is.controlling_ni'
                  AND amount_won IS NOT NULL
                  {cum_filter}
            """), {"rs": list({r for r in sources.values()}), "b": basis}).fetchall()
            cands = [r[0] for r in alt]
            if cands:
                canon["is.controlling_ni"] = min(cands, key=lambda x: abs(x - expected))
    return canon


def _period_end(session, corp_code: str, fiscal_year: int, fiscal_period: str,
                rcept: str | None = None) -> date | None:
    """period_end. 우선 source filing 의 period_end_date(보고 (YYYY.MM) 말일, PRD 01a)를 쓴다
    — 결산월 변경·stub 에서도 정확. 없으면 비12월 결산은 corporations.fiscal_month 로 FY 말일 보정(폴백)."""
    if rcept:
        pe = session.execute(text(
            "SELECT period_end_date FROM filings WHERE rcept_no=:r"), {"r": rcept}).scalar()
        if pe:
            return pe
    md = _FP_MONTH_DAY.get(fiscal_period, (12, 31))
    try:
        if fiscal_period == "FY":
            fm = session.execute(text(
                "SELECT fiscal_month FROM corporations WHERE corp_code=:c"
            ), {"c": corp_code}).scalar() or 12
            import calendar
            last = calendar.monthrange(fiscal_year, fm)[1]
            return date(fiscal_year, fm, last)
        return date(fiscal_year, md[0], md[1])
    except Exception:
        return None


def _future_guard(dq: int, period_end) -> int:
    """미래 period_end(아직 끝나지 않은 기간)= 실제 데이터 불가 → DQ3 격리(소비계층 배제).
    합성/시드나 기간 오라벨로 period_end 가 오늘 이후인 행 방어."""
    return 3 if (period_end is not None and period_end > date.today()) else dq


def _shares_out(session, corp_code: str, period_end: date | None) -> int | None:
    if not period_end:
        return None
    row = session.execute(text("""
        SELECT shares_out FROM stock_prices
        WHERE stock_code = (SELECT stock_code FROM corporations WHERE corp_code = :cc)
          AND shares_out IS NOT NULL
          AND trade_date BETWEEN :d1 AND :d2
        ORDER BY ABS(trade_date - :target) ASC LIMIT 1
    """), {"cc": corp_code, "d1": period_end - timedelta(days=30),
           "d2": period_end + timedelta(days=7), "target": period_end}).fetchone()
    return row[0] if row else None


def _dq_cross_year(session, corp_code: str, basis: str, col: dict) -> int:
    """교차연도 이상값(중앙값 대비 200x→DQ3, 30x→DQ2). std_financials_v2 기준."""
    dq = 1
    for c, lim_err, lim_warn in (("revenue", 200, 30), ("total_assets", 200, 30)):
        nv = col.get(c)
        if not nv or nv <= 0:
            continue
        med = session.execute(text(f"""
            SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {c})
            FROM std_financials_v2
            WHERE corp_code=:cc AND statement_type=:st AND fiscal_period='FY'
              AND {c}>0 AND version=1 AND data_quality<3
        """), {"cc": corp_code, "st": basis}).scalar()
        if med and med >= 1_000_000_000:
            ratio = nv / med
            if ratio > lim_err or ratio < 1.0 / lim_err:
                return 3
            if ratio > lim_warn or ratio < 1.0 / lim_warn:
                dq = max(dq, 2)
    return dq


def standardize_corp(session, corp_code: str, fiscal_year: int | None = None) -> int:
    """statement_source 를 읽어 std_financials_v2 upsert. 반환=레코드 수."""
    fy_clause = "AND fiscal_year = :fy" if fiscal_year is not None else ""
    params: dict = {"corp": corp_code}
    if fiscal_year is not None:
        params["fy"] = fiscal_year

    # (fy, fp, basis) → {statement: rcept}
    rows = session.execute(text(f"""
        SELECT fiscal_year, fiscal_period, basis, statement, source_rcept_no, has_anchor,
               COALESCE(is_stub, false) AS is_stub
        FROM statement_source
        WHERE corp_code = :corp {fy_clause}
    """), params).fetchall()
    if not rows:
        logger.warning(f"[standardize2] statement_source 없음: corp={corp_code} fy={fiscal_year}")
        return 0

    # (fy, fp, basis, is_stub) → {statement: rcept}. is_stub: 결산월 변경 stub 분리(PRD 01a).
    groups: dict[tuple, dict[str, str]] = {}
    for r in rows:
        key = (r.fiscal_year, r.fiscal_period, r.basis, bool(r.is_stub))
        groups.setdefault(key, {})[r.statement] = r.source_rcept_no

    written = 0
    for (fy, fp, basis, is_stub), sources in groups.items():
        canon = _collect(session, basis, sources, fiscal_period=fp)
        ctx = StdContext(corp_code=corp_code, fiscal_year=fy, fiscal_period=fp, basis=basis, canon=canon)
        run_rules(ctx)

        period_end = _period_end(session, corp_code, fy, fp,
                                 sources.get("BS") or sources.get("IS") or sources.get("CF"))
        shares_out = _shares_out(session, corp_code, period_end)
        # is_ifrs 도출: Track A(xbrl_acode) source 는 ifrs-full_/dart_ 택소노미만 방출 → IFRS.
        # 그 외(Track B 텍스트)는 회계연도로 판정(K-IFRS 상장사 의무화 = FY2011~).
        is_ifrs = _derive_is_ifrs(session, sources, fy)

        dq = max(validate_equations(ctx.col),
                 _dq_cross_year(session, corp_code, basis, ctx.col) if fp == "FY" else 1)
        dq = _future_guard(dq, period_end)

        # ★ 헤드라인(BS/IS 핵심) 전무 행은 생성 안 함: 단일basis 기업의 반대basis phantom(stray CF
        # 만 존재)·추출 실패 stale 행 = 데이터 없는 빈 행. std_v2 에 두면 감사 pending 만 늘고 무용
        # (시각화도 불가). 기존에 있으면 삭제(재추출 후 orphan 정리). 비교/K-GAAP 폴백은 별도패스라 무영향.
        if all(ctx.col.get(c) is None for c in _HEADLINE_COLS):
            session.execute(text("""DELETE FROM std_financials_v2 WHERE corp_code=:c AND fiscal_year=:y
                AND fiscal_period=:p AND statement_type=:b AND version=1 AND is_stub=:s
                AND NOT COALESCE(is_discrete,false)"""),
                {"c": corp_code, "y": fy, "p": fp, "b": basis, "s": is_stub})
            continue

        record = {
            "corp_code": corp_code, "fiscal_year": fy, "fiscal_period": fp,
            "statement_type": basis, "version": 1, "is_stub": is_stub,
            "period_end": period_end, "is_ifrs": is_ifrs,
            "data_quality": dq,
            "bs_rcept": sources.get("BS"), "is_rcept": sources.get("IS"), "cf_rcept": sources.get("CF"),
            "applied_rules": ctx.applied, "shares_out": shares_out,
            "calculated_at": datetime.utcnow(),
            **{c: ctx.col.get(c) for c in VALUE_COLS},
        }
        stmt = insert(StdFinancialV2).values(record)
        update_cols = {k: stmt.excluded[k] for k in record if k not in
                       ("corp_code", "fiscal_year", "fiscal_period", "statement_type", "version", "is_stub")}
        stmt = stmt.on_conflict_do_update(constraint="uq_std_v2", set_=update_cols)
        session.execute(stmt)
        written += 1

    logger.info(f"[standardize2] corp={corp_code} fy={fiscal_year or 'all'} — std_v2 {written}레코드")
    return written


def _derive_is_ifrs(session, sources: dict[str, str], fy: int) -> bool:
    """
    std_v2 행의 회계기준(IFRS vs K-GAAP) 도출.

    - Track A(xbrl_acode) source 가 하나라도 있으면 IFRS: 추출기(xbrl.py)는 ifrs-full_/dart_
      표준개념(ACODE)만 방출하고, 구 K-GAAP ACODE 보고서는 Track A 0행이라 Track B 로 가므로
      xbrl_acode fact 존재 ⟺ IFRS 택소노미.
    - 그 외(전부 Track B 텍스트)는 회계연도로 판정: K-IFRS 상장사 의무적용은 FY2011~ 이므로
      fy≥2011 → IFRS, fy≤2010 → K-GAAP. (2009~10 조기채택사는 XBRL 제출 시 위 Track A 로 포착.)
    """
    rcepts = [r for r in {v for v in sources.values()} if r]
    if rcepts:
        row = session.execute(text("""
            SELECT 1 FROM fact_v2
            WHERE rcept_no IN :rs AND source_format = 'xbrl_acode' LIMIT 1
        """).bindparams(bindparam("rs", expanding=True)), {"rs": rcepts}).first()
        if row is not None:
            return True
    return fy >= 2011


_COMP_MARKER = "comparative_fallback"
_KGAAP_MARKER = "kgaap_gap"
# 비교컬럼 폴백 허용 기간. H1/Q3 는 Track B 누적컬럼 정합(text._interim_cumulative_cols,
# 2026-06-13) 후 신뢰가능해져 재포함. FY·Q1 은 단일/연간 컬럼이라 원래부터 안전.
_COMP_PERIODS = ("FY", "Q1", "H1", "Q3")


def standardize_kgaap_gap_corp(session, corp_code: str) -> int:
    """
    K-GAAP(pre-IFRS) 갭 채우기: K-GAAP 자기보고서 source 로 std_v2 행을 만들되,
    **기존 std_v2 행이 없는 (corp,fy,period,basis) 키만** 채운다(기존 own/comparative
    불가침). K-GAAP 원본값은 IFRS 재작성 비교컬럼값과 상충하므로, 비교컬럼이 닿지 못한
    구년도(대개 pre-2009)만 보충한다. 파생행: is_ifrs=False + applied_rules='kgaap_gap'
    + DQ≥2. idempotent. 반환=기록 레코드 수.
    """
    existing = {(r.fiscal_year, r.fiscal_period, r.statement_type)
                for r in session.execute(text("""
                    SELECT fiscal_year, fiscal_period, statement_type FROM std_financials_v2
                    WHERE corp_code = :c AND version = 1
                      AND NOT (applied_rules @> :m)
                """), {"c": corp_code, "m": f'["{_KGAAP_MARKER}"]'})}

    rows = session.execute(text("""
        SELECT fiscal_year, fiscal_period, basis, statement, source_rcept_no
        FROM statement_source WHERE corp_code = :corp
          AND NOT COALESCE(is_stub, false)
    """), {"corp": corp_code}).fetchall()
    groups: dict[tuple, dict[str, str]] = {}
    for r in rows:
        groups.setdefault((r.fiscal_year, r.fiscal_period, r.basis), {})[r.statement] = r.source_rcept_no

    written = 0
    for (fy, fp, basis), sources in groups.items():
        if (fy, fp, basis) in existing:
            continue  # 기존 행 불가침(own/comparative 우선)
        canon = _collect(session, basis, sources, fiscal_period=fp)
        if not (canon.get("is.revenue") or canon.get("bs.total_assets")):
            continue
        ctx = StdContext(corp_code=corp_code, fiscal_year=fy, fiscal_period=fp, basis=basis, canon=canon)
        run_rules(ctx)
        period_end = _period_end(session, corp_code, fy, fp,
                                 sources.get("BS") or sources.get("IS") or sources.get("CF"))
        shares_out = _shares_out(session, corp_code, period_end)
        dq = max(validate_equations(ctx.col),
                 _dq_cross_year(session, corp_code, basis, ctx.col) if fp == "FY" else 1, 2)
        dq = _future_guard(dq, period_end)
        record = {
            "corp_code": corp_code, "fiscal_year": fy, "fiscal_period": fp,
            "statement_type": basis, "version": 1, "is_stub": False,
            "period_end": period_end, "is_ifrs": False, "data_quality": dq,
            "bs_rcept": sources.get("BS"), "is_rcept": sources.get("IS"), "cf_rcept": sources.get("CF"),
            "applied_rules": list(ctx.applied) + [_KGAAP_MARKER],
            "shares_out": shares_out, "calculated_at": datetime.utcnow(),
            **{c: ctx.col.get(c) for c in VALUE_COLS},
        }
        stmt = insert(StdFinancialV2).values(record)
        update_cols = {k: stmt.excluded[k] for k in record if k not in
                       ("corp_code", "fiscal_year", "fiscal_period", "statement_type", "version", "is_stub")}
        stmt = stmt.on_conflict_do_update(constraint="uq_std_v2", set_=update_cols)
        session.execute(stmt)
        written += 1

    logger.info(f"[kgaap-gap] corp={corp_code} — K-GAAP 갭 std_v2 {written}레코드")
    return written


def _collect_comparative(session, basis: str, sources: dict[str, tuple]) -> dict[str, int]:
    """비교컬럼 수집. sources: {statement: (rcept, col_index, cfy)}.
    해당 source 의 col_index(1=전기/2=전전기)·context_fiscal_year=cfy 셀에서 canonical→value."""
    canon: dict[str, int] = {}

    def _merge(c, v):
        if v is None:
            return
        if c not in canon or abs(v) > abs(canon[c]):
            canon[c] = v

    for stmt, (rcept, col, cfy) in sources.items():
        rows = session.execute(text("""
            SELECT canonical_account, amount_won FROM fact_v2
            WHERE rcept_no = :r AND basis = :b AND col_index = :ci
              AND context_fiscal_year = :cfy AND NOT is_dimensional
              AND (canonical_account LIKE :p OR canonical_account = ANY(:da))
        """), {"r": rcept, "b": basis, "ci": col, "cfy": cfy,
               "p": _PREFIX[stmt] + "%", "da": list(_DA_SUPP)}).fetchall()
        for c, v in rows:
            _merge(c, v)

    # 총포괄 오염 교정(비교컬럼 경로) — _collect(line 109~) 와 동일 로직의 이식.
    # 지배주주 귀속 '순이익'과 '총포괄손익'이 동일 축약 라벨로 둘 다 is.controlling_ni 로 매핑돼
    # 위 _merge 의 max-abs 가 총포괄분(OCI 포함, 더 큼)을 오선택하는 것을, 항등식
    # controlling+noncontrolling=net 으로 (net - nci)에 가장 가까운 후보로 재선택한다. 후보가
    # 하나뿐이면 무변경이라 정당 케이스(비지배 음수 등) 안전. 비교컬럼은 col_index=col·
    # context_fiscal_year=cfy 셀로 한정해 후보를 모은다(원 수집 쿼리와 동일 셀 의미).
    cni, ni2 = canon.get("is.controlling_ni"), canon.get("is.net_income")
    if cni is not None and ni2 is not None:
        nci = canon.get("is.noncontrolling_ni") or 0
        expected = ni2 - nci
        if abs(cni - expected) > abs(expected) * 0.02 + 1_000_000:
            cands: list[int] = []
            for stmt, (rcept, col, cfy) in sources.items():
                rows = session.execute(text("""
                    SELECT DISTINCT amount_won FROM fact_v2
                    WHERE rcept_no = :r AND basis = :b AND col_index = :ci
                      AND context_fiscal_year = :cfy AND NOT is_dimensional
                      AND canonical_account = 'is.controlling_ni' AND amount_won IS NOT NULL
                """), {"r": rcept, "b": basis, "ci": col, "cfy": cfy}).fetchall()
                cands += [r[0] for r in rows]
            if cands:
                canon["is.controlling_ni"] = min(cands, key=lambda x: abs(x - expected))
    return canon


def standardize_comparative_corp(session, corp_code: str) -> int:
    """
    비교컬럼 폴백: 자기연도 정기보고서가 없어 std_v2 행이 없는 (corp,fy,period,basis) 키를,
    **나중 보고서의 비교컬럼**(전기=col1/전전기=col2)에서 합성한다.

    source 는 reconcile 가 고른 좋은 보고서(statement_source)의 비교컬럼만 사용 →
    ×1000 버그본·period 불일치 회피(statement_source 는 period 별). statement 별 독립
    선택(BS/IS/CF), col1(전기) 우선. anchor 없으면 스킵. 자기보고서 행은 절대 덮지 않음.
    파생행은 applied_rules 에 'comparative_fallback' + data_quality≥2 로 표시. idempotent.
    반환=기록한 레코드 수.
    """
    # 자기보고서(비-파생) 행이 있는 키 — 폴백 대상에서 제외(자기보고서 우선·불가침)
    own = {(r.fiscal_year, r.fiscal_period, r.statement_type)
           for r in session.execute(text("""
               SELECT fiscal_year, fiscal_period, statement_type FROM std_financials_v2
               WHERE corp_code = :c AND version = 1
                 AND NOT (applied_rules @> :m)
           """), {"c": corp_code, "m": f'["{_COMP_MARKER}"]'})}

    srcs = session.execute(text("""
        SELECT fiscal_year AS fy, fiscal_period AS fp, basis,
               statement AS stmt, source_rcept_no AS rcept
        FROM statement_source WHERE corp_code = :c
          AND NOT COALESCE(is_stub, false)
    """), {"c": corp_code}).fetchall()

    # (cfy, fp, basis) → {stmt: (rcept, col, cfy)} — col1(전기) 우선
    targets: dict[tuple, dict[str, tuple]] = {}
    for s in srcs:
        if s.fp not in _COMP_PERIODS:
            continue  # H1/Q3 비교컬럼은 누적컬럼 혼선으로 제외
        for col, cfy in ((1, s.fy - 1), (2, s.fy - 2)):
            key = (cfy, s.fp, s.basis)
            if key in own:
                continue
            d = targets.setdefault(key, {})
            if s.stmt not in d or col < d[s.stmt][1]:
                d[s.stmt] = (s.rcept, col, cfy)

    written = 0
    for (cfy, fp, basis), sources in targets.items():
        canon = _collect_comparative(session, basis, sources)
        if not (canon.get("is.revenue") or canon.get("bs.total_assets")):
            continue  # anchor 없으면 합성하지 않음

        ctx = StdContext(corp_code=corp_code, fiscal_year=cfy, fiscal_period=fp, basis=basis, canon=canon)
        run_rules(ctx)

        period_end = _period_end(session, corp_code, cfy, fp)
        shares_out = _shares_out(session, corp_code, period_end)
        dq = max(validate_equations(ctx.col),
                 _dq_cross_year(session, corp_code, basis, ctx.col) if fp == "FY" else 1,
                 2)  # 비교컬럼 파생은 2차 출처 → 최소 DQ2(검토 등급)
        dq = _future_guard(dq, period_end)

        record = {
            "corp_code": corp_code, "fiscal_year": cfy, "fiscal_period": fp,
            "statement_type": basis, "version": 1, "is_stub": False,
            "period_end": period_end, "is_ifrs": None, "data_quality": dq,
            "bs_rcept": sources.get("BS", (None,))[0],
            "is_rcept": sources.get("IS", (None,))[0],
            "cf_rcept": sources.get("CF", (None,))[0],
            "applied_rules": list(ctx.applied) + [_COMP_MARKER],
            "shares_out": shares_out, "calculated_at": datetime.utcnow(),
            **{c: ctx.col.get(c) for c in VALUE_COLS},
        }
        stmt = insert(StdFinancialV2).values(record)
        update_cols = {k: stmt.excluded[k] for k in record if k not in
                       ("corp_code", "fiscal_year", "fiscal_period", "statement_type", "version", "is_stub")}
        stmt = stmt.on_conflict_do_update(constraint="uq_std_v2", set_=update_cols)
        session.execute(stmt)
        written += 1

    logger.info(f"[comparative] corp={corp_code} — 비교컬럼 폴백 std_v2 {written}레코드")
    return written
