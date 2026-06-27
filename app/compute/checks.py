"""
재무 이상치(outlier) 점검.

DB 값은 보고서와 100% 일치(Gate B)하지만, **소스 보고서 자체가 비정상**일 수 있다
(정정 전 오기재·합성/테스트 데이터·DART 측 오류 등). 사용자가 그런 값을 무심코 신뢰하지
않도록, 표시 단계에서 자기상대(self-relative) 기준으로 이상치를 가볍게 플래그한다.

이 모듈은 데이터를 수정하지 않는다 — 표시용 경고 메시지만 생성한다.
"""
from __future__ import annotations

import statistics

# 자기상대 급증 배수 임계 (인접 기간 중앙값 대비)
# 경기민감(반도체 등) 정상 변동 오탐을 줄이려 보수적으로 4.0배 적용 — 명백한 이상치만 포착
_SPIKE_RATIO = 4.0
# 영업이익률 의심/불가 임계
_MARGIN_SUSPECT = 0.60
_MARGIN_IMPOSSIBLE = 1.00

# 급증 점검 대상 flow 지표
_SPIKE_METRICS = [("revenue", "매출"), ("operating_income", "영업이익"), ("net_income", "순이익")]
EOK = 100_000_000


def _label(sf: dict, grain: str) -> str:
    if grain == "quarter":
        return f"{sf.get('calendar_year')} {sf.get('calendar_period')}"
    return f"{sf.get('fiscal_year')} FY"


def financial_anomalies(series: list[dict], grain: str = "annual") -> list[str]:
    """
    재무 시계열에서 이상치 경고 메시지 리스트 생성.

    1) 영업이익률 > 100%(불가) / > 60%(의심)
    2) 매출·영업이익·순이익이 인접 기간 중앙값 대비 2.5배 이상 급증
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

    # 2) 자기상대 급증
    for key, name in _SPIKE_METRICS:
        vals = [(sf, sf.get(key)) for sf in series if sf.get(key) is not None]
        if len(vals) < 4:
            continue
        for sf, v in vals:
            others = [x for s2, x in vals if s2 is not sf and x > 0]
            if len(others) < 3 or v <= 0:
                continue
            med = statistics.median(others)
            if med > 0 and v > _SPIKE_RATIO * med:
                msgs.append(f"🟠 {_label(sf, grain)}: {name} {v/EOK:,.0f}억 — "
                            f"인접 기간 중앙값({med/EOK:,.0f}억) 대비 {v/med:.1f}배 급증(이상치 가능)")

    # 중복 제거(순서 보존)
    seen, out = set(), []
    for m in msgs:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out
