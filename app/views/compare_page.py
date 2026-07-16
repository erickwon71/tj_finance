"""
Compare 페이지 — 여러 기업 핵심지표 나란히 비교.

`analyzer.comparator.compare` 재사용(= `run.py compare` 와 동일 수치). 기업은 사이드바와
별개로 이 페이지에서 검색·추가/제거하고, 항목(세로)×기업(가로) 표로 렌더한다.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import cache, state
from app.format import fmt_amount, fmt_corp_identity, fmt_pct, fmt_ratio

# 표시 행: (라벨, key, 종류)  종류: amount/pct/x/score
_ROWS = [
    ("시장",          "market",        "raw"),
    ("FY",            "fiscal_year",   "raw"),
    ("매출액",        "revenue",       "amount"),
    ("영업이익",      "op_income",     "amount"),
    ("순이익",        "net_income",    "amount"),
    ("시가총액",      "market_cap",    "amount"),
    ("영업이익률",    "op_margin",     "pct"),
    ("순이익률",      "net_margin",    "pct"),
    ("ROE",          "roe",           "pct"),
    ("ROIC",         "roic",          "pct"),
    ("PER",          "per",           "x"),
    ("PBR",          "pbr",           "x"),
    ("EV/EBITDA",    "ev_ebitda",     "x"),
    ("PSR",          "psr",           "x"),
    ("매출성장",      "revenue_growth", "pct"),
    ("순이익성장",    "ni_growth",     "pct"),
    ("부채비율",      "debt_ratio",    "pct"),
    ("유동비율",      "current_ratio", "pct"),
    ("이자보상배율",  "interest_coverage", "x"),
    ("배당수익률",    "div_yield",     "pct"),
    ("Piotroski",    "piotroski",     "score"),
]

_CMP_KEY = "compare_corps"  # session_state: list[corp_code]


def _fmt(kind: str, v) -> str:
    if v is None:
        return "—"
    if kind == "amount":
        return fmt_amount(v)
    if kind == "pct":
        return fmt_pct(v)
    if kind == "x":
        return fmt_ratio(v)
    if kind == "score":
        return f"{int(v)}/9" if v is not None else "—"
    return str(v)


def _corp_picker() -> None:
    st.subheader("비교 기업 선택")
    chosen: list[str] = st.session_state.setdefault(_CMP_KEY, [])

    c1, c2 = st.columns([3, 1])
    with c1:
        q = st.text_input("기업 검색", key="cmp_query", placeholder="삼성전자 / 005930")
    if q:
        results = cache.search_corps(q, limit=15)
        if results:
            labels = {fmt_corp_identity(r["corp_name"], r["corp_code"],
                                        r.get("stock_code"), r.get("market")): r["corp_code"]
                      for r in results}
            pick = st.selectbox("검색 결과", list(labels.keys()), key="cmp_pick")
            if st.button("➕ 비교에 추가", key="cmp_add"):
                cc = labels[pick]
                if cc not in chosen:
                    chosen.append(cc)
                st.rerun()
        else:
            st.caption("검색 결과 없음")

    if chosen:
        st.caption("현재 비교 대상:")
        for cc in list(chosen):
            meta = cache.resolve_corp(cc)
            name = meta["corp_name"] if meta else cc
            cols = st.columns([4, 1])
            cols[0].write(f"• {name} ({cc})")
            if cols[1].button("제거", key=f"cmp_rm_{cc}"):
                chosen.remove(cc)
                st.rerun()


def render() -> None:
    st.header("⚖️ 기업 비교")
    _corp_picker()

    chosen: list[str] = st.session_state.get(_CMP_KEY, [])
    if len(chosen) < 2:
        st.info("기업을 2개 이상 추가하면 비교표가 표시됩니다.")
        return

    stmt = state.get_stmt_type()
    results = cache.compare_companies(tuple(chosen), stmt)
    if not results:
        st.warning("비교 데이터를 불러오지 못했습니다.")
        return

    # 항목(세로) × 기업(가로)
    headers = [r["corp_name"] for r in results]
    data = {label: [_fmt(kind, r.get(key)) for r in results]
            for label, key, kind in _ROWS}
    df = pd.DataFrame(data, index=headers).T
    df.columns = headers
    st.caption(f"{'연결' if stmt=='consolidated' else '별도'} 기준 · "
               f"`run.py compare` 와 동일 수치")
    st.caption("⚠ 시가총액·PER·PBR·배당수익률 = 각 사 **최신 거래일 종가** 기준입니다. 기업 시각화의 "
               "💰 밸류에이션 탭(FY말 종가 기준)과는 값이 다를 수 있습니다.")
    st.dataframe(df, width="stretch")
