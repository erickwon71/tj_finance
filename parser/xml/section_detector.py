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
    ("BS_C", ["연결", "대차대조표"]),       # K-GAAP(pre-IFRS) 연결 BS
    ("IS_C", ["연결", "손익계산서"]),      # 포괄손익계산서 / 손익계산서 모두 포함
    ("CF_C", ["연결", "현금흐름표"]),
    ("NOTE_C", ["연결", "주석"]),
    # 별도 (연결 없이 단독)
    ("BS_S", ["재무상태표"]),
    ("BS_S", ["대차대조표"]),               # K-GAAP(pre-IFRS) 별도 BS
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

# <P> 헤더 섹션탐지(금융업/구형 레거시)용 길이 가드.
# 실제 재무제표 제목은 짧고 단독("연결재무상태표"=7자, "연결포괄손익계산서"=9자)인 반면,
# 주석/정관 문장("재무상태표에 표시되는 금융자산…", "제64기는 종전기준서인 K-IFRS…")은 길다.
# 이 가드로 주석 오매칭을 차단한다.
_MAX_HEADER_LEN = 30

# 주석 항목 번호 접두("33.", "(1)", "1)") — 표제가 아니라 주석/세부항목 번호.
_NOTE_NUM_PREFIX_RE = re.compile(r"^\(?\d+[.)]")

# 소·중형사 레이아웃: 표제가 번호접두+기간 인라인("1)재무상태표(대차대조표)제33기2022년…").
# 선두 enumerator·연결/별도 수식어 제거용 + 기간마커(=진짜 재무제표는 기간 표기, 주석은 없음).
_LEAD_QUALIFIER_RE = re.compile(r"^(연결|별도|개별)")
_PERIOD_MARKER_RE = re.compile(r"제\d+\s*기|\d{4}\s*년|부터")

# <P> 섹션 경계 추가 표제 — 추출 대상은 아니나(BS/IS/CF 만 추출) IS·CF 표 수집의 경계로
# 인식해야 하는 재무제표. 특히 자본변동표(SCE)는 포괄손익계산서 바로 뒤 <P> 로 와서,
# 경계로 인식 안 하면 IS_C 가 SCE 의 "연결당기순이익/반기순이익" 행을 흡수해 순이익이 오염됨.
_BOUNDARY_EXTRA: list[list[str]] = [["자본변동표"]]


# ══════════════════════════════════════════════════════════════════════════
# DART 문서 섹션(<SECTION-2>) 식별 — 본문/주석/요약을 **구조로** 가른다
# ══════════════════════════════════════════════════════════════════════════
# 배경: 기존 탐지는 문서의 **모든 TABLE** 을 후보로 놓고 표제 정규식으로 주석·요약을 걸러내려
# 했다. 그러다 뚫려서 주석표(백만원 단위)가 본문으로 들어가 std_v2 에 이익잉여금 8.5경원 같은
# 값이 실렸다(DB손해보험 2023 H1). DART 정기보고서는 이미 아래처럼 구획돼 있다:
#
#   <SECTION-2><TITLE>III. 재무에 관한 사항</TITLE>
#   <SECTION-2><TITLE>1. 요약재무정보</TITLE>        → 본문 아님(적재 제외)
#   <SECTION-2><TITLE>2. 연결재무제표</TITLE>        → 본문(연결)
#   <SECTION-2><TITLE>3. 연결재무제표 주석</TITLE>   → 주석(연결)
#   <SECTION-2><TITLE>4. 재무제표</TITLE>            → 본문(별도)
#   <SECTION-2><TITLE>5. 재무제표 주석</TITLE>       → 주석(별도)
#
# 실측(무작위 400건, fy≥2015): 5개 섹션 전부 보유 399/400(99.8%).
# 본문 섹션 내부 TABLE 6,229 vs 주석 섹션 내부 TABLE 149,831 → **전체 표의 96%가 주석**.
# 섹션 경계로 자르면 그 96% 가 본문 후보에 **진입 자체 불가**가 된다.
#
# ★ 왜 '정확일치'인가(실측 근거, 무작위 600건 TITLE 전수):
#   표준 5종이 압도적인 한편, 부분일치라면 본문으로 오인했을 함정이 실재한다 —
#     '합병전ㆍ후의재무제표'(81) · '연결재무제표에대한감사인의감사의견등'(24) ·
#     '재무제표이용상의유의점'(81) · '연결재무제표에관한사항'(3)
#   → 정확일치가 이들을 자동 배제한다. 부분/퍼지 매칭은 금지(추측 금지 원칙).

