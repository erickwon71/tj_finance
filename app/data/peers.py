"""섹터 피어 벤치마킹 — 같은 업종(KSIC 중분류) 기업 대비 지표 백분위. UI 비의존.

스크리너 모집단(전 기업 지표)을 재사용해 대상 기업의 업종 피어를 뽑고, 핵심 지표의 섹터 분포
(중앙값)와 대상의 백분위를 계산한다. 모집단은 호출자(cache)가 넘긴다(중복 스캔 방지).
"""
from __future__ import annotations

from statistics import median
from typing import Optional

from sqlalchemy import text

from analyzer.ksic import is_financial_sector, sector_key, sector_name
from collector.db import get_session

# 금융업(은행/보험/지주)에서 제조업 기준으로 오도되는 지표 — 백분위·평가 딱지에서 제외(외부평가 2026-07-15).
# 이자수익 중심 손익구조·고레버리지가 정상이라 영업이익률·부채비율을 일반 임계로 평가하면 오해를 부른다.
_FINANCIAL_EXCLUDED_METRICS = frozenset({"op_margin", "debt_ratio"})

# (key, 라벨, 높을수록좋음, 종류) — pct=비율(프랙션), mult=멀티플, score=점수
PEER_METRICS: list[tuple[str, str, bool, str]] = [
    ("roe", "ROE", True, "pct"),
    ("roic", "ROIC", True, "pct"),
    ("op_margin", "영업이익률", True, "pct"),
    ("net_margin", "순이익률", True, "pct"),
    ("revenue_growth", "매출성장률", True, "pct"),
    ("per", "PER", False, "mult"),
    ("pbr", "PBR", False, "mult"),
    ("ev_ebitda", "EV/EBITDA", False, "mult"),
    ("debt_ratio", "부채비율", False, "pct"),
    ("piotroski", "Piotroski", True, "score"),
]


def _pct_rank(vals: list[float], target: float) -> float:
    """target 이 vals 분포에서 차지하는 백분위(작은 값의 비율, 0~100)."""
    n = len(vals)
    return sum(1 for v in vals if v < target) / n * 100 if n else 0.0


def load_peer_benchmark(corp_code: str, population: list[dict]) -> Optional[dict]:
    """대상 기업의 업종 피어 벤치마크. population=스크리너 모집단(전 기업 지표)."""
    with get_session() as s:
        induty = s.execute(text(
            "SELECT induty_code FROM corporations WHERE corp_code = :c"),
            {"c": corp_code}).scalar()
        induty_map = dict(s.execute(text(
            "SELECT corp_code, induty_code FROM corporations WHERE induty_code IS NOT NULL"
        )).fetchall())

    skey = sector_key(induty)
    if not skey:
        return {"has_sector": False}

    is_financial = is_financial_sector(induty)
    peers = [r for r in population if sector_key(induty_map.get(r["corp_code"])) == skey]
    target = next((r for r in peers if r["corp_code"] == corp_code), None)
    result = {
        "has_sector": True, "sector_name": sector_name(induty), "induty": induty,
        "n_peers": len(peers), "is_financial": is_financial,
    }
    if not target or len(peers) < 3:
        result["insufficient"] = True
        return result

    metrics = []
    for key, label, hb, kind in PEER_METRICS:
        # 금융업: 제조업 기준 오도 지표(영업이익률·부채비율)는 백분위·평가에서 제외.
        if is_financial and key in _FINANCIAL_EXCLUDED_METRICS:
            continue
        vals = [r[key] for r in peers if r.get(key) is not None]
        tv = target.get(key)
        if tv is None or len(vals) < 3:
            metrics.append({"key": key, "label": label, "kind": kind, "higher_better": hb,
                            "value": tv, "median": None, "percentile": None, "n": len(vals)})
            continue
        metrics.append({
            "key": key, "label": label, "kind": kind, "higher_better": hb,
            "value": tv, "median": median(vals), "percentile": _pct_rank(vals, tv), "n": len(vals),
        })
    result["metrics"] = metrics
    # 시총 상위 피어(대상 포함)
    result["peers"] = sorted(peers, key=lambda r: r.get("market_cap_jo") or 0, reverse=True)[:12]
    return result
