"""
fin2 표준화 규칙 엔진 (S-레이어).

현 `analyzer/aggregator.py` 의 13 휴리스틱을 **명명·순서·테스트가능 규칙**으로 이식.
입력: canonical→value(원 단위) dict(중복 후보는 build._resolve 가 이미 판정 — 충돌은 보류). 출력: std_financials_v2 컬럼.

fin2 구조적 단순화:
  - statement_source 가 BS/IS/CF source 를 분리 선택 → 섹션 혼용 fixup 대부분 불필요.
  - canonical 코드가 명확 → 'revenue<1억→큰값 교체' 같은 값 고르기는 하지 않는다.
    후보가 갈리면 build._resolve 가 **보류**(결측 > 오염, 2026-07-17).
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
    | {"lease_liability", "borrowings_proceeds", "borrowings_repaid"}   # C 합산(2026-07-18)
)

# 차입성부채 세부 → 단기/장기 합산 컴포넌트(개념별 1캐논 → 이중계상 없음)
# 사채유동분은 일반/전환 별도 canonical → 둘 다 단기부채에 합산(구 bs.current_bonds collapse 대체).
_ST_DEBT_PARTS = ("bs.short_term_debt", "bs.current_lt_debt",
                  "bs.current_bonds_plain", "bs.current_bonds_conv")
_LT_DEBT_PARTS = ("bs.long_term_debt", "bs.bonds")

# C 합산(2026-07-18): 유동+비유동 리스부채 → lease_liability, 단기+장기 차입 유입/상환 → 각 합계.
# 서로 다른 항목이라 한 canonical 로 collapse 하면 값충돌(보류)이므로 별도 canonical 로 두고 합산.
_LEASE_PARTS = ("bs.lease_current", "bs.lease_noncurrent")
_BORROW_PROCEEDS_PARTS = ("cf.borrow_proceeds_st", "cf.borrow_proceeds_lt")
_BORROW_REPAID_PARTS = ("cf.borrow_repaid_st", "cf.borrow_repaid_lt")

# ★ std_v2 컬럼에 실제로 닿는 canonical 전체(직접매핑 + 합산/보완/파생 입력).
# build._collect 은 접두어(bs./is./cf.)로 훑기 때문에 **아무도 안 읽는 canonical** 도 딸려온다
# (bs.other_current_payables·cf.ppe_proceeds 등). 그런 것의 충돌까지 value_lineage 에 남기면
# 컬럼만 부풀고 패턴루프의 작업목록이 소음에 묻힌다 → 소비되는 것만 기록한다.
CONSUMED_CANON = (
    set(DIRECT_MAP)
    | set(_CAPEX_CANON) | set(_DEP_CANON) | set(_AMORT_CANON) | set(_DA_TOTAL_CANON)
    | set(_ST_DEBT_PARTS) | set(_LT_DEBT_PARTS)
    | set(_LEASE_PARTS) | set(_BORROW_PROCEEDS_PARTS) | set(_BORROW_REPAID_PARTS)
    | {"note.rd_expense", "is.noncontrolling_ni",
       "is.insurance_revenue", "is.operating_revenue_ins", "is.interest_revenue",
       "bs.deposits", "bs.cash_deposits_combined"}   # 금융사 현금+예치금(rule_cash_with_deposits)
)


@dataclass
class StdContext:
    corp_code: str
    fiscal_year: int
    fiscal_period: str
    basis: str                       # consolidated / separate
    canon: dict[str, int]            # canonical → value(원). 충돌 후보는 이미 보류돼 없음
    col: dict[str, int | None] = field(default_factory=dict)
    applied: list[str] = field(default_factory=list)

    def _mark(self, name: str):
        if name not in self.applied:
            self.applied.append(name)


# ── 규칙들 ────────────────────────────────────────────────────────────────
# 한 std 컬럼에 여러 canonical 이 매핑될 때의 **명시적 우선순위**(앞이 이김).
# 현재 해당하는 컬럼은 interest_expense 뿐이다(그 외 DIRECT_MAP 은 1:1).
#   is.interest_expense(이자비용) = 이 컬럼이 뜻하는 바로 그 개념.
#   is.finance_cost(금융원가)     = 이자비용을 **포함하는 상위 개념**. 회사가 이자비용을 따로
#                                  주지 않을 때만 쓰는 대용치.
_COL_PRIORITY = {
    "interest_expense": ("is.interest_expense", "is.finance_cost"),
}


def rule_map_direct(ctx: StdContext) -> None:
    """canonical → std 컬럼 직접 매핑(비합산).

    ★ 2026-07-17(C7): **max-abs 폐지**. 구버전은 같은 컬럼에 후보가 여럿이면 절대값 큰 쪽을
    집었다. 유일한 다중 컬럼인 interest_expense 에서 이는 **항상 금융원가(상위개념·더 큼)를
    골라** 둘 다 공시한 기업의 이자비용을 체계적으로 과대계상한다는 뜻이다.
    ⟹ 개념 우선순위(_COL_PRIORITY)로 **명시 선택**하고, 대용치를 쓴 경우 표시를 남긴다.
    """
    for col, order in _COL_PRIORITY.items():
        for canon in order:
            v = ctx.canon.get(canon)
            if v is not None:
                ctx.col[col] = v
                ctx._mark("map_direct")
                if canon != order[0]:
                    # 대용치 채택 — 어떤 개념으로 채웠는지 남긴다(정확한 이자비용이 아님).
                    ctx._mark(f"map_direct_proxy:{col}={canon}")
                break

    for canon, val in ctx.canon.items():
        col = DIRECT_MAP.get(canon)
        if col is None or val is None or col in _COL_PRIORITY:
            continue
        ctx.col[col] = val
        ctx._mark("map_direct")


def rule_mark_opinc_kifrs(ctx: StdContext) -> None:
    """★ provenance(2026-07-18, Option B): is.operating_income 은 K-IFRS 전용
    (dart_OperatingIncomeLoss 또는 본문 '영업이익' 라벨 — 둘 다 K-IFRS). IFRS 영업손익은
    concept_map 에서 is.operating_income_ifrs 로 분리돼 컬럼에 유입 불가.
    operating_income 이 채워진 행에 'opinc_kifrs' 를 남겨 출처를 SQL 로 감사 가능하게 한다:
      SELECT count(*) FROM std_financials_v2 WHERE operating_income IS NOT NULL
        AND NOT (applied_rules @> '[\"opinc_kifrs\"]');   -- Phase D 불변식 = 0"""
    if ctx.col.get("operating_income") is not None:
        ctx._mark("opinc_kifrs")


def rule_cash_with_deposits(ctx: StdContext) -> None:
    """금융사(증권·보험) 현금 = 현금성자산 + 예치금 (2026-07-18, 사용자 확정).

    실측(유안타 원문): '현금및예치금'(총계) = '현금및현금성자산'(812B) + '예치금'(1,133B).
    같은 라벨 '현금및예치금'이 보고서마다 총계/예치금계정/단독합산으로 역할이 달라(형제행으로만
    구분 — 그건 이번 재구축이 없애려는 문맥추측) 구성요소로 나눠 저장하고 여기서 합산한다:

      · base cash = bs.cash(현금및현금성자산) 우선, 없으면 bs.cash_deposits_combined(결합/단독 라벨).
      · + bs.deposits(예치금).

    이렇게 하면:
      · 유안타(현금성 812 + 예치금 1,133, 결합 1,946 총계 공존) → 812 + 1,133 = 1,946 ✓
        (결합총계 1,946 은 base 가 현금성으로 채워졌으므로 무시 = 이중계상 방지)
      · 흥국화재/대신증권(현금및예치금 단독) → 결합값 그대로 ✓
      · 상상인(현금성 + 현금및예치금, 예치금 라인 없음) → 현금성만(예치금 미포함, 사용자
        '무리없으면' 수준으로 용인). 일반기업(예치금 무관)은 base=현금성, +0 = 불변.

    map_direct 뒤에 실행(현금성이 이미 ctx.col['cash'] 에 있음). 대용치·합산 시 표시를 남긴다.
    """
    combined = ctx.canon.get("bs.cash_deposits_combined")
    dep = ctx.canon.get("bs.deposits")
    if combined is None and dep is None:
        return   # 금융사 현금+예치금 구조 아님 → 관여하지 않음(일반기업 불변)
    base = ctx.col.get("cash")           # 현금성자산(map_direct 결과)
    if base is None and combined is not None:
        base = combined
        ctx._mark("cash_from_combined")   # 현금성 라인 없이 결합 라벨로 채움
    if base is None:
        return
    ctx.col["cash"] = base + (dep or 0)
    if dep:
        ctx._mark("cash_plus_deposits")   # 예치금 합산됨(순수 현금 아님)


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
    """별도재무제표는 비지배지분이 없어 지배순이익 ≡ 당기순이익(회계 정의). 따라서 별도는
    controlling_ni 가 NULL 이든, '지배기업 주주지분'(자본 라인) 오매핑·XBRL 오류·단위/스케일
    오류로 net_income 과 어긋나든 **항상 net_income 으로 강제**한다. (연결은 실제 비지배분이
    있으므로 불변.) 예: 기업은행 별도 지배순이익 138,722억(=자본) → 분기순이익 2,749억."""
    if ctx.basis == "separate":
        ni = ctx.col.get("net_income")
        if ni is not None and ctx.col.get("controlling_ni") != ni:
            ctx.col["controlling_ni"] = ni
            ctx._mark("controlling_ni_fill")


def rule_revenue_from_cogs_gp(ctx: StdContext) -> None:
    """revenue NULL 이면 cogs + gross_profit 으로 역산('수익' 단독 표기 기업 구제)."""
    if ctx.col.get("revenue") is None:
        cogs, gp = ctx.col.get("cogs"), ctx.col.get("gross_profit")
        if cogs is not None and gp is not None:
            ctx.col["revenue"] = abs(cogs) + gp
            ctx._mark("revenue_from_cogs_gp")


def rule_additive_debt(ctx: StdContext) -> None:
    """단기/장기차입금 = 차입금 + 유동성장기부채·유동성사채 / 사채 등 세부 합산.

    세부항목이 하나라도 있으면 합산값으로 덮어 과소계상을 보정한다(차입금만 있던 기업은
    동일값 = 변화 없음, 세부만 있던 기업은 NULL→값). 각 leaf 개념은 단일 canonical 로만
    매핑되므로 합산해도 이중계상 없음. map_direct 뒤에 실행.

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


