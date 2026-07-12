"""
파생 지표 계산 — 두 필드의 비율(A÷B)·차분(A−B)·주당(A÷주식수)·YoY(전년동기比)·
TTM(분기, 직전4분기 합산)을 합성 시리즈로.

베이스 지표는 resolver.build_metric_frame 로 기간별 원시값을 얻고, 여기서 파생값을
계산해 **같은 tidy 스키마**(period_label·period_end·metric_id·name·category·unit·value)로
반환한다. 따라서 차트/표/CSV 는 베이스 지표와 동일 경로로 렌더된다.

- 비율(ratio)  : A÷B, 무차원 → UnitType.MULTIPLE_X. (예: FCF/영업이익 = 현금전환)
- 차분(diff)   : A−B, 금액 필드끼리만 → UnitType.AMOUNT_EOK. (예: 매출−매출원가 검산)
- 주당(pershare): A÷발행주식수, 금액 필드만 → UnitType.WON_PER_SHARE. (예: 임의 항목의 주당값)
- YoY(yoy)     : A 의 전년 동기 대비 변화율(연간=직전 기간, 분기=4분기 전) → UnitType.PCT.
  analyzer.ratio_engine._growth_rate 재사용(부호 규약 동일 — 분모=|전기|).
- TTM(ttm)     : A 의 최근 4분기 합산(분기 그레인 전용, flow 금액 지표만) → A 와 동일 단위.
  screen_eval._ttm_row 와 동일 원칙(base frame 이 이미 분기 discrete 값이라 그대로 합산).

값은 원시값(비율=배수, 금액=원, 주당=원/주)으로 보존 — 표시 변환은 units 가 담당.
"""
from __future__ import annotations

import pandas as pd

from analyzer.ratio_engine import _growth_rate
from app.compute.resolver import _period_label, build_metric_frame
from app.registry.metrics import REGISTRY_BY_ID
from app.registry.units import AMOUNT_UNITS, UnitType

DERIVED_CATEGORY = "파생"

OP_LABELS = {
    "ratio": "비율 (A÷B)",
    "diff": "차분 (A−B)",
    "pershare": "주당 (A÷주식수)",
    "yoy": "YoY (전년동기比 %)",
    "ttm": "TTM (분기, 직전4분기 합산)",
}

# 1필드(B 불요) 연산 — chart_builder_page.py 의 B 필드 비활성화 판단에도 재사용.
SINGLE_FIELD_OPS = {"pershare", "yoy", "ttm"}

# TTM 합산 대상에서 제외할 잔액(stock) 성격 금액 지표 — 분기 스냅샷 합산은 무의미(자산총계 등).
# screen_eval.py::_FLOW_KEYS(합산 대상)의 반대 개념을 AMOUNT_EOK 전체에서 제외 목록으로 표현.
_TTM_EXCLUDE_STOCK_IDS = {
    "total_assets", "total_liabilities", "total_equity", "controlling_equity",
    "cash", "net_debt", "inventory", "receivables",
}


def _name(mid: str) -> str:
    return REGISTRY_BY_ID[mid].name_ko


def _is_amount(mid: str) -> bool:
    return mid in REGISTRY_BY_ID and REGISTRY_BY_ID[mid].unit in AMOUNT_UNITS


def _is_ttm_eligible(mid: str) -> bool:
    return _is_amount(mid) and mid not in _TTM_EXCLUDE_STOCK_IDS


def derived_id(spec: dict) -> str:
    """세션·차트 그룹 키로 쓰는 안정적 합성 id."""
    op = spec["op"]
    if op in SINGLE_FIELD_OPS:
        prefix = {"pershare": "ps", "yoy": "yoy", "ttm": "ttm"}[op]
        return f"d_{prefix}_{spec['a']}"
    return f"d_{op}_{spec['a']}_{spec['b']}"


def derived_name(spec: dict) -> str:
    op = spec["op"]
    if op == "ratio":
        return f"{_name(spec['a'])} ÷ {_name(spec['b'])}"
    if op == "diff":
        return f"{_name(spec['a'])} − {_name(spec['b'])}"
    if op == "yoy":
        return f"{_name(spec['a'])} YoY"
    if op == "ttm":
        return f"{_name(spec['a'])} TTM"
    return f"{_name(spec['a'])} (주당)"


