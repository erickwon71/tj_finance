"""pre-2015(K-GAAP 구서식) 계층2 2차 패스 — 본문표 식별.

설계 = `docs/plans/pre2015_layer2_backfill_phase2_design_2026-08-10.md` §2-1.
실측 근거 = `docs/qa/pre2015_existing_pipeline_reuse_probe_2026-08-10.md` (근본원인) ·
`docs/qa/pre2015_boundary_walk_prototype_probe_2026-08-10.md` (수정안 검증, 2004~2007
annual 8/8=100% 회복).

★ 근본원인(실측, 원문 XML 직접 대조 — 현대모비스 20000330000228 등):
`assign_tables_to_dart_sections`(`parser/xml/section_detector.py`) 와 그 짝인
`iter_section_elements` 는 **중첩 깊이 무관하게** "SECTION 으로 시작하는 태그를 만날 때마다"
현재 섹션을 재판정한다. 최상위 `<SECTION-2><TITLE>3. 재무제표</TITLE>` 매치가 성공해도, 그
안의 `<SECTION-3><TITLE>가. 대차대조표</TITLE>` (K-GAAP 특유의 한글서수 하위표제) 를
`classify_dart_section` 이 인식 못 해 **즉시 리셋**한다 — 최상위 매치 이후의 모든 TABLE 이
후보에서 탈락한다(1999~2008 실측 0%). 2011~2014 는 이 하위표제 자체가 없어져(TITLE 소멸)
반대로 우연히 100% 성공한다.

이 모듈은 **기존 2015+ 소비 경로를 한 줄도 건드리지 않는다**(회귀 방지가 Phase3 완료
조건 — 위 설계문서 §4). `assign_tables_to_dart_sections`/`iter_section_elements` 의
"부분일치 아니면 즉시 리셋"은 2015+ 문서에서 **의도된 안전장치**다(요약재무정보·주석
섹션 오분류 방지, `section_detector.py:89-93` 실측 근거) — 그 규칙을 깊이인식으로 바꾸면
2015+ 문서에도 영향이 가 이득 없이 회귀 위험만 커진다. 대신 새 함수 + 연도 라우팅으로
pre-2015 만 이 경로를 탄다(라우팅 지점 = `report_lines.py::extract_report_lines`).
"""
from __future__ import annotations

import re

from lxml import etree

from parser.xml.section_detector import (
    SEC_CONSOL_FS, SEC_SEP_FS, normalize_dart_section_title,
)
from fin2.extract.statement_titles import (
    SECTION_CODE_OF, _LEGACY_ENUM_PREFIX, _LEGACY_EXCLUDE, is_legacy_note_marker,
)
from fin2.extract.text import _LEGACY_PENDING_SPAN, _table_has_data_rows, declared_unit


# 한글서수 하위표제 접두("가." "나." "다." … "하.") — K-GAAP 특유. 숫자/로마숫자 접두
# (`_LEGACY_ENUM_PREFIX`, 주석 번호)와는 별개 패턴이라 따로 벗긴다.
# ★2026-09-05(설계, 아래 §A-2 참고) — `iter_section_span_depth_aware()`의 진입판정에서도
# 재사용하므로 `classify_pre2015_statement_heading()`보다 앞에 선언한다.
_PRE2015_ORDINAL_PREFIX = re.compile(r"^[가-힣]\s*[.．)）]\s*")


