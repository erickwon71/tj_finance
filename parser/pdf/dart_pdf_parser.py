"""
DART PDF 파서 — 영업보고서 요약 재무제표 추출

대상: DART 영업보고서 PDF (annual/half/quarter)
전략:
  1. pdfplumber로 텍스트 추출 가능 여부 확인 (이미지 PDF 감지)
  2. 재무제표 키워드가 포함된 페이지 탐지
  3. 각 페이지의 테이블에서 계정과목·금액 추출
  4. account_mapper로 표준 코드 매핑
  5. ParseResult(FactRow) 반환 (XML 파서와 동일 인터페이스)

한계:
  - 이미지 스캔 PDF: parse_status='skip' (OCR 없이 파싱 불가)
  - 요약 재무제표만 포함 (완전한 주석 미포함)
  - 금액은 보통 백만원 단위 (영업보고서 관행)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from loguru import logger

# XML 파서의 ParseResult·FactRow 재사용 (동일 테이블에 저장)
from parser.xml.dart_xml_parser import ParseResult, FactRow
from parser.common.account_mapper import get_mapper, MappingResult
from parser.common.amount_normalizer import normalize_account_name

from parser.pdf.pdf_section_detector import (
    find_financial_pages,
    is_text_based_pdf,
    classify_table_on_page,
    is_financial_table,
)
from parser.pdf.pdf_table_extractor import (
    extract_financial_rows,
    PdfRowData,
)

# ── fs_type → (statement_type, period_type) 매핑 ─────────────────────

_FS_META: dict[str, tuple[str, str]] = {
    'BS_C': ('consolidated', 'point_in_time'),
    'IS_C': ('consolidated', 'cumulative_ytd'),
    'CF_C': ('consolidated', 'cumulative_ytd'),
    'BS_S': ('separate',     'point_in_time'),
    'IS_S': ('separate',     'cumulative_ytd'),
    'CF_S': ('separate',     'cumulative_ytd'),
}

# 연간 보고서 기간 유형 보정
_ANNUAL_PERIOD_TYPE: dict[str, str] = {
    'BS_C': 'point_in_time',
    'IS_C': 'annual',
    'CF_C': 'annual',
    'BS_S': 'point_in_time',
    'IS_S': 'annual',
    'CF_S': 'annual',
}


# ── 메인 파서 ─────────────────────────────────────────────────────────

def parse_dart_pdf(
    file_path: Path,
    rcept_no:  str,
    corp_code: str,
    fiscal_year:   int,
    fiscal_period: str,
    report_type:   str,
) -> ParseResult:
    """
    단일 DART PDF 파일을 파싱해 ParseResult를 반환한다.

    XML 파서(parse_dart_xml)와 동일한 시그니처·반환 타입.

    Args:
        file_path:    PDF 파일 경로
        rcept_no:     DART 접수번호
        corp_code:    DART 기업코드
        fiscal_year:  회계연도 (정수)
        fiscal_period: FY / H1 / Q1 / Q3
        report_type:  annual / half / quarter
    """
    result = ParseResult(
        rcept_no=rcept_no,
        corp_code=corp_code,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        report_type=report_type,
        fin_type='B',          # 기본값 (별도만); 연결 탐지 시 'A'로 변경
        is_ifrs=True,
        unit_multiplier=1,     # 개별 facts는 원 단위로 저장
        parser_track='PDF',
    )

    try:
        import pdfplumber
    except ImportError:
        result.parse_status = 'failed'
        result.errors.append('pdfplumber 미설치: pip install pdfplumber')
        return result

    try:
        with pdfplumber.open(str(file_path)) as pdf:
            # ── 이미지 PDF 감지 ──────────────────────────────────
            if not is_text_based_pdf(pdf, sample_pages=6):
                result.parse_status = 'skip'
                result.errors.append('이미지 스캔 PDF — 텍스트 추출 불가')
                return result

            # ── 정정신고 커버 문서 감지 ─────────────────────────
            # "정정 신고" 3~5페이지 커버 문서 → 재무 데이터 없음 → skip
            if _is_correction_cover(pdf):
                result.parse_status = 'skip'
                result.errors.append('정정신고 커버 문서 — 첨부파일 참조용')
                return result

            # ── 재무 페이지 탐지 ─────────────────────────────────
            fin_pages = find_financial_pages(pdf)
            if not fin_pages:
                result.parse_status = 'partial'
                result.errors.append('재무제표 섹션 미탐지 (키워드 없음)')
                return result

            # ── 각 페이지·테이블 파싱 ────────────────────────────
            mapper = get_mapper()
            seen_tables: set[str] = set()    # 중복 테이블 방지 (내용 해시)

            for page_info in fin_pages:
                page = page_info['page']
                page_text = page_info['text']
                unit = page_info['unit']
                page_no = page_info['page_idx'] + 1

                try:
                    raw_tables = page.extract_tables()
                except Exception as e:
                    logger.debug(f"테이블 추출 실패 [p{page_no}]: {e}")
                    continue

                # ── 1패스: 각 테이블의 (fs_type, statement_type) 결정 ──────
                # (None, None) 테이블은 2패스에서 보완 추론
                classifications: list[Optional[tuple[str, str]]] = []
                valid_tables: list[tuple[int, list]] = []  # (t_idx, raw_table)

                for t_idx, raw_table in enumerate(raw_tables):
                    if not raw_table or not is_financial_table(raw_table):
                        continue

                    table_key = _table_fingerprint(raw_table)
                    if table_key in seen_tables:
                        continue
                    seen_tables.add(table_key)

                    fs_type, statement_type = classify_table_on_page(
                        page, t_idx, fallback_text=page_text
                    )
                    valid_tables.append((t_idx, raw_table))
                    classifications.append(
                        (fs_type, statement_type) if fs_type else None
                    )

                # ── 2패스: None 테이블의 섹션 보완 추론 ──────────────────
                classifications = _infer_missing_classifications(
                    classifications, page_info['keywords']
                )

                # ── 3패스: FactRow 생성 ───────────────────────────────────
                for (t_idx, raw_table), clf in zip(valid_tables, classifications):
                    if clf is None:
                        logger.debug(
                            f"섹션 미판별 [p{page_no} T{t_idx}] — 스킵"
                        )
                        continue

                    fs_type, statement_type = clf

                    # 연결 섹션 발견 시 fin_type='A'로 갱신
                    if statement_type == 'consolidated':
                        result.fin_type = 'A'

                    rows = extract_financial_rows(raw_table, multiplier=unit)
                    if not rows:
                        continue

                    _fs_section = fs_type[:2].lower()  # "BS"→"bs", "IS"→"is", "CF"→"cf"
                    period_type = _get_period_type(fs_type, fiscal_period)

                    for row in rows:
                        mapping: MappingResult = mapper.map(
                            row.account_name,
                            fs_section=_fs_section,
                        )

                        if mapping.account_code.startswith('unknown.'):
                            norm = normalize_account_name(row.account_name)[:300]
                            entry = result.unknown_accounts_seen.setdefault(norm, {
                                'fs_type': fs_type[:6], 'count': 0,
                            })
                            entry['count'] += 1
                            continue

                        for col_idx, amount in enumerate(row.amounts):
                            if col_idx > 3:
                                break
                            fy = fiscal_year - col_idx

                            result.facts.append(FactRow(
                                fs_type=fs_type,
                                statement_type=statement_type,
                                period_type=period_type,
                                account_code=mapping.account_code,
                                account_name_raw=row.account_name_raw,
                                period_end=None,
                                fiscal_year=fy,
                                fiscal_period=fiscal_period,
                                amount=amount,
                                col_index=col_idx,
                                row_order=row.row_order,
                                is_subtotal=row.is_subtotal,
                                unit_multiplier=unit,
                                source_format='pdf_text',
                                extraction_confidence=mapping.confidence * 0.9,
                                parser_track='PDF',
                            ))

    except Exception as e:
        logger.error(f"PDF 파싱 오류 [{rcept_no}]: {e}")
        result.parse_status = 'failed'
        result.errors.append(str(e))
        return result

    # ── 파싱 품질 판정 ────────────────────────────────────────────────
    _evaluate_result(result)
    return result


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────

def _get_period_type(fs_type: str, fiscal_period: str) -> str:
    """fs_type + fiscal_period 조합으로 period_type 결정"""
    if fiscal_period == 'FY':
        return _ANNUAL_PERIOD_TYPE.get(fs_type, 'annual')
    # 반기/분기: IS·CF는 누적(cumulative_ytd), BS는 point_in_time
    if fs_type.startswith('BS'):
        return 'point_in_time'
    return 'cumulative_ytd'


def _infer_missing_classifications(
    classifications: list[Optional[tuple[str, str]]],
    page_keywords: list[str],
) -> list[Optional[tuple[str, str]]]:
    """
    페이지 내 테이블 분류 결과에서 None 항목을 보완 추론한다.

    규칙:
    1. 단일 테이블이고 키워드가 하나만 있으면 → 해당 키워드로 분류
    2. 한 테이블이 IS_C이고 다른 테이블이 None → None을 IS_S로
       (연결/별도 쌍이 같은 페이지에 있는 영업보고서 구조)
    3. BS_C ↔ BS_S, CF_C ↔ CF_S 동일 원칙
    4. 단일 키워드 페이지에서 None → 해당 키워드로 분류
    """
    from parser.pdf.pdf_section_detector import CONSOL_FS_KEYWORDS, SEPARATE_FS_KEYWORDS

    # 보완 타입 매핑: 연결 ↔ 별도
    _COMPLEMENT: dict[str, tuple[str, str]] = {
        'IS_C': ('IS_S', 'separate'),
        'IS_S': ('IS_C', 'consolidated'),
        'BS_C': ('BS_S', 'separate'),
        'BS_S': ('BS_C', 'consolidated'),
        'CF_C': ('CF_S', 'separate'),
        'CF_S': ('CF_C', 'consolidated'),
    }

    result = list(classifications)
    n = len(result)

    if n == 0:
        return result

    # 규칙 1: 단일 키워드 폴백
    if len(page_keywords) == 1:
        kw = page_keywords[0]
        if kw in CONSOL_FS_KEYWORDS:
            single_clf = (CONSOL_FS_KEYWORDS[kw], 'consolidated')
        elif kw in SEPARATE_FS_KEYWORDS:
            single_clf = (SEPARATE_FS_KEYWORDS[kw], 'separate')
        else:
            single_clf = None
        if single_clf:
            result = [clf if clf else single_clf for clf in result]
            return result

    # 규칙 2/3: 보완 쌍 추론 (N=2 테이블)
    if n == 2:
        c0, c1 = result[0], result[1]
        if c0 is None and c1 is not None:
            complement = _COMPLEMENT.get(c1[0])
            if complement:
                result[0] = complement
        elif c0 is not None and c1 is None:
            complement = _COMPLEMENT.get(c0[0])
            if complement:
                result[1] = complement

    # 규칙 4: 여전히 None → 별도(S) 타입 기본값 (영업보고서는 별도 우선)
    # 페이지 키워드에서 가장 구체적인 섹션 추출
    for i, clf in enumerate(result):
        if clf is None:
            # 키워드에서 추론 시도
            for kw in page_keywords:
                if kw in SEPARATE_FS_KEYWORDS:
                    result[i] = (SEPARATE_FS_KEYWORDS[kw], 'separate')
                    break

    return result


def _is_correction_cover(pdf) -> bool:
    """
    정정신고 커버 문서 감지.

    특징:
    - 페이지 수 <= 6
    - 첫 3페이지 중 "정정 신고" 또는 "정정신고" 포함
    - 재무 테이블 없음 (재무 섹션 키워드가 텍스트 내용이 아닌 목차에만 등장)

    이런 문서는 실제 재무 데이터 없이 "첨부파일 오류 정정" 등을 공지하는 커버임.
    """
    from parser.pdf.pdf_section_detector import find_financial_pages

    if len(pdf.pages) > 10:
        return False  # 긴 문서는 커버가 아님

    # 첫 3페이지에서 "정정신고" 키워드 확인
    correction_found = False
    for page in list(pdf.pages)[:3]:
        text = page.extract_text() or ''
        if '정정' in text and ('신고' in text or '공시' in text):
            correction_found = True
            break

    if not correction_found:
        return False

    # 재무 섹션 실제 데이터 없음 확인
    # (목차에만 등장하는 "재무상태표" 같은 텍스트는 무시하고, 실제 테이블이 없어야 함)
    fin_pages = find_financial_pages(pdf)
    for pi in fin_pages:
        tables = pi['page'].extract_tables()
        for t in tables:
            from parser.pdf.pdf_section_detector import is_financial_table
            if is_financial_table(t):
                return False  # 실제 재무 테이블 발견 → 커버 아님

    return True


def _table_fingerprint(rows: list[list]) -> str:
    """테이블 내용의 간단한 지문 (중복 탐지용)"""
    # 처음 3행, 각 행의 처음 3셀 기준
    parts = []
    for row in rows[:3]:
        for cell in (row or [])[:3]:
            parts.append(str(cell or '')[:20])
    return '|'.join(parts)


def _evaluate_result(result: ParseResult) -> None:
    """파싱 결과 품질 판정 → result.parse_status 갱신"""
    core_mapped = sum(
        1 for f in result.facts
        if not f.account_code.startswith('unknown.')
        and not f.fs_type.startswith('NOTE')
    )
    core_unknown = sum(
        info['count']
        for info in result.unknown_accounts_seen.values()
    )
    core_total = core_mapped + core_unknown

    if core_total == 0 and not result.facts:
        result.parse_status = 'partial'
        result.errors.append('추출된 재무 항목 없음')
        return

    if core_total == 0:
        result.parse_status = 'partial'
        result.errors.append('핵심 재무제표 항목 없음')
        return

    unknown_ratio = core_unknown / core_total if core_total else 1.0

    if unknown_ratio > 0.5:
        result.parse_status = 'partial'
    else:
        result.parse_status = 'success'

    logger.debug(
        f"  PDF 품질 [{result.rcept_no}]: facts={len(result.facts)} "
        f"unknown={core_unknown} ({unknown_ratio:.0%})"
    )
