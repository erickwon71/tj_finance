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
    SEC_CONSOL_FS, SEC_SEP_FS, normalize_dart_section_title, table_direct_rows,
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


# ── (A-3, 2026-09-05) 통짜-셀 레거시 BS 표 — total_assets 한정 안전 복구 ──────────
# 설계문서: docs/plans/category_c_a3_squished_cell_bs_total_assets_design_2026-09-05.md
#
# 위 `detect_pre2015_body_statement_tables()`가 BS 데이터표를 못 찾는 문서의 96.7%가
# "표 하나가 물리적으로 TR 1개뿐이고 계정과목·금액이 각각 줄바꿈 없이 셀 하나에 통짜로
# 이어붙은" 옛 포맷이다(무작위 60건 실측). 개별 라인아이템 재구성은 라벨 셀의 항목 간
# 공백 폭이 불규칙(실측: "미착자재 Ⅱ.고정자산"이 한 항목으로 오분리)해 안전하지 않지만,
# **"부채와자본총계"가 DART 서식상 항상 BS의 마지막 줄**이라는 관행 + 회계항등식
# (자산=부채+자본)을 쓰면 total_assets 하나만은 위치 무관하게 안전하게 복구된다 —
# 몇 번째 항목인지 셀 필요 없이 그냥 각 컬럼의 마지막 숫자 토큰을 취하면 된다.
#
# 실측검증: 3개사(호텔신라 20050915000066·한국팩키지 20040528000335·삼표시멘트
# 20051214000337) 라벨 꼬리 전부 "...총계부채와자본총계"로 끝남 확인. 한국팩키지
# fy2004 Q1 복구값(35,292,944,214)이 인접기간 실측값(H1 36,908,500,244·Q3
# 37,700,319,350)의 성장궤적과 정확히 일치. 무작위 80건 재확인 — 라벨꼬리 게이트
# 재현율 75/75(100%).
_SQUISHED_TOTAL_TAIL_RE = re.compile(r"(부채와자본총계|자산총계)$")
# 콤마 3자리 그룹(최소 1개조=4자리 이상)만 인정 — 표제표의 날짜 숫자('2005')나 기수
# ('제33기')를 금액으로 오인하지 않기 위함(콤마 없는 순수 1~3자리 숫자는 절대 안 잡음,
# `_table_has_data_rows`/`_AMOUNT_CELL_RE`와 같은 "콤마 그룹" 요건). 음수는 원문 자체에
# 이미 부호가 박혀있다(실측: ASCII '-'·'△'·'▲' 3종 — 결측/오염 방지를 위해 앞에 부호가
# 있어도 그대로 살린다).
_SQUISHED_AMOUNT_TOKEN_RE = re.compile(r"[△▲\-]?\d{1,3}(?:,\d{3})+")