def iter_section_span_depth_aware(
    root: "etree._Element", normalized_title: str,
) -> list[tuple[str, "etree._Element"]]:
    """`iter_section_elements` 와 같은 계약(한 섹션 구간의 요소를 문서 순서로 [(태그,요소),…])
    이지만, **진입 깊이와 같거나 얕은 레벨의 표제 변경에서만** 구간을 끝낸다.

    `iter_section_elements`/`assign_tables_to_dart_sections` 는 SECTION 진입 깊이를 보지
    않아 K-GAAP 의 중첩 하위표제("가.대차대조표")를 만나는 즉시 구간을 리셋한다(위 모듈
    docstring 근본원인 참고). 이 워커는 SECTION 진입/퇴장을 깊이 카운터로 추적해, 하위표제
    (entry_depth 보다 깊은 SECTION)는 통과시키고 그 TITLE 텍스트도 요소로 낸다(표제 헤딩
    앵커로 쓰기 위함) — **형제-이하 레벨**(entry_depth 이하)의 다른 표제를 만났을 때만
    구간을 종료한다.

    2015+ 소비 경로는 이 함수를 쓰지 않는다(pre-2015 라우팅 전용, 회귀 위험 없음).

    ★A-1(2026-09-05, 실측 재현 — 호텔신라 20050915000066) — 하위표제 통과 시 **SECTION
    컨테이너 자신**을 append하면 `el.itertext()`가 그 서브트리 전체(자기 TITLE + 데이터표
    전부)를 통짜 문자열로 합쳐, 뒤이은 헤딩 판정(`classify_pre2015_statement_heading`)이
    "명칭 뒤에 다른 한글이 이어지면 거부"에 걸려 실패한다. 이 함수 자신의 docstring(위
    문단)은 원래 "TITLE 텍스트만 낸다"고 약속했는데 실제 코드엔 그 필터가 없었던 것 —
    새 설계가 아니라 버그 수정이다. SECTION 컨테이너 자신은 **절대 append하지 않고**
    (항상 continue), 통과되는 하위표제의 TITLE 텍스트만 별도로 낸다.

    ★A-2(2026-09-05, 실측 재현 — SK네트웍스 20080331001324) — `normalize_dart_section_title`
    은 숫자·로마숫자 접두만 벗기고 한글 가나다 접두는 안 벗긴다. `SEC_SEP_FS`/`SEC_CONSOL_FS`
    와 **정확일치하는 제목이 SECTION-3에 "라. 재무제표"처럼 가나다 접두를 달고 있는 문서**는
    진입판정(`norm == normalized_title`)이 영원히 실패해 이 함수가 통째로 빈 결과를 낸다.
    진입판정에서만 가나다 접두를 추가로 벗겨 재비교한다(`normalize_dart_section_title` 자체는
    2015+ 주경로와 공유되므로 안 건드린다 — 설계문서
    `category_c_fy2004_2006_section3_and_summary_prefix_design_2026-09-05.md` §2-3 옵션1).
    """
    out: list[tuple[str, "etree._Element"]] = []
    inside = False
    entry_depth: int | None = None
    depth = 0
    for event, el in etree.iterwalk(root, events=("start", "end")):
        tag = el.tag.upper() if isinstance(el.tag, str) else ""
        is_section = tag.startswith("SECTION")
        if event == "end":
            if is_section:
                depth -= 1
            continue
        # event == "start"
        if is_section:
            depth += 1
            title_elem = el.find("TITLE")
            norm = (normalize_dart_section_title("".join(title_elem.itertext()))
                    if title_elem is not None else None)
            # A-2 — 진입판정 전용: 가나다 접두를 추가로 벗겨 한 번 더 비교.
            norm_stripped = _PRE2015_ORDINAL_PREFIX.sub("", norm) if norm else norm
            if inside and norm is not None and depth <= entry_depth and norm != normalized_title:
                inside = False
                entry_depth = None
            elif not inside and (norm == normalized_title or norm_stripped == normalized_title):
                inside = True
                entry_depth = depth
            elif inside and title_elem is not None:
                # A-1 — 하위표제 통과: 컨테이너 자신이 아니라 TITLE 텍스트만 헤딩 후보로 낸다.
                out.append(("TITLE", title_elem))
            continue
        if inside and tag != "TITLE":
            anc = el.getparent()
            in_table = False
            while anc is not None:
                if isinstance(anc.tag, str) and anc.tag.upper() == "TABLE":
                    in_table = True
                    break
                anc = anc.getparent()
            if not in_table:
                out.append((tag, el))
    return out
