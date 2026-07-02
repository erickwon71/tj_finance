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
            "회계분기를 **달력분기(1~3월=Q1 …)로 재배치·합성(recomposed)**한 값이라, 회사가 "
            "보고한 **회계연도(FY)와 기간이 다릅니다**. (예: 6월 결산사의 달력 CY2025 = 2025년 "
            "1~12월, 회계 FY2025 = 2024.7~2025.6)"),
    "주2": ("**별도 기준 대체** — 연결(consolidated) 재무제표를 요청했으나 해당 기업·기간에 "
            "연결이 없어 **별도(개별) 재무제표**로 대체 표시한 값입니다. (종속기업이 없어 연결을 "
            "작성하지 않는 경우 등)"),
}


def corp_notes(fiscal_month: Optional[int] = None,
               used_stmt: Optional[str] = None,
               requested_stmt: Optional[str] = None) -> list[str]:
    """기업에 적용된 특별 조치 각주 키 목록(예: ['주1','주2']).

    - 주1: 비-12월 결산(fiscal_month != 12) → 달력분기 재구성.
    - 주2: 연결 요청인데 별도로 대체된 경우(used_stmt != requested_stmt).
    """
    notes: list[str] = []
    if fiscal_month is not None and fiscal_month != 12:
        notes.append("주1")
    if used_stmt and requested_stmt and used_stmt != requested_stmt:
        notes.append("주2")
    return notes


def fmt_notes(notes: list[str]) -> str:
    """['주1','주2'] → ' (주1)(주2)'. 빈 목록이면 '' (앞 공백 포함)."""
    return (" " + "".join(f"({n})" for n in notes)) if notes else ""