def _extract_squished_bs_total(tables: list) -> int | None:
    """통짜-셀 BS 표 묶음에서 total_assets(=total_liabilities_and_equity)만 위치
    무관하게 복구한다. 실패 시(안전장치 불통과) None — 절대 추측하지 않는다. 값은
    아직 단위(천원/백만원 등) 배수를 안 곱한 원문 그대로의 정수다(호출측이 기존
    단위판정 경로를 적용한다).

    호출측(`detect_squished_bs_total_assets`)이 라벨이 "총계"로 끝나는 순간 즉시
    이 함수를 불러 확정하므로(더 안 기다림), `tables`는 **정확히 한 기간 분량**만
    담겨 있다고 가정할 수 있다 — 서로 다른 기간이 섞여 들어올 걱정은 호출측이
    이미 해소했다(아래 함수 docstring 참고).

    ★2026-09-05(구현 중 실측 발견, 빙그레 20050429000950) — 검증한 3개사(호텔신라·
    한국팩키지·삼표시멘트)는 표마다 값열이 **딱 하나**(당기 한 열)였는데, 일부
    문서는 **한 표 안에 같은 기간의 값열이 여러 개**다(실측: 제17기 하나에 열
    2개 — 항목수 15개짜리[부분/차감 세부로 추정]와 60개짜리[완전한 값]가 나란히).
    무조건 "첫 값열"을 취하면 항목수 적은 부분열을 총계로 오인한다(실측 확정 —
    그 열의 마지막 값이 참조기간 대비 1000배 이상 벗어남). **항목수(토큰 개수)가
    가장 많은 열 쪽을 신뢰**한다 — 완전한 값열은 거의 모든 계정과목에 값이 있어
    토큰이 많고, 부분/차감 열은 일부 항목에만 값이 있어 토큰이 적다.
    """
    if not tables:
        return None

    label_parts: list[str] = []
    # 표마다 "그 표의 값열 리스트"를 따로 모은다 — 표 사이에 열 개수가 다르면
    # (구조 불일치 신호) 안전하게 포기한다(아래).
    per_table_value_cols: list[list[str]] = []
    for tbl in tables:
        rows = table_direct_rows(tbl)
        if len(rows) < 2:
            continue  # 헤더뿐인 표(기간·단위 정보표, TD 1개) — 스킵
        tds = list(rows[1].iter("TD"))
        if len(tds) < 2:
            continue  # 실데이터 없는 행
        label_parts.append(tds[0].text or "")
        per_table_value_cols.append([td.text or "" for td in tds[1:]])

    label_nows = re.sub(r"\s+", "", "".join(label_parts))
    if not _SQUISHED_TOTAL_TAIL_RE.search(label_nows):
        return None
    if not per_table_value_cols:
        return None

    n_cols_set = {len(v) for v in per_table_value_cols}
    if len(n_cols_set) != 1:
        return None  # 표들 사이 값열 개수가 안 맞음 — 이어붙이면 안 되는 구조
    n_cols = n_cols_set.pop()
    if n_cols == 0:
        return None

    # 각 열의 토큰을 표 순서(='계속' 연속 페이지 순서)대로 이어붙여 개수를 센다.
    col_tokens: list[list[str]] = [[] for _ in range(n_cols)]
    for cols in per_table_value_cols:
        for k in range(n_cols):
            col_tokens[k].extend(_SQUISHED_AMOUNT_TOKEN_RE.findall(cols[k]))

    counts = [len(t) for t in col_tokens]
    max_count = max(counts)
    if max_count == 0:
        return None
    # 당기(맨 왼쪽) 후보를 찾되, 항목수가 최댓값의 75% 에 못 미치는(부분/차감열로
    # 추정) 열은 건너뛴다 — 검증된 3개사는 열마다 항목수가 거의 같아(83~84·73~75·
    # 66~77, 최저비율 66/77=0.857) 그냥 col0(첫 열)이 뽑히고, 부분열이 섞인 문서
    # (실측: 15~18개짜리 부분열 vs 56~76개짜리 완전열, 비율 0.24~0.27)만 다음 열로
    # 넘어간다. ★2026-09-05(구현 중 실측 발견, 프로텍 20050506000182) — 임계 0.5는
    # 부분열(34)이 완전열(68)의 정확히 절반이라 경계에서 오탐(부분열을 그대로 채택)
    # 하는 반례가 나와 0.75로 올림 — 위 3개사 최저비율(0.857)과 위 반례 최고비율
    # (0.5) 사이에 안전여유를 두고 잡은 값.
    target = next((k for k, c in enumerate(counts) if c >= max_count * 0.75), None)
    if target is None:
        return None
    tokens = col_tokens[target]
    if not tokens:
        return None
    raw = tokens[-1].replace(",", "").replace("△", "-").replace("▲", "-")
    value = int(raw)
    if value <= 0:
        return None
    return value