SEC_SUMMARY      = "요약재무정보"
SEC_CONSOL_FS    = "연결재무제표"
SEC_CONSOL_NOTE  = "연결재무제표주석"
SEC_SEP_FS       = "재무제표"
SEC_SEP_NOTE     = "재무제표주석"
# 'II. 사업의 내용' — 재무제표가 아니라 **사업 서술** 구획. [연구개발비용]·생산능력 표가 산다.
# 실측(2016+ 무작위 120건): 정확일치 TITLE 보유 **120/120(100%)**, '사업'+'내용' 을 포함하는
# 다른 TITLE 은 **0건**(부분일치 함정 없음). rd_note 가 이 경계를 써서 동명 주석표를 배제한다.
SEC_BIZ_CONTENT  = "사업의내용"

# 적재 대상 4종(요약은 의도적으로 제외 — 본문으로 쓰지 않는다)
DART_BODY_SECTIONS = (SEC_CONSOL_FS, SEC_SEP_FS)
DART_NOTE_SECTIONS = (SEC_CONSOL_NOTE, SEC_SEP_NOTE)

# 정규화된 TITLE → 섹션 종류. **정확일치만** 인정한다.
_DART_SECTION_EXACT: dict[str, str] = {
    SEC_SUMMARY:     SEC_SUMMARY,
    SEC_CONSOL_FS:   SEC_CONSOL_FS,
    SEC_CONSOL_NOTE: SEC_CONSOL_NOTE,
    SEC_SEP_FS:      SEC_SEP_FS,
    SEC_SEP_NOTE:    SEC_SEP_NOTE,
    SEC_BIZ_CONTENT: SEC_BIZ_CONTENT,
}

# 선두 번호 접두("1.", "Ⅲ.", "2 )") 제거용. 번호는 문서마다 달라 분류 키에서 뺀다.
_SEC_NUM_PREFIX_RE = re.compile(r"^[\dⅠ-Ⅻ IVXivx]+\s*[.．)]\s*")


def normalize_dart_section_title(title: str) -> str:
    """SECTION-2 TITLE → 분류 키(선두 번호 제거 + 공백 전제거).

    '3. 연결재무제표 주석' → '연결재무제표주석'. 공백 제거는 '재무제표 주석'/'재무제표주석'
    표기 흔들림을 흡수하기 위한 것이며, **의미를 바꾸는 변형(부분일치)은 하지 않는다.**
    """
    t = re.sub(r"\s+", " ", title).strip()
    t = _SEC_NUM_PREFIX_RE.sub("", t)
    return re.sub(r"\s+", "", t)


def classify_dart_section(title: str) -> Optional[str]:
    """SECTION-2 TITLE → 섹션 종류(정확일치) 또는 None(대상 아님)."""
    return _DART_SECTION_EXACT.get(normalize_dart_section_title(title))


def detect_dart_sections(root: etree._Element) -> dict[str, etree._Element]:
    """DART <SECTION-2> 구조로 재무 섹션 컨테이너를 식별한다.

    반환: {섹션종류: SECTION-2 요소}. **표를 꺼낼 때는 반드시 `section_own_tables()` 를 쓸 것**
    (`.//TABLE` 직접 호출 금지 — 아래 중첩 경고 참조).

    같은 종류가 여러 번 나오면 **첫 번째만** 취한다(중복 시 추측하지 않기 위함).
    구조가 없는 서식(구형·감사보고서 등)에서는 빈 dict 를 반환한다 → 호출측이 보류 처리.
    """
    found: dict[str, etree._Element] = {}
    for sec in root.iter("SECTION-2"):
        title_elem = sec.find("TITLE")
        if title_elem is None:
            continue
        kind = classify_dart_section("".join(title_elem.itertext()))
        if kind is not None and kind not in found:
            found[kind] = sec
    return found


