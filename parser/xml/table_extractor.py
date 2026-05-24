"""
DART XML TABLE 구조에서 재무 행 데이터 추출

입력: TABLE 요소 (lxml etree._Element)
출력: list[RowData] — (계정과목명, [당기, 전기, 전전기]) 형태의 행 리스트

DART XML TABLE 구조:
  <TABLE>
    <THEAD> or first TBODY rows → 헤더 (기수/날짜)
    <TBODY>
      <TR>
        <TD> 계정과목명 </TD>
        <TD ALIGN="RIGHT"> 당기금액 </TD>
        <TD ALIGN="RIGHT"> 전기금액 </TD>
        <TD ALIGN="RIGHT"> 전전기금액 </TD>   ← 사업보고서만
      </TR>
    </TBODY>
  </TABLE>

주의사항:
  - TE 태그: ACODE 속성 있는 데이터 셀 (Track A 전용)
  - TD 태그: 일반 셀
  - TH 태그: 헤더 셀
  - TU 태그: 단위/날짜 셀
  - 소계 행: 앞에 공백 있거나 굵게 표시된 합계 행 탐지
"""
import re
from dataclasses import dataclass, field
from typing import Optional
from lxml import etree

from parser.common.amount_normalizer import parse_amount, normalize_account_name


# 숫자 컬럼으로 판단할 패턴 (쉼표 구분 숫자, 괄호음수 등)
_NUMBER_PATTERN = re.compile(
    r'^[\s\-\─\—\―]$|'              # 공란 / 대시
    r'^\([\d,]+\)$|'                 # (음수)
    r'^[\d,]+$|'                     # 양수
    r'^△[\d,]+$|'                    # △음수
    r'^▲[\d,]+$'                     # ▲음수
)

# 소계/합계 행 판단 키워드
_SUBTOTAL_KEYWORDS = frozenset([
    "합계", "소계", "총계", "계",
    "자산총계", "부채총계", "자본총계",
    "매출총이익", "영업이익", "당기순이익",
    "유동자산합계", "비유동자산합계",
    "유동부채합계", "비유동부채합계",
])


@dataclass
class RowData:
    account_name: str              # 원문 계정과목명
    amounts: list[Optional[int]]   # [당기, 전기, 전전기] (None=공란)
    row_order: int = 0
    is_subtotal: bool = False      # 합계/소계 행 여부
    indent_level: int = 0          # 들여쓰기 수준 (0=최상위, 1=하위...)


def extract_rows(
    table_elem: etree._Element,
    multiplier: int = 1,
    num_cols: int = 3,
) -> list[RowData]:
    """
    TABLE 요소에서 재무 행 데이터를 추출한다.

    Args:
        table_elem: lxml TABLE 요소
        multiplier: 금액 단위 배수 (1 또는 1000)
        num_cols:   금액 열 수 (사업보고서=3, 반기/분기=2 가능)

    Returns:
        RowData 리스트 (헤더 행 제외, 빈 행 제외)
    """
    rows: list[RowData] = []
    row_order = 0

    # TBODY 또는 직접 TR 탐색
    trs = table_elem.findall(".//TR")

    for tr in trs:
        cells = _get_cells(tr)
        if not cells:
            continue

        first_text = cells[0].strip() if cells else ""

        # 헤더/제목/단위 행 감지 → 위치에 관계없이 항상 건너뜀
        # (DART 테이블은 반복 헤더 행 또는 섹션 구분 행이 중간에 나올 수 있음)
        if _is_header_cell(first_text):
            continue

        # 재무제표 이름만 있는 제목 행 건너뜀 (예: "재무상태표", "포괄손익계산서")
        if _is_fs_title_row(cells):
            continue

        # 계정과목명 + 금액 분리
        label, amount_cells = _split_label_amounts(cells)

        if not label:
            continue

        # 금액 파싱
        amounts: list[Optional[int]] = []
        for i in range(num_cols):
            if i < len(amount_cells):
                amounts.append(parse_amount(amount_cells[i], multiplier))
            else:
                amounts.append(None)

        indent = _detect_indent(label)
        label_clean = label.lstrip()  # 들여쓰기 공백 제거

        rows.append(RowData(
            account_name=label_clean,
            amounts=amounts,
            row_order=row_order,
            is_subtotal=_is_subtotal(label_clean),
            indent_level=indent,
        ))
        row_order += 1

    return rows


