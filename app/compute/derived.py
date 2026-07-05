"""
파생 지표 계산 — 두 필드의 비율(A÷B)·차분(A−B)·주당(A÷주식수)을 합성 시리즈로.

베이스 지표는 resolver.build_metric_frame 로 기간별 원시값을 얻고, 여기서 파생값을
계산해 **같은 tidy 스키마**(period_label·period_end·metric_id·name·category·unit·value)로
반환한다. 따라서 차트/표/CSV 는 베이스 지표와 동일 경로로 렌더된다.

- 비율(ratio)  : A÷B, 무차원 → UnitType.MULTIPLE_X. (예: FCF/영업이익 = 현금전환)
- 차분(diff)   : A−B, 금액 필드끼리만 → UnitType.AMOUNT_EOK. (예: 매출−매출원가 검산)
- 주당(pershare): A÷발행주식수, 금액 필드만 → UnitType.WON_PER_SHARE. (예: 임의 항목의 주당값)

값은 원시값(비율=배수, 금액=원, 주당=원/주)으로 보존 — 표시 변환은 units 가 담당.
"""
from __future__ import annotations

import pandas as pd

from app.compute.resolver import _period_label, build_metric_frame
from app.registry.metrics import REGISTRY_BY_ID
from app.registry.units import AMOUNT_UNITS, UnitType

DERIVED_CATEGORY = "파생"

OP_LABELS = {
    "ratio": "비율 (A÷B)",
    "diff": "차분 (A−B)",
    "pershare": "주당 (A÷주식수)",
}


def _name(mid: str) -> str:
    return REGISTRY_BY_ID[mid].name_ko


def _is_amount(mid: str) -> bool:
    return mid in REGISTRY_BY_ID and REGISTRY_BY_ID[mid].unit in AMOUNT_UNITS


def derived_id(spec: dict) -> str:
    """세션·차트 그룹 키로 쓰는 안정적 합성 id."""
    if spec["op"] == "pershare":
        return f"d_ps_{spec['a']}"
    return f"d_{spec['op']}_{spec['a']}_{spec['b']}"


def derived_name(spec: dict) -> str:
    op = spec["op"]
    if op == "ratio":
        return f"{_name(spec['a'])} ÷ {_name(spec['b'])}"
    if op == "diff":
        return f"{_name(spec['a'])} − {_name(spec['b'])}"
    return f"{_name(spec['a'])} (주당)"


def derived_unit(spec: dict) -> UnitType:
    op = spec["op"]
    if op == "ratio":
        return UnitType.MULTIPLE_X
    if op == "diff":
        return UnitType.AMOUNT_EOK
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
    periods = (base[["period_label", "period_end"]]
               .drop_duplicates().to_dict("records"))
    # 주당용 발행주식수(기간 라벨 기준) — 베이스 프레임엔 없으므로 series 에서 직접.
    shares = {_period_label(sf, grain): sf.get("shares_out") for sf in series}

    rows = []
    for p in periods:
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
            else:  # pershare
                sh = shares.get(pl)
                val = (av / sh) if (av is not None and sh not in (None, 0)) else None
            rows.append({
                "period_label": pl, "period_end": pe,
                "metric_id": derived_id(s), "name": derived_name(s),
                "category": DERIVED_CATEGORY, "unit": derived_unit(s), "value": val,
            })
    return pd.DataFrame(rows)
