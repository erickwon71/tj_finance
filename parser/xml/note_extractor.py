"""
DART XML 현금흐름표 주석 추출기 (note_extractor.py)

현금흐름표 주석(Note "N. 현금흐름표")에서 D&A(감가상각비·무형자산상각비)를
추출해 financial_facts에 NOTE 계정으로 저장한다.

추출 대상:
  - 감가상각비 (Depreciation)          → note.depreciation
  - 무형자산상각비 (Amortization)       → note.amortization
  - 사용권자산 감가상각비 (ROU dep.)    → note.rou_depreciation
  - D&A 합계 (합산)                    → note.da_total
  - 유형자산 취득 (CAPEX)              → note.capex_acquisition

지원 포맷:
  1. 삼성/현대 스타일: TABLE-GROUP에 조정항목 테이블 포함
     (3열: 카테고리 | 계정명 | 금액, 단위 헤더 "(단위 : 백만원)")
  2. 기아 스타일: 당기/전기 별도 테이블
"""
from __future__ import annotations

import re
from typing import Optional
from lxml import etree

# ── D&A 계정 매핑 패턴 ──────────────────────────────────────────────
# (계정코드, 포함 패턴, 제외 패턴)
_DA_ACCOUNT_PATTERNS: list[tuple[str, list[str], list[str]]] = [
    # 우선순위 높은 것 먼저
    ("note.rou_depreciation", ["사용권자산", "감가상각"],    []),
    ("note.depreciation",     ["감가상각비"],                ["무형", "사용권"]),
    ("note.amortization",     ["무형자산상각비"],             []),
    ("note.amortization",     ["무형자산", "상각비"],         ["감가상각비"]),
]

# ENG 속성으로 빠른 매핑
_ENG_TO_CODE: dict[str, str] = {
    "depreciation":         "note.depreciation",
    "amortization":         "note.amortization",
    "right-of-use":         "note.rou_depreciation",
}

# ── 단위 감지 패턴 ──────────────────────────────────────────────────
_UNIT_PATTERN = re.compile(r'단위\s*[：:]\s*(백만원|천원|억원|만원|원)')
_UNIT_MAP = {
    "원":    1,
    "천원":  1_000,
    "만원":  10_000,
    "백만원":1_000_000,
    "억원":  100_000_000,
}

# CF 주석 TITLE 패턴 ("27. 현금흐름표 (연결)", "30. 현금흐름표", etc.)
_CF_NOTE_TITLE = re.compile(r'\d+\s*[.．]\s*현금흐름표')


def _get_text(elem: etree._Element) -> str:
    return "".join(elem.itertext()).strip()


def _detect_unit_in_text(text: str) -> int:
    """텍스트에서 단위 배수 추출. 기본값 1_000_000 (백만원 = DART 기본)."""
    m = _UNIT_PATTERN.search(text)
    if m:
        return _UNIT_MAP.get(m.group(1), 1_000_000)
    return 1_000_000  # DART 사업보고서 기본값 = 백만원


def _parse_amount(text: str, multiplier: int) -> Optional[int]:
    """금액 문자열 → 정수 (None이면 빈 셀)."""
    s = text.strip().replace(",", "").replace(" ", "").replace("　", "")
    if not s or s in ("-", "─", "―", "　", "—"):
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        val = int(float(s)) * multiplier
        return -val if negative else val
    except ValueError:
        return None


def _map_account_by_eng(eng: str) -> Optional[str]:
    """ENG 속성으로 계정 코드 매핑."""
    if not eng:
        return None
    eng_lower = eng.lower()
    for key, code in _ENG_TO_CODE.items():
        if key in eng_lower:
            return code
    return None


def _map_account_by_text(text: str) -> Optional[str]:
    """계정명 텍스트로 D&A 코드 매핑."""
    normalized = re.sub(r'\s+', '', text)  # 공백 제거 후 매칭
    for code, inc_pats, exc_pats in _DA_ACCOUNT_PATTERNS:
        if all(p.replace(" ", "") in normalized for p in inc_pats):
            if not any(p.replace(" ", "") in normalized for p in exc_pats):
                return code
    return None


