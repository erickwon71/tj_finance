"""
PDF 재무제표 테이블 행 추출

pdfplumber의 extract_table() 결과(list[list[str|None]])를
계정과목명·금액 구조의 PdfRowData 리스트로 변환한다.

XML 파서의 RowData(table_extractor.py)와 유사한 인터페이스를 제공하여
account_mapper와 amount_normalizer를 동일하게 활용할 수 있도록 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ── 데이터 구조 ───────────────────────────────────────────────────────

@dataclass
class PdfRowData:
    """PDF 테이블에서 추출된 단일 재무 행"""
    account_name: str               # 정제된 계정과목명 (한글)
    account_name_raw: str           # 원문 계정과목명 (로마숫자 접두어 포함)
    amounts: list[Optional[int]]    # [당기, 전기, 전전기, ...] (원 단위)
    row_order: int
    is_subtotal: bool = False


# ── 상수 ─────────────────────────────────────────────────────────────

# 헤더 행으로 판단할 첫 셀 값
_HEADER_EXACT = {'과목', '항목', '구분', '계정과목', '내역'}
_HEADER_PREFIXES = ('제', '당기', '전기', '제1')  # '제49기', '당기' 등

# 로마숫자 접두어: "I. ", "II. " ... "XXIV. "
_ROMAN_PREFIX = re.compile(r'^[IVXivx]+[.．]\s*')

# 음수 표현: (숫자), △숫자, -숫자
_NEG_PAREN  = re.compile(r'^[\(（]([\d,]+)[\)）]$')
_NEG_DELTA  = re.compile(r'^[△▲]([\d,]+)$')
_NEG_MINUS  = re.compile(r'^-[\d,]+$')

# 합계·소계 판별 키워드
_SUBTOTAL_KEYWORDS = (
    '합계', '총계', '자산총', '부채총', '자본총',
    '당기순', '순이익', '순손실', '영업이익합계',
)

# 완전 무시할 셀 값
_NULL_CELLS = {'-', '–', '−', '△', '—', 'N/A', '해당없음', '', ' ', '-'}


# ── 금액 파싱 ─────────────────────────────────────────────────────────

def parse_amount_cell(cell: Optional[str], multiplier: int = 1) -> Optional[int]:
    """
    PDF 테이블 셀에서 금액을 파싱해 원 단위 정수로 반환.

    Args:
        cell:       "380,898", "(28,065)", "△3,690", "-", None 등
        multiplier: 단위 배수 (1=원, 1_000=천원, 1_000_000=백만원)

    Returns:
        원 단위 금액 (None = 빈 값·해당없음)
    """
    if cell is None:
        return None

    s = str(cell).strip().replace('\n', '').replace(' ', '').replace('\xa0', '')
    if not s or s in _NULL_CELLS:
        return None

    # 음수 판별
    is_negative = (
        bool(_NEG_PAREN.match(s)) or
        bool(_NEG_DELTA.match(s)) or
        bool(_NEG_MINUS.match(s))
    )

    # 숫자만 추출
    digits = re.sub(r'[^\d]', '', s)
    if not digits:
        return None

    try:
        amount = int(digits) * multiplier
        return -amount if is_negative else amount
    except (ValueError, OverflowError):
        return None


# ── 헤더 판별 ─────────────────────────────────────────────────────────

def is_header_row(row: list) -> bool:
    """행이 헤더인지 판별 ('과목', '제X기', '당기/전기' 등)"""
    if not row or not row[0]:
        return False
    first = str(row[0]).strip()

    # 완전 일치
    if first in _HEADER_EXACT:
        return True

    # 접두어 매칭
    for pfx in _HEADER_PREFIXES:
        if first.startswith(pfx):
            return True

    return False


# ── 계정명 정제 ───────────────────────────────────────────────────────

def clean_account_name(raw: str) -> str:
    """
    계정과목명 정제.

    1. 로마숫자 접두어 제거: "I. 매출액" → "매출액"
    2. 줄바꿈·공백 정리
    3. 숫자·점만 남는 경우 원문 반환
    """
    cleaned = raw.strip().replace('\n', ' ')
    # 로마숫자 접두어 제거
    cleaned = _ROMAN_PREFIX.sub('', cleaned).strip()
    # 결과가 너무 짧으면 원문 반환
    return cleaned if len(cleaned) >= 2 else raw.strip()


# ── 메인 추출 ─────────────────────────────────────────────────────────

def extract_financial_rows(
    table_rows: list[list],
    multiplier: int = 1_000_000,
) -> list[PdfRowData]:
    """
    pdfplumber extract_table() 결과에서 재무 행 리스트 추출.

    Args:
        table_rows: pdfplumber Table.extract() 반환값
        multiplier: 단위 배수 (기본값: 백만원)

    Returns:
        list[PdfRowData] — 유효한 재무 행만 포함
    """
    result: list[PdfRowData] = []
    row_order = 0

    for row in table_rows:
        if not row:
            continue

        # ── 첫 셀: 계정과목명 ──────────────────────────────────────
        account_raw = str(row[0] or '').strip().replace('\n', ' ')
        if not account_raw:
            continue

        # 헤더 행 스킵
        if is_header_row(row):
            continue

        # 한글 포함 여부 확인 (계정과목명 필수)
        if not any('가' <= c <= '힣' for c in account_raw):
            continue

        # ── 금액 컬럼 파싱 ────────────────────────────────────────
        amounts: list[Optional[int]] = []
        for cell in row[1:]:
            amounts.append(parse_amount_cell(cell, multiplier))

        if not amounts:
            continue

        # 금액이 모두 None인 행 스킵 (텍스트 설명 행)
        if all(a is None for a in amounts):
            continue

        # ── 계정명 정제 ───────────────────────────────────────────
        account_clean = clean_account_name(account_raw)

        # ── 합계/소계 판별 ────────────────────────────────────────
        is_subtotal = any(kw in account_clean for kw in _SUBTOTAL_KEYWORDS)

        result.append(PdfRowData(
            account_name=account_clean,
            account_name_raw=account_raw,
            amounts=amounts,
            row_order=row_order,
            is_subtotal=is_subtotal,
        ))
        row_order += 1

    return result


def detect_num_amount_cols(table_rows: list[list]) -> int:
    """
    테이블의 금액 컬럼 수를 추정 (헤더 행 분석).

    '과목' 이후 컬럼이 금액 컬럼으로 추정된다.
    최소 1, 최대 4(당기·전기·전전기·그 이전).

    Returns:
        추정 금액 컬럼 수 (0 = 판별 불가)
    """
    for row in table_rows[:3]:
        if not row:
            continue
        first = str(row[0] or '').strip()
        if first in _HEADER_EXACT or any(first.startswith(p) for p in _HEADER_PREFIXES):
            return max(0, len(row) - 1)
    return 0
