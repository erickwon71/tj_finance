"""
Screener 페이지.

Phase 3(단일패스): 카탈로그 필터 + 정렬/한도 + 결과표(기업명/corp_code/종목코드).
수치·필터·정렬은 `analyzer.screener` 엔진(`screen`/`_parse_condition`/`_check`)을 그대로
재사용하므로 `python run.py screen ...` CLI 와 결과가 일치한다. 모집단은 한 번 캐시
로드한 뒤 필터·정렬·한도를 메모리에서 적용한다.

Phase 4+: 윈도우 집계(avg/CAGR/YoY)·퀀트 다단계·비파괴 분할 시각화.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from analyzer.screener import _check, _parse_condition
from app import state
from app.cache import screen_population

# ── 필터/정렬 가능 필드 (screen() 행 키 기준) ──────────────────────
# (key, 라벨, unit)  unit: "pct"=비율(소수 저장, % 입력) · "x"=배수 · "num"=수치 · "jo"=조원
_PCT, _X, _NUM, _JO = "pct", "x", "num", "jo"

FIELDS: list[tuple[str, str, str]] = [
    # 수익성
    ("roe", "ROE", _PCT),
    ("roa", "ROA", _PCT),
    ("roic", "ROIC", _PCT),
    ("op_margin", "영업이익률", _PCT),
    ("net_margin", "순이익률", _PCT),
    ("ebitda_margin", "EBITDA마진", _PCT),
    # 밸류에이션
    ("per", "PER", _X),
    ("pbr", "PBR", _X),
    ("ev_ebitda", "EV/EBITDA", _X),
    ("pcr", "PCR", _X),
    ("psr", "PSR", _X),
    # 성장성
    ("revenue_growth", "매출성장률", _PCT),
    ("op_growth", "영업이익성장률", _PCT),
    ("ni_growth", "순이익성장률", _PCT),
    # 안정성
    ("debt_ratio", "부채비율", _PCT),
    ("current_ratio", "유동비율", _PCT),
    ("interest_coverage", "이자보상배율", _X),
    ("fcf_quality", "CFO/순이익", _X),
    ("accrual_ratio", "발생액비율", _PCT),
    ("ccc", "현금전환주기(일)", _NUM),
    # 복합 / 규모
    ("piotroski", "Piotroski F", _NUM),
    ("market_cap_jo", "시가총액(조)", _JO),
]

_LABEL_BY_KEY = {k: lbl for k, lbl, _ in FIELDS}
_UNIT_BY_KEY = {k: u for k, _, u in FIELDS}
_OPS = [">", ">=", "<", "<=", "="]


def _build_condition(op_sym: str, value: float, unit: str) -> str:
    """UI 입력 → screen 조건 문자열 (CLI 와 동일 문법: '>15%', '<12')."""
    if unit == _PCT:
        return f"{op_sym}{value}%"
    return f"{op_sym}{value}"


def _apply(rows: list[dict], parsed: dict[str, tuple[str, float]],
           market: str | None, sort_by: str, sort_asc: bool, limit: int) -> list[dict]:
    """모집단에 필터·시장·정렬·한도 적용. screen() 의 메모리 단계와 동일 로직."""
    out = []
    for r in rows:
        if market and (r.get("market") or "").upper() != market.upper():
            continue
        ok = True
        for key, (op, thr) in parsed.items():
            if not _check(r.get(key), op, thr):
                ok = False
                break
        if ok:
            out.append(r)

    def _sort_key(r):
        v = r.get(sort_by)
        return (1, 0) if v is None else (0, v)

    out.sort(key=_sort_key, reverse=not sort_asc)
    return out[:limit]


# ── 결과표 포맷 ────────────────────────────────────────────────
def _fmt_cell(key: str, value) -> str:
    if value is None:
        return "—"
    unit = _UNIT_BY_KEY.get(key)
    if unit == _PCT:
        return f"{value * 100:.1f}%"
    if unit == _X:
        return f"{value:.2f}x"
    if unit == _JO:
        return f"{value:.2f}조"
    if key == "piotroski":
        return f"{int(value)}/9"
    if key == "ccc":
        return f"{value:.0f}일"
    return f"{value}"


_DISPLAY_COLS = [
    "roe", "roic", "per", "pbr", "ev_ebitda",
    "op_margin", "revenue_growth", "debt_ratio", "piotroski",
]


def _to_dataframe(results: list[dict]) -> pd.DataFrame:
    recs = []
    for r in results:
        rec = {
            "기업명": r["corp_name"],
            "종목코드": r.get("stock_code") or "—",
            "corp_code": r["corp_code"],
            "시장": r.get("market") or "—",
            "FY": r.get("fiscal_year"),
            "시총": _fmt_cell("market_cap_jo", r.get("market_cap_jo")),
        }
        for k in _DISPLAY_COLS:
            rec[_LABEL_BY_KEY.get(k, k)] = _fmt_cell(k, r.get(k))
        recs.append(rec)
    return pd.DataFrame(recs)


def render() -> None:
    st.header("🔎 스크리너")
    st.caption("카탈로그 지표로 활성 보통주(최신 FY·연결)를 필터링합니다. "
               "수치·정렬은 `run.py screen` CLI 와 동일.")

    # ── 필터 빌더 ──
    with st.form("screen_form"):
        picked = st.multiselect(
            "필터 지표", options=[k for k, _, _ in FIELDS],
            format_func=lambda k: _LABEL_BY_KEY[k],
            default=["roe", "per"],
            help="선택한 지표마다 연산자·값을 지정합니다.",
        )

        parsed: dict[str, tuple[str, float]] = {}
        conds: dict[str, str] = {}
        for key in picked:
            unit = _UNIT_BY_KEY[key]
            c1, c2 = st.columns([1, 2])
            with c1:
                op = st.selectbox(_LABEL_BY_KEY[key], _OPS,
                                  index=0 if unit != _X else 2,  # 배수는 기본 '<'
                                  key=f"op_{key}")
            with c2:
                suffix = " (%)" if unit == _PCT else (" (조)" if unit == _JO else "")
                val = st.number_input(f"값{suffix}", value=15.0 if unit == _PCT else 12.0,
                                      step=1.0, key=f"val_{key}", label_visibility="visible")
            cond = _build_condition(op, val, unit)
            conds[key] = cond
            parsed[key] = _parse_condition(cond)

        st.divider()
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            market_label = st.selectbox("시장", ["전체", "KOSPI", "KOSDAQ"])
        with c2:
            sort_by = st.selectbox("정렬 기준", [k for k, _, _ in FIELDS],
                                   format_func=lambda k: _LABEL_BY_KEY[k],
                                   index=0)
        with c3:
            order = st.selectbox("정렬 방향", ["내림차순", "오름차순"])
        with c4:
            limit = int(st.number_input("최대 건수", value=30, min_value=1,
                                        max_value=2000, step=10))

        submitted = st.form_submit_button("스크리닝 실행", type="primary", width="stretch")

    if submitted:
        market = None if market_label == "전체" else market_label
        pop = screen_population()
        results = _apply(pop, parsed, market, sort_by, order == "오름차순", limit)
        st.session_state[state.SCREEN_RESULTS] = results
        st.session_state["screen_conds"] = conds

    results = st.session_state.get(state.SCREEN_RESULTS)
    if results is None:
        st.info("필터를 설정하고 **스크리닝 실행**을 누르세요.")
        return

    conds = st.session_state.get("screen_conds", {})
    cond_str = "  ".join(f"`{_LABEL_BY_KEY[k]} {v}`" for k, v in conds.items()) or "(필터 없음)"
    st.markdown(f"**{len(results)}건** · {cond_str}")

    if not results:
        st.warning("조건에 맞는 기업이 없습니다.")
        return

    df = _to_dataframe(results)
    st.dataframe(df, hide_index=True, width="stretch")

    from app.components.export import to_csv_bytes
    st.download_button(
        "결과 CSV 내려받기", data=to_csv_bytes(pd.DataFrame(results), index=False),
        file_name="screen_results.csv", mime="text/csv",
    )
