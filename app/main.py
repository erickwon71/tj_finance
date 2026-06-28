"""
tj_finance 시각화 + 스크리너 앱 — 진입점.

실행: `streamlit run app/main.py` (프로젝트 루트에서)

구성: 글로벌 사이드바(기업검색 · 연결/별도 · 분기/연간) + st.navigation(Company/Screener).
"""
from __future__ import annotations

import sys
from pathlib import Path

# streamlit 은 스크립트 디렉터리(app/)를 sys.path[0] 으로 넣으므로,
# collector/analyzer/app 절대 import 를 위해 프로젝트 루트를 경로에 추가한다.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app import state  # noqa: E402
from app.cache import search_corps, table_counts  # noqa: E402
from app.format import fmt_corp_identity  # noqa: E402
from app.views import (  # noqa: E402
    company_page, compare_page, screener_page, valuation_page,
)


def _sidebar() -> None:
    """글로벌 사이드바 — 모든 페이지 공유 선택값."""
    with st.sidebar:
        st.title("📊 TJ Finance")

        # ── 기업 검색 ──
        st.subheader("기업 검색")
        query = st.text_input("기업명 또는 종목코드", key="corp_query",
                              placeholder="예: 삼성전자 / 005930")
        if query:
            results = search_corps(query, limit=30)
            if not results:
                st.caption("검색 결과 없음")
            elif len(results) == 1:
                # 결과가 1개면 선택 단계 없이 바로 표시.
                # 검색어가 바뀐 경우에만 자동선택(스크리너 행클릭 등 다른 선택을 덮지 않도록).
                r = results[0]
                st.caption(f"✅ {fmt_corp_identity(r['corp_name'], r['corp_code'], r.get('stock_code'), r.get('market'))}")
                if st.session_state.get("_auto_pick_q") != query:
                    st.session_state["_auto_pick_q"] = query
                    state.set_focus_corp(r["corp_code"])
                    st.rerun()
            else:
                labels = {
                    fmt_corp_identity(r["corp_name"], r["corp_code"],
                                      r.get("stock_code"), r.get("market")): r["corp_code"]
                    for r in results
                }
                picked = st.radio("결과", list(labels.keys()), key="corp_pick",
                                  label_visibility="collapsed")
                if st.button("선택", width="stretch"):
                    state.set_focus_corp(labels[picked])
                    st.rerun()

        st.divider()

        # ── 표시 옵션 (전역) ──
        st.subheader("표시 옵션")
        stmt_opts = list(state.STMT_LABELS.keys())
        stmt_label = st.radio(
            "재무제표", stmt_opts, horizontal=True, key="stmt_seg",
            index=stmt_opts.index(state.STMT_LABELS_INV.get(state.get_stmt_type(), "연결")))
        st.session_state[state.STMT_TYPE] = state.STMT_LABELS[stmt_label]

        grain_opts = list(state.GRAIN_LABELS.keys())
        grain_label = st.radio(
            "기간", grain_opts, horizontal=True, key="grain_seg",
            index=grain_opts.index(state.GRAIN_LABELS_INV.get(state.get_grain(), "연간")))
        st.session_state[state.GRAIN] = state.GRAIN_LABELS[grain_label]

        # ── DB 연결 스모크 ──
        with st.expander("DB 상태", expanded=False):
            try:
                counts = table_counts()
                st.success("DB 연결 OK")
                st.write(
                    f"활성 보통주 **{counts.get('active_corps', 0):,}** · "
                    f"재무행 **{counts.get('std_rows', 0):,}** · "
                    f"주가행 **{counts.get('price_rows', 0):,}**"
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"DB 연결 실패: {exc}")


def main() -> None:
    st.set_page_config(page_title="TJ Finance", page_icon="📊", layout="wide")
    state.init_defaults()
    _sidebar()

    pages = [
        st.Page(company_page.render, title="기업 시각화", icon="📈",
                url_path="company", default=True),
        st.Page(screener_page.render, title="스크리너", icon="🔎",
                url_path="screener"),
        st.Page(valuation_page.render, title="밸류에이션", icon="💎",
                url_path="valuation"),
        st.Page(compare_page.render, title="기업 비교", icon="⚖️",
                url_path="compare"),
    ]
    st.navigation(pages).run()


main()
