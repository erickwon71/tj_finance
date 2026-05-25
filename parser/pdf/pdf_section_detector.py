"""
PDF 재무제표 섹션 탐지

pdfplumber를 이용해 각 페이지의 재무제표 섹션을 탐지한다.

DART 영업보고서 PDF 구조:
  - 페이지 텍스트에 재무 키워드(재무상태표 등) 포함
  - 동일 페이지에 별도/연결 테이블이 함께 있을 수 있음
  - 테이블 위 bbox 텍스트로 섹션(연결/별도) 구분
  - 단위: "(단위: 백만원)" 형태로 페이지 텍스트에 포함
"""
from __future__ import annotations

import re
from typing import Optional

# ── 재무제표 섹션 키워드 ──────────────────────────────────────────────

# 연결 재무제표 키워드 → fs_type
CONSOL_FS_KEYWORDS: dict[str, str] = {
    '연결재무상태표':     'BS_C',
    '연결포괄손익계산서': 'IS_C',
    '연결손익계산서':     'IS_C',
    '연결현금흐름표':     'CF_C',
    '요약연결재무상태표': 'BS_C',
    '요약연결손익':       'IS_C',
}

# 별도 재무제표 키워드 → fs_type
SEPARATE_FS_KEYWORDS: dict[str, str] = {
    '재무상태표':       'BS_S',
    '포괄손익계산서':   'IS_S',
    '손익계산서':       'IS_S',
    '현금흐름표':       'CF_S',
    '요약재무상태표':   'BS_S',
    '이익잉여금처분':   'IS_S',  # 이익잉여금처분계산서
    # 구형 용어 (2010년 이전 보고서)
    '대차대조표':       'BS_S',   # 재무상태표 구 명칭
    '요약재무정보':     'BS_S',   # 분기보고서 요약 섹션
}

# 모든 키워드 목록 (탐지용)
ALL_FS_KEYWORDS: list[str] = list(CONSOL_FS_KEYWORDS) + list(SEPARATE_FS_KEYWORDS)

# ── 단위 패턴 ─────────────────────────────────────────────────────────

_UNIT_PATTERNS: list[tuple] = [
    (re.compile(r'단위[:\s]*백\s*만\s*원'),  1_000_000),
    (re.compile(r'단위[:\s]*천\s*원'),         1_000),
    (re.compile(r'단위[:\s]*억\s*원'),         100_000_000),
    (re.compile(r'단위[:\s]*원(?!\s*단위)'),   1),
    (re.compile(r'\(백만원\)'),               1_000_000),
    (re.compile(r'\(천원\)'),                 1_000),
]
_DEFAULT_UNIT = 1_000_000  # 영업보고서 기본값: 백만원


def detect_unit_from_text(text: str) -> int:
    """페이지 텍스트에서 단위 배수 탐지. 기본값: 백만원(1_000_000)"""
    for pattern, mult in _UNIT_PATTERNS:
        if pattern.search(text):
            return mult
    return _DEFAULT_UNIT