def detect_squished_bs_total_assets(
    root: "etree._Element", fin_type: str,
) -> dict[str, tuple[int, "etree._Element | None"]]:
    """`detect_pre2015_body_statement_tables()`가 BS 를 못 채운 문서에서만(호출측이
    이미 확인) 시도하는 **완전히 추가적인** 폴백 — 정상표가 있으면 이 함수 자체를
    호출할 필요가 없다(호출측 게이트, `report_lines.py::extract_report_lines`).

    위 `detect_pre2015_body_statement_tables()`와 같은 워커(`iter_section_span_
    depth_aware`+`classify_pre2015_statement_heading`)로 BS 헤딩을 찾은 뒤, 그
    구간에 나온 TABLE 을(정상표 판정 여부와 무관하게) 모은다.

    ★2026-09-05(구현 중 실측 발견, 롯데에너지머티리얼즈 20040802000167) — 표를
    다음 헤딩/주석마커/구간 끝까지 무조건 다 모으면 안 된다. 검증된 3개사(호텔
    신라 등)는 표 여러 개가 **'계속'(P 텍스트)+PGBRK 명시 마커로 이어진 같은
    기간의 연속 페이지**였지만, 이 문서는 그런 마커가 **전혀 없이** 서로 다른
    기간(제18기1분기/제17기/제16기)의 **완결된** BS 가 바로 이어 나온다(실측:
    `iter_section_span_depth_aware` 출력에 '계속'/PGBRK 없이 표3개가 연달아
    나옴). 이어붙이면 다른 기간의 값이 섞인다.

    구분 마커('계속' 유무)를 직접 찾는 대신 **더 단순하고 안전한 불변식**을
    쓴다 — "부채와자본총계"는 BS 의 정의상 항상 통계의 진짜 끝이다. 그래서 표를
    하나씩 추가할 때마다 **그 자리에서** 지금까지 모은 라벨이 이미 총계로
    끝나는지 확인하고, 끝나면 **즉시 확정하고 더 이상 모으지 않는다** — 계속
    페이지든(누적된 라벨이 마지막 페이지에서만 총계로 끝남) 별개 기간이든
    (표 하나만으로 이미 총계로 끝남) 둘 다 이 규칙 하나로 안전하게 처리된다.

    반환: {section_code: (raw_value_unscaled, unit_hint_table)} — `unit_hint_table`은
    로컬 단위선언 탐색용 대표 표(모은 표 중 `declared_unit()`이 있는 첫 표, 없으면
    None) — 호출측이 기존 `declared_unit`/`nearest_section_default_unit`/
    `document_default_unit` 3단 폴백(R67, `_pick_fallback_unit`)을 그대로 적용한다
    (새 단위판정 로직을 만들지 않는다, 설계문서 §3-4).
    """
    out: dict[str, tuple[int, "etree._Element | None"]] = {}

    for sec_title, basis in ((SEC_SEP_FS, "separate"), (SEC_CONSOL_FS, "consolidated")):
        if basis == "consolidated" and fin_type == "B":
            continue
        norm_title = normalize_dart_section_title(sec_title)
        elements = iter_section_span_depth_aware(root, norm_title)
        in_bs = False
        accum: list = []

        def _reset():
            nonlocal in_bs, accum
            in_bs = False
            accum = []

        def _try_finalize(basis=basis):
            """지금까지 모은 것으로 확정을 시도한다. 성공하면(총계까지 다 모임)
            결과를 저장하고 True — 호출측이 더 이상 표를 안 모으게 한다."""
            nonlocal accum
            section_code = SECTION_CODE_OF[(basis, "BS")]
            if section_code in out:
                return True  # 이미 확정됨(이 섹션 재진입 등) — 더 볼 필요 없음
            value = _extract_squished_bs_total(accum)
            if value is None:
                return False
            # 로컬 선언 있는 표를 우선하되, 없으면 마지막(실데이터) 표라도 대표로
            # 남긴다 — 호출측 `nearest_section_default_unit` 폴백이 섹션 위치를
            # 찾으려면 표 객체 자체(트리 안 위치)가 필요하다.
            unit_hint = next((t for t in accum if declared_unit(t) is not None), accum[-1])
            out[section_code] = (value, unit_hint)
            return True

        for tag, el in elements:
            text_ = " ".join("".join(el.itertext()).split())
            if is_legacy_note_marker(text_):
                _reset()
                continue
            head = classify_pre2015_statement_heading(text_, include_sce=True)
            if head is not None:
                _reset()
                _, stmt = head
                in_bs = (stmt == "BS")
                continue
            if in_bs and tag == "TABLE":
                if _table_has_data_rows(el):
                    # 방어적 안전장치 — 이 구간에 **정상 다행 데이터표**가 섞여
                    # 있으면 통짜-셀 케이스가 아니라고 보고 조용히 포기한다(호출측이
                    # 이미 `code not in groups`로 걸러주지만, 이 함수 자신도 독립적으로
                    # 안전해야 한다).
                    _reset()
                    continue
                accum.append(el)
                if _try_finalize():
                    _reset()  # 확정 완료 — 이 뒤에 또 나오는 표는 다른 기간이다

    return out