def rule_additive_lease(ctx: StdContext) -> None:
    """리스부채(총) = 유동 + 비유동 리스부채. BS stock → 절대값 합(각 leaf 단일 canonical)."""
    parts = [abs(ctx.canon[c]) for c in _LEASE_PARTS if ctx.canon.get(c) is not None]
    if parts:
        ctx.col["lease_liability"] = sum(parts)
        ctx._mark("additive_lease")


def rule_additive_borrowings(ctx: StdContext) -> None:
    """차입 유입/상환(총) = 단기 + 장기. CF flow → **부호 보존 합**(유입 +, 상환 −)."""
    pp = [ctx.canon[c] for c in _BORROW_PROCEEDS_PARTS if ctx.canon.get(c) is not None]
    rp = [ctx.canon[c] for c in _BORROW_REPAID_PARTS if ctx.canon.get(c) is not None]
    if pp:
        ctx.col["borrowings_proceeds"] = sum(pp)
        ctx._mark("additive_borrowings")
    if rp:
        ctx.col["borrowings_repaid"] = sum(rp)
        ctx._mark("additive_borrowings")


def rule_revenue_fallback(ctx: StdContext) -> None:
    """금융(보험) 매출 보완: 제조업 표준 revenue(ifrs-full_Revenue)가 없을 때만,
    **보험 주력**(보험수익 ≥ 이자수익) 기업에 한해 영업수익(보험)/보험수익을 매출로 채운다.
    은행·혼합지주(이자수익 우위)는 단일 총매출 개념이 없어 **미적용**(잘못된 과소값 방지).
    map_direct 뒤 실행."""
    if ctx.col.get("revenue") is not None:
        return
    ins = ctx.canon.get("is.insurance_revenue")
    op_ins = ctx.canon.get("is.operating_revenue_ins")
    cand = op_ins if op_ins is not None else ins   # 영업수익(보험) 우선, 없으면 보험수익
    if cand is None:
        return
    interest = ctx.canon.get("is.interest_revenue")
    ins_size = ins if ins is not None else op_ins
    if interest is not None and ins_size is not None and abs(ins_size) < abs(interest):
        return  # 이자수익 우위 = 은행/혼합지주 → 미적용
    ctx.col["revenue"] = abs(cand)
    ctx._mark("revenue_fallback")


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
    ("mark_opinc_kifrs", rule_mark_opinc_kifrs),
    ("cash_with_deposits", rule_cash_with_deposits),
    ("additive_capex", rule_additive_capex),
    ("additive_da", rule_additive_da),
    ("additive_debt", rule_additive_debt),
    ("additive_lease", rule_additive_lease),
    ("additive_borrowings", rule_additive_borrowings),
    ("net_income_fill", rule_net_income_fill),
    ("controlling_ni_fill", rule_controlling_ni_fill),
    ("revenue_from_cogs_gp", rule_revenue_from_cogs_gp),
    ("revenue_fallback", rule_revenue_fallback),
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
    """BS=L+E, IS revenue-cogs≈gp, CF 합 정합. 자산총계<=0(불가)→3. 1=정상 2=경고 3=오류."""
    dq = 1
    ta, tl, te = col.get("total_assets"), col.get("total_liabilities"), col.get("total_equity")
    # 자산총계는 자산계정의 합이라 정상 기업이면 항상 양수. <=0 은 추출/부호/컬럼정렬 오류
    # (예: 텍스트 BS 의 연결/비교 컬럼 오추출) → 오류(DQ3)로 소비계층(data_quality<3)에서 배제.
    if ta is not None and ta <= 0:
        return 3
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
