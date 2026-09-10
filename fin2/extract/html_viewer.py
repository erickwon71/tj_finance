"""
Track C(PDF-only) 잔여 93건 대상 — DART 웹뷰어(HTML) 기반 재무제표 face 추출.

배경: `docs/plans/html_viewer_extractor_design_2026-09-07.md` — PDF는 좌표기반
텍스트라 "표" 개념이 없어 KD류 라벨-숫자 밀림(§4)·R78류 줄바꿈 버그가 반복
발생했다. 같은 필링을 DART 웹뷰어 내부 API(`report/viewer.do`)로 받으면 원본
SGML/XML이 실제로 갖고 있던 `<TABLE><TR><TD>` 구조가 그대로 나와, 이 두 버그
계열이 원천적으로 발생하지 않음을 KD(00111218)·동성제약(00116268) 2건 교차
검증(자산총계=부채총계+자본총계 항등식까지 원문 확정치와 정확히 일치)으로
확인했다.

**스코프**: PDF 경로(`fin2/extract/pdf.py`)를 전면 대체하지 않는다 — Track C
잔여 93건(fail 19 + missing 74, 검증대장 링크는 위 설계문서 참고)에서만 이
모듈을 병행 사용한다. R78 설계 원칙과 동일: "정상 동작하는 경로를 검증 없이
전면 교체하지 않는다".

**출력 계약**: `fin2.extract.pdf.facts_from_text()`와 완전히 동일하게
`ExtractedFact` 리스트를 산출하고(`source_format='html'`), 같은 사후보정
(`_fix_paren_formatted_bs`/`_fix_swapped_grand_total_equity`)을 그대로
재사용한다 — `collector/pdf_lines_sync.py::facts_to_report_lines()`가 무변경
그대로 소비 가능(이 모듈의 통합 지점은 별도 스크립트에서 처리, `docs/plans/
html_viewer_extractor_design_2026-09-07.md` §5 참고 — 아직 배선 안 됨).

**레이아웃 2종 대응**(§8-1/§8-2/§8-3 93건 전수 실측 확정, 필링 단위 A 45%/
B 55%/미분류 0%):
  - A(거대-셀형, KD류): 라벨 열·각 기간 값 열이 각각 `<BR/>`로만 항목을
    구분한 **하나의 거대한 `<TD>`** — 라벨 세그먼트와 값 세그먼트를 인덱스로
    1:1 zip.
  - B(행별-TR형, 동성제약·케이티·DB증권·삼익악기·제주은행 등 다수): 항목마다
    정상적인 `<TR>` 한 행 — 열 폭 맞춤용 빈 플레이스홀더 컬럼이 실제 값 컬럼
    사이에 낄 수 있어(§8-1 동성제약 실측), 라벨 다음 TD들 중 **첫 비어있지
    않은 셀**을 당기(col0) 값으로 취한다.

**col_index는 항상 0(당기)만** — `fin2/extract/pdf.py::facts_from_text()`와
동일한 계약(다른 컬럼은 뽑지 않음, calendarize 단계가 별도로 처리).

**헤더 먼저 읽기(2026-09-10 확장)** — 레이아웃 B는 이제 값-위치 휴리스틱 전에
`<THEAD>`(없으면 `<TBODY>` 선두의 헤더행류)를 먼저 읽어 위치→회계기간 맵을
만든다(`parser/xml/table_extractor.py`의 R88/§7과 동일 원리 재사용, 설계:
`docs/plans/header_first_parsing_expansion_design_2026-09-10.md`). 이걸로 아래
"3개월 vs 누적" 갭이 해소됐고, **실 필링 재확인 중 잠복 버그도 발견했다** — 제일
기획(00148276) 연결 2001H1(rcpNo=20010814000859) 같은 사례는 당기·전기 열이
연결재무제표 전체에서 진짜로 대시(미공시)인데, 옛 "숫자로 파싱되는 첫 셀=당기"
휴리스틱이 그 오른쪽의 **전전기** 값을 당기로 잘못 채택하고 있었다(R86/R87과 같은
클래스). 헤더그리드 경로는 이제 이런 행을 정직하게 결측으로 남긴다(R3). THEAD도
없고 TBODY 선두 헤더행 판정도 실패하는 표에서만 옛 값-위치 휴리스틱이 그대로
남는다(회귀 위험 최소화 — 실패시 완전 폴백).

**미해결/의도적 범위 밖(§7 리스크, 구현 시 재확인 필요)**:
  - 연결(consolidated) 섹션 중 "다. 연결재무제표"류 통짜 소제목 아래
    개별 표제(`<P class='table-group'>연결대차대조표</P>` 등)로만 표가
    구분되는 네 번째 관례 — `_iter_statement_tables()`가 table-group 표제도
    보므로 처리는 되나, 93건 census(§8-3)만큼 폭넓게 검증되진 않았다.
  - 위 헤더그리드 확장은 이번 세션 실측 1건(제일기획, 라이브 재확인) + 합성
    fixture 단위테스트로만 검증됐다 — Track C 잔여 93건 census 전체 재실행은
    아직 안 함(다음 세션 확장 지점, R88과 동일 스코프 정책).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup, NavigableString, Tag

from parser.common.account_mapper import get_mapper
from parser.common.amount_normalizer import normalize_account_name
from parser.xml.table_extractor import (
    HeaderColumn,
    select_by_header_columns,
    _looks_like_header_row,
    _columns_from_grid,
)
from fin2.extract.pdf import (
    parse_number,
    _strip_inline_english_gloss,
    _fix_paren_formatted_bs,
    _fix_swapped_grand_total_equity,
)
from fin2.extract.xbrl import ExtractedFact

# ── statement 제목 → 섹션코드 ────────────────────────────────────────────────
# fin2/extract/pdf.py::_TITLE_TOKENS 와 동일 어휘(의도적 중복 — pdf.py 내부
# private 상수를 모듈 경계 너머로 재사용하기보다, 각 추출기가 자기 사본을
# 갖는 쪽이 서로 독립적으로 진화할 수 있어 더 안전하다는 판단, R78 원칙과
# 같은 맥락). 바꿀 일이 생기면 두 곳 다 확인할 것.
_TITLE_TOKENS = {
    "재무상태표": "BS", "대차대조표": "BS",
    "포괄손익계산서": "IS", "손익계산서": "IS",
    "현금흐름표": "CF",
    "자본변동표": "SCE",  # 추출 대상 아님 — 앵커로만 인식해 뒤섞임 방지
}
_TITLE_NAMES_BY_LEN = sorted(_TITLE_TOKENS, key=len, reverse=True)

# 레이아웃 A(거대-셀형)에서만 적용하는 그랜드토탈 3종 엄격 라벨 허용목록(위
# facts_from_sections()의 "원인B 부분 대응" 주석 참고) — 실측으로 확인된
# 클린 형태만(`normalize_account_name()`이 numbering/note-ref 접두는 이미
# 지운 뒤의 문자열). 새 변형이 발견되면 여기 추가(카탈로그화 원칙).
_STRICT_TOTAL_LABELS: dict[str, set[str]] = {
    "bs.total_assets": {"자산총계", "자산총액"},
    "bs.total_liabilities": {"부채총계", "부채총액"},
    "bs.total_equity": {"자본총계", "자본총액"},
}

_UNIT_RE = re.compile(r"단위\s*[:：]?\s*(백만원|천원|원)")
_UNIT_FACTOR = {"원": 1, "천원": 1000, "백만원": 1_000_000}

# 목차(TOC) 노드 중 진짜 재무제표 섹션만 — 유의점/합병전후/감사의견은 텍스트에
# "재무제표"가 섞여 있어도 실제 표가 아니다(§8-2 한솔홈데코 원인조사로 확정된
# "감사의견" 오탐 사례 포함).
_TOC_EXCLUDE_RE = re.compile(r"유의점|합병전|감사의견|감사인")


@dataclass
class TocNode:
    text: str
    ele_id: str
    offset: str
    length: str
    dtd: str
    dcm_no: str


def parse_toc_tree(main_do_text: str) -> list[TocNode]:
    """`dsaf001/main.do` 원문에서 node1/node2 JS 객체 블록을 평면 리스트로 파싱.

    실측 확인된 리터럴 패턴(`node2['text'] = "..."` 등, 설계문서 §4-1)을
    그대로 파싱한다 — TOC는 트리(children.push)지만 평면 리스트로도 충분.
    """
    nodes: list[TocNode] = []
    for block in re.split(r"var\s+node[12]\s*=\s*\{\};", main_do_text)[1:]:
        block = block[:2000]  # 다음 필드들이 이 안에 다 있음(여유있게 자름)

        def field(name: str, _block=block) -> str | None:
            m = re.search(rf"\['{name}'\]\s*=\s*\"([^\"]*)\"", _block)
            return m.group(1) if m else None

        text = field("text")
        if text is None:
            continue
        ele_id, offset, length, dtd, dcm_no = (
            field("eleId"), field("offset"), field("length"), field("dtd"), field("dcmNo"))
        if None in (ele_id, offset, length, dtd, dcm_no):
            continue
        nodes.append(TocNode(text=text, ele_id=ele_id, offset=offset,
                              length=length, dtd=dtd, dcm_no=dcm_no))
    return nodes


def find_statement_nodes(nodes: list[TocNode]) -> list[TocNode]:
    """'재무제표'/'연결재무제표' 노드만(유의점·합병전후·감사의견 등 제외)."""
    return [n for n in nodes if "재무제표" in n.text and not _TOC_EXCLUDE_RE.search(n.text)]


def _match_statement(text_normalized: str) -> str | None:
    for name in _TITLE_NAMES_BY_LEN:
        if name in text_normalized:
            return _TITLE_TOKENS[name]
    return None


def _split_by_br(td: Tag) -> list[str]:
    """<BR/>를 구분자로 셀 내용을 텍스트 세그먼트 리스트로 쪼갠다(레이아웃 A 전용)."""
    segments: list[str] = []
    current: list[str] = []
    for node in td.contents:
        if getattr(node, "name", None) == "br":
            segments.append("".join(current))
            current = []
        elif isinstance(node, NavigableString):
            current.append(str(node))
        else:
            current.append(node.get_text())
    segments.append("".join(current))
    return segments


def _iter_statement_tables(soup: BeautifulSoup):
    """섹션 HTML 안의 (statement, table, unit) 를 문서 순서대로 산출.

    제목 위치 관례가 최소 3~4가지(§8-3 실측)라 앵커를 하나로 고정하지 않고
    문서를 순서대로 훑으며 상태(candidate statement)를 갱신한다:
      - `<P class='section-3'>`: 소제목이 통계표 이름을 직접 담고 있으면
        (예: "가. 대차대조표") 그 자체로 후보 확정 — table-group 유무와
        무관하게 다음 border=1 표에 그대로 적용된다(삼익악기·제주은행류
        "table-group 비어있음/아예 없음" 두 관례 모두 이걸로 커버됨).
        통짜 소제목("다. 연결재무제표")은 매칭 안 되어 후보를 초기화한다.
      - `<P class='table-group'>`: 텍스트가 통계표 이름과 매칭되면 후보
        갱신(연결 섹션처럼 통짜 소제목 아래 개별 표제로만 구분되는 경우).
      - 그 외 class 없는 plain `<P>`: 후보가 아직 없을 때만, 15자 이내
        정규화 텍스트가 매칭되면 후보로 채택(안전판, 실측 사례는 아직 없음).
      - `<TABLE class='nb'>`: 데이터 표가 아니라 기간/단위 커버 표 — 단위만
        갱신하고 후보를 소비하지 않는다.
      - `<TABLE border='1'>`: 후보가 있으면 (statement, table, unit) 산출 후
        후보·단위를 리셋(다음 표는 자기 단위 커버가 따로 있다고 가정).
    """
    unit = 1
    candidate: str | None = None
    for el in soup.find_all(["p", "table"]):
        if el.name == "table":
            cls = el.get("class") or []
            if "nb" in cls:
                m = _UNIT_RE.search(el.get_text())
                if m:
                    unit = _UNIT_FACTOR.get(m.group(1), 1)
                continue
            if el.get("border") == "1":
                if candidate:
                    yield candidate, el, unit
                candidate = None
                unit = 1
            continue

        cls = el.get("class") or []
        text_norm = re.sub(r"\s+", "", el.get_text().strip())
        if "section-3" in cls:
            candidate = _match_statement(text_norm)
        elif "table-group" in cls:
            stmt = _match_statement(text_norm)
            if stmt:
                candidate = stmt
        elif not cls:
            if candidate is None and 0 < len(text_norm) <= 15:
                stmt = _match_statement(text_norm)
                if stmt:
                    candidate = stmt


# 정상적인 개별 계정 라벨(영문 대역어 포함)은 이보다 훨씬 짧다 — 실측
# (KD "1)현금및현금등가물(주2,3,11)(Cash and Cash Equivalents)" 약 35자)보다
# 넉넉히 여유를 둔 상한.
_MAX_REASONABLE_LABEL_LEN = 80


# ── 헤더 먼저 읽기(2026-09-10, docs/plans/header_first_parsing_expansion_design_
# 2026-09-10.md §1) — 레이아웃 B(행별-TR형) 전용. `<THEAD>`가 있으면(실측 대다수 —
# 이 파일의 기존 테스트 fixture 전부가 이미 `<THEAD>`를 씀) 그걸 최우선으로 읽는다,
# XML의 R88과 동일. 드물게 `<THEAD>`가 없는 구서식은 헤더행이 `<TBODY>` 선두 `<TR>`
# (들)로 섞여 오는데(pre-2015 XML과 같은 문제, `table_extractor.py`의 §7 확장과
# 동일 정책) 그때만 내용판정(`_looks_like_header_row`)으로 THEAD 대용을 모은다.
# 그리드→HeaderColumn 해석(`_columns_from_grid`)은 어느 경로든 공유한다(중복 방지).
# COLSPAN/ROWSPAN 그리드 해석 자체는 BeautifulSoup Tag API가 lxml과 달라 독자 사본을
# 둔다(이 파일이 `fin2/extract/pdf.py`의 `_TITLE_TOKENS`를 독자 사본으로 두는 것과
# 같은 이유 — 서로 다른 트리 API를 억지로 공용화하기보다 각자 진화 가능하게 둔다).


def _resolve_bs4_header_grid(header_trs: list[Tag]) -> Optional[list[list[str]]]:
    """`table_extractor.py::_resolve_header_grid()`와 동일한 표준 HTML COLSPAN/ROWSPAN
    해석을 BeautifulSoup Tag에 맞게 재구현."""
    if not header_trs:
        return None
    n_rows = len(header_trs)
    cells_by_row: list[dict[int, str]] = [dict() for _ in range(n_rows)]
    for r, tr in enumerate(header_trs):
        col = 0
        for cell in tr.find_all(["td", "th"], recursive=False):
            while col in cells_by_row[r]:
                col += 1
            try:
                colspan = int(cell.get("colspan", "1") or "1")
            except ValueError:
                colspan = 1
            try:
                rowspan = int(cell.get("rowspan", "1") or "1")
            except ValueError:
                rowspan = 1
            text = cell.get_text().strip()
            for rr in range(r, min(r + rowspan, n_rows)):
                for cc in range(col, col + max(colspan, 1)):
                    cells_by_row[rr][cc] = text
            col += max(colspan, 1)
    n_cols = max((max(d.keys()) + 1 for d in cells_by_row if d), default=0)
    if n_cols == 0:
        return None
    return [[cells_by_row[r].get(c, "") for c in range(n_cols)] for r in range(n_rows)]


def _detect_header_trs_bs4(trs: list[Tag]) -> list[Tag]:
    """선두 TR들 중 `_looks_like_header_row`에 걸리는 것만 모은다(THEAD 대용) — 처음
    으로 안 걸리는(=진짜 데이터) TR을 만나면 멈춘다(`table_extractor.py::
    _headerless_header_trs`와 같은 정책, XML lxml 트리 대신 BS4 Tag 버전)."""
    header_trs: list[Tag] = []
    for tr in trs:
        cell_texts = [td.get_text().strip() for td in tr.find_all("td", recursive=False)]
        if not cell_texts or not _looks_like_header_row(cell_texts):
            break
        header_trs.append(tr)
    return header_trs


def _parse_header_columns_bs4(
    table: Tag, tbody_trs: list[Tag],
) -> tuple[Optional[list[HeaderColumn]], int]:
    """레이아웃 B 표 → (HeaderColumn 리스트 또는 None, `<TBODY>` 선두에서 헤더로 소비한
    TR 개수). 실측(2026-09-10, rcpNo=20010814000859 제일기획 연결 라이브 재확인)
    — 실제 DART 웹뷰어 표는 XML과 마찬가지로 `<THEAD>`를 갖는 경우가 대다수다
    (이 파일의 기존 테스트 fixture 전부가 `<THEAD>`를 포함하는 것도 같은 이유).
    ★그래서 THEAD가 있으면 그걸 최우선으로 쓴다(구조적 신호가 있는데 무시하고
    TBODY 선두 내용판정으로 갈 이유가 없다) — `<TBODY>`의 TR은 전부 데이터 행이라
    2번째 반환값은 0. THEAD가 없을 때만(§7과 같은 예외적 구서식) `_detect_header_
    trs_bs4`로 TBODY 선두를 훑는다. 실패(헤더행 후보 없음·그리드 해석 실패·기간
    패턴 인식 실패)하면 (None, 0) — 호출측이 기존 값-위치 휴리스틱으로 완전히
    폴백한다."""
    thead = table.find("thead")
    if thead is not None:
        header_trs = thead.find_all("tr", recursive=False)
        n_consumed_from_tbody = 0
    else:
        header_trs = _detect_header_trs_bs4(tbody_trs)
        n_consumed_from_tbody = len(header_trs)
    if not header_trs:
        return None, 0
    grid = _resolve_bs4_header_grid(header_trs)
    if grid is None:
        return None, 0
    columns = _columns_from_grid(grid)
    if columns is None:
        return None, 0
    return columns, n_consumed_from_tbody


def _iter_label_value0(table: Tag):
    """표 하나 → (label, value_text, is_giant_cell) 스트림, col0(당기)만.

    `is_giant_cell`: 이 항목이 레이아웃 A(거대-셀형, `<BR/>`로만 항목 구분)
    에서 나왔는지 — `facts_from_sections()`가 그랜드토탈 3종에 한해 라벨
    엄격검사(§ _STRICT_TOTAL_LABELS)를 적용할지 판단하는 데 쓴다(레이아웃
    B는 애초에 각 라벨이 자기 `<TD>`로 이미 분리돼 있어 이 위험이 없음).

    레이아웃 감지(§8-1/§8-2 census와 동일 휴리스틱): `<TBODY>`에 `<TR>`이
    1~2개뿐이고 첫 데이터 셀에 `<BR/>`이 여러 개(≥5)면 레이아웃 A(거대-셀형).
    그 외에는 레이아웃 B(행별-TR형).
    """
    tbody = table.find("tbody")
    if not tbody:
        return
    trs = tbody.find_all("tr", recursive=False)
    if not trs:
        return
    first_tds = trs[0].find_all("td", recursive=False)
    is_giant_cell = (
        len(trs) <= 2 and len(first_tds) >= 2
        and len(first_tds[0].find_all("br")) >= 5
    )
    if is_giant_cell:
        label_segs = _split_by_br(first_tds[0])
        value_segs = _split_by_br(first_tds[1])
        # ★방어적 가드(일반) — 세그먼트 하나가 비정상적으로 길면(개별 계정
        # 라벨은 영문 대역어를 포함해도 이보다 훨씬 짧다) 여러 항목이
        # 구분자 없이 한 세그먼트에 뭉쳤을 가능성이 높다는 뜻 — 어디서
        # 잘라야 할지 원리적으로 모호해 짐작으로 잘라내면 값이 엉뚱한
        # 라벨에 붙을 위험이 있다("결측이 오염보다 낫다" 원칙). 그런
        # 세그먼트가 하나라도 있으면 표 전체를 신뢰 못 함 — 통째로 스킵.
        # ★주의(2026-09-07, 일성건설 00146232·일진디스플 00198697 fail19
        # 비교 중 발견) — 이 두 필링이 바로 그 "여러 라벨이 뭉친" 사례지만
        # 실측해보니 뭉친 세그먼트도 길이가 짧다(최대 19자, 실측 확인) —
        # "자산총계부채"처럼 합계 라벨이 다음 섹션 머리글과 **구분자 없이
        # 바로 붙되 둘 다 원래 짧은 단어**라 길이만으로는 못 잡는다. 즉
        # 이 가드는 이 두 필링을 걸러내지 못한다(원인B는 여전히 미해결 —
        # 다음에 이 표를 만나면 값이 조용히 틀린 라벨에 매핑될 수 있다는
        # 뜻, §7 리스크로 남김). 더 극단적인(진짜 긴) 뭉침 사례에 대한
        # 최소한의 안전판으로만 유지.
        if any(len(re.sub(r"\s+", "", s)) > _MAX_REASONABLE_LABEL_LEN for s in label_segs):
            return
        for lab, val in zip(label_segs, value_segs):
            lab = lab.strip()
            if lab:
                yield lab, val.strip(), True
        return

    # ── 레이아웃 B: 헤더를 먼저 읽어 위치→기간 맵을 만들고, 그 맵으로 "당기(rank0)"
    # 열을 직접 인덱싱한다(2026-09-10 확장, 위 §1 주석 참고) — 성공하면 아래 값-위치
    # 휴리스틱을 완전히 우회한다. 이러면 3개월/누적 2단헤더 구분(모듈 docstring이
    # 자인하던 갭)도 R85와 같은 원칙(cumulative 우선, 없어도 3개월로 대체 안 함)으로
    # 같이 해소된다. THEAD가 아예 없는 표라 실패(헤더행 후보를 못 찾음·기간패턴 인식
    # 실패)하는 경우가 XML보다 흔할 수 있다 — 그때만 기존 값-위치 휴리스틱으로 완전히
    # 폴백한다(회귀 위험 최소화, R88과 동일 안전원칙).
    columns, n_header_trs = _parse_header_columns_bs4(table, trs)
    if columns is not None:
        for tr in trs[n_header_trs:]:
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 2:
                continue
            label = tds[0].get_text().strip()
            if not label:
                continue
            value_tds = tds[1:]
            amounts = [parse_number(td.get_text().strip()) for td in value_tds]
            picked = select_by_header_columns(columns, amounts)
            if 0 not in picked:
                continue  # 당기(rank0) 값 없음 — 진짜 결측 또는 판정 불가(R6) → 스킵
            # `select_by_header_columns`는 이미 파싱된 int(picked[0])만 돌려준다 —
            # 어느 물리 위치에서 왔는지 값만으로 역추적하면 동값 충돌에 취약하니
            # (0/0 등) 텍스트로 되짚지 않는다. 호출측(`facts_from_sections`)은 이
            # value_text 를 다시 `parse_number()`로 재파싱만 하므로, 이미 확정된
            # 정수를 문자열로 그대로 넘겨도 동치(부호 포함 — `parse_number("-123")`
            # 은 음수로 정상 인식).
            yield label, str(picked[0]), False
        return

    # ── 값-위치 휴리스틱(폴백, THEAD 없는 XML의 R85~R87 이전과 같은 계열) — 라벨
    # 다음 TD들 중 **실제로 숫자로 파싱되는 첫 셀**을 col0 값으로 취한다. 처음엔
    # "표 전체에서 첫 비어있지 않은 셀"(행별 판정)이었는데, 제일기획(00148276) 연결
    # 실측(2026-09-07)에서 헤더가 "제28기/제27기/제26기"인데 앞 두 컬럼이 전부 진짜
    # 대시("-")고 실제 값은 가장 오른쪽에만 있는 경우를 발견 — 대시에서 멈춰 값을
    # 놓쳤다(원인A). "표 전체에서 데이터 있는 첫 컬럼을 고정"하는 방식으로 한 번
    # 고쳐봤으나 DB증권(00115694) 실측으로 반증됨 — **같은 표 안에서도 행마다 빈칸의
    # 물리적 위치가 다르다**(일반 항목행은 [값1,빈칸,값2,빈칸], 합계행은 [빈칸,값1,
    # 빈칸,값2] 처럼 합계행에만 앞에 빈칸 하나가 더 낌, 아마 서식상 합계 들여쓰기
    # 때문으로 추정). 그래서 컬럼 인덱스를 표 단위로 고정하면 안 되고, 여전히
    # **행마다** 판정해야 한다 — 다만 "비어있지 않으면 멈춤"이 아니라 "**숫자로
    # 파싱되면** 멈춤"으로 바꿔 완전 빈칸과 대시(둘 다 그 칸엔 값이 없다는 뜻)를
    # 똑같이 건너뛰고 진짜 첫 숫자에서 멈춘다 — DB증권류(빈칸)·제일기획류(대시) 모두
    # 이 규칙 하나로 커버됨.
    # ★주의(2026-09-10) — 위 헤더그리드 경로가 성공하는 표에서는 이 폴백이 더 이상
    # 돌지 않는다(위 `return`). 제일기획류(당기가 진짜 대시고 값은 전전기에만 있는
    # 행)에서 이 휴리스틱이 "첫 숫자"로 전전기 값을 주워 당기로 둔갑시키던 것이
    # 바로 R86/R87과 같은 클래스의 결함이었다 — 헤더그리드 경로는 그런 행을 (전전기
    # 값을 당기로 둔갑시키지 않고) 정직하게 결측으로 남긴다. 이 폴백은 헤더행 자체를
    # 못 찾는 표(THEAD도 없고 TBODY 선두도 헤더 패턴이 아님)에서만 남는다.
    for tr in trs:
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2:
            continue
        label = tds[0].get_text().strip()
        if not label:
            continue
        value_text = ""
        for vtd in tds[1:]:
            t = vtd.get_text().strip()
            if t and parse_number(t) is not None:
                value_text = t
                break
        yield label, value_text, False


def facts_from_sections(
    sections: dict[str, bytes],
    *,
    corp_code: str,
    rcept_no: str,
    report_fiscal_year: int,
    report_fiscal_period: str,
) -> list[ExtractedFact]:
    """섹션 HTML 바이트(basis별) → ExtractedFact 리스트. I/O 와 분리(테스트 가능).

    `sections`: {"separate": html_bytes, "consolidated": html_bytes} — 한쪽만
    있어도 됨(연결재무제표 없는 필링, §4-보강에서 확인된 흔한 케이스).
    """
    mapper = get_mapper()
    facts: list[ExtractedFact] = []
    seen: set[tuple] = set()

    for basis, html_bytes in sections.items():
        if not html_bytes:
            continue
        soup = BeautifulSoup(html_bytes, "lxml")
        for stmt, table, unit in _iter_statement_tables(soup):
            if stmt == "SCE":
                continue
            adecimal = _adecimal_from_unit(unit)
            fs_section = stmt.lower()
            period_kind = "instant" if stmt == "BS" else "duration"
            for raw_label, value_text, is_giant_cell in _iter_label_value0(table):
                amount = parse_number(value_text)
                if amount is None:
                    continue
                # ★실측 발견(제일기획 00148276, 2026-09-07 구현 직후 PDF결과 비교 중) —
                # 일부 필링은 라벨을 "유동자산(Current Assets)" 처럼 단일 줄 이중언어로
                # 적는다(3줄 분리형과 다른 변형). fin2/extract/pdf.py 가 세 곳의 라벨
                # 추출 지점 전부에서 이미 하는 처리(`_strip_inline_english_gloss`)를
                # 여기서도 그대로 재사용 — 안 하면 account_mapper 가 못 알아봐 그
                # basis/statement 전체가 통째로 빈손이 된다(72행 파싱은 됐지만 매핑이
                # 전부 실패해 facts 0건 → 상류 비교스크립트에 None/None/None으로 보임).
                label = _strip_inline_english_gloss(raw_label)
                mapping = mapper.map(label, fs_section=fs_section)
                canon = mapping.account_code
                if not canon or canon.startswith("unknown."):
                    continue
                if not canon.startswith(stmt.lower() + "."):
                    continue
                # ★원인B 부분 대응(일성건설 00146232·일진디스플 00198697 실측,
                # 2026-09-07) — 레이아웃 A는 <BR/> 분리 단위가 항목보다 굵을 수
                # 있어(§_MAX_REASONABLE_LABEL_LEN 주석 참고) "3)영업권자산총계"
                # 처럼 이전 항목의 꼬리가 그랜드토탈 라벨에 구분자 없이 붙을 수
                # 있다. `account_mapper`는 substring 포함만으로도 fuzzy 매치
                # 하므로("자산총계부채"→bs.total_assets 실측 확인) 이 오염된
                # 라벨도 그대로 통과해버린다 — 값까지 우연히 파싱되면 조용히
                # 틀린 숫자가 정답처럼 보이는 canonical_account 에 실린다. 항등식
                # 검증(자산=부채+자본) 기준선인 이 세 계정만은 예외 없이 "정확히
                # 이 단어"여야 인정 — 나머지 계정(세부 라인아이템)은 지금처럼
                # fuzzy 매치를 그대로 허용(오탐 위험이 훨씬 낮고, 여기까지
                # 막으면 정상 필링에서도 과도하게 결측이 늘어남).
                if is_giant_cell and canon in _STRICT_TOTAL_LABELS:
                    acode_check = (normalize_account_name(label) or label).strip()
                    if acode_check not in _STRICT_TOTAL_LABELS[canon]:
                        continue
                if canon == "is.tax_expense" and "차감전" in label:
                    continue
                amount_won = amount * unit
                if abs(amount_won) > 10 ** 16:
                    continue
                magnitude_cap = {
                    "bs.total_assets": 1e15, "bs.total_equity": 5e14,
                    "bs.retained_earnings": 5e14, "is.revenue": 4e14,
                }.get(canon)
                if magnitude_cap is not None and abs(amount_won) > magnitude_cap:
                    continue
                is_cumulative = period_kind == "duration" and report_fiscal_period != "FY"
                acode = (normalize_account_name(label) or label)[:120]
                key = (acode, stmt, basis)
                if key in seen:
                    continue
                seen.add(key)
                facts.append(ExtractedFact(
                    corp_code=corp_code,
                    rcept_no=rcept_no,
                    report_fiscal_year=report_fiscal_year,
                    report_fiscal_period=report_fiscal_period,
                    acode=acode,
                    basis=basis,
                    context_fiscal_year=report_fiscal_year,
                    col_index=0,
                    period_kind=period_kind,
                    period_type="FY" if report_fiscal_period == "FY" else report_fiscal_period,
                    is_cumulative=is_cumulative,
                    extra_dims=None,
                    is_dimensional=False,
                    adecimal=adecimal,
                    amount_won=amount_won,
                    source_format="html",
                    source_ref=f"{stmt}_{basis[:3]}/{label[:60]}"[:180],
                    acontext_raw=f"html:{stmt}:{basis[:3]}:c0:{report_fiscal_year}",
                    context_parsed=False,
                    canonical_account=canon,
                ))

    _fix_paren_formatted_bs(facts)
    _fix_swapped_grand_total_equity(facts)
    return facts


def _adecimal_from_unit(unit: int) -> int:
    import math
    if unit <= 1:
        return 0
    return -int(round(math.log10(unit)))


def extract_html_facts(
    scraper,
    rcept_no: str,
    *,
    corp_code: str,
    report_fiscal_year: int,
    report_fiscal_period: str,
) -> list[ExtractedFact]:
    """rcept_no 하나 → 웹뷰어에서 재무제표 섹션(별도+연결) 실제 fetch 후 파싱.

    `scraper`: `collector.legacy_downloader.LegacyDartScraper` 인스턴스(호출자가
    생성·재사용 — 세션 쿠키·스로틀 유지를 위해 여러 rcept_no에 걸쳐 재사용할 것).
    """
    toc_text = scraper.fetch_toc_page(rcept_no)
    if toc_text is None:
        return []
    nodes = parse_toc_tree(toc_text)
    fs_nodes = find_statement_nodes(nodes)
    if not fs_nodes:
        return []

    sections: dict[str, bytes] = {}
    for node in fs_nodes:
        basis = "consolidated" if "연결" in node.text else "separate"
        html_bytes = scraper.fetch_viewer_section(
            rcept_no, dcm_no=node.dcm_no, ele_id=node.ele_id,
            offset=node.offset, length=node.length, dtd=node.dtd,
        )
        if html_bytes:
            sections[basis] = html_bytes

    if not sections:
        return []
    return facts_from_sections(
        sections, corp_code=corp_code, rcept_no=rcept_no,
        report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
    )