def _find_cf_note_sections(root: etree._Element) -> list[etree._Element]:
    """
    "N. 현금흐름표" 패턴의 TITLE 요소(TABLE-GROUP 부모)를 모두 반환.
    연결 + 별도 포함.
    """
    results = []
    for title in root.findall(".//TITLE"):
        text = _get_text(title)
        if _CF_NOTE_TITLE.search(text):
            parent = title.getparent()
            if parent is not None:
                results.append(parent)
    return results


class NoteDAFact:
    """D&A 팩트 결과."""
    __slots__ = ["account_code", "account_name_raw", "amount", "unit_multiplier",
                 "col_index", "is_consolidated"]

    def __init__(self, account_code, account_name_raw, amount,
                 unit_multiplier, col_index, is_consolidated):
        self.account_code = account_code
        self.account_name_raw = account_name_raw
        self.amount = amount
        self.unit_multiplier = unit_multiplier
        self.col_index = col_index
        self.is_consolidated = is_consolidated


def extract_da_from_cf_notes(root: etree._Element) -> list[NoteDAFact]:
    """
    XML 루트에서 현금흐름표 주석의 D&A 항목을 추출.

    Returns:
        NoteDAFact 리스트 (col_index 0=당기, 1=전기)
    """
    facts: list[NoteDAFact] = []

    cf_sections = _find_cf_note_sections(root)
    if not cf_sections:
        return facts

    for section in cf_sections:
        # 연결/별도 판단: 섹션 TITLE에 "연결" 포함 여부
        section_title = ""
        title_elem = section.find("./TITLE")
        if title_elem is not None:
            section_title = _get_text(title_elem)
        is_consolidated = "연결" in section_title

        # 섹션 전체 텍스트에서 단위 탐지
        section_text = _get_text(section)
        unit = _detect_unit_in_text(section_text)

        # 이 섹션 내 모든 TABLE을 순서대로 탐색
        # 직접 자식 요소를 순서대로 보면서 당기/전기 컨텍스트 추적
        # 규칙: 작은 테이블(≤2행)에 "당기" 또는 "전기" 텍스트가 있으면 컨텍스트 전환
        children = list(section)
        current_col = 0  # 기본: 당기 (col_index=0)

        for child in children:
            child_text = _get_text(child)

            if child.tag == "TABLE":
                rows_count = len(child.findall(".//TR"))

                # 컨텍스트 신호 테이블: 행 수 ≤ 2이고 당기/전기 키워드 포함
                if rows_count <= 2:
                    if "전기" in child_text and "당기" not in child_text:
                        current_col = 1
                    elif "당기" in child_text:
                        current_col = 0
                    continue  # 신호 테이블 자체는 데이터 추출 안 함

                # 데이터 테이블: 행 수 ≥ 3
                # CF 조정항목 테이블인지 확인
                is_adjustment_table = any(
                    kw in child_text for kw in
                    ["당기순이익", "조정내역", "감가상각", "영업활동"]
                )
                if not is_adjustment_table:
                    continue

                # 헤더에서 열 구조 파악
                # 단일 금액열(공시금액) vs 두 금액열(당기|전기)
                thead = child.find(".//THEAD")
                header_text = _get_text(thead) if thead is not None else ""
                has_prior = "전기" in header_text

                # TBODY 행 순회
                tbody = child.find(".//TBODY")
                if tbody is None:
                    tbody = child
                fact_rows = _extract_da_rows(tbody, unit, has_prior, current_col)
                facts.extend(
                    NoteDAFact(
                        account_code=r["code"],
                        account_name_raw=r["name"],
                        amount=r["amount"],
                        unit_multiplier=unit,
                        col_index=r["col_index"],
                        is_consolidated=is_consolidated,
                    )
                    for r in fact_rows
                )
            else:
                # 비TABLE 요소에서도 당기/전기 컨텍스트 업데이트
                if "전기" in child_text and "당기" not in child_text:
                    current_col = 1
                elif "당기" in child_text:
                    current_col = 0

    # 당기 D&A 합계 계산 (depreciation + amortization)
    _add_da_total(facts)

    return facts


