"""
재무 이상치(outlier) 점검.

DB 값은 보고서와 100% 일치(Gate B)하지만, **소스 보고서 자체가 비정상**일 수 있다
(정정 전 오기재·합성/테스트 데이터·DART 측 오류 등). 사용자가 그런 값을 무심코 신뢰하지
않도록, 표시 단계에서 가볍게 플래그한다.

급증 점검 기준 = **전년 동기(YoY, 같은 분기 작년)** 우선 + **직전 분기/연도(QoQ)** 병기.
계절성(분기 편차)을 전년 동기 비교로 흡수한다. 이 모듈은 데이터를 수정하지 않는다.
"""
from __future__ import annotations

# 급증 배수 임계
# 분기: 전년 동기 4배↑ **그리고** 직전 분기 1.8배↑ 동시 충족 시 플래그.
#   (경기민감 회복은 전년比 급증해도 직전 분기 대비는 완만 → 오탐 배제)
# 연간/단일비교: 전년 4배↑.
_SPIKE_YOY = 4.0
_SPIKE_QOQ = 1.8
# 영업이익률 의심/불가 임계
_MARGIN_SUSPECT = 0.60
_MARGIN_IMPOSSIBLE = 1.00

_SPIKE_METRICS = [("revenue", "매출"), ("operating_income", "영업이익"), ("net_income", "순이익")]
_QNUM = {"CQ1": 1, "CQ2": 2, "CQ3": 3, "CQ4": 4}
EOK = 100_000_000


def _label(sf: dict, grain: str) -> str:
    if grain == "quarter":
        return f"{sf.get('calendar_year')} {sf.get('calendar_period')}"
    return f"{sf.get('fiscal_year')} FY"


def _period_key(sf: dict, grain: str):
    if grain == "quarter":
        return (sf.get("calendar_year"), sf.get("calendar_period"))
    return (sf.get("fiscal_year"), "FY")


def _prev_key(key, grain):
    """직전 분기/연도 키."""
    y, p = key
    if grain == "quarter":
        qn = _QNUM.get(p, 0)
        return (y - 1, "CQ4") if qn == 1 else (y, f"CQ{qn-1}")
    return (y - 1, "FY")


def _yoy_key(key, grain):
    """전년 동기 키(분기: 같은 분기 1년 전 / 연간: 전년)."""
    y, p = key
    return (y - 1, p)


def _eok(v) -> str:
    return f"{v/EOK:,.0f}억"


def financial_anomalies(series: list[dict], grain: str = "annual") -> list[str]:
    """
    재무 시계열 이상치 경고 메시지.

    1) 영업이익률 > 100%(불가) / > 60%(의심)
    2) 매출·영업이익·순이익이 **전년 동기 대비 4배 이상** 급증(직전 분기 비교 병기)
    """
    msgs: list[str] = []

    # 1) 영업이익률 sanity
    for sf in series:
        rev, op = sf.get("revenue"), sf.get("operating_income")
        if rev and op is not None and rev > 0:
            m = op / rev
            if m > _MARGIN_IMPOSSIBLE:
                msgs.append(f"🔴 {_label(sf, grain)}: 영업이익이 매출을 초과 "
                            f"(영업이익률 {m*100:.0f}%) — 보고서 원값 확인 필요")
            elif m > _MARGIN_SUSPECT:
                msgs.append(f"🟠 {_label(sf, grain)}: 영업이익률 {m*100:.0f}% "
                            f"(비정상적으로 높음 — 확인 권장)")

    # 2) 전년 동기 / 직전 기간 대비 급증
    for key, name in _SPIKE_METRICS:
        vmap = {_period_key(sf, grain): sf.get(key) for sf in series if sf.get(key) is not None}
        for sf in series:
            v = sf.get(key)
            if v is None or v <= 0:
                continue
            k = _period_key(sf, grain)
            pv = vmap.get(_prev_key(k, grain))
            yv = vmap.get(_yoy_key(k, grain))
            qoq = (v / pv) if (pv and pv > 0) else None
            yoy = (v / yv) if (yv and yv > 0) else None

            if grain == "quarter":
                # 전년 동기 + 직전 분기 동시 급증이라야 이상치(계절성·완만한 회복·적자기저
                # 회복 배제). 전년 동기 비교가 불가하면(전년 적자/결측) 플래그하지 않음.
                trigger = (yoy is not None and yoy > _SPIKE_YOY
                           and qoq is not None and qoq > _SPIKE_QOQ)
            else:  # annual — 비교군이 전년 하나
                trigger = yoy is not None and yoy > _SPIKE_YOY
            if not trigger:
                continue

            parts = []
            if grain == "quarter" and yoy is not None:
                parts.append(f"전년 동기 {_eok(yv)} 대비 {yoy:.1f}배")
            if qoq is not None:
                unit = "분기" if grain == "quarter" else "연도"
                parts.append(f"직전 {unit} {_eok(pv)} 대비 {qoq:.1f}배")
            if not parts:  # 연간이고 yoy만 있는 경우
                parts.append(f"전년 {_eok(yv)} 대비 {yoy:.1f}배")

            msgs.append(f"🟠 {_label(sf, grain)}: {name} {_eok(v)} — "
                        f"{', '.join(parts)} 급증(이상치 가능)")

    # 중복 제거(순서 보존)
    seen, out = set(), []
    for m in msgs:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out
