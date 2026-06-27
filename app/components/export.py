"""
표 데이터 CSV export.

사용자 결정: CSV 단독. export 값은 표시(억원)와 무관하게 **raw 원**을 보존한다.
한글 깨짐 방지를 위해 UTF-8 BOM(utf-8-sig)으로 인코딩(엑셀 호환).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st


def to_csv_bytes(df: pd.DataFrame, index: bool = True) -> bytes:
    """DataFrame → CSV 바이트(utf-8-sig). 엑셀에서 한글 정상 표시."""
    return df.to_csv(index=index).encode("utf-8-sig")


def download_button(df: pd.DataFrame, filename: str, label: str = "⬇ CSV 다운로드",
                    index: bool = True, key: str | None = None) -> None:
    """raw 데이터(원 단위) CSV 다운로드 버튼."""
    st.download_button(
        label=label,
        data=to_csv_bytes(df, index=index),
        file_name=filename,
        mime="text/csv",
        key=key,
        width="content",
    )
