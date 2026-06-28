"""
session_state 키 상수 + 타입드 게터/세터.

Streamlit 은 상호작용마다 스크립트를 전체 재실행하므로, 페이지 간 공유 선택값
(현재 기업·연결/별도·분기/연간 등)은 session_state 에 보관한다. 키 문자열을 흩뿌리지
않도록 여기에 모은다.
"""
from __future__ import annotations

from typing import Optional

import streamlit as st

# ── 키 상수 ──────────────────────────────────────────────
FOCUS_CORP = "focus_corp"          # 현재 시각화 대상 corp_code
STMT_TYPE = "stmt_type"            # "consolidated" | "separate"
GRAIN = "grain"                    # "annual" | "quarter"
SCREEN_RESULTS = "screen_results"  # 스크리너 결과 DataFrame (비파괴 분할용)
QUANT_PASSES = "quant_passes"      # 퀀트 다단계 패스 리스트 (<=4)

# ── 표시 라벨 ↔ 내부값 매핑 ──────────────────────────────
STMT_LABELS = {"연결": "consolidated", "별도": "separate"}
STMT_LABELS_INV = {v: k for k, v in STMT_LABELS.items()}
GRAIN_LABELS = {"연간": "annual", "분기": "quarter"}
GRAIN_LABELS_INV = {v: k for k, v in GRAIN_LABELS.items()}


def init_defaults() -> None:
    """앱 시작 시 session_state 기본값을 1회 세팅."""
    st.session_state.setdefault(FOCUS_CORP, None)
    st.session_state.setdefault(STMT_TYPE, "consolidated")
    st.session_state.setdefault(GRAIN, "annual")
    st.session_state.setdefault(QUANT_PASSES, [])


def get_focus_corp() -> Optional[str]:
    return st.session_state.get(FOCUS_CORP)


def set_focus_corp(corp_code: Optional[str]) -> None:
    st.session_state[FOCUS_CORP] = corp_code


def get_stmt_type() -> str:
    return st.session_state.get(STMT_TYPE, "consolidated")


def get_grain() -> str:
    return st.session_state.get(GRAIN, "annual")
