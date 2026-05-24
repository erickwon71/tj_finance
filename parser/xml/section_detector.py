"""
DART XML 재무제표 섹션 탐지기 (Track B용)

DART XML 문서에서 TITLE 태그를 기반으로 재무제표 섹션
(재무상태표, 포괄손익계산서, 현금흐름표, 주석)의 위치를 찾는다.

반환 구조:
    {
        "BS_C": element,   # 연결 재무상태표 시작 TITLE 요소
        "IS_C": element,
        "CF_C": element,
        "BS_S": element,   # 별도 재무상태표
        "IS_S": element,
        "CF_S": element,
        "NOTE_C": element, # 연결재무제표 주석
        "NOTE_S": element,
    }
"""
import re
from typing import Optional
from lxml import etree


# ── 섹션명 패턴 ─────────────────────────────────────────────────────
# 각 섹션 코드별로 TITLE 텍스트에서 찾을 키워드 패턴
# 순서 중요: 더 구체적인 패턴이 앞에 와야 함 (연결 > 별도)

_SECTION_PATTERNS: list[tuple[str, list[str]]] = [
    # (섹션 코드, 매칭 키워드 리스트) — 모두 포함되어야 매칭
    ("BS_C", ["연결", "재무상태표"]),
    ("IS_C", ["연결", "손익계산서"]),      # 포괄손익계산서 / 손익계산서 모두 포함
    ("CF_C", ["연결", "현금흐름표"]),
    ("NOTE_C", ["연결", "주석"]),
    # 별도 (연결 없이 단독)
    ("BS_S", ["재무상태표"]),
    ("IS_S", ["손익계산서"]),
    ("CF_S", ["현금흐름표"]),
    ("NOTE_S", ["주석"]),
]

# 제외 키워드 (이 단어가 있으면 제외)
_EXCLUDE_PATTERNS: dict[str, list[str]] = {
    "BS_S": ["연결"],
    "IS_S": ["연결"],
    "CF_S": ["연결"],
    "NOTE_S": ["연결"],
}


def detect_sections(root: etree._Element) -> dict[str, Optional[etree._Element]]:
    """
    XML 루트 요소에서 TITLE 태그를 탐색해 재무제표 섹션별 위치를 반환한다.

    TITLE 기반 탐지 후 핵심 섹션(BS/IS/CF)이 누락된 경우 TABLE 기반 fallback 실행:
    1. TABLE-GROUP 구조 (분기보고서 일부): TABLE-GROUP 내 첫 TABLE에서 섹션명 감지
    2. TABLE-first-row 구조 (감사보고서 첨부): TABLE 첫 행 텍스트에서 섹션명 감지

    Args:
        root: lxml 파싱된 DART XML 루트 요소

    Returns:
        섹션 코드 → TITLE/TABLE 요소 또는 None
    """
    sections: dict[str, Optional[etree._Element]] = {
        code: None for code, _ in _SECTION_PATTERNS
    }

    # ── TITLE 기반 탐지 (1순위) ───────────────────────────────────────
    titles = root.findall(".//TITLE")

    for title_elem in titles:
        title_text = _get_text(title_elem)
        if not title_text:
            continue

        for code, keywords in _SECTION_PATTERNS:
            if sections[code] is not None:  # lxml Element: 반드시 `is not None` 사용
                continue  # 이미 찾음

            # 제외 키워드 체크
            exclude_kws = _EXCLUDE_PATTERNS.get(code, [])
            if any(kw in title_text for kw in exclude_kws):
                continue

            # 포함 키워드 전체 매칭
            if all(kw in title_text for kw in keywords):
                sections[code] = title_elem
                break  # 하나의 TITLE은 하나의 섹션만 매핑

    # ── TABLE 기반 fallback (핵심 섹션이 없을 때) ─────────────────────
    core_missing = [
        code for code, elem in sections.items()
        if elem is None and not code.startswith("NOTE")
    ]
    if core_missing:
        _detect_sections_from_tables(root, sections)

    return sections