def table_direct_rows(table: etree._Element) -> list[etree._Element]:
    """표의 **직접** 데이터행(TR)만. 중첩 TABLE 안의 행은 제외한다.

    ★ 반드시 이걸 써야 하는 이유(실측): **DART 원문 XML 이 깨져 있는 경우가 흔하다**
    (</TABLE> 누락 → lxml 이 이후 문서 전체를 그 표 **안쪽에** 중첩시킴).

      - DB손해보험 20230927000457: 연결 BS 표의 `.//TR` = **5,218행**, 중첩 TABLE **775개**.
        하지만 **직접 행 51개**가 진짜 연결재무상태표다('1. 현금및예치금 985,598,436,033').
      - 메가스터디 20190401004405: 진짜 BS = 직접 54행 / wrapper 표 = 직접 1행·중첩 472개.

    ⟹ '중첩 TABLE 이 있으면 wrapper 이니 버린다'는 규칙은 **DB손해보험의 진짜 데이터를 버린다.**
    반대로 `.//TR`(하위 전체)을 쓰면 문서 전체를 재무제표로 읽는다. **직접 행만**이 정답이다.
    """
    out: list[etree._Element] = []
    for tr in table.iter("TR"):
        anc = tr.getparent()
        while anc is not None:
            tag = anc.tag if isinstance(anc.tag, str) else ""
            if tag == "TABLE":
                break
            anc = anc.getparent()
        if anc is table:
            out.append(tr)
    return out


def assign_tables_to_dart_sections(
    root: etree._Element,
) -> dict[str, list[etree._Element]]:
    """각 TABLE 을 **문서 순서상 직전 섹션 표제**에 귀속시켜 {섹션종류: [TABLE,…]} 반환.

    ★ 왜 '포함관계'가 아니라 '문서 순서'인가 (실측으로 확정):
    DART 문서의 SECTION-2 는 형제가 아니라 **계단식 중첩**인 경우가 많다 —
    DB손해보험(20230927000457) 실측 계층:

        SECTION-1 'III. 재무에 관한 사항'          tables=781
          SECTION-2 '1. 요약재무정보'              tables=4
            SECTION-2 '2. 연결재무제표'            tables=777   ← 요약 안에 중첩
              SECTION-2 '3. 연결재무제표 주석'     tables=769   ← 본문 안에 중첩
                SECTION-2 '4. 재무제표'            tables=337
                  SECTION-2 '5. 재무제표 주석'     tables=329

    즉 각 섹션이 **다음 섹션을 통째로 품는다**. 그래서 `.//TABLE`(하위 전체)은 물론이고
    "하위 SECTION-2 제외" 방식으로도 경계가 잡히지 않는다(중첩 깊이·무제 섹션이 문서마다 다름).
    반면 **문서 순서**(= 사람이 읽는 순서)는 어떤 중첩 구조에서도 일관된다.

    규칙: TITLE 을 가진 SECTION-* 을 만나면 현재 섹션을 그 분류로 갱신한다. 분류 불가 표제
    ('6. 기타 재무에 관한 사항' 등)를 만나면 현재 섹션을 **해제**한다(그 뒤 표를 앞 섹션에
    잘못 귀속시키지 않기 위함 — 추측 금지).
    """
    result: dict[str, list[etree._Element]] = {}
    current: Optional[str] = None

    for el in root.iter():
        tag = el.tag.upper() if isinstance(el.tag, str) else ""
        if tag.startswith("SECTION"):
            title_elem = el.find("TITLE")
            if title_elem is not None:
                # 분류되면 그 섹션 시작, 분류 불가면 해제(= 대상 아님 구간)
                current = classify_dart_section("".join(title_elem.itertext()))
        elif tag == "TABLE" and current is not None:
            result.setdefault(current, []).append(el)

    return result


# 개별 주석의 번호 제목("27. 현금흐름표 (연결)", "29. 부문별 보고", "10. 유형자산") —
# 주석 섹션 안의 sub-heading. 이 번호 제목이 주석 정체성(로케이터)이다.
_NUMBERED_NOTE_TITLE = re.compile(r"^\s*\d+\s*[.．]\s*\S")

