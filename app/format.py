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