def _detect_sections_from_tables(
    root: etree._Element,
    sections: dict[str, Optional[etree._Element]],
) -> None:
    """
    TABLE 구조에서 재무제표 섹션을 탐지해 sections dict를 in-place 수정한다.

    패턴 1 — TABLE-GROUP 구조 (일부 분기/반기 보고서):
        <TABLE-GROUP>
          <TABLE><TR><TD><P>재무상태표</P>...</TABLE>  ← 제목 TABLE
          <TABLE>... BS 데이터 ...</TABLE>             ← 데이터 TABLE
        </TABLE-GROUP>
        → sections[code] = 데이터 TABLE (두 번째 TABLE)

    패턴 2 — TABLE-first-row 구조 (감사보고서 첨부):
        <TABLE><TR><TD><P>연 결 재 무 상 태 표</P></TD></TR></TABLE>  ← 제목 TABLE
        <TABLE>... BS 데이터 ...</TABLE>                              ← 데이터 TABLE
        → sections[code] = 데이터 TABLE (다음 sibling TABLE)
    """
    # ── 패턴 1: TABLE-GROUP ────────────────────────────────────────────
    # TABLE-GROUP[첫 TABLE = 제목, 두 번째 TABLE = 데이터] 구조
    for tg in root.iter('TABLE-GROUP'):
        direct_tables = [c for c in tg if c.tag == 'TABLE']
        if len(direct_tables) < 2:
            continue

        title_table = direct_tables[0]   # sections에 저장할 제목 TABLE

        rows = title_table.findall('.//TR')
        if not rows:
            continue
        title_text = _get_text(rows[0])
        if not title_text:
            continue

        for code, keywords in _SECTION_PATTERNS:
            if sections[code] is not None:
                continue
            exclude_kws = _EXCLUDE_PATTERNS.get(code, [])
            if _matches(title_text, keywords, exclude_kws):
                sections[code] = title_table  # 제목 TABLE 저장 (단위·기간 탐색에 활용)
                break

    # ── 패턴 2: TABLE-first-row ────────────────────────────────────────
    # 아직 누락된 섹션이 있을 때만 실행
    if not any(sections[c] is None and not c.startswith("NOTE") for c in sections):
        return

    for table in root.iter('TABLE'):
        rows = table.findall('.//TR')
        if not rows:
            continue
        # 행 수 적은 TABLE만 제목 후보 (여러 행이면 데이터 TABLE일 가능성 높음)
        if len(rows) > 8:
            continue
        title_text = _get_text(rows[0])
        if not title_text:
            continue

        for code, keywords in _SECTION_PATTERNS:
            if sections[code] is not None:
                continue
            exclude_kws = _EXCLUDE_PATTERNS.get(code, [])
            if _matches(title_text, keywords, exclude_kws):
                # 제목 TABLE을 sections에 저장 (find_section_tables가 다음 sibling 탐색)
                sections[code] = table
                break