# ── <P> 주석 헤딩 ────────────────────────────────────────────────────────────
# 전체 기업의 ~57.5% 는 개별 주석 제목이 <TITLE> 이 아니라 평문 <P> 로만 존재한다
# (DART XML 에는 주석 단위 구조 표시가 없다 — AASSOCNOTE 는 목차 수준 전용).
# 이 경우 <TITLE> 만 추적하면 모든 주석 행이 상위 '3. 연결재무제표 주석' 하나로
# 붕괴한다. (2026-07-27 실측: 붕괴 57.5%, 정상 23%)
#
# <P> 헤딩은 두 형태로 나타난다:
#   ① 단독      : '2. 연결재무제표 작성기준 및 중요한 회계정책'
#   ② 본문 접합 : '1. 회사의 개요 (1) 지배기업의 개요 주식회사 …' (len 316)
# ② 때문에 <TITLE> 처럼 "전체가 짧을 것"을 요구할 수 없고 **접두 제목만** 뽑아야 한다.
# 제목은 하위항목 표지 '(1)' 이나 본문 상투어에서 끝난다고 본다.
_NOTE_HEADING_PREFIX = re.compile(
    r"^\s*(\d{1,2})\s*[.．]\s*(?!\d)"          # 번호. — '1.1.5' 같은 다단 번호는 제외
    r"(.{2,40}?)\s*"                           # 제목(접두)
    r"(?=[(（]\s*[0-9①-⑮가-힣]\s*[)）]|보고기간|당기말|전기말|당기와|주식회사|$)"
)


# 폴백: 제목이 종결 표지 없이 본문과 붙은 경우('17. 리스 리스와 관련하여 재무상태표에…').
# 이때 제목 경계는 확정할 수 없지만 **주석 번호**는 확실하며, 계층3 의 표-주석 귀속에는
# 번호가 결정적이다(제목은 이후 topic 정규화 단계에서 다룬다). 그래서 번호를 살리고
# 제목은 앞쪽 일부만 잠정 채택한다.
_NOTE_HEADING_LOOSE = re.compile(r"^\s*(\d{1,2})\s*[.．]\s*(?!\d)([가-힣][^\n]{1,60})")
_TITLE_TOKEN_CAP = 6          # 잠정 제목으로 취할 최대 토큰 수


def _extract_note_heading(text: str) -> Optional[tuple[int, str]]:
    """평문에서 (주석번호, 제목) 접두를 뽑는다. 주석 헤딩이 아니면 None."""
    m = _NOTE_HEADING_PREFIX.match(text)
    if m:
        title = m.group(2).strip(" .·-—")
        # 숫자 덩어리가 섞이면 표 셀에서 흘러든 텍스트일 확률이 높다.
        if title and not re.search(r"\d{3}", title):
            return int(m.group(1)), title

    loose = _NOTE_HEADING_LOOSE.match(text)
    if not loose:
        return None
    body = loose.group(2).strip()
    if re.search(r"\d{3}", body.split()[0] if body.split() else ""):
        return None
    title = " ".join(body.split()[:_TITLE_TOKEN_CAP])[:40].strip(" .·-—")
    return (int(loose.group(1)), title) if title else None


