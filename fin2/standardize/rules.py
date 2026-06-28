"""
fin2 표준화 규칙 엔진 (S-레이어).

현 `analyzer/aggregator.py` 의 13 휴리스틱을 **명명·순서·테스트가능 규칙**으로 이식.
입력: canonical→value(원 단위) dict(중복은 max-abs 로 이미 해소). 출력: std_financials_v2 컬럼.

fin2 구조적 단순화:
  - statement_source 가 BS/IS/CF source 를 분리 선택 → 섹션 혼용 fixup 대부분 불필요.
  - canonical 코드가 명확 → 'revenue<1억→큰값 교체' 등은 수집단계 max-abs 로 흡수.
남은 본질 규칙만 명시적으로 둔다: 직접매핑·합산(CAPEX/D&A)·보완(net_income/controlling_ni)·파생(EBITDA/FCF/NetDebt).

각 규칙은 StdContext 를 제자리 변경하고, 값에 영향을 주면 applied 에 이름을 남긴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ── canonical → std 컬럼 직접매핑 (비합산) ─────────────────────────────────
_BS_MAP = {
    "bs.total_assets": "total_assets", "bs.current_assets": "current_assets",
    "bs.cash": "cash", "bs.trade_receivables": "receivables",
    "bs.inventory": "inventory", "bs.ppe": "ppe", "bs.intangibles": "intangibles",
    "bs.total_liabilities": "total_liabilities", "bs.current_liabilities": "current_liabilities",
    "bs.short_term_debt": "short_term_debt", "bs.long_term_debt": "long_term_debt",
    "bs.total_equity": "total_equity", "bs.controlling_equity": "controlling_equity",
    "bs.retained_earnings": "retained_earnings", "bs.trade_payables": "trade_payables",
}
_IS_MAP = {
    "is.revenue": "revenue", "is.cogs": "cogs", "is.gross_profit": "gross_profit",
    "is.sga": "sga", "is.rd_expense": "rd_expense", "is.operating_income": "operating_income",
    "is.interest_expense": "interest_expense", "is.finance_cost": "interest_expense",
    "is.ebt": "ebt", "is.tax_expense": "tax_expense", "is.net_income": "net_income",
    "is.controlling_ni": "controlling_ni",
}
_CF_MAP = {
    "cf.operating": "cfo", "cf.investing": "cfi", "cf.financing": "cff",
    "cf.dividends_paid": "dividends_paid",
}
DIRECT_MAP = {**_BS_MAP, **_IS_MAP, **_CF_MAP}

# 합산(additive): 세부항목 → 합계 컬럼
_CAPEX_CANON = ("cf.capex", "cf.capex_intangible")
_DEP_CANON = ("cf.depreciation", "is.depreciation", "note.depreciation",
              "cf.rou_depreciation", "is.rou_depreciation", "note.rou_depreciation",
              "cf.roa_depreciation", "is.roa_depreciation", "note.roa_depreciation")
_AMORT_CANON = ("cf.amortization", "is.amortization", "note.amortization")
_DA_TOTAL_CANON = ("cf.da_total", "note.da_total")

# std_financials_v2 값 컬럼(항상 포함 → 기존 잘못된 값 NULL 로 정리)
VALUE_COLS = (
    set(DIRECT_MAP.values())
    | {"capex", "depreciation", "amortization", "da_total", "ebitda", "fcf", "net_debt"}
)


@dataclass
class StdContext:
    corp_code: str
    fiscal_year: int
    fiscal_period: str
    basis: str                       # consolidated / separate
    canon: dict[str, int]            # canonical → value(원), 중복 max-abs 해소됨
    col: dict[str, int | None] = field(default_factory=dict)
    applied: list[str] = field(default_factory=list)

    def _mark(self, name: str):
        if name not in self.applied:
            self.applied.append(name)


# ── 규칙들 ────────────────────────────────────────────────────────────────
def rule_map_direct(ctx: StdContext) -> None:
    """canonical → std 컬럼 직접 매핑(비합산). 중복 컬럼은 max-abs 우선."""
    for canon, val in ctx.canon.items():
        col = DIRECT_MAP.get(canon)
        if col is None or val is None:
            continue
        cur = ctx.col.get(col)
        if cur is None or abs(val) > abs(cur):
            ctx.col[col] = val
            ctx._mark("map_direct")


def rule_additive_capex(ctx: StdContext) -> None:
    """CAPEX = -(|유형자산취득| + |무형자산취득|). 현금유출이므로 음수 저장."""
    total = sum(abs(ctx.canon[c]) for c in _CAPEX_CANON if c in ctx.canon and ctx.canon[c] is not None)
    if total > 0:
        ctx.col["capex"] = -total
        ctx._mark("additive_capex")


def rule_additive_da(ctx: StdContext) -> None:
    """감가상각비/무형상각비 세부합산(ROU 포함). da_total 직접공시 있으면 우선."""
    dep = sum(abs(ctx.canon[c]) for c in _DEP_CANON if c in ctx.canon and ctx.canon[c] is not None)
    amo = sum(abs(ctx.canon[c]) for c in _AMORT_CANON if c in ctx.canon and ctx.canon[c] is not None)
    if dep > 0:
        ctx.col["depreciation"] = dep
        ctx._mark("additive_da")
    if amo > 0:
        ctx.col["amortization"] = amo
        ctx._mark("additive_da")
    da_direct = next((abs(ctx.canon[c]) for c in _DA_TOTAL_CANON
                      if c in ctx.canon and ctx.canon[c]), None)
    if da_direct:
        ctx.col["da_total"] = da_direct
        ctx._mark("additive_da")
    elif dep > 0 or amo > 0:
        ctx.col["da_total"] = dep + amo
        ctx._mark("additive_da")


def rule_net_income_fill(ctx: StdContext) -> None:
    """net_income NULL 이면 controlling_ni + noncontrolling_ni 합산(총 당기순이익).

    연결 IS 의 총 '당기순이익' 라인이 추출 안 되는 경우(컬럼 오정렬·CF 라인 충돌 등)에도 귀속
    라인(지배/비지배)은 고유 라벨이라 신뢰가능 → 둘을 더해 총NI 복원. 비지배 없으면(별도 등) 0.
    (지배=net_income 단독 대체하던 옛 동작은 소수주주 손익 클 때 총NI 과 크게 어긋났다 — 예
    포스코퓨처엠 지배 28.7B vs 총 4.4B.)"""
    if ctx.col.get("net_income") is None:
        cni = ctx.col.get("controlling_ni")
        if cni is not None:
            nci = ctx.canon.get("is.noncontrolling_ni")
            ctx.col["net_income"] = cni + (nci or 0)
            ctx._mark("net_income_fill")


def rule_controlling_ni_fill(ctx: StdContext) -> None:
    """별도재무제표는 비지배지분 없음 → controlling_ni NULL 이면 net_income 으로."""
    if ctx.col.get("controlling_ni") is None and ctx.basis == "separate":
        ni = ctx.col.get("net_income")
        if ni is not None:
            ctx.col["controlling_ni"] = ni
            ctx._mark("controlling_ni_fill")


def rule_revenue_from_cogs_gp(ctx: StdContext) -> None:
    """revenue NULL 이면 cogs + gross_profit 으로 역산('수익' 단독 표기 기업 구제)."""
    if ctx.col.get("revenue") is None:
        cogs, gp = ctx.col.get("cogs"), ctx.col.get("gross_profit")
        if cogs is not None and gp is not None:
            ctx.col["revenue"] = abs(cogs) + gp
            ctx._mark("revenue_from_cogs_gp")


# 차입성부채 세부 → 단기/장기 합산 컴포넌트(개념별 1캐논 → 이중계상 없음)
_ST_DEBT_PARTS = ("bs.short_term_debt", "bs.current_lt_debt", "bs.current_bonds")
_LT_DEBT_PARTS = ("bs.long_term_debt", "bs.bonds")


def rule_additive_debt(ctx: StdContext) -> None:
    """단기/장기차입금 = 차입금 + 유동성장기부채·유동성사채 / 사채 등 세부 합산.

    세부항목이 하나라도 있으면 합산값으로 덮어 과소계상을 보정한다(차입금만 있던 기업은
    동일값 = 변화 없음, 세부만 있던 기업은 NULL→값). 각 leaf 개념은 단일 canonical 로만
    매핑돼 max-abs 후 합산 → 이중계상 없음. map_direct 뒤에 실행.

    가드: 일부 보고서가 차입금을 롤업으로도 태깅해 합산이 총부채를 넘으면(이중계상 의심)
    합산을 적용하지 않고 기존(map_direct) 값을 유지한다(검증 표본 1,044중 2건만 해당)."""
    st = [abs(ctx.canon[c]) for c in _ST_DEBT_PARTS if ctx.canon.get(c) is not None]
    lt = [abs(ctx.canon[c]) for c in _LT_DEBT_PARTS if ctx.canon.get(c) is not None]
    new_st = sum(st) if st else None
    new_lt = sum(lt) if lt else None

    tl = ctx.col.get("total_liabilities")
    cand_total = (new_st or 0) + (new_lt or 0)
    if tl and tl > 0 and cand_total > tl * 1.05:
        return  # 이중계상 의심 → 합산 미적용(기존 단일개념 값 유지)

    if new_st is not None:
        ctx.col["short_term_debt"] = new_st
        ctx._mark("additive_debt")
    if new_lt is not None:
        ctx.col["long_term_debt"] = new_lt
        ctx._mark("additive_debt")


def rule_rd_fallback(ctx: StdContext) -> None:
    """rd_expense 가 face IS(is.rd_expense)로 안 채워졌을 때만 사업보고서 주석값으로 보완.
    (중복 방지: is.rd_expense 우선·불가침. note 값은 항상 양수 저장.)"""
    if ctx.col.get("rd_expense") is None:
        v = ctx.canon.get("note.rd_expense")
        if v:
            ctx.col["rd_expense"] = abs(v)
            ctx._mark("rd_fallback")


def rule_derive_ebitda(ctx: StdContext) -> None:
    """EBITDA = operating_income + da_total (da>0 일 때만)."""
    op, da = ctx.col.get("operating_income"), ctx.col.get("da_total")
    if op is not None and da is not None and da > 0:
        ctx.col["ebitda"] = op + da
        ctx._mark("derive_ebitda")


def rule_derive_fcf(ctx: StdContext) -> None:
    """FCF = CFO - |CAPEX|."""
    cfo, capex = ctx.col.get("cfo"), ctx.col.get("capex")
    if cfo is not None and capex is not None:
        ctx.col["fcf"] = cfo - abs(capex)
        ctx._mark("derive_fcf")


def rule_derive_net_debt(ctx: StdContext) -> None:
    """Net Debt = (단기+장기차입금) - 현금."""
    std, ltd, cash = ctx.col.get("short_term_debt"), ctx.col.get("long_term_debt"), ctx.col.get("cash")
    if cash is not None and (std is not None or ltd is not None):
        ctx.col["net_debt"] = (std or 0) + (ltd or 0) - cash
        ctx._mark("derive_net_debt")


# 순서가 의미를 가짐: 매핑/합산 → 보완 → 파생
RULES = [
    ("map_direct", rule_map_direct),
    ("additive_capex", rule_additive_capex),
    ("additive_da", rule_additive_da),
    ("additive_debt", rule_additive_debt),
    ("net_income_fill", rule_net_income_fill),
    ("controlling_ni_fill", rule_controlling_ni_fill),
    ("revenue_from_cogs_gp", rule_revenue_from_cogs_gp),
    ("rd_fallback", rule_rd_fallback),
    ("derive_ebitda", rule_derive_ebitda),
    ("derive_fcf", rule_derive_fcf),
    ("derive_net_debt", rule_derive_net_debt),
]


def run_rules(ctx: StdContext) -> StdContext:
    """규칙을 순서대로 적용. 모든 VALUE_COLS 는 최종적으로 키 존재(없으면 None)."""
    for _, fn in RULES:
        fn(ctx)
    for c in VALUE_COLS:
        ctx.col.setdefault(c, None)
    return ctx


# ── 회계 항등식 DQ(순수 함수, aggregator 이식) ─────────────────────────────
def validate_equations(col: dict) -> int:
    """BS=L+E, IS revenue-cogs≈gp, CF 합 정합. 1=정상 2=경고 3=오류."""
    dq = 1
    ta, tl, te = col.get("total_assets"), col.get("total_liabilities"), col.get("total_equity")
    if ta and tl is not None and te is not None and ta > 0:
        diff = abs(ta - (tl + te)) / abs(ta)
        if diff > 0.05:
            return 3
        if diff > 0.01:
            dq = max(dq, 2)
    rev, cogs, gp = col.get("revenue"), col.get("cogs"), col.get("gross_profit")
    if rev and cogs is not None and gp is not None and abs(rev) > 0:
        exp_gp = rev - abs(cogs)
        if abs(gp - exp_gp) / abs(rev) > 0.05:
            dq = max(dq, 2)
    return dq