def derived_unit(spec: dict) -> UnitType:
    op = spec["op"]
    if op == "ratio":
        return UnitType.MULTIPLE_X
    if op == "diff":
        return UnitType.AMOUNT_EOK
    if op == "yoy":
        return UnitType.PCT
    if op == "ttm":
        return REGISTRY_BY_ID[spec["a"]].unit
    return UnitType.WON_PER_SHARE


def validate(spec: dict) -> str | None:
    """부적합하면 사유 문자열, 적합하면 None."""
    op = spec.get("op")
    a, b = spec.get("a"), spec.get("b")
    if op not in OP_LABELS:
        return "연산 종류가 올바르지 않습니다."
    if a not in REGISTRY_BY_ID:
        return "A 필드를 선택하세요."
    if op in ("ratio", "diff"):
        if b not in REGISTRY_BY_ID:
            return "B 필드를 선택하세요."
        if a == b:
            return "A와 B가 같습니다."
    if op == "diff" and not (_is_amount(a) and _is_amount(b)):
        return "차분(A−B)은 금액 필드끼리만 가능합니다."
    if op == "pershare" and not _is_amount(a):
        return "주당 변환은 금액 필드만 가능합니다."
    if op == "ttm" and not _is_ttm_eligible(a):
        return "TTM은 유량(flow) 금액 지표만 가능합니다(자산총계 등 잔액 항목 제외)."
    return None


def build_derived_frame(series: list[dict], derived_specs: list[dict],
                        grain: str) -> pd.DataFrame:
    """유효한 파생 spec 들을 tidy long DataFrame 으로. 무효/빈 입력이면 빈 프레임."""
    valid = [s for s in derived_specs if validate(s) is None]
    if not valid or not series:
        return pd.DataFrame()

    # 참조된 베이스 지표만 한 번에 계산(기간당 1회 엔진 호출).
    ids = set()
    for s in valid:
        ids.add(s["a"])
        if s.get("b"):
            ids.add(s["b"])
    base = build_metric_frame(series, sorted(ids), grain)
    if base.empty:
        return pd.DataFrame()

    lut = {(r["period_label"], r["metric_id"]): r["value"]
           for _, r in base.iterrows()}
    # periods 는 base 행 삽입 순서(=series 순서, 최신→과거)를 보존 — yoy/ttm 의 "N 기간 전" 오프셋은
    # 이 리스트의 인덱스 이동으로 계산한다(달력 계산 불필요, resolver 의 series 순서 규약 재사용).
    periods = (base[["period_label", "period_end"]]
               .drop_duplicates().to_dict("records"))
    period_labels = [p["period_label"] for p in periods]
    # 주당용 발행주식수(기간 라벨 기준) — 베이스 프레임엔 없으므로 series 에서 직접.
    shares = {_period_label(sf, grain): sf.get("shares_out") for sf in series}
    # YoY/TTM 오프셋 — 분기 그레인은 4기 전(같은 분기 전년), 연간은 1기 전.
    yoy_step = 4 if grain == "quarter" else 1

    rows = []
    for i, p in enumerate(periods):
        pl, pe = p["period_label"], p["period_end"]
        for s in valid:
            av = lut.get((pl, s["a"]))
            op = s["op"]
            if op == "ratio":
                bv = lut.get((pl, s["b"]))
                val = (av / bv) if (av is not None and bv not in (None, 0)) else None
            elif op == "diff":
                bv = lut.get((pl, s["b"]))
                val = (av - bv) if (av is not None and bv is not None) else None
            elif op == "pershare":
                sh = shares.get(pl)
                val = (av / sh) if (av is not None and sh not in (None, 0)) else None
            elif op == "yoy":
                prev_i = i + yoy_step
                pv = lut.get((period_labels[prev_i], s["a"])) if prev_i < len(period_labels) else None
                val = _growth_rate(av, pv)
            else:  # ttm — 분기 그레인 전용, 이 기간부터 과거로 4개 분기 합산.
                if grain != "quarter":
                    val = None
                else:
                    window = period_labels[i:i + 4]
                    if len(window) < 4:
                        val = None
                    else:
                        vals = [lut.get((lbl, s["a"])) for lbl in window]
                        val = sum(v for v in vals if v is not None) if any(v is not None for v in vals) else None
            rows.append({
                "period_label": pl, "period_end": pe,
                "metric_id": derived_id(s), "name": derived_name(s),
                "category": DERIVED_CATEGORY, "unit": derived_unit(s), "value": val,
            })
    return pd.DataFrame(rows)