def find_section_tables(
    section_elem: etree._Element,
    max_tables: int = 5,
) -> list[etree._Element]:
    """
    섹션 마커 요소 이후에 오는 TABLE 요소들을 반환한다.

    - section_elem이 TITLE 요소인 경우: 다음 TITLE까지 sibling TABLE 수집 (기존 동작)
    - section_elem이 TABLE 요소인 경우: 그 자체가 데이터 TABLE → [section_elem] 반환
      (_detect_sections_from_tables fallback에서 데이터 TABLE을 직접 저장하므로)

    Args:
        section_elem: 섹션의 TITLE 또는 데이터 TABLE 요소
        max_tables: 최대 TABLE 수 (재무제표 본문은 보통 1~3개)

    Returns:
        TABLE 요소 리스트
    """
    elem_tag = section_elem.tag.upper() if isinstance(section_elem.tag, str) else ""

    if elem_tag == "TABLE":
        # TABLE 요소 = 제목 TABLE → 같은 부모의 sibling TABLE들에서 데이터 탐색
        # (다음 섹션 제목 TABLE 이전까지만 수집)
        parent = section_elem.getparent()
        if parent is None:
            return []
        siblings = list(parent)
        try:
            start_idx = siblings.index(section_elem)
        except ValueError:
            return []

        tables = []
        for s in siblings[start_idx + 1:]:
            stag = s.tag.upper() if isinstance(s.tag, str) else ""
            if stag == "TITLE":
                break  # 다음 TITLE 섹션 시작
            if stag != "TABLE":
                continue
            # 다음 섹션 제목 TABLE인지 확인 (행 수 ≤ 8이고 섹션 패턴 매칭)
            s_rows = s.findall('.//TR')
            if s_rows and len(s_rows) <= 8:
                s_title = _get_text(s_rows[0])
                if s_title and any(
                    _matches(s_title, kws, _EXCLUDE_PATTERNS.get(c, []))
                    for c, kws in _SECTION_PATTERNS
                ):
                    break  # 다음 섹션 제목 TABLE → 여기서 중단
            tables.append(s)
            if len(tables) >= max_tables:
                break
        return tables

    # TITLE 기반: 다음 TITLE 전까지 sibling TABLE 수집
    parent = section_elem.getparent()
    if parent is None:
        return []

    siblings = list(parent)
    try:
        start_idx = siblings.index(section_elem)
    except ValueError:
        return []

    tables = []
    for elem in siblings[start_idx + 1:]:
        tag = elem.tag.upper() if isinstance(elem.tag, str) else ""

        if tag == "TITLE":
            # 다음 섹션 시작 → 중단
            break
        if tag == "TABLE":
            tables.append(elem)
            if len(tables) >= max_tables:
                break

    return tables


def detect_unit_from_section(section_elem: etree._Element) -> int:
    """
    섹션 내 텍스트에서 "(단위 : 천원)" 등 단위 표기를 찾아 multiplier 반환.

    TABLE에서 직접 찾거나, 섹션 내 P 태그에서 찾는다.
    """
    from parser.common.amount_normalizer import detect_unit_multiplier

    parent = section_elem.getparent()
    if parent is None:
        return 1

    siblings = list(parent)
    try:
        start_idx = siblings.index(section_elem)
    except ValueError:
        return 1

    # 섹션 시작부터 다음 TITLE 전까지 텍스트 탐색
    for elem in siblings[start_idx:start_idx + 20]:
        tag = elem.tag.upper() if isinstance(elem.tag, str) else ""
        if tag == "TITLE" and elem is not section_elem:
            break
        text = _get_text(elem)
        if "단위" in text:
            multiplier = detect_unit_multiplier(text)
            if multiplier > 1:
                return multiplier

    return 1


def detect_periods_from_header(table_elem: etree._Element) -> list[str]:
    """
    TABLE 헤더에서 기간 정보(열 헤더)를 추출한다.

    DART XML 헤더 예시:
      "제 72 기          2023.12.31 현재"
      "제 71 기          2022.12.31 현재"

    Returns:
        ["2023-12-31", "2022-12-31", "2021-12-31"] 형식의 리스트
        (col_index 0,1,2 순서)
    """
    import re

    periods = []
    # TH 태그에서 날짜 패턴 탐색
    headers = table_elem.findall(".//TH")
    for th in headers:
        text = _get_text(th)
        # "2023.12.31" 또는 "2023년 12월 31일" 패턴 탐색
        match = re.search(
            r'(\d{4})[.\-년\s](\d{1,2})[.\-월\s](\d{1,2})',
            text
        )
        if match:
            y, m, d = match.groups()
            periods.append(f"{y}-{int(m):02d}-{int(d):02d}")

    return periods[:3]  # 최대 3기(당기/전기/전전기)