def assign_note_tables_with_titles(
    root: etree._Element,
) -> dict[str, list[tuple[etree._Element, Optional[str]]]]:
    """`assign_tables_to_dart_sections` 와 동일한 문서순서 pass 이되, 주석 섹션 안에서는
    **관장 번호 제목(running header)** 도 함께 추적해 각 표를 (TABLE, 번호제목) 으로 태깅한다.

    반환: {주석섹션종류: [(TABLE, note_title), …]}. note_title = 그 표 직전(문서순서)의 가장
    최근 '번호. 제목'(예 '27. 현금흐름표 (연결)'). 없으면 None. 본문 섹션은 대상 아님(주석만).

    ★ 왜 running header 인가: 주석 표의 직전 형제 텍스트는 설명문장('보고부문 사이의 거래에…')
    이라 로케이터로 부정확했다. 개별 주석의 번호 제목이 진짜 정체성이며, 계층3가 이걸로 어느
    주석(현금흐름표/부문/유형자산)인지 판단해 D&A 등을 안전하게 집는다. (2026-07-25)
    """
    result: dict[str, list[tuple[etree._Element, Optional[str]]]] = {}
    current: Optional[str] = None
    note_title: Optional[str] = None
    note_no: int = 0                             # 관장 주석 번호(단조 증가 가드용)

    for el in root.iter():
        tag = el.tag.upper() if isinstance(el.tag, str) else ""
        if tag.startswith("SECTION"):
            title_elem = el.find("TITLE")
            if title_elem is not None:
                new_current = classify_dart_section("".join(title_elem.itertext()))
                if new_current != current:
                    current = new_current
                    note_title = None            # 섹션 경계 → 번호제목 초기화
                    note_no = 0                  # 연결/별도 주석은 각각 1번부터 재시작
        elif tag == "TITLE" and current in DART_NOTE_SECTIONS:
            txt = " ".join("".join(el.itertext()).split())
            if _NUMBERED_NOTE_TITLE.match(txt) and len(txt) < 60:
                note_title = txt[:255]           # 개별 주석 번호 제목 갱신
                head = _extract_note_heading(txt)
                if head is not None:
                    note_no = head[0]            # <P> 가드와 번호 기준을 공유
        elif tag == "P" and current in DART_NOTE_SECTIONS:
            # <TITLE> 우선. <P> 는 <TITLE> 이 주석 제목을 주지 못한 보고서를 메운다.
            txt = " ".join("".join(el.itertext()).split())
            head = _extract_note_heading(txt)
            # 단조 증가 가드: 주석 번호는 순차적이므로 현재 번호보다 큰 것만 채택한다.
            # 주석 본문 안의 '1. …' 같은 열거 항목이 헤딩으로 오인되는 것을 막는 핵심 장치.
            if head is not None and head[0] > note_no:
                note_no, name = head
                note_title = f"{note_no}. {name}"[:255]
        elif tag == "TABLE" and current in DART_NOTE_SECTIONS:
            result.setdefault(current, []).append((el, note_title))

    return result


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

    # ── <P> 헤더 기반 탐지 (금융업/구형 레거시, 핵심 섹션 누락 시) ──────
    # 보험·증권·지주 및 SPAC 등 레거시 ACODE 보고서는 재무제표 표제가 <TITLE> 이 아니라
    # <P>연결재무상태표</P> 처럼 데이터 TABLE 과 같은 SECTION 의 직계 형제 <P> 로 존재한다.
    # TITLE 스캔은 컨테이너("2. 연결재무제표")만 잡으므로 표제 <P> 를 별도 탐지한다.
    # (TABLE 폴백보다 먼저 실행 → 주석표가 BS_S 등을 선점하는 오매칭을 방지.)
    core_missing = [
        code for code, elem in sections.items()
        if elem is None and not code.startswith("NOTE")
    ]
    if core_missing:
        _detect_sections_from_paragraphs(root, sections)

    # ── TABLE 기반 fallback (핵심 섹션이 없을 때) ─────────────────────
    core_missing = [
        code for code, elem in sections.items()
        if elem is None and not code.startswith("NOTE")
    ]
    if core_missing:
        _detect_sections_from_tables(root, sections)

    return sections


def _detect_sections_from_paragraphs(
    root: etree._Element,
    sections: dict[str, Optional[etree._Element]],
) -> None:
    """<P> 표제 헤더로 재무제표 섹션을 탐지(in-place). 핵심(BS/IS/CF)만 대상.

    레이아웃:
        <SECTION-2>
          <TITLE>2. 연결재무제표</TITLE>      ← 컨테이너(키워드 미보유)
          <P>연결재무상태표</P>                ← 표제 헤더(짧은 단독 <P>)
          <TABLE>...기간 헤더...</TABLE>
          <TABLE>...BS 데이터...</TABLE>
          <P>연결포괄손익계산서</P>            ← 다음 표제
          ...
    → sections[code] = 표제 <P> 요소. find_section_tables 가 다음 표제 <P> 전까지
      형제 TABLE 을 수집한다.
    """
    for p in root.iter("P"):
        ptext = _get_text(p)
        if not ptext:
            continue
        for code, keywords in _SECTION_PATTERNS:
            if code.startswith("NOTE"):
                continue  # 주석은 <P> 헤더 탐지 대상 아님(BS/IS/CF 만)
            if sections[code] is not None:
                continue
            exclude_kws = _EXCLUDE_PATTERNS.get(code, [])
            if _is_statement_header(ptext, keywords, exclude_kws):
                sections[code] = p
                break  # 한 <P> 는 한 섹션만


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
        if tag == "P":
            # 다음 재무제표 표제 <P>(=새 섹션) 를 만나면 중단. 그 외 <P>(단위·각주문장
            # 등)는 건너뛰고 계속 수집. (<P> 마커 섹션의 형제 경계 인식)
            ptxt = _get_text(elem)
            if ptxt and (
                any(_is_statement_header(ptxt, kws, _EXCLUDE_PATTERNS.get(c, []))
                    for c, kws in _SECTION_PATTERNS if not c.startswith("NOTE"))
                or any(_is_statement_header(ptxt, kws, []) for kws in _BOUNDARY_EXTRA)
            ):
                break
            continue
        if tag == "TABLE":
            tables.append(elem)
            if len(tables) >= max_tables:
                break
        elif tag == "TABLE-GROUP" and not tables:
            # K-GAAP(pre-IFRS) 중첩: 섹션헤더 TITLE 다음 데이터가 직접 TABLE 이 아니라
            # TABLE-GROUP(내부에 실제 제목 TITLE + 데이터 TABLE) 안에 있음. 직접 TABLE 이
            # 하나도 없을 때만 그 안의 TABLE 을 수집(IFRS 본문은 직접 TABLE 이라 무영향).
            for t in elem.findall(".//TABLE"):
                tables.append(t)
                if len(tables) >= max_tables:
                    break
            if tables:
                break

    return tables