def classify_from_text(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    텍스트에서 (fs_type, statement_type) 판별.

    연결 키워드를 별도보다 먼저 체크 (연결재무상태표 ⊃ 재무상태표).

    Returns:
        (fs_type, statement_type) — 미탐지 시 (None, None)
    """
    # 연결 먼저 (더 구체적인 키워드)
    for kw, fs_type in CONSOL_FS_KEYWORDS.items():
        if kw in text:
            return fs_type, 'consolidated'

    for kw, fs_type in SEPARATE_FS_KEYWORDS.items():
        if kw in text:
            return fs_type, 'separate'

    return None, None


def classify_table_on_page(
    page,
    table_idx: int,
    fallback_text: str = "",
) -> tuple[Optional[str], Optional[str]]:
    """
    pdfplumber Page에서 table_idx번 테이블의 (fs_type, statement_type) 결정.

    전략:
    1. 단어(word) 위치 기반 탐지 — 이전 테이블 bottom ~ 현재 테이블 top 사이
       구간의 텍스트에서 섹션 키워드를 탐지
    2. 실패 시 페이지 상단 ~ 현재 테이블 top 범위에서 탐지
    3. 최종 실패 시 (None, None) — 전체 페이지 폴백은 사용하지 않음
       (다중 테이블 페이지에서 잘못된 연결/별도 분류 방지)

    Args:
        page:          pdfplumber Page 객체
        table_idx:     페이지 내 테이블 인덱스 (0부터)
        fallback_text: 사용하지 않음 (인터페이스 호환성 유지)
    """
    try:
        tables_info = page.find_tables()
        if not tables_info or table_idx >= len(tables_info):
            return None, None

        # 현재 테이블 위치
        cur_top    = tables_info[table_idx].bbox[1]    # 현재 테이블 top
        cur_bottom = tables_info[table_idx].bbox[3]    # 현재 테이블 bottom

        # 검색 범위: 이전 테이블 bottom (없으면 페이지 상단)
        if table_idx > 0:
            prev_bottom = tables_info[table_idx - 1].bbox[3]
        else:
            prev_bottom = 0

        # ── 1단계: 이전 테이블 bottom ~ 현재 테이블 top 사이 텍스트 ─────
        # 이 범위에 섹션 헤더("연결포괄손익계산서" 등)가 있으면 가장 정확함
        gap_start = max(0, prev_bottom)
        gap_end   = cur_top

        if gap_end > gap_start:
            # 단어 위치 기반으로 섹션 키워드 탐색
            fs_type, stmt = _classify_from_word_positions(page, gap_start, gap_end)
            if fs_type:
                return fs_type, stmt

        # ── 2단계: 페이지 상단 ~ 현재 테이블 top (더 넓은 범위) ────────
        # 첫 번째 테이블이거나 앞 테이블과 같은 섹션 키워드 구간인 경우
        fs_type, stmt = _classify_from_word_positions(page, 0, cur_top)
        if fs_type:
            return fs_type, stmt

    except Exception:
        pass

    return None, None


def _classify_from_word_positions(
    page, top_limit: float, bottom_limit: float
) -> tuple[Optional[str], Optional[str]]:
    """
    페이지의 단어 위치(top 좌표)를 이용해 [top_limit, bottom_limit) 범위 내
    텍스트에서 재무제표 섹션 키워드를 탐지한다.

    단어들의 top 좌표 기준으로 필터링하므로 within_bbox보다 정밀하다.
    """
    try:
        words = page.extract_words(keep_blank_chars=True)
    except Exception:
        return None, None

    # 해당 Y 범위 단어들을 연결해 텍스트 생성
    filtered = [
        w['text'] for w in words
        if top_limit <= w['top'] < bottom_limit
    ]
    combined = ' '.join(filtered)

    return classify_from_text(combined)


def is_financial_table(rows: list[list]) -> bool:
    """
    테이블이 재무 데이터 테이블인지 판별.

    조건:
      1. 최소 3행 이상
      2. 첫 번째 열에 한글 계정과목명 포함
      3. 두 번째 열 이후에 숫자(금액) 포함
    """
    if not rows or len(rows) < 3:
        return False

    # 데이터 행 추출 (빈 행 제외)
    data_rows = [r for r in rows if r and r[0] and str(r[0]).strip()]
    if len(data_rows) < 2:
        return False

    # 첫 번째 열에 한글 포함 여부
    has_korean = any(
        any('가' <= c <= '힣' for c in str(row[0] or ''))
        for row in data_rows
    )
    if not has_korean:
        return False

    # 금액 컬럼(2열~)에 숫자 포함 여부
    for row in data_rows[:6]:
        for cell in (row[1:] if len(row) > 1 else []):
            cell_str = re.sub(r'[,\(\)\s]', '', str(cell or ''))
            if cell_str and cell_str.lstrip('-').isdigit():
                return True

    return False


def find_financial_pages(pdf) -> list[dict]:
    """
    PDF 전체 페이지에서 재무제표 관련 페이지 목록 반환.

    Returns:
        list of {
            'page_idx': int,
            'page':     pdfplumber.Page,
            'text':     str,
            'unit':     int,       단위 배수
            'keywords': list[str], 탐지된 재무 키워드
        }
    """
    result: list[dict] = []

    for i, page in enumerate(pdf.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            continue

        found = [kw for kw in ALL_FS_KEYWORDS if kw in text]
        if not found:
            continue

        result.append({
            'page_idx': i,
            'page':     page,
            'text':     text,
            'unit':     detect_unit_from_text(text),
            'keywords': found,
        })

    return result


def is_text_based_pdf(pdf, sample_pages: int = 5) -> bool:
    """
    PDF가 텍스트 기반인지 확인 (이미지 스캔 PDF 감지).

    처음 sample_pages 페이지의 평균 텍스트 길이로 판별.
    평균 50자 미만이면 이미지 PDF로 간주.
    """
    total_text = 0
    checked    = 0

    for page in list(pdf.pages)[:sample_pages]:
        try:
            t = page.extract_text() or ""
            total_text += len(t)
            checked += 1
        except Exception:
            continue

    if checked == 0:
        return False

    avg_chars = total_text / checked
    return avg_chars >= 50
