"""
표제기반 본문 재무제표 표 식별 (Track B 추출기 + Gate B 감사 reader 공용).

DART 본문은 `<TABLE-GROUP>[표제 TABLE("(연결) 재무상태표 제N기..."), 데이터 TABLE]` 또는
`<P>연결재무상태표</P> + 데이터 TABLE` 구조다. 데이터 TABLE 의 **직전 형제 텍스트(표제)** 에
statement 명 + 기간마커가 있고 요약/주석/분할·합병/자본변동이 아니면 그 TABLE 이 본문 face 다.

이 방식은 복잡문서(분할·기재정정)에서 `find_section_tables` 전방수집이 2차 조정표/요약을
오연결하던 문제(NAVER false-fail, 00259545 오추출, 00111838 0행)를 구조적으로 회피한다.

추출기(`fin2/extract/text.py`)와 감사 reader(`fin2/audit/face_audit.py`)가 이 단일 로직을
공유한다(패턴 드리프트 방지).
"""
from __future__ import annotations

import re

# 본문 재무제표 표제 패턴(제목 표 텍스트에서). 요약/주석/분할·합병/자본변동표 배제.
_STMT_TITLE = [
    (re.compile(r"재무상태표|대차대조표"), "BS"),
    (re.compile(r"포괄손익계산서|손익계산서"), "IS"),
    (re.compile(r"현금흐름표"), "CF"),
]
# 본문 표제임을 확정하는 기간 마커(요약표·일반표 배제용).
_PERIOD_MARK = re.compile(r"제\s*\d+\s*기|반기말|분기말|기말|현재|\d{4}\s*[.\-]\s*\d{1,2}\s*[.\-]\s*\d{1,2}")
# 본문 face 표가 아닌 표제(주석·요약·분할·자본변동·세부명세) 배제.
_TITLE_EXCLUDE = re.compile(r"분할|합병|주석|요약|자본변동|변동표|명세|부속")
_CONSOL_TITLE = re.compile(r"연결\s*(재무상태표|대차대조표|포괄손익계산서|손익계산서|현금흐름표)")

# (basis, statement) → fact_v2 섹션 코드.
SECTION_CODE_OF: dict[tuple[str, str], str] = {
    ("consolidated", "BS"): "BS_C", ("consolidated", "IS"): "IS_C", ("consolidated", "CF"): "CF_C",
    ("separate", "BS"): "BS_S", ("separate", "IS"): "IS_S", ("separate", "CF"): "CF_S",
}


def title_text(tbl) -> str:
    """데이터 표의 표제 텍스트. DART 본문은 <TABLE-GROUP>[표제 TABLE, 데이터 TABLE] 구조라
    표제가 직전 형제 TABLE/<P> 에 들어있다 → 직전 형제(태그 무관) 텍스트를 표제로 본다."""
    prev = tbl.getprevious()
    if prev is None:
        return ""
    return " ".join("".join(prev.itertext()).split())[:200]


def classify_statement_title(title: str) -> tuple[str, str] | None:
    """표제 → (basis, statement) 또는 None(본문 재무제표 표 아님).

    basis ∈ {"consolidated","separate"}, statement ∈ {"BS","IS","CF"}.
    """
    if not title or not _PERIOD_MARK.search(title):
        return None
    head = title[:45]
    if _TITLE_EXCLUDE.search(head):
        return None
    stmt = None
    for pat, s in _STMT_TITLE:
        if pat.search(head):
            stmt = s
            break
    if stmt is None:
        return None
    basis = "consolidated" if _CONSOL_TITLE.search(title) else "separate"
    return (basis, stmt)