def _extract_da_rows(
    tbody: etree._Element,
    unit: int,
    has_prior: bool,
    default_col: int,
) -> list[dict]:
    """
    TBODY에서 D&A 관련 행을 추출.

    테이블 구조:
      - 3열: category(ROWSPAN) | account_name | amount
      - 2열: account_name | amount
      - 다중열: account_name | current_amount | prior_amount
    """
    results = []
    rows = tbody.findall(".//TR")

    for row in rows:
        cells = row.findall(".//TE") + row.findall(".//TD")
        if not cells:
            continue

        # 각 셀의 텍스트와 ENG 속성 수집
        cell_texts = [_get_text(c) for c in cells]
        cell_engs  = [c.get("ENG", "") for c in cells]

        # 계정명과 금액 셀 분리
        # 금액처럼 보이는 셀: 숫자/괄호로 구성
        _NUM_RE = re.compile(r'^[\d(,\-─\s）（]+[\d））]$')
        def is_amount_cell(text: str) -> bool:
            t = text.strip().replace(",", "").replace(" ", "")
            if not t or t in ("-", "─", "―", "　", "—"):
                return True  # 빈 칸도 금액 칸일 수 있음
            return bool(re.match(r'^[-\d(）]+$', t.replace(",", "")))

        # 텍스트가 있는 비금액 셀 = 계정명 후보
        name_cells = [(i, cell_texts[i], cell_engs[i])
                      for i in range(len(cells))
                      if cell_texts[i] and not is_amount_cell(cell_texts[i])]

        if not name_cells:
            continue

        # 계정명: 마지막 비금액 셀 (3열 구조에서 col1이 실제 계정명)
        _, account_name, eng_attr = name_cells[-1]

        # 계정 코드 매핑 (ENG 우선, 텍스트 fallback)
        code = _map_account_by_eng(eng_attr) or _map_account_by_text(account_name)
        if not code:
            continue

        # 금액 셀 추출 (오른쪽부터)
        amount_cells = [cell_texts[i] for i in range(len(cells))
                        if is_amount_cell(cell_texts[i])]

        if not amount_cells:
            continue

        if has_prior and len(amount_cells) >= 2:
            # 두 금액열: [당기, 전기] or [전기, 당기] → 항상 [당기, 전기]
            curr_amount = _parse_amount(amount_cells[0], unit)
            prev_amount = _parse_amount(amount_cells[1], unit)
            if curr_amount is not None:
                results.append({"code": code, "name": account_name,
                                 "amount": curr_amount, "col_index": 0})
            if prev_amount is not None:
                results.append({"code": code, "name": account_name,
                                 "amount": prev_amount, "col_index": 1})
        else:
            # 단일 금액열
            amount = _parse_amount(amount_cells[-1], unit)
            if amount is not None:
                results.append({"code": code, "name": account_name,
                                 "amount": amount, "col_index": default_col})

    return results


def _add_da_total(facts: list[NoteDAFact]) -> None:
    """
    depreciation + amortization + rou_depreciation → da_total 계산하여 추가.
    연결/별도 × col_index 조합별로 합산.
    """
    from collections import defaultdict
    # key: (is_consolidated, col_index)
    da_parts: dict[tuple, list[int]] = defaultdict(list)

    for f in facts:
        if f.account_code in ("note.depreciation", "note.amortization",
                               "note.rou_depreciation"):
            if f.amount is not None:
                da_parts[(f.is_consolidated, f.col_index)].append(f.amount)

    for (is_consol, col_idx), amounts in da_parts.items():
        if amounts:
            total = sum(amounts)
            # unit_multiplier은 이미 반영된 절대금액이므로 multiplier=1
            facts.append(NoteDAFact(
                account_code="note.da_total",
                account_name_raw="D&A 합계 (감가상각비+무형자산상각비)",
                amount=total,
                unit_multiplier=1,  # 이미 배수 반영된 절대금액
                col_index=col_idx,
                is_consolidated=is_consol,
            ))