_PRE2015_HEAD = re.compile(
    r"^(?:연결|별도|개별|반기|분기|중간|당|전)*"
    r"(재무상태표|대차대조표|포괄손익계산서|손익계산서|현금흐름표|자본변동표|"
    r"이익잉여금처분계산서|결손금처리계산서)"
)
_PRE2015_PERIOD_AFTER = re.compile(
    r"^(?:제\d+(?:\([^)]*\))?기|\d{4}[.\-년]|[당전]?(?:반기말|분기말|기말)|"
    r"[(（]?단위|[당전]기(?=[\d(（]))"
)
_PRE2015_NAME_TO_CODE = {
    "재무상태표": "BS", "대차대조표": "BS",
    "포괄손익계산서": "IS", "손익계산서": "IS",
    "현금흐름표": "CF", "자본변동표": "SCE",
    "이익잉여금처분계산서": "APPR", "결손금처리계산서": "APPR",
}


def classify_pre2015_statement_heading(
    text_: str, include_sce: bool = False,
) -> tuple[str, str] | None:
    """K-GAAP 중첩 하위표제("가. 대차대조표" 등) → (basis, statement) 또는 None.

    `classify_legacy_statement_heading`(`fin2/extract/statement_titles.py`, 2015+ 구형
    병합섹션 `재무제표등` 폴백 전용 — **그대로 둔다**, 이 함수는 그 조건을 복사해 확장한다)
    과 두 가지가 다르다(설계문서 §2-1):
      1. **한글서수 접두 제거** — 원문 표제 자체가 "가.대차대조표" 형태(원본 함수는 숫자·
         로마숫자 접두만 벗긴다, 주석 번호용).
      2. **K-GAAP 전용 표 인식** — 이익잉여금처분계산서/결손금처리계산서 → 코드 `APPR`
         (사용자 결정 Q1=포함, `pre2015_layer2_backfill_todo_2026-08-10.md`).

    통과 조건은 원본과 동일(번호 접두 없음 · 배제어 없음 · 재무제표명으로 시작 · 명칭 직후
    기간/단위 마커 또는 명칭 단독) — 상세는 `classify_legacy_statement_heading` docstring.

    ★ 반환하는 basis 는 **참고용**이다. 호출측(`detect_pre2015_body_statement_tables`)은
    이 섹션들(`SEC_SEP_FS`/`SEC_CONSOL_FS`)이 이미 분리형이라 basis 를 섹션 자체가
    보장한다고 보고 **이 반환값의 basis 를 쓰지 않는다** — 표제 문구에 '연결' 접두가
    항상 있는지는 Phase1 에서 실측되지 않은 채로 남았다(연결 섹션 하위 표제 구조 미확인,
    `pre2015_layer2_backfill_plan_2026-08-10.md` §3). 접두가 없는 경우까지 이 반환값의
    basis 를 신뢰하면 별도(separate) 그룹과 뒤섞일 위험이 있어, 더 안전한 섹션-권위
    원칙(2015+ 주경로와 동일, `_detect_body_statement_tables` 참고)을 택한다.
    """
    if not text_:
        return None
    t = re.sub(r"\s+", "", text_)
    if _PRE2015_ORDINAL_PREFIX.match(t):
        t = _PRE2015_ORDINAL_PREFIX.sub("", t)
    if not t or _LEGACY_ENUM_PREFIX.match(t):
        return None
    if _LEGACY_EXCLUDE.search(t[:45]):
        return None
    m = _PRE2015_HEAD.match(t)
    if m is None:
        return None
    stmt = _PRE2015_NAME_TO_CODE[m.group(1)]
    if stmt == "SCE" and not include_sce:
        return None
    rest = t[m.end():].lstrip("：:·-—")
    if rest and not _PRE2015_PERIOD_AFTER.match(rest):
        return None
    basis = "consolidated" if "연결" in t[:m.start(1)] else "separate"
    return (basis, stmt)