def detect_unit_from_section(section_elem: etree._Element) -> int:
    """
    섹션 내 텍스트에서 "(단위 : 천원)" 등 단위 표기를 찾아 multiplier 반환.

    TABLE에서 직접 찾거나, 섹션 내 P 태그에서 찾는다.
    """
    from parser.common.amount_normalizer import detect_unit_declaration

    parent = section_elem.getparent()
    if parent is None:
        return 1

    siblings = list(parent)
    try:
        start_idx = siblings.index(section_elem)
    except ValueError:
        return 1

    # 섹션 시작부터 다음 TITLE 전까지 탐색.
    # 가장 먼저 나오는 '명시적 단위 선언'(원 포함)을 채택한다.
    # (이전: multiplier>1만 채택 → '단위: 원' 표를 건너뛰고 뒤쪽 천원을 잘못 적용하는 버그)
    for elem in siblings[start_idx:start_idx + 20]:
        tag = elem.tag.upper() if isinstance(elem.tag, str) else ""
        if tag == "TITLE" and elem is not section_elem:
            break
        decl = detect_unit_declaration(_get_text(elem))
        if decl is not None:
            return decl

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


def _is_statement_header(text: str, keywords: list[str], exclude_kws: list[str]) -> bool:
    """<P>/제목 텍스트가 **재무제표 표제 그 자체**인지(주석 문장 아님) 판정.

    가드:
      1) 길이(공백 제거 ≤ _MAX_HEADER_LEN) — 표제는 짧은 단독 문구, 주석/정관은 긴 문장.
      2) 주석/요약 마커 배제 — "요약"·"부문"(부문별/요약 재무정보 주석),
         번호 접두("33.", "(1)", "1)" = 주석 항목 번호)로 시작하면 표제 아님.
      3) **표제명으로 끝나야 함**(공백 제거 후 keywords[-1] 로 endswith) — 진짜 표제는
         "…재무상태표"로 끝나지만, 주석 문장("재무상태표에 표시되는 금융자산…")은 표제명
         뒤로 문장이 이어진다. 이 한 줄이 짧은 주석 문장까지 정확히 걸러낸다.
      4) _matches(키워드 포함 + 제외어).
    실제 표제("연결재무상태표","재무상태표","포괄손익계산서","현금흐름표")는 통과하고,
    주석표("(1)부문별 요약 재무상태표","33.현금흐름표","재무상태표에 표시되는…")는 걸러진다.
    """
    no_space = text.replace(' ', '')
    # 공통: 키워드 포함+제외어, 주석/요약 마커 배제.
    if not _matches(text, keywords, exclude_kws):
        return False
    if any(marker in no_space for marker in ("요약", "부문")):
        return False
    name = keywords[-1] if keywords else ""
    # (A) 깨끗한 단독 표제: 짧고(≤_MAX), 번호접두 없고, 표제명으로 끝남.
    if (len(no_space) <= _MAX_HEADER_LEN
            and not _NOTE_NUM_PREFIX_RE.match(no_space)
            and (not name or no_space.endswith(name))):
        return True
    # (B) 번호접두+기간 인라인 표제(소·중형사): "1)재무상태표(대차대조표)제33기2022년…".
    #     선두 enumerator·연결/별도 수식어 제거 후 표제명으로 **시작** + 기간마커 보유 → 표제.
    #     주석 제목("21.현금흐름표 당사는 간접법으로…")은 기간마커가 없어 걸러진다.
    if name:
        body = _LEAD_QUALIFIER_RE.sub("", _NOTE_NUM_PREFIX_RE.sub("", no_space))
        if body.startswith(name) and _PERIOD_MARKER_RE.search(no_space):
            return True
    return False
