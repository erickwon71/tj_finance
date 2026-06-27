"""
스크리너 윈도우 집계 + 퀀트 다단계.

윈도우 로드(`app.data.screen_window.load_screening_window`)의 corp별 시계열을
지표별로 집계(average / CAGR / YoY)해 **기업당 1행** base DataFrame 을 만들고,
≤3개 퀀트 패스(filter→sort→limit)를 순차 적용한다.

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
AVERAGE, CAGR, YOY = "average", "CAGR", "YoY"
AGG_METHODS = [AVERAGE, CAGR, YOY]

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
def aggregate(values: list, method: str, n_years: int) -> Optional[float]:
    """
    values: 최신→과거 순. None 허용.
      average = 비결측 평균
      CAGR    = _cagr(가장 오래된 비결측, 최신 비결측, 기간수)
      YoY     = _growth_rate(최신, 직전)
    """
    if not values:
        return None
    if method == AVERAGE:
        vals = [v for v in values if v is not None]
        return sum(vals) / len(vals) if vals else None
    if method == YOY:
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
        # 부호가 바뀌거나(end<=0) start<=0 이면 CAGR 정의 불가 → None
        # (_cagr 의 분수승이 음수 밑에서 복소수가 되는 것을 차단)
        if span <= 0 or start is None or start <= 0 or end is None or end <= 0:
            return None
        return _cagr(start, end, span)
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


def _latest_multiples(rows: list[dict], market_cap: Optional[float]) -> dict[str, Optional[float]]:
    """최신 FY 기준 점값 멀티플(시총/재무). 윈도우 집계 비대상."""
    curr = rows[0] if rows else {}
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


def build_base_frame(window: dict[str, dict], method: str, n_years: int) -> pd.DataFrame:
    """
    윈도우 → 기업당 1행 base DataFrame.
    컬럼: 식별(corp_code/corp_name/stock_code/market) + market_cap_jo + n_periods +
          레지스트리 전 지표(집계값) + 멀티플(최신 점값). 원시값 보존.
    """
    recs = []
    for cc, c in window.items():
        rows = c["rows"]
        series = _corp_metric_values(rows, WINDOW_METRIC_IDS, n_years)
        rec: dict[str, object] = {
            "corp_code":   cc,
            "corp_name":   c["corp_name"],
            "stock_code":  c["stock_code"],
            "market":      c["market"],
            MARKET_CAP_ID: (c["market_cap"] / 1e12) if c.get("market_cap") else None,
            "n_periods":   min(n_years, len(rows)),
        }
        for mid, vals in series.items():
            rec[mid] = aggregate(vals, method, n_years)
        rec.update(_latest_multiples(rows, c.get("market_cap")))
        rec.update(_latest_master(rows, c.get("market_cap"), c.get("close_price")))
        recs.append(rec)
    df = pd.DataFrame(recs)
    return add_magic_rank(df)


def _latest_master(rows: list[dict], market_cap, price) -> dict:
    """최신 FY 기준 대가 점값(Graham/Greenblatt/Lynch/Fisher)."""
    from app.compute.master_metrics import compute_master

    m = compute_master(rows, market_cap, price)
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
def apply_pass(df: pd.DataFrame, filters: dict[str, tuple[str, float]],
               sort_by: Optional[str], asc: bool, limit: Optional[int]) -> pd.DataFrame:
    """한 패스: filter(_check) → sort → head. 순수 DataFrame→DataFrame."""
    out = df
    for key, (op, thr) in filters.items():
        if key not in out.columns:
            continue
        mask = out[key].map(lambda v: _check(None if pd.isna(v) else v, op, thr))
        out = out[mask]
    if sort_by and sort_by in out.columns:
        out = out.sort_values(sort_by, ascending=asc, na_position="last")
    if limit:
        out = out.head(limit)
    return out


def run_quant_passes(base: pd.DataFrame, passes: list[dict]) -> tuple[pd.DataFrame, list[int]]:
    """
    passes: [{filters:{key:(op,thr)}, sort_by, asc, limit}, ...]  (≤3)
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
    if method in (CAGR, YOY):
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
