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
from app.cache import resolve_corp, search_corps, table_counts  # noqa: E402
from app.format import fmt_corp_identity  # noqa: E402
from app.views import (  # noqa: E402
    chart_builder_page, collect_page, company_page, compare_page, help_page,
    quarter_change_page, screener_page, valuation_page,
)


def _watchlist_sidebar() -> None:
    """⭐ 관심종목 — 저장된 corp 를 클릭해 바로 포커스 이동, ❌ 로 해제."""
    from app.data import watchlist as wl

    corps = wl.get_watchlist()
    with st.expander(f"⭐ 관심종목 ({len(corps)})", expanded=bool(corps)):
        if not corps:
            st.caption("기업 시각화 페이지에서 ⭐ 버튼으로 추가하세요.")
            return
        for cc in corps:
            meta = resolve_corp(cc)
            name = meta["corp_name"] if meta else cc
            code = (meta.get("stock_code") if meta else None) or cc
            c1, c2 = st.columns([5, 1])
            if c1.button(f"{name} · {code}", key=f"wl_go_{cc}", width="stretch"):
                state.set_focus_corp(cc)
                st.rerun()
            if c2.button("❌", key=f"wl_rm_{cc}", help="관심종목 해제"):
                wl.remove(cc)
                st.rerun()


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
                label = fmt_corp_identity(r["corp_name"], r["corp_code"], r.get("stock_code"), r.get("market"))
                already_focused = state.get_focus_corp() == r["corp_code"]
                st.caption(f"{'✅' if already_focused else '🔎'} {label}")
                if st.session_state.get("_auto_pick_q") != query:
                    st.session_state["_auto_pick_q"] = query
                    state.set_focus_corp(r["corp_code"])
                    st.rerun()
                elif not already_focused:
                    # 자동선택 가드가 막았어도(스크리너 등에서 포커스가 옮겨간 뒤 같은 검색어로
                    # 되돌아온 경우) 이 버튼으로 항상 다시 전환할 수 있게 한다.
                    st.caption("← 스크리너 등에서 다른 기업이 선택됨")
                    if st.button("이 기업 다시 보기", key="corp_single_repick", width="stretch"):
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

        _watchlist_sidebar()

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


def _quit_button_topbar() -> None:
    """상단 'Deploy' 자리 바로 아래에 종료 버튼을 고정 배치. 로컬 데스크톱 전용 앱이라
    배포 버튼은 쓸모가 없어 숨기고, 그 아래에 종료 버튼을 둬 사이드바 스크롤 없이 항상
    보이게 한다. Streamlit 자체 툴바 행(0~60px, Deploy·⋮메뉴·"Running…" 표시줄)과 같은
    줄에 두면 재실행 중 "Running…" 표시가 넓어질 때 버튼과 겹치므로, 그 아래 줄(top 4rem)
    에 배치해 겹칠 일이 구조적으로 없게 한다."""
    st.markdown("""
        <style>
        [data-testid="stAppDeployButton"] { display: none; }
        div[data-testid="stElementContainer"]:has(#tj-quit-anchor)
            + div[data-testid="stElementContainer"] {
            position: fixed; top: 4rem; right: 1.2rem; z-index: 999999;
        }
        </style>
        <div id="tj-quit-anchor"></div>
        """, unsafe_allow_html=True)
    if st.button("🛑 앱 종료", key="quit_app_topbar",
                 help="Streamlit 서버와 이 앱을 실행한 터미널 창을 함께 닫습니다."):
        st.info("앱을 종료합니다. 잠시 후 이 창과 터미널이 자동으로 닫힙니다…")
        import time

        from app.shutdown import shutdown_app
        time.sleep(0.8)  # 위 안내 메시지가 브라우저로 전달될 시간을 확보
        shutdown_app()


def main() -> None:
    st.set_page_config(page_title="TJ Finance", page_icon="📊", layout="wide")
    state.init_defaults()
    _quit_button_topbar()
    _sidebar()

    pages = [
        # DEF-1(딥링크 첫 진입 시 'Page not found' 모달)은 이 default 페이지에 url_path 를
        # 붙이든 떼든 /company 직접진입에서 동일하게 재현되는 Streamlit 프레임워크 동작임을
        # 실측 확인함(정상 진입 경로 '/'는 모달 없음). url_path 를 떼면 /company 딥링크만
        # 잃고 모달은 그대로라, 딥링크를 유지하는 원상태를 둔다. 근본해소는 Streamlit
        # 버전 업그레이드 백로그로 이관.
        st.Page(company_page.render, title="기업 시각화", icon="📈",
                url_path="company", default=True),
        st.Page(screener_page.render, title="스크리너", icon="🔎",
                url_path="screener"),
        st.Page(quarter_change_page.render, title="분기 변화", icon="📊",
                url_path="quarter-change"),
        st.Page(valuation_page.render, title="밸류에이션", icon="💎",
                url_path="valuation"),
        st.Page(compare_page.render, title="기업 비교", icon="⚖️",
                url_path="compare"),
        st.Page(chart_builder_page.render, title="자유조합 차트", icon="🧪",
                url_path="chart-builder"),
        st.Page(collect_page.render, title="보고서 수집", icon="🗂",
                url_path="collect"),
        st.Page(help_page.render, title="도움말", icon="ℹ️",
                url_path="help"),
    ]
    st.navigation(pages).run()


main()