def _get_cells(tr: etree._Element) -> list[str]:
    """TR 요소의 모든 셀 텍스트 리스트 반환 (TD, TH, TE, TU)"""
    cells = []
    for child in tr:
        tag = child.tag.upper() if isinstance(child.tag, str) else ""
        if tag in ("TD", "TH", "TE", "TU"):
            text = ''.join(child.itertext()).strip()
            cells.append(text)
    return cells


def _split_label_amounts(cells: list[str]) -> tuple[str, list[str]]:
    """
    셀 리스트에서 계정과목명(첫 번째 비숫자 셀)과 금액 셀을 분리한다.

    DART XML 구조:
      [계정과목명, 당기금액, 전기금액, 전전기금액, (주석)]
    """
    label = ""
    amount_cells: list[str] = []

    for i, cell in enumerate(cells):
        if i == 0:
            # 첫 셀은 항상 계정과목명
            label = cell
        else:
            # 숫자 패턴이거나 공란이면 금액 셀
            cell_stripped = cell.replace(',', '').replace(' ', '')
            if _NUMBER_PATTERN.match(cell_stripped) or cell_stripped in ('-', '—', ''):
                amount_cells.append(cell)
            else:
                # 숫자가 아닌 추가 텍스트 (주석 번호 등) → 무시
                pass

    return label, amount_cells


def _is_header_cell(text: str) -> bool:
    """
    첫 번째 셀이 헤더/단위/기수 표기이면 True.
    DART 테이블에서 반복 출현하는 비데이터 행 패턴을 모두 포함.
    """
    if not text:
        return False
    # 기간 날짜: "2023.12.31", "2023-12-31", "2023년"
    if re.search(r'\d{4}[.\-년]', text):
        return True
    # 기수 표기: "제 72 기", "제72기"
    if re.search(r'제\s*\d+\s*기', text):
        return True
    # 단위 표기: "(단위 : 원)", "단위:천원"
    if re.search(r'단위\s*[:\(]', text):
        return True
    # 열 헤더: "구 분", "구분", "과 목", "과목"
    if re.fullmatch(r'[구과]\s*[분목]', text):
        return True
    # 빈 값이거나 "-"만 있는 첫 셀
    if re.fullmatch(r'[\s\-\─\—\―　]*', text):
        return True
    return False


# 재무제표 이름만 있는 단독 행 (섹션 제목이 TABLE 안에 포함된 경우)
_FS_TITLE_PATTERNS = re.compile(
    r'^(연결|별도)?\s*(재무상태표|손익계산서|포괄손익계산서|현금흐름표|'
    r'자본변동표|이익잉여금처분계산서)\s*$'
)


def _is_fs_title_row(cells: list[str]) -> bool:
    """
    재무제표 이름만 있는 제목 행 감지.
    예: ["재무상태표"], ["연결 포괄손익계산서"]
    → 금액 열이 없고 첫 셀이 재무제표명이면 제목 행으로 판단.
    """
    if not cells:
        return False
    first = cells[0].strip()
    if _FS_TITLE_PATTERNS.match(first):
        # 나머지 셀이 모두 비어 있거나 숫자가 아닌 경우
        rest_are_empty = all(
            not c.strip() or re.fullmatch(r'[\s\-\─\—\―　]*', c.strip())
            for c in cells[1:]
        )
        return rest_are_empty
    return False


def _is_subtotal(label: str) -> bool:
    """합계/소계 행 판단"""
    label_norm = normalize_account_name(label)
    return any(kw in label_norm for kw in _SUBTOTAL_KEYWORDS)


def _detect_indent(label: str) -> int:
    """
    앞쪽 공백 수로 들여쓰기 수준 추정
    (DART XML은 공백으로 계층 구조를 표현하는 경우가 많음)
    """
    count = 0
    for ch in label:
        if ch in (' ', '\t', '　'):
            count += 1
        else:
            break
    # 공백 2~3개당 1 레벨
    return min(count // 2, 5)
