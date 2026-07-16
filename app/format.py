"""
표시 포맷 헬퍼.

기존 analyzer/display/table_view.py 의 포맷터를 재export 하여 억원/조원/%/x 렌더링을
앱 전역에서 일관 사용한다. table_view 는 Rich 마크업([green]…[/green])을 섞으므로,
Streamlit/Plotly 용 순수 문자열 포맷터를 별도로 제공한다.

저장 단위는 항상 원(KRW). 표시 경계에서만 변환한다.
"""
from __future__ import annotations

from typing import Optional

# 기존 포맷터 재export (Rich 마크업 포함 — 터미널/디버그용)
from analyzer.display.table_view import (  # noqa: F401
    _fmt_amount as rich_fmt_amount,
    _fmt_pct as rich_fmt_pct,
    _fmt_ratio as rich_fmt_ratio,
    _period_label as period_label,
)

EOK = 100_000_000        # 1억
JO = 1_000_000_000_000   # 1조


def won_to_eok(value: Optional[float]) -> Optional[float]:
    """원 → 억원 (숫자). None 안전."""
    if value is None:
        return None
    return value / EOK


def fmt_amount(value: Optional[float], decimals: int = 0) -> str:
    """억원 문자열. ≥1만억(=1조)이면 조 단위로 자동 전환. Rich 마크업 없음."""
    if value is None:
        return "—"
    eok = value / EOK
    if abs(eok) >= 10_000:
        return f"{value / JO:,.1f}조"
    return f"{eok:,.{decimals}f}억"


def fmt_pct(value: Optional[float], decimals: int = 1) -> str:
    """비율(소수) → % 문자열. Rich 마크업 없음."""
    if value is None:
        return "—"
    return f"{value * 100:.{decimals}f}%"


def fmt_ratio(value: Optional[float], suffix: str = "x", decimals: int = 1) -> str:
    """멀티플 → 'x' 문자열."""
    if value is None:
        return "—"
    return f"{value:.{decimals}f}{suffix}"


def render_dataframe(df, *, num_cols=None, pct_cols=None, na: str = "—",
                     hide_index: bool = True, width: str = "stretch",
                     column_config=None, **kwargs):
    """결측(None/NaN)을 안전하게 렌더하는 st.dataframe 공통 래퍼 (P0-4).

    st.dataframe 은 결측을 **문자 그대로 'None'** 으로 렌더한다 — object 컬럼의 Python None 은
    물론, **float64 의 NaN 도(NumberColumn 유무와 무관하게)** 'None' 으로 표시된다(Streamlit 1.50
    격리테스트로 확인). 그래서 안전한 유일한 방법은 **셀을 문자열로 포맷하며 결측을 na("—")로 치환**
    하는 것이다(회사 시각화 재무제표 표 `_show_statement` 가 쓰던 검증된 패턴을 공통화).
    이 헬퍼로만 표를 그리면 'None' 노출이 구조적으로 차단된다(외부평가 2026-07-15).

    - num_cols: 금액/개수 컬럼 → 천단위 구분 정수 문자열(`1,234`), 결측 na.
    - pct_cols: 비율(%) 컬럼 → 소수1자리+`%`(`12.3%`), 결측 na.
    - 그 외 object 컬럼: None/NaN → na.
    주의: 문자열화되므로 UI 숫자 정렬은 사전(pandas)정렬에 의존(대상 표는 문제 없음).
    """
    import pandas as pd
    import streamlit as st

    def _isna(v) -> bool:
        return v is None or (isinstance(v, float) and pd.isna(v))

    def _num(v):
        return na if _isna(v) else f"{v:,.0f}"

    def _pct(v):
        return na if _isna(v) else f"{v:.1f}%"

    disp = df.copy()
    numset, pctset = set(num_cols or []), set(pct_cols or [])
    for col in disp.columns:
        if col in numset:
            disp[col] = disp[col].map(_num)
        elif col in pctset:
            disp[col] = disp[col].map(_pct)
        elif disp[col].dtype == object:
            disp[col] = disp[col].map(lambda v: na if _isna(v) else v)
    return st.dataframe(disp, hide_index=hide_index, width=width,
                        column_config=column_config, **kwargs)


def fmt_corp_identity(corp_name: str, corp_code: str, stock_code: Optional[str] = None,
                      market: Optional[str] = None) -> str:
    """기업명 + 종목코드 + corp_code 동시 표시 (앱 전역 규약)."""
    parts = [corp_name]
    if stock_code:
        parts.append(f"({stock_code})")
    bits = " ".join(parts)
    tail = f" · {corp_code}"
    if market:
        tail += f" · {market}"
    return bits + tail


# ── 특별 조치 각주(주n) — 기업명 옆 마커 + 도움말 페이지 설명의 단일 출처 ──
# 각주 키(주n) → 설명. app/views/help_page.py 가 이 매핑을 그대로 렌더한다.
CORP_NOTES: dict[str, str] = {
    "주1": ("**비-12월 결산** — 결산월이 12월이 아닌 기업. 분기·비교 화면의 수치는 각 사의 "
            "회계분기를 **달력분기(1–3월=Q1 …)로 재배치·합성(recomposed)**한 값이라, 회사가 "
            "보고한 **회계연도(FY)와 기간이 다릅니다**. (예: 6월 결산사의 달력 CY2025 = 2025년 "
            "1–12월, 회계 FY2025 = 2024.7–2025.6)"),
    "주2": ("**별도 기준 대체** — 연결(consolidated) 재무제표를 요청했으나 해당 기업·기간에 "
            "연결이 없어 **별도(개별) 재무제표**로 대체 표시한 값입니다. (종속기업이 없어 연결을 "
            "작성하지 않는 경우 등)"),
    "주3": ("**시장조치/규제 지정 이력** — 거래소(KRX)가 관리종목 지정·상장폐지 관련·매매거래정지·"
            "불성실공시법인 지정·회생절차 개시 등 투자위험 관련 조치를 취한 이력이 있는 기업입니다. "
            "현재도 해제되지 않은 조치가 있습니다. 상세 사유·시점은 기업 화면의 **⚠ 시장조치 이력** "
            "패널을 참고하세요."),
}


def corp_notes(fiscal_month: Optional[int] = None,
               used_stmt: Optional[str] = None,
               requested_stmt: Optional[str] = None,
               has_regulatory_flag: bool = False) -> list[str]:
    """기업에 적용된 특별 조치 각주 키 목록(예: ['주1','주2']).

    - 주1: 비-12월 결산(fiscal_month != 12) → 달력분기 재구성.
    - 주2: 연결 요청인데 별도로 대체된 경우(used_stmt != requested_stmt).
    - 주3: 활성(미해제) 시장조치/규제 지정 이력이 있는 경우.
    """
    notes: list[str] = []
    if fiscal_month is not None and fiscal_month != 12:
        notes.append("주1")
    if used_stmt and requested_stmt and used_stmt != requested_stmt:
        notes.append("주2")
    if has_regulatory_flag:
        notes.append("주3")
    return notes


def fmt_notes(notes: list[str]) -> str:
    """['주1','주2'] → ' (주1)(주2)'. 빈 목록이면 '' (앞 공백 포함)."""
    return (" " + "".join(f"({n})" for n in notes)) if notes else ""