def detect_pre2015_body_statement_tables(
    root: "etree._Element", fin_type: str, include_sce: bool = False,
) -> dict[str, list[tuple]]:
    """pre-2015(1999~2010대) K-GAAP 레이아웃 본문표 식별(설계문서 §2-1 결정).

    `_detect_legacy_body_statement_tables`(2015+ 구형 **병합** 섹션 `재무제표등` 전용, 그대로
    유지)의 pending-anchor-then-data-table 패턴을 재사용하되 두 가지를 바꾼다:
      · 훑는 대상 = `SEC_LEGACY_FS`(병합 단일 섹션) 대신 **`SEC_SEP_FS`/`SEC_CONSOL_FS`**
        (1999~2010 의 실제 구조 = 연결/별도 **분리형** 최상위 섹션, 2015+ 주경로와 동일 종류).
      · 워커 = `iter_section_elements` 대신 `iter_section_span_depth_aware`(중첩 하위표제를
        통과시키기 위함) + 헤딩분류기 = `classify_pre2015_statement_heading`.

    basis 는 섹션 자체(SEC_SEP_FS→separate / SEC_CONSOL_FS→consolidated)로 확정한다 —
    2015+ 주경로와 같은 원칙(위 `classify_pre2015_statement_heading` 참고 basis 불신 이유).

    호출측(`report_lines.py::extract_report_lines`)이 `report_fiscal_year` 로 라우팅한다 —
    이 함수 자신은 연도를 보지 않는다(순수 구조 판단, R0).

    반환 계약은 `_detect_body_statement_tables`/`_detect_legacy_body_statement_tables` 와
    동일: {section_code: [(table_elem, unit, section_kind), ...]}.
    """
    groups: dict[str, list[tuple]] = {}

    for sec_title, basis in ((SEC_SEP_FS, "separate"), (SEC_CONSOL_FS, "consolidated")):
        if basis == "consolidated" and fin_type == "B":
            continue  # 연결 없는 기업의 연결 표 무시(2015+ 경로와 동일 규약)
        norm_title = normalize_dart_section_title(sec_title)
        elements = iter_section_span_depth_aware(root, norm_title)
        pending: str | None = None          # statement 만 들고 있는다(basis 는 섹션이 확정)
        pending_unit: int | None = None
        pending_age = 0

        for tag, el in elements:
            text_ = " ".join("".join(el.itertext()).split())

            if pending is not None:
                pending_age += 1
                if pending_age > _LEGACY_PENDING_SPAN:
                    pending = None            # 데이터표 없이 끝난 헤딩 — 멀리서 끌어오지 않는다
                    pending_unit = None

            if tag == "TABLE" and _table_has_data_rows(el):
                if pending is None:
                    continue                  # 관장 헤딩 없는 데이터표 = 주석/부속표 → 취하지 않음
                unit = pending_unit if pending_unit is not None else declared_unit(el)
                section_code = SECTION_CODE_OF[(basis, pending)]
                groups.setdefault(section_code, []).append((el, unit, sec_title))
                pending = None
                pending_unit = None
                continue

            if is_legacy_note_marker(text_):
                pending = None                # 주석 구간 진입 — 대기 중 헤딩도 버린다
                pending_unit = None
                continue

            head = classify_pre2015_statement_heading(text_, include_sce=include_sce)
            if head is not None:
                _heading_basis, stmt = head    # basis 는 버린다(위 docstring 이유)
                pending = stmt
                pending_age = 0
                # 헤딩이 표(제목표)면 그 표가 단위를 들고 있을 수 있다(A형 '… (단위 : 원)').
                pending_unit = declared_unit(el) if tag == "TABLE" else None

    return groups