def find_summary_tables(root: etree._Element) -> dict[str, Optional[etree._Element]]:
    """
    분기/반기 보고서의 '요약재무정보' 섹션에서 연결/별도 요약 테이블을 찾는다.

    DART 분기보고서 구조:
      <TITLE>1. 요약재무정보</TITLE>
      <P>가. 요약연결재무정보</P>
      <TABLE>(1행: 단위)</TABLE>
      <TABLE>(N행: BS+IS 데이터)</TABLE>
      <P>나. 요약재무정보</P>
      <TABLE>(1행: 단위)</TABLE>
      <TABLE>(N행: BS+IS 데이터)</TABLE>

    Returns:
        {"consolidated": TABLE 요소, "separate": TABLE 요소}  (없으면 None)
    """
    result: dict[str, Optional[etree._Element]] = {
        "consolidated": None,
        "separate": None,
    }

    # 요약재무정보 TITLE 탐색
    summary_title = None
    for title in root.findall(".//TITLE"):
        text = _get_text(title)
        if "요약재무정보" in text and "주석" not in text:
            summary_title = title
            break

    if summary_title is None:
        return result

    parent = summary_title.getparent()
    if parent is None:
        return result

    siblings = list(parent)
    try:
        start_idx = siblings.index(summary_title)
    except ValueError:
        return result

    # 요약재무정보 섹션 안에서 P 태그로 연결/별도 구분
    current_key = None
    tables_seen: list[etree._Element] = []

    for elem in siblings[start_idx + 1:]:
        tag = elem.tag.upper() if isinstance(elem.tag, str) else ""

        if tag == "TITLE":
            break  # 다음 섹션 시작

        if tag == "P":
            p_text = _get_text(elem)
            if "연결" in p_text and ("요약" in p_text or "재무" in p_text):
                if tables_seen and current_key:
                    _assign_summary(result, current_key, tables_seen)
                current_key = "consolidated"
                tables_seen = []
            elif "요약재무정보" in p_text or "별도" in p_text or "재무정보" in p_text:
                if tables_seen and current_key:
                    _assign_summary(result, current_key, tables_seen)
                # 연결 P 태그가 없거나 두 번째 P → separate
                if current_key is None:
                    current_key = "consolidated"  # 연결 없는 기업이면 첫 번째가 separate
                else:
                    current_key = "separate"
                tables_seen = []

        if tag == "TABLE":
            tables_seen.append(elem)

    # 마지막 그룹 처리
    if tables_seen and current_key:
        _assign_summary(result, current_key, tables_seen)

    return result


def _assign_summary(
    result: dict,
    key: str,
    tables: list,
) -> None:
    """테이블 리스트 중 가장 큰 것(데이터 행 수 기준)을 result[key]에 할당"""
    data_tables = sorted(tables, key=lambda t: len(t.findall(".//TR")), reverse=True)
    if data_tables and len(data_tables[0].findall(".//TR")) >= 5:
        result[key] = data_tables[0]


def _get_text(elem: etree._Element) -> str:
    """요소의 전체 텍스트를 공백 정리해서 반환"""
    try:
        parts = []
        for text in elem.itertext():
            if text:
                parts.append(text.strip())
        return ' '.join(p for p in parts if p)
    except Exception:
        return ""


def _matches(text: str, keywords: list[str], exclude_kws: list[str]) -> bool:
    """
    텍스트가 섹션 패턴에 매칭되는지 확인.

    매칭 방법: 원문(text) 또는 공백 제거 버전(text_no_space)에서 키워드 탐색.
    예: "연 결 재 무 상 태 표" → 공백 제거 후 "연결재무상태표" → 키워드 ["연결","재무상태표"] 매칭
    """
    text_no_space = text.replace(' ', '')
    # 제외 키워드 체크
    if any(kw in text or kw in text_no_space for kw in exclude_kws):
        return False
    # 포함 키워드 전체 매칭 (원문 또는 공백 제거 버전)
    return all(
        kw in text or kw in text_no_space
        for kw in keywords
    )
