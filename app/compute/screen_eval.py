"""
스크리너 윈도우 집계 + 퀀트 다단계.

윈도우 로드(`app.data.screen_window.load_screening_window`)의 corp별 시계열을
지표별로 집계(average / CAGR / YoY)해 **기업당 1행** base DataFrame 을 만들고,
≤4개 퀀트 패스(filter→sort→limit)를 순차 적용한다.

집계·필터·성장률은 기존 엔진 재사용:
- `analyzer.ratio_engine.compute_ratios` (기간당 1회)·`_cagr`·`_growth_rate`
- `analyzer.screener._check` (필터 비교)
- `app.registry.metrics.METRIC_REGISTRY` (지표 카탈로그)

값은 원시값 보존(금액=원, 비율=소수). 표시 변환은 페이지에서.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from analyzer.ratio_engine import _cagr, _growth_rate, compute_ratios
from analyzer.screener import _check
from app.registry.metrics import METRIC_REGISTRY, REGISTRY_BY_ID
from app.registry.units import UnitType

# 집계 방법
AVERAGE, CAGR, YOY, QOQ = "average", "CAGR", "YoY", "QoQ"
AGG_METHODS = [AVERAGE, CAGR, YOY]              # 연간
AGG_METHODS_QUARTER = [AVERAGE, CAGR, YOY, QOQ]  # 분기(QoQ=직전분기比 추가)

# 윈도우 집계 대상 = 레지스트리 전 지표
WINDOW_METRIC_IDS: list[str] = [m.id for m in METRIC_REGISTRY]

# 최신 FY 점값(point) 멀티플 — 윈도우 집계 비대상(항상 최신값)
MULTIPLE_FIELDS: list[tuple[str, str]] = [
    ("per", "PER"), ("pbr", "PBR"), ("ev_ebitda", "EV/EBITDA"),
    ("psr", "PSR"), ("pcr", "PCR"),
]
MULTIPLE_IDS = [k for k, _ in MULTIPLE_FIELDS]

# 대가(Master) 점값 필드 — 최신 FY 기준(윈도우 집계 비대상)
MASTER_FIELDS: list[tuple[str, str]] = [
    ("earnings_yield", "이익수익률(EY)"),
    ("return_on_capital", "투하자본수익률(ROC)"),
    ("magic_rank", "마법공식 랭크"),
    ("peg", "PEG"),
    ("graham_upside", "Graham 상승여력"),
    ("ncav_to_price", "NCAV/주가"),
    ("rd_to_revenue", "R&D/매출"),
]
MASTER_IDS = [k for k, _ in MASTER_FIELDS]
_MASTER_PCT = {"earnings_yield", "return_on_capital", "graham_upside", "rd_to_revenue"}
_MASTER_X = {"peg", "ncav_to_price"}
MAGIC_RANK_ID = "magic_rank"

# 규모 필드(조원)
MARKET_CAP_ID = "market_cap_jo"


# ── 단일 시계열 집계 ────────────────────────────────────────────
def aggregate(values: list, method: str, n_periods: int, grain: str = "annual") -> Optional[float]:
    """
    values: 최신→과거 순. None 허용. grain="quarter" 면 분기 의미로 보정:
      average = 비결측 평균(공통)
      YoY     = 최신 대비 1년 전(연간=직전, 분기=4분기 전)
      CAGR    = 연복리(분기는 경과기간을 연수로 환산: span/4)
    """
    if not values:
        return None
    step = 4 if grain == "quarter" else 1
    per_year = 4 if grain == "quarter" else 1

    if method == AVERAGE:
        vals = [v for v in values if v is not None]
        return sum(vals) / len(vals) if vals else None
    if method == YOY:
        curr = values[0] if values else None
        prev = values[step] if len(values) > step else None
        return _growth_rate(curr, prev)
    if method == QOQ:
        # 직전 기간 대비(분기=직전 분기). 연간에선 노출 안 함.
        curr = values[0] if values else None
        prev = values[1] if len(values) > 1 else None
        return _growth_rate(curr, prev)
    if method == CAGR:
        # 최신=end(values[0]), 가장 오래된 비결측=start
        end = values[0]
        start, span = None, 0
        for i in range(1, len(values)):
            if values[i] is not None:
                start, span = values[i], i
        years = span / per_year
        # 부호가 바뀌거나(end<=0) start<=0 이면 CAGR 정의 불가 → None
        # (_cagr 의 분수승이 음수 밑에서 복소수가 되는 것을 차단)
        if years <= 0 or start is None or start <= 0 or end is None or end <= 0:
            return None
        return _cagr(start, end, years)
    return None


# ── corp별 다지표 집계 ─────────────────────────────────────────
def _corp_metric_values(rows: list[dict], metric_ids: list[str],
                        n_years: int) -> dict[str, list]:
    """corp 한 곳의 (윈도우 내 기간별) 지표값 시계열. compute_ratios 는 기간당 1회."""
    specs = [REGISTRY_BY_ID[m] for m in metric_ids if m in REGISTRY_BY_ID]
    need_ratios = any(s.source == "ratios" for s in specs)
    out: dict[str, list] = {m: [] for m in metric_ids}
    n = len(rows)
    for i in range(min(n_years, n)):
        ratios = None
        if need_ratios:
            prev = rows[i + 1] if i + 1 < n else None
            ratios = compute_ratios(rows[i], prev)
        for spec in specs:
            if spec.source == "column":
                out[spec.id].append(rows[i].get(spec.key))
            else:
                out[spec.id].append(getattr(ratios, spec.key, None))
    return out


# 분기 TTM 합산 대상 flow 컬럼(손익·현금흐름). BS/주식수는 최신 분기 스냅샷 사용.
_FLOW_KEYS = (
    "revenue", "cogs", "gross_profit", "sga", "rd_expense", "operating_income",
    "ebt", "tax_expense", "net_income", "controlling_ni", "ebitda",
    "cfo", "cfi", "cff", "capex", "fcf", "da_total", "interest_expense", "dividends_paid",
)


def _ttm_row(rows: list[dict], start: int = 0) -> Optional[dict]:
    """rows(최신→과거)의 [start:start+4] 4개 분기로 TTM 행 합성.
    flow 는 합산, BS/주식수 등은 윈도우 내 최신 분기(rows[start]) 스냅샷. 4분기 미만이면 None."""
    window = rows[start:start + 4]
    if len(window) < 4:
        return None
    out = dict(window[0])  # BS 스냅샷 + 식별
    for k in _FLOW_KEYS:
        vals = [w.get(k) for w in window]
        out[k] = sum(v for v in vals if v is not None) if any(v is not None for v in vals) else None
    return out


def _latest_multiples(rows: list[dict], market_cap: Optional[float],
                      grain: str = "annual") -> dict[str, Optional[float]]:
    """점값 멀티플(시총/재무). 분기는 TTM(직전 4분기 합산 손익/현금흐름) 기준 → 분기 단발 왜곡 방지."""
    curr = (_ttm_row(rows, 0) if grain == "quarter" else (rows[0] if rows else {})) or {}
    mc = market_cap

    def _div(a, b):
        return a / b if (a and b and b > 0) else None

    ni     = curr.get("net_income") or 0
    eq     = curr.get("total_equity") or 0
    ebitda = curr.get("ebitda") or 0
    cfo    = curr.get("cfo") or 0
    rev    = curr.get("revenue") or 0
    net_dt = curr.get("net_debt") or 0
    ev = (mc or 0) + (net_dt or 0)
    return {
        "per": _div(mc, ni),
        "pbr": _div(mc, eq),
        "ev_ebitda": _div(ev, ebitda),
        "psr": _div(mc, rev),
        "pcr": _div(mc, cfo),
    }


def build_base_frame(window: dict[str, dict], method: str, n_periods: int,
                     grain: str = "annual") -> pd.DataFrame:
    """
    윈도우 → 기업당 1행 base DataFrame.
    컬럼: 식별(corp_code/corp_name/stock_code/market) + market_cap_jo + n_periods +
          레지스트리 전 지표(집계값) + 멀티플·대가(점값, 분기는 TTM). 원시값 보존.
    """
    recs = []
    for cc, c in window.items():
        rows = c["rows"]
        series = _corp_metric_values(rows, WINDOW_METRIC_IDS, n_periods)
        rec: dict[str, object] = {
            "corp_code":   cc,
            "corp_name":   c["corp_name"],
            "stock_code":  c["stock_code"],
            "market":      c["market"],
            MARKET_CAP_ID: (c["market_cap"] / 1e12) if c.get("market_cap") else None,
            "n_periods":   min(n_periods, len(rows)),
        }
        for mid, vals in series.items():
            rec[mid] = aggregate(vals, method, n_periods, grain)
        rec.update(_latest_multiples(rows, c.get("market_cap"), grain))
        rec.update(_latest_master(rows, c.get("market_cap"), c.get("close_price"), grain))
        recs.append(rec)
    df = pd.DataFrame(recs)
    return add_magic_rank(df)


def _latest_master(rows: list[dict], market_cap, price, grain: str = "annual") -> dict:
    """대가 점값(Graham/Greenblatt/Lynch/Fisher). 분기는 TTM(현재 4분기) + 전년 TTM(직전 4분기)
    로 합성해 PEG(YoY 성장)·EY 등을 분기 단발 왜곡 없이 계산."""
    from app.compute.master_metrics import compute_master

    if grain == "quarter":
        ttm_curr, ttm_prev = _ttm_row(rows, 0), _ttm_row(rows, 4)
        sf_list = [r for r in (ttm_curr, ttm_prev) if r is not None] or rows
    else:
        sf_list = rows
    m = compute_master(sf_list, market_cap, price)
    return {
        "earnings_yield": m.earnings_yield,
        "return_on_capital": m.return_on_capital,
        "peg": m.peg,
        "graham_upside": m.graham_upside,
        "ncav_to_price": m.ncav_to_price,
        "rd_to_revenue": m.rd_to_revenue,
    }


def add_magic_rank(df: pd.DataFrame) -> pd.DataFrame:
    """
    Greenblatt 마법공식 종합 랭크 = rank(EY 내림) + rank(ROC 내림).
    값이 작을수록(=둘 다 상위) 우수. 두 지표 모두 있는 기업만 부여, 나머지 NaN.
    """
    if df.empty or "earnings_yield" not in df.columns or "return_on_capital" not in df.columns:
        df[MAGIC_RANK_ID] = pd.NA
        return df
    ey_rank = df["earnings_yield"].rank(ascending=False, method="min")
    roc_rank = df["return_on_capital"].rank(ascending=False, method="min")
    combined = ey_rank + roc_rank
    # 두 지표 모두 존재할 때만 유효
    valid = df["earnings_yield"].notna() & df["return_on_capital"].notna()
    df[MAGIC_RANK_ID] = combined.where(valid)
    # 종합 랭크를 1..N 정수 순위로 재산출(작을수록 우수)
    df[MAGIC_RANK_ID] = df[MAGIC_RANK_ID].rank(ascending=True, method="min")
    return df


# ── 퀀트 다단계 ────────────────────────────────────────────────
def apply_pass(df: pd.DataFrame, filters: dict,
               sort_by: Optional[str], asc: bool, limit: Optional[int]) -> pd.DataFrame:
    """한 패스: filter(_check) → sort → head. 순수 DataFrame→DataFrame.

    filters 값은 단일 조건 (op, thr) 또는 조건 리스트 [(op, thr), ...](구간=하한+상한).
    모든 조건을 AND 로 적용."""
    out = df
    for key, cond in filters.items():
        if key not in out.columns:
            continue
        conds = cond if isinstance(cond, list) else [cond]
        for op, thr in conds:
            mask = out[key].map(
                lambda v, op=op, thr=thr: _check(None if pd.isna(v) else v, op, thr))
            out = out[mask]
    if sort_by and sort_by in out.columns:
        out = out.sort_values(sort_by, ascending=asc, na_position="last")
    if limit:
        out = out.head(limit)
    return out


def run_quant_passes(base: pd.DataFrame, passes: list[dict]) -> tuple[pd.DataFrame, list[int]]:
    """
    passes: [{filters:{key:(op,thr)}, sort_by, asc, limit}, ...]  (≤4)
    각 패스를 직전 결과에 순차 적용. 반환: (최종 df, [패스별 잔존 건수]).
    """
    df = base
    counts = []
    for p in passes:
        df = apply_pass(df, p.get("filters", {}), p.get("sort_by"),
                        p.get("asc", False), p.get("limit"))
        counts.append(len(df))
    return df, counts


# ── 필드 단위/임계 헬퍼 ────────────────────────────────────────
def effective_unit(metric_id: str, method: str) -> UnitType:
    """집계 결과의 표시 단위. CAGR/YoY 는 성장률(%). 멀티플·대가는 점값(고정 단위)."""
    if metric_id in MULTIPLE_IDS:
        return UnitType.MULTIPLE_X
    if metric_id in _MASTER_PCT:
        return UnitType.PCT
    if metric_id in _MASTER_X:
        return UnitType.MULTIPLE_X
    if metric_id == MAGIC_RANK_ID:
        return UnitType.MULTIPLE_X  # 정수 랭크(별도 포맷)
    if metric_id == MARKET_CAP_ID:
        return UnitType.MULTIPLE_X  # 조원(별도 포맷)
    if method in (CAGR, YOY, QOQ):
        return UnitType.PCT
    spec = REGISTRY_BY_ID.get(metric_id)
    return spec.unit if spec else UnitType.MULTIPLE_X


_OP_MAP = {">": "gt", ">=": "gte", "<": "lt", "<=": "lte", "=": "eq"}
EOK = 100_000_000


def make_threshold(metric_id: str, method: str, op_sym: str, value: float) -> tuple[str, float]:
    """UI 입력(연산자·값) → (op, raw threshold). 단위에 맞춰 원시값으로 변환."""
    op = _OP_MAP[op_sym]
    unit = effective_unit(metric_id, method)
    if unit == UnitType.PCT:
        return op, value / 100.0          # % → 소수
    if unit == UnitType.AMOUNT_EOK:
        return op, value * EOK            # 억원 → 원
    return op, value                      # 배수/일수/조원 그대로
