"""
fin2 S-레이어 조립: statement_source 선택 → fact_v2 수집 → 규칙엔진 → std_financials_v2.

(corp, fy, period, basis) 마다:
  1) statement_source 에서 BS/IS/CF source filing 조회.
  2) 각 statement source 에서 해당 접두어 canonical 의 col0 값 수집
     (후보 다중 시 **값이 갈리면 보류** + value_lineage 기록 — 고르지 않는다).
     + D&A 보조: 선택 source 들의 note./is./cf. 감가상각 canonical 합산용 수집.
  3) rules.run_rules 로 std 컬럼 산출.
  4) period_end 추정 · shares_out 조회 · DQ(항등식+교차연도) · std_financials_v2 upsert.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime

from loguru import logger
from sqlalchemy import text, bindparam
from sqlalchemy.dialects.postgresql import insert

from collector.models import StdFinancialV2
from fin2.standardize.rules import (
    StdContext, run_rules, validate_equations, VALUE_COLS, CONSUMED_CANON,
    _DEP_CANON, _AMORT_CANON, _DA_TOTAL_CANON,
)

_PREFIX = {"BS": "bs.", "IS": "is.", "CF": "cf."}
# 기간 끝 = **그 기업의 FY 말일에서 N개월 뒤로**. (달력월 하드코딩이 아니라 결산월 상대 — 3월
# 결산사의 H1 은 9/30 이다.) 실측 검증: 결산월 3·6·9월사에서 권위값(filings.period_end_date)과 일치.
_FP_MONTHS_BEFORE_FY_END = {"FY": 0, "Q4": 0, "Q3": 3, "H1": 6, "Q2": 6, "Q1": 9}
# 실제 재무제표 행이면 최소 하나는 있어야 하는 BS/IS 핵심 헤드라인(전무=빈/phantom 행).
_HEADLINE_COLS = ("total_assets", "total_equity", "current_assets",
                  "revenue", "net_income", "operating_income", "gross_profit")
# D&A 보조 + R&D 주석(note.rd_expense): build 단계에서 union source 들로부터 수집 →
# rules 의 rule_additive_da / rule_rd_fallback 가 조립.
_DA_SUPP = set(_DEP_CANON) | set(_AMORT_CANON) | set(_DA_TOTAL_CANON) | {"note.rd_expense"}


# 매핑 근거 우선순위 — 값이 갈릴 때 **더 엄격하게 매핑된 후보를 우선**한다(추측 아님, 기록된
# provenance). exact/normalized(사전 일치) > guard(명시 규칙) > fuzzy(유사도) > 미상(NULL).
# 이로써 base 라벨(예 '매출채권'=exact)이 승급 변형('매출채권및기타유동채권'=normalized)을
# 이겨 승급이 공존 기업을 회귀시키지 않는다. 실측: 재추출 전 fact_v2 는 stage 전부 NULL 이라
# 이 우선순위가 무효(전부 동급) → 기존 conflict-hold 동작. 재추출 후 활성화(forward-compatible).
_STAGE_RANK = {"exact": 3, "normalized": 2, "guard": 2, "fuzzy": 1, None: 0}


def _resolve(cands: dict[str, list[dict]]) -> tuple[dict[str, int], dict[str, list[dict]]]:
    """후보 dict → (확정값, lineage). 값이 갈리면 **더 엄격한 매핑을 우선**, 그래도 갈리면 보류.

    ★ 왜 max-abs 를 없앴나
    구버전은 후보가 여럿이면 **절대값이 큰 쪽**을 집었다. 근거는 "단위가 온전한 값이 더 크다"
    였는데, 이는 단일 사례(엘브이엠씨 USD/KRW)를 전 충돌에 일반화한 것이고 실제로는
    **원문 단위 오기**(3S ×10⁶·네오크레마 ×10³)가 실재하므로 '큰 쪽=정답'이 성립하지 않는다.
    게다가 진 후보는 **흔적 없이 사라져** 사후에 무엇이 경합했는지 알 수 없었다 — 그래서
    "오염된 것만 골라 삭제"가 불가능했고 전수 재파싱 말고는 길이 없었다.

    ⟹ ① 후보가 하나면 확정. ② 여럿이면 **매핑 근거가 가장 엄격한 것**만 남긴다(exact >
      normalized > fuzzy) — 이건 추측이 아니라 provenance 우선순위다. ③ 최엄격 등급에서도
      값이 갈리면 **적재하지 않고**(결측 > 오염) lineage 에 후보 전체를 기록한다
      (statement_source.lineage 선례). 그 lineage 가 Phase C 패턴루프의 작업목록이다.

    실측(2015+ 199보고서): 충돌은 std_v2 소비 셀의 **0.85%**(보고서의 14.6%)뿐이고,
    대부분 max-abs 가 눈감고 고르던 진짜 애매지점이다 — is.sga 28 · is.revenue 16 · is.cogs 12.
    """
    canon: dict[str, int] = {}
    lineage: dict[str, list[dict]] = {}
    for c, rows in cands.items():
        vals = {r["value"] for r in rows}
        if len(vals) == 1:
            canon[c] = next(iter(vals))
            continue
        # ② 최엄격 매핑등급만 후보로 남긴다(base exact 가 승급 변형 normalized 를 이김).
        best = max(_STAGE_RANK.get(r.get("stage"), 0) for r in rows)
        top = [r for r in rows if _STAGE_RANK.get(r.get("stage"), 0) == best]
        top_vals = {r["value"] for r in top}
        if len(top_vals) == 1:
            canon[c] = next(iter(top_vals))
            continue
        # ③ 최엄격 등급에서도 값이 갈림 → 판정 불가. 값은 비우고, **std_v2 가 실제로 읽는
        # canonical 일 때만** 후보를 기록한다(아무도 안 읽는 계정의 충돌까지 남기면 lineage 가
        # 소음으로 부푼다 — 실측: 안 거르면 bs.other_current_payables 만으로 1,647행).
        if c in CONSUMED_CANON:
            lineage[c] = sorted(
                ({**r, "chosen": False} for r in rows),
                key=lambda r: (r["value"] is None, r["value"]),
            )
    return canon, lineage


def _collect(session, basis: str, sources: dict[str, str],
             fiscal_period: str | None = None) -> tuple[dict[str, int], dict[str, list[dict]]]:
    """
    선택 source 들에서 canonical→value(원) 수집. 반환 (canon, lineage).

    중복 셀 해소:
      - **반기/3분기(H1/Q3) flow(IS/CF)**: Track A 보고서는 같은 acode 에 누적(YTD)·3개월 셀이
        둘 다 col_index=0 으로 존재한다. std_v2 는 누적값을 저장해야 하므로 **누적 셀
        (is_cumulative)만** 후보로 삼는다(누적 셀이 아예 없을 때만 3개월). 이건 추측이 아니라
        std_v2 의 저장 규약이다 — 다만 **누적 셀끼리 값이 갈리면 보류**한다(구버전은 max-abs).
        BS(instant)·FY·Q1 은 영향 없음.
      - 그 외: 후보를 모아 _resolve 가 판정(단일=확정 / 충돌=보류+lineage).
    """
    interim = fiscal_period in ("H1", "Q3")
    # canonical → [{value, rcept, cumulative}] 후보 누적
    cands: dict[str, list[dict]] = {}
    cum_seen: set[str] = set()   # interim flow 에서 누적 셀이 있었던 canonical

    def _add(c, v, is_cum, rcept, stage):
        if v is None:
            return
        flow = interim and (c.startswith("is.") or c.startswith("cf."))
        if flow:
            if is_cum:
                if c not in cum_seen:      # 누적 등장 → 그간의 3개월 후보는 폐기
                    cands.pop(c, None)
                    cum_seen.add(c)
            elif c in cum_seen:
                return                     # 누적이 이미 있으면 3개월은 후보 아님
        cands.setdefault(c, []).append(
            {"value": v, "rcept": rcept, "cumulative": bool(is_cum), "stage": stage})

    for stmt, rcept in sources.items():
        rows = session.execute(text("""
            SELECT canonical_account, amount_won, COALESCE(is_cumulative, false) AS is_cum,
                   mapping_stage
            FROM fact_v2
            WHERE rcept_no = :r AND basis = :b AND col_index = 0
              AND NOT is_dimensional AND canonical_account LIKE :p
        """), {"r": rcept, "b": basis, "p": _PREFIX[stmt] + "%"}).fetchall()
        for c, v, is_cum, stage in rows:
            _add(c, v, is_cum, rcept, stage)

    # D&A 보조: note./is./cf. 감가상각 — 선택 source 들의 union 에서
    union = list({r for r in sources.values()})
    if union:
        rows = session.execute(text("""
            SELECT canonical_account, amount_won, COALESCE(is_cumulative, false) AS is_cum,
                   rcept_no, mapping_stage
            FROM fact_v2
            WHERE rcept_no = ANY(:rs) AND basis = :b AND col_index = 0
              AND NOT is_dimensional AND canonical_account = ANY(:cs)
        """), {"rs": union, "b": basis, "cs": list(_DA_SUPP)}).fetchall()
        for c, v, is_cum, rc, stage in rows:
            _add(c, v, is_cum, rc, stage)

    # ★ 폐지된 사후 재선택 2종(C3/C4/C5) — 되살리지 말 것.
    #
    #  · operating_income 재선택: op==ni 면 오매핑 신호로 보고 **다른 후보 중 max-abs** 채택.
    #  · controlling_ni 재선택: 회계 항등식(controlling+noncontrolling=net)에 비춰
    #    (net-nci)에 **가장 가까운 후보**를 채택.
    #
    # 둘 다 "값을 로직으로 정하는" 행위이고, run_rules **이전**에 돌아 applied_rules 에
    # 기록조차 남지 않았다(§2-A C3~C5). 즉 DB 에서 이 값이 원문인지 코드가 고른 것인지
    # 구분 불가 — 이번 재구축이 없애려는 바로 그 성질이다.
    #
    # 대체: 애초에 후보가 갈리면 **보류**한다(_resolve). 총포괄 오염(삼성전자 2023 17.85조 vs
    # 정답 14.47조)의 근본 원인은 '총포괄 귀속' 라인이 is.controlling_ni 로 매핑되던 것이고,
    # 그건 text.py 의 귀속 섹션 가드(comp_attr)와 account_mapper 의 포괄손익 가드가 **입구에서**
    # 막는다. 그래도 두 값이 남아 갈리면 이제 오염 대신 결측이 된다.
    return _resolve(cands)


def _period_end(session, corp_code: str, fiscal_year: int, fiscal_period: str,
                rcept: str | None = None) -> date | None:
    """period_end. **① 원문 filing 의 period_end_date(권위) → ② 기업 결산월로 도출 → ③ None.**

    ★ 2026-07-17(F6) — '12월 가정' 제거 + 비12월 결산 오산 교정:

    구버전은 filing 이 없으면 `_FP_MONTH_DAY` 로 **H1=6/30 · Q1=3/31 을 하드코딩**하고, FY 는
    `fiscal_month or 12` 로 **결산월을 모르면 12월이라고 가정**했다. 둘 다 틀렸다:

      · 비12월 결산 기업에서 하드코딩은 **실제와 다르다**(실측: 권위값과 비교해 결산월 3월사
        2,116행 중 **1,827행 불일치**, 6월사 1,978중 1,588 불일치). 3월 결산사의 H1 은 6/30 이
        아니라 **9/30** 이다.
      · 결산월 미상인데 12월로 가정하면 그건 데이터가 아니라 추측이다.

    대신 **회사가 신고한 결산월(corporations.fiscal_month)** 과 분기의 정의로 도출한다 —
    FY 말일에서 {FY:0, Q3:3, H1:6, Q1:9}개월 뒤로 물린 달의 말일. 이 규칙은 실측으로 검증했다
    (결산월 3·6·9월사 전 기간에서 권위값과 일치). 결산월이 없으면 **도출하지 않고 None**.

    ①이 99.14%(filings.period_end_date 보유율)를 덮고, ②는 주로 비교컬럼 파생행(rcept 없음,
    31,064행)에 쓰인다.
    """
    if rcept:
        pe = session.execute(text(
            "SELECT period_end_date FROM filings WHERE rcept_no=:r"), {"r": rcept}).scalar()
        if pe:
            return pe

    off = _FP_MONTHS_BEFORE_FY_END.get(fiscal_period)
    if off is None:
        return None
    fm = session.execute(text(
        "SELECT fiscal_month FROM corporations WHERE corp_code=:c"), {"c": corp_code}).scalar()
    if not fm:
        return None      # 결산월 미상 → 추측하지 않는다(구버전은 12월로 가정했다)
    try:
        # FY 말일(fiscal_year, fm)에서 off 개월 뒤로 → 그 달의 말일
        total = fiscal_year * 12 + (fm - 1) - off
        y, m = divmod(total, 12)
        return date(y, m + 1, calendar.monthrange(y, m + 1)[1])
    except Exception:  # noqa: BLE001
        return None


def _future_guard(dq: int, period_end) -> int:
    """미래 period_end(아직 끝나지 않은 기간)= 실제 데이터 불가 → DQ3 격리(소비계층 배제).
    합성/시드나 기간 오라벨로 period_end 가 오늘 이후인 행 방어."""
    return 3 if (period_end is not None and period_end > date.today()) else dq


# ★ C17 폐지(2026-07-17): `_shares_out` — period_end 기준 **−30/+7일 안에서 가장 가까운 거래일**의
# stock_prices.shares_out 을 std_v2 에 적재하던 함수를 제거했다.
#
# 왜: 그 값은 **이 보고서가 말하는 주식수가 아니다.** 시세 테이블의 다른 날짜 스냅샷을 가져와
# 재무제표 행에 붙인 것이고, 붙인 날짜조차 기록하지 않아 사후 검증이 불가능했다. 무상증자·
# 분할·자사주 소각이 기말 근처에 있으면 조용히 틀린다.
#
# 대신: 주식수는 **보고서에서 읽는다**(fin2/extract/shares.py → std_v2.shares_out 백필).
# 여기서는 record 에 shares_out 키를 **아예 넣지 않는다** → ON CONFLICT 갱신 대상에서 빠져
# 기존 보고서 유래 값이 **보존**된다(None 을 넣으면 그 값을 지워버린다).
#
# ⚠ 재구축(Phase C)으로 std_v2 행이 새로 INSERT 되면 shares_out 은 NULL 로 시작한다 →
# **직후 shares 재백필 필수**(계획 §4 Phase C · 핸드오프 §6-1). 놓치면 valuation_daily 의
# PER/PBR/시총이 전부 NULL 이 된다.


def _dq_cross_year(session, corp_code: str, basis: str, col: dict, version: int = 1) -> int:
    """교차연도 이상값(중앙값 대비 200x→DQ3, 30x→DQ2). std_financials_v2 기준.
    중앙값은 **같은 version** 기준(재구축 v2 는 v2 행끼리 비교)."""
    dq = 1
    for c, lim_err, lim_warn in (("revenue", 200, 30), ("total_assets", 200, 30)):
        nv = col.get(c)
        if not nv or nv <= 0:
            continue
        med = session.execute(text(f"""
            SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {c})
            FROM std_financials_v2
            WHERE corp_code=:cc AND statement_type=:st AND fiscal_period='FY'
              AND {c}>0 AND version=:v AND data_quality<3
        """), {"cc": corp_code, "st": basis, "v": version}).scalar()
        if med and med >= 1_000_000_000:
            ratio = nv / med
            if ratio > lim_err or ratio < 1.0 / lim_err:
                return 3
            if ratio > lim_warn or ratio < 1.0 / lim_warn:
                dq = max(dq, 2)
    return dq


def standardize_corp(session, corp_code: str, fiscal_year: int | None = None,
                     version: int = 1) -> int:
    """statement_source 를 읽어 std_financials_v2 upsert. 반환=레코드 수.
    version: 소비계층이 읽는 버전(기본 1). Phase C 재구축은 version=2 로 병행 구축(swap 대상)."""
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
        canon, lineage = _collect(session, basis, sources, fiscal_period=fp)
        ctx = StdContext(corp_code=corp_code, fiscal_year=fy, fiscal_period=fp, basis=basis, canon=canon)
        run_rules(ctx)

        period_end = _period_end(session, corp_code, fy, fp,
                                 sources.get("BS") or sources.get("IS") or sources.get("CF"))
        # is_ifrs: Track A(xbrl_acode) source 가 있으면 IFRS(원문 증거). 없으면 None(연도 추론 폐지).
        is_ifrs = _derive_is_ifrs(session, sources)

        dq = max(validate_equations(ctx.col),
                 _dq_cross_year(session, corp_code, basis, ctx.col, version) if fp == "FY" else 1)
        dq = _future_guard(dq, period_end)

        # ★ 헤드라인(BS/IS 핵심) 전무 행은 생성 안 함: 단일basis 기업의 반대basis phantom(stray CF
        # 만 존재)·추출 실패 stale 행 = 데이터 없는 빈 행. std_v2 에 두면 감사 pending 만 늘고 무용
        # (시각화도 불가). 기존에 있으면 삭제(재추출 후 orphan 정리). 비교/K-GAAP 폴백은 별도패스라 무영향.
        if all(ctx.col.get(c) is None for c in _HEADLINE_COLS):
            session.execute(text("""DELETE FROM std_financials_v2 WHERE corp_code=:c AND fiscal_year=:y
                AND fiscal_period=:p AND statement_type=:b AND version=:v AND is_stub=:s
                AND NOT COALESCE(is_discrete,false)"""),
                {"c": corp_code, "y": fy, "p": fp, "b": basis, "s": is_stub, "v": version})
            continue

        # ★ shares_out 은 **의도적으로 넣지 않는다**(C17): 넣지 않으면 ON CONFLICT 갱신 대상에서
        # 빠져 보고서 유래 값(shares.py)이 보존된다. None 을 넣으면 그 값을 지운다.
        record = {
            "corp_code": corp_code, "fiscal_year": fy, "fiscal_period": fp,
            "statement_type": basis, "version": version, "is_stub": is_stub,
            "period_end": period_end, "is_ifrs": is_ifrs,
            "data_quality": dq,
            "bs_rcept": sources.get("BS"), "is_rcept": sources.get("IS"), "cf_rcept": sources.get("CF"),
            "applied_rules": ctx.applied,
            "value_lineage": lineage or None,
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


def _derive_is_ifrs(session, sources: dict[str, str]) -> bool | None:
    """
    std_v2 행의 회계기준(IFRS vs K-GAAP). **증거가 있을 때만** True, 없으면 None.

    - Track A(xbrl_acode) source 가 하나라도 있으면 IFRS: 추출기(xbrl.py)는 ifrs-full_/dart_
      표준개념(ACODE)만 방출하고, 구 K-GAAP ACODE 보고서는 Track A 0행이라 Track B 로 가므로
      **xbrl_acode fact 존재 ⟺ IFRS 택소노미**(원문에서 읽은 증거).

    ★ 2026-07-17(F7): `return fy >= 2011` **연도 추론을 제거**했다. K-IFRS 상장사 의무적용이
    FY2011~ 인 것은 사실이지만, 그건 **보고서에서 읽은 값이 아니라 연도로 미룬 추정**이고
    (사용자 원칙: "로직으로 값을 정해서 db에 적재하는 것은 없도록 해") 틀릴 여지도 있다
    (비상장 구간·재작성본 등). ⟹ 증거 없으면 **None**.

    소비측 영향 없음: display 는 이미 `curr.get('is_ifrs', True)` 로 NULL 을 IFRS 로 표시하고,
    std_v2 에는 이미 NULL 행이 55,755개 있다(비교컬럼 파생행). 원문에서 회계기준 문구를 읽어
    채우는 것은 Phase C 파서 개선 과제.
    """
    rcepts = [r for r in {v for v in sources.values()} if r]
    if rcepts:
        row = session.execute(text("""
            SELECT 1 FROM fact_v2
            WHERE rcept_no IN :rs AND source_format = 'xbrl_acode' LIMIT 1
        """).bindparams(bindparam("rs", expanding=True)), {"rs": rcepts}).first()
        if row is not None:
            return True
    return None


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
        canon, lineage = _collect(session, basis, sources, fiscal_period=fp)
        if not (canon.get("is.revenue") or canon.get("bs.total_assets")):
            continue
        ctx = StdContext(corp_code=corp_code, fiscal_year=fy, fiscal_period=fp, basis=basis, canon=canon)
        run_rules(ctx)
        period_end = _period_end(session, corp_code, fy, fp,
                                 sources.get("BS") or sources.get("IS") or sources.get("CF"))
        dq = max(validate_equations(ctx.col),
                 _dq_cross_year(session, corp_code, basis, ctx.col) if fp == "FY" else 1, 2)
        dq = _future_guard(dq, period_end)
        record = {
            "corp_code": corp_code, "fiscal_year": fy, "fiscal_period": fp,
            "statement_type": basis, "version": 1, "is_stub": False,
            "period_end": period_end, "is_ifrs": False, "data_quality": dq,
            "bs_rcept": sources.get("BS"), "is_rcept": sources.get("IS"), "cf_rcept": sources.get("CF"),
            "applied_rules": list(ctx.applied) + [_KGAAP_MARKER],
            "value_lineage": lineage or None,
            "calculated_at": datetime.utcnow(),
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


def _collect_comparative(session, basis: str,
                         sources: dict[str, tuple]) -> tuple[dict[str, int], dict[str, list[dict]]]:
    """비교컬럼 수집. sources: {statement: (rcept, col_index, cfy)}. 반환 (canon, lineage).

    해당 source 의 col_index(1=전기/2=전전기)·context_fiscal_year=cfy 셀에서 canonical→value.
    _collect 과 동일하게 **max-abs 채택·항등식 재선택을 폐지**하고 충돌은 보류한다(C6).
    """
    cands: dict[str, list[dict]] = {}
    for stmt, (rcept, col, cfy) in sources.items():
        rows = session.execute(text("""
            SELECT canonical_account, amount_won, mapping_stage FROM fact_v2
            WHERE rcept_no = :r AND basis = :b AND col_index = :ci
              AND context_fiscal_year = :cfy AND NOT is_dimensional
              AND (canonical_account LIKE :p OR canonical_account = ANY(:da))
        """), {"r": rcept, "b": basis, "ci": col, "cfy": cfy,
               "p": _PREFIX[stmt] + "%", "da": list(_DA_SUPP)}).fetchall()
        for c, v, stage in rows:
            if v is not None:
                cands.setdefault(c, []).append(
                    {"value": v, "rcept": rcept, "col_index": col, "stage": stage})
    return _resolve(cands)


def standardize_comparative_corp(session, corp_code: str, version: int = 1) -> int:
    """
    비교컬럼 폴백: 자기연도 정기보고서가 없어 std_v2 행이 없는 (corp,fy,period,basis) 키를,
    **나중 보고서의 비교컬럼**(전기=col1/전전기=col2)에서 합성한다.
    version: 소비계층 버전(기본 1). Phase C 재구축은 version=2.

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
               WHERE corp_code = :c AND version = :v
                 AND NOT (applied_rules @> :m)
           """), {"c": corp_code, "v": version, "m": f'["{_COMP_MARKER}"]'})}

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
        canon, lineage = _collect_comparative(session, basis, sources)
        if not (canon.get("is.revenue") or canon.get("bs.total_assets")):
            continue  # anchor 없으면 합성하지 않음

        ctx = StdContext(corp_code=corp_code, fiscal_year=cfy, fiscal_period=fp, basis=basis, canon=canon)
        run_rules(ctx)

        period_end = _period_end(session, corp_code, cfy, fp)
        dq = max(validate_equations(ctx.col),
                 _dq_cross_year(session, corp_code, basis, ctx.col, version) if fp == "FY" else 1,
                 2)  # 비교컬럼 파생은 2차 출처 → 최소 DQ2(검토 등급)
        dq = _future_guard(dq, period_end)

        record = {
            "corp_code": corp_code, "fiscal_year": cfy, "fiscal_period": fp,
            "statement_type": basis, "version": version, "is_stub": False,
            "period_end": period_end, "is_ifrs": None, "data_quality": dq,
            "bs_rcept": sources.get("BS", (None,))[0],
            "is_rcept": sources.get("IS", (None,))[0],
            "cf_rcept": sources.get("CF", (None,))[0],
            "applied_rules": list(ctx.applied) + [_COMP_MARKER],
            "value_lineage": lineage or None,
            "calculated_at": datetime.utcnow(),
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
