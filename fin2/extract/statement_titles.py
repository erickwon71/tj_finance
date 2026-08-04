"""
표제기반 본문 재무제표 표 식별 (Track B 추출기 + Gate B 감사 reader 공용).

DART 본문은 `<TABLE-GROUP>[표제 TABLE("(연결) 재무상태표 제N기..."), 데이터 TABLE]` 또는
`<P>연결재무상태표</P> + 데이터 TABLE` 구조다. 데이터 TABLE 의 **직전 형제 텍스트(표제)** 에
statement 명 + 기간마커가 있고 요약/주석/분할·합병/자본변동이 아니면 그 TABLE 이 본문 face 다.

이 방식은 복잡문서(분할·기재정정)에서 `find_section_tables` 전방수집이 2차 조정표/요약을
오연결하던 문제(NAVER false-fail, 00259545 오추출, 00111838 0행)를 구조적으로 회피한다.

추출기(`fin2/extract/text.py`)와 감사 reader(`fin2/audit/face_audit.py`)가 이 단일 로직을
공유한다(패턴 드리프트 방지).
"""
from __future__ import annotations

import re

from parser.common.amount_normalizer import detect_unit_tokens
from parser.xml.section_detector import table_has_amount_rows

# 본문 재무제표 표제 패턴(제목 표 텍스트에서). 요약/주석/분할·합병/자본변동표 배제.
_STMT_TITLE = [
    (re.compile(r"재무상태표|대차대조표"), "BS"),
    (re.compile(r"포괄손익계산서|손익계산서"), "IS"),
    (re.compile(r"현금흐름표"), "CF"),
]
# 본문 표제임을 확정하는 기간 마커(요약표·일반표 배제용).
_PERIOD_MARK = re.compile(r"제\s*\d+\s*기|반기말|분기말|기말|현재|\d{4}\s*[.\-]\s*\d{1,2}\s*[.\-]\s*\d{1,2}")
# 본문 face 표가 아닌 표제(주석·요약·분할·자본변동·세부명세) 배제.
_TITLE_EXCLUDE = re.compile(r"분할|합병|주석|요약|자본변동|변동표|명세|부속")
_CONSOL_TITLE = re.compile(r"연결\s*(재무상태표|대차대조표|포괄손익계산서|손익계산서|현금흐름표)")
# ★ 본문 face 표제는 statement 명으로 **시작**한다(선택적 enumerator + 연결/별도/개별 접두 허용).
# 주석표 표제는 statement 명을 문장 속에 포함("…리스와 관련하여 연결재무상태표에 인식된 금액…",
# "22.1 …퇴직급여채무와 관련하여 재무상태표…")해 천원 단위 노트값이 face 를 오염(×1000)시켰다.
# 시작-앵커로 본문만 채택 → 노트 오염·×1000 제거.
# ★ 추가① statement 명 뒤에 한글이 바로 이어지면(="현금흐름표의 현금은…", "재무상태표 상 자산…")
#   표제 토큰이 아니라 **문장 속 명사구**(주석/보충표) → (?![가-힣]) 로 배제.
# ★ 추가② statement 명 **직후에 기간마커**(제N기·날짜·기말류·단위)가 와야 본문 face 로 확정한다.
#   노트 섹션 제목 "24. 현금흐름표(1) 현금흐름표의 현금은…보고기간종료일 현재…"은 명칭 뒤가 "(1)"이라
#   기간마커가 멀리(문장 속 '현재')에 있어 거부 → CF 보충표 천원값의 ×1000 오염 제거(동일기연류).
#   기간마커: 제N기(제32(당)기말 등 괄호주석 허용)·YYYY.·[당전]?기말/반기말/분기말·(단위.
_PERIOD_AFTER = (
    r"\s*(?:제\s*\d+\s*(?:\([^)]*\))?\s*기|\d{4}\s*[.\-]|"
    r"[당전]?\s*(?:반기말|분기말|기말)|[(（]?\s*단위)"
)
_FACE_TITLE_START = re.compile(
    r"^[\sⅠⅡⅢⅣⅤ\d.\)\(]{0,8}(?:연결|별도|개별)?\s*"
    r"(재무상태표|대차대조표|포괄손익계산서|손익계산서|현금흐름표)(?![가-힣])"
    + _PERIOD_AFTER
)
_STMT_NAME = {
    "재무상태표": "BS", "대차대조표": "BS",
    "포괄손익계산서": "IS", "손익계산서": "IS", "현금흐름표": "CF",
}

# (basis, statement) → fact_v2 섹션 코드.
SECTION_CODE_OF: dict[tuple[str, str], str] = {
    ("consolidated", "BS"): "BS_C", ("consolidated", "IS"): "IS_C", ("consolidated", "CF"): "CF_C",
    ("separate", "BS"): "BS_S", ("separate", "IS"): "IS_S", ("separate", "CF"): "CF_S",
    # 자본변동표 — 계층2 report_lines 전용(include_sce=True 로 명시 요청할 때만 생성).
    # fact_v2 경로는 classify_statement_in_body_section() 기본값이 SCE 를 배제하므로 영향 없음.
    ("consolidated", "SCE"): "SCE_C", ("separate", "SCE"): "SCE_S",
}


def title_text(tbl) -> str:
    """데이터 표의 표제 텍스트. DART 본문은 <TABLE-GROUP>[표제 TABLE, 데이터 TABLE] 구조라
    표제가 직전 형제 TABLE/<P> 에 들어있다 → 직전 형제(태그 무관) 텍스트를 표제로 본다."""
    prev = tbl.getprevious()
    if prev is None:
        return ""
    return " ".join("".join(prev.itertext()).split())[:200]


# 메타데이터 전용 형제(제목명 없음): 단위선언 '(단위 : 천원)' 또는 기간마커만 '제 19 기 : …'.
# 요약재무정보 서식은 [제목][기간][단위] 를 별도 <P> 로 분리해 데이터표의 직전 형제(들)가
# 메타줄이 된다(엠로/에스앤디 등 구형 KOSDAQ 요약).
_UNIT_ONLY_RE = re.compile(r"^\(?\s*단위\s*[:：]")


# 재무제표명 판정 — **공백을 제거하고** 본다. `_STMT_TITLE` 을 원문에 그대로 걸면
# DART 가 흔히 쓰는 자간 벌림('분 기 연 결 재 무 상 태 표')이 매칭되지 않는다.
# 자본변동표도 포함한다 — 이 술어의 쓰임은 "이게 표제인가"이지 "추출 대상인가"가 아니다.
_STMT_NAME_ANY = re.compile(
    r"재무상태표|대차대조표|포괄손익계산서|손익계산서|현금흐름표|자본변동표")


def has_statement_name(txt: str) -> bool:
    """텍스트에 재무제표명이 있는가(자간 공백 무시)."""
    return bool(txt) and bool(_STMT_NAME_ANY.search(re.sub(r"\s+", "", txt)))


def _is_metadata_only(txt: str) -> bool:
    """제목명이 없고 단위선언 또는 기간마커뿐인 형제인가(스킵 대상).

    ★2026-08-05 두 가지를 고쳤다. 둘 다 **거짓 부재**(표제를 못 읽어 표가 통째로 유실)였다:

    1) **자간 공백** — 종전에는 `_STMT_TITLE` 을 원문에 그대로 걸어 '분 기 연 결 재 무 상 태 표'
       가 재무제표명으로 인식되지 않았다. 그러면 기간마커('제 11 기')만 보고 **메타줄로 판정해
       표제를 건너뛰었다.** 정작 뒷단 분류기(`classify_statement_in_body_section`)는 공백을
       제거해 이것을 BS 로 맞힌다 — **앞단 필터가 뒷단보다 엄격해서 생긴 유실**이다.
       실측: 롯데렌탈 20151113000605(BS/IS/CF 전부) · 세화피앤씨 20171114002715(BS·SCE).
       자본변동표가 `_STMT_TITLE` 에 아예 없던 것도 같은 계열의 누락이다.

    2) **회사명이 앞에 붙은 단위줄** — '케이티비투자증권주식회사와 그 종속기업 (단위 : 원)'.
       `_UNIT_ONLY_RE` 는 문자열이 '(단위' 로 **시작**할 것을 요구해 이 줄을 메타로 보지 못했고,
       back-scan 이 여기서 멈춰 그 앞의 진짜 표제에 닿지 못했다.
       실측: 다올투자증권 20150817000725(연결 BS/IS 등).
       → 재무제표명이 **없으면서** 단위 선언을 품은 줄은 표제가 아니다 → 건너뛴다.
    """
    if not txt:
        return True   # 빈 형제(장식/공백)도 건너뛴다
    if has_statement_name(txt):
        return False  # 재무제표명이 있으면 그게 표제 — 스킵 안 함
    if _UNIT_ONLY_RE.match(txt) or _PERIOD_MARK.search(txt):
        return True
    return bool(detect_unit_tokens(txt))    # 회사명 등이 앞에 붙은 단위줄


def _is_data_boundary(el) -> bool:
    """이 형제가 **다른 재무제표의 몸통**인가(= back-scan 을 여기서 멈춰야 하는가).

    ★ `<TABLE>` 만 보면 안 된다. DART 는 같은 문서 안에서도 표를 두 가지로 담는다:
        · `<TABLE-GROUP>[제목표, 데이터표]` 로 묶는 경우
        · 제목표·데이터표를 `<SECTION-2>` 직계 형제로 나란히 두는 경우
      실측 일진홀딩스 20210318000893 은 **둘이 섞여 있다** — 현금흐름표는 TABLE-GROUP 안,
      이익잉여금처분계산서는 SECTION-2 직계. 그래서 처분계산서 제목표에서 뒤로 훑으면
      형제가 `<TABLE>` 이 아니라 `<TABLE-GROUP>` 이라 경계 검사를 그냥 통과해 버렸다.
    """
    tag = el.tag.upper() if isinstance(el.tag, str) else ""
    if tag == "TABLE":
        return table_has_amount_rows(el)
    return any(table_has_amount_rows(t) for t in el.iter("TABLE"))


def title_text_for_classify(tbl, max_skip: int = 3) -> str:
    """**분류 전용** 표제 — 직전 형제가 메타데이터(단위/기간)뿐이면 그 형제(들)를 건너뛰고 그
    앞의 표제를 본다(제목·기간·단위가 별도 <P> 로 분리된 요약재무정보 서식). 건너뛰는 대상은
    **재무제표명이 없는 단위/기간 줄뿐**이고, 데이터표(TABLE) 나 라벨 있는 텍스트를 만나면 멈춘다
    → 남의 표로 넘어가지 않는다(위험한 무제한 back-scan 아님, max_skip 로 상한).

    ★ title_text(단위 획득용, declared_unit 이 사용)는 단위줄을 그대로 반환해야 하므로 건드리지
      않는다 — 이 함수를 별도로 둔다(둘의 요구가 반대: declared_unit=단위줄 필요, 분류=제목 필요).

    ★★ 2026-08-04 — **데이터표 경계가 구현돼 있지 않았다**(위 설명이 약속하는 계약인데
       코드에 검사가 없었다). `_is_metadata_only` 는 텍스트만 보므로, 기간 헤더로 시작하는
       데이터표('제 39 기 제 38 기 … 영업활동으로 인한 현금흐름 …')를 '기간줄' 로 오인해
       **통째로 건너뛰고 그 앞 재무제표의 제목을 주워왔다.**

       실측 사고 — 일진홀딩스 2020FY(20210318000893) 섹션 '재무제표':
           [7] 현금흐름표 데이터표(54행)
           [8] 이익잉여금처분계산서 **제목표**(데이터 없음) ← 여기서 [7]을 건너뛰어 CF 로 분류
           [9] 이익잉여금처분계산서 데이터표(11행, 단위 백만원)
       [8]이 CF 로 분류되자 '제목표/데이터표 분리 서식' 분기가 [9]를 **CF 데이터로 연결**해,
       처분계산서 11행이 현금흐름표로 적재됐다(한솔제지 2022FY 등 동일 형태).

       데이터표는 **다른 재무제표의 몸통**이다. 그 너머의 제목은 남의 것이므로 여기서 멈춘다.
    """
    prev = tbl.getprevious()
    for _ in range(max_skip):
        if prev is None:
            return ""
        if _is_data_boundary(prev):
            return ""               # 데이터표 = 남의 재무제표 몸통 — 넘어가지 않는다
        txt = " ".join("".join(prev.itertext()).split())
        if not _is_metadata_only(txt):
            return txt[:200]        # 표제(또는 라벨 있는 비메타 형제) — 여기서 멈춘다
        prev = prev.getprevious()   # 메타줄(단위/기간/빈칸) 건너뛴다
    return ""


# ══════════════════════════════════════════════════════════════════════════
# 본문 섹션 **내부** 전용 분류기 (섹션 기반 추출용)
# ══════════════════════════════════════════════════════════════════════════
# `classify_statement_title`(아래)은 **문서 전체**를 훑던 시절의 함수라, 주석 문장 속 재무제표명
# 을 배제하려고 강한 가드(_FACE_TITLE_START: 재무제표명이 표제 시작 + 직후 기간마커)를 건다.
# 그 가드에 사각지대가 있었다 — 접두사로 `연결|별도|개별` 만 허용해 **`반기`/`분기` 를 누락**했고,
# 재무제표명 **내부 공백**('반 기 재 무 상 태 표')도 처리 못 했다. 그 결과 DB손해보험
# 20230927000457 은 6개 섹션이 전부 거부되어 레거시 폴백으로 떨어졌고, 폴백이 주석표를 집어
# **이익잉여금 8.5경원**이 적재됐다.
#
# 섹션 기반 추출에서는 이 가드가 **불필요**하다: DART `2.연결재무제표`/`4.재무제표` 섹션 안이면
# 이미 본문이 보장되므로, 주석을 배제할 이유가 없고 BS/IS/CF 구분만 하면 된다.
# 그래서 여기서는 **공백을 제거하고 재무제표명만** 본다(= 위 사각지대가 구조적으로 사라진다).
#
# ⚠ 단 **자본변동표(SCE)는 반드시 배제**한다. 본문 섹션에는 BS·IS·**SCE**·CF 가 함께 있고,
# SCE 의 '연결당기순이익' 행이 IS 로 흡수되면 순이익이 오염된다(과거 실사고).
# 실측 본문 섹션 구성(3S·DB손해보험 공통): [단위표 4행 + 데이터표] × 4 = BS·IS·SCE·CF.

_SCE_RE = re.compile(r"자본변동표")
# 재무제표명(공백 제거 후). 순서 중요 — '포괄손익계산서'가 '손익계산서'보다 먼저.
_BODY_STMT_ORDER: list[tuple[str, str]] = [
    ("재무상태표", "BS"),
    ("대차대조표", "BS"),
    ("포괄손익계산서", "IS"),
    ("손익계산서", "IS"),
    ("현금흐름표", "CF"),
]


def classify_statement_in_body_section(title: str, include_sce: bool = False) -> str | None:
    """본문 섹션 **내부** 표의 표제 → 'BS'|'IS'|'CF'(|'SCE') 또는 None(대상 아님).

    basis(연결/별도)는 **섹션이 결정**하므로 여기서 보지 않는다(표제 문구에 의존하지 않음).
    공백을 제거해 '반 기 재 무 상 태 표'·'반기재무상태표'·'연결 재무상태표' 를 모두 인식한다.
    단위표(빈 표제)는 None.

    include_sce: 기본 False 면 자본변동표를 **배제**한다(IS 오흡수 방지 — fact_v2 경로의
        기존 동작 그대로). True 면 'SCE' 를 반환한다 — **계층2 report_lines 전용 opt-in**.
        ★ 기본값을 바꾸지 말 것: fact_v2/std_v2(앱이 사용 중인 구 체인)가 이 함수를 공유하며,
          SCE 가 흘러들면 순이익이 SCE 의 '연결당기순이익' 행으로 오염된다(부국증권 회귀,
          커밋 1b13981 · fin2/tests/test_section_p_header.py 참고).
    """
    if not title:
        return None
    t = re.sub(r"\s+", "", title)
    if _SCE_RE.search(t):
        return "SCE" if include_sce else None
    for name, code in _BODY_STMT_ORDER:
        if name in t:
            return code
    return None


# ══════════════════════════════════════════════════════════════════════════
# 구형 레이아웃(`XI. 재무제표 등`) 전용 헤딩 분류기
# ══════════════════════════════════════════════════════════════════════════
# 2015+ 서식은 `2.연결재무제표`/`4.재무제표` SECTION-2 가 본문을 보장하고 basis 도 알려준다.
# 구형 서식(주로 12월 결산이 아닌 기업의 2014년 제출분)은 그런 구획이 없다 —
# **재무제표와 주석이 `XI. 재무제표 등` 한 섹션에 같이 산다**(실측 20141128001023:
# 연결 BS/IS/SCE/CF → `연결재무제표에 대한 주석` → 별도 4표 → `별도재무제표에 대한 주석`).
# 따라서 섹션은 아무것도 보장해주지 않고, **표제 앵커가 유일한 방어선**이다.
#
# ⚠ 여기서 느슨해지면 2023년 DB손해보험 사고가 재현된다(앵커 없는 폴백이 천원단위 주석표를
#   본문으로 집어 이익잉여금 8.5경원 적재). 그래서 아래 5가지를 모두 통과해야 헤딩으로 본다.
#
# ★ 결정적 함정 — 주석 헤딩도 재무제표명으로 시작한다: `<P>29. 현금흐름표`(실측
#   20141128001023 요소 161). 이것을 헤딩으로 채택하면 뒤따르는 주석표가 CF 본문이 된다.
#   가르는 근거는 **번호 접두**다 — 주석은 번호를 달고, 본문 재무제표 표제는 달지 않는다.
#   (추측이 아니라 서식의 구조 사실이다.)

# 번호 접두('29.', 'Ⅲ.', '1)') = 주석·세부항목 표지. 본문 재무제표 표제에는 없다.
_LEGACY_ENUM_PREFIX = re.compile(r"^[\dⅠ-Ⅻ]+\s*[.．)）]")
# 본문 face 가 아닌 것(첫 45자 기준). '주석' 은 여기서도 배제한다.
_LEGACY_EXCLUDE = re.compile(r"분할|합병|요약|명세|부속|주석|검토보고서|감사보고서")
# 재무제표명 앞에 붙을 수 있는 수식어. 공백 제거 후 판정하므로 '반 기 연 결' 도 흡수된다.
_LEGACY_HEAD = re.compile(
    r"^(?:연결|별도|개별|반기|분기|중간|당|전)*"
    r"(재무상태표|대차대조표|포괄손익계산서|손익계산서|현금흐름표|자본변동표)"
)
# 재무제표명 **직후**에 와야 하는 기간/단위 마커(공백 제거 기준). 이게 있어야 표제로 확정한다.
# 없으면(=명칭만 있는 단독 헤딩) 별도 규칙으로 받는다 — 아래 docstring 참조.
_LEGACY_PERIOD_AFTER = re.compile(
    r"^(?:제\d+(?:\([^)]*\))?기|\d{4}[.\-년]|[당전]?(?:반기말|분기말|기말)|"
    r"[(（]?단위|[당전]기(?=[\d(（]))"
)
_LEGACY_NAME_TO_CODE = {
    "재무상태표": "BS", "대차대조표": "BS",
    "포괄손익계산서": "IS", "손익계산서": "IS",
    "현금흐름표": "CF", "자본변동표": "SCE",
}
# 주석 구간 시작 마커 — 이 뒤의 표는 본문 후보에서 제외한다(실측 '연결재무제표에 대한 주석').
_LEGACY_NOTE_MARK = re.compile(r"재무제표에?대한주석|^주석$")


def is_legacy_note_marker(text: str) -> bool:
    """구형 레이아웃에서 **주석 구간의 시작**을 알리는 헤딩인가."""
    if not text:
        return False
    return bool(_LEGACY_NOTE_MARK.search(re.sub(r"\s+", "", text)[:40]))


def classify_legacy_statement_heading(
    text: str, include_sce: bool = False,
) -> tuple[str, str] | None:
    """구형 레이아웃의 재무제표 **표제 헤딩** → (basis, statement) 또는 None.

    basis 를 섹션이 알려주지 않으므로 **표제 문구에서** 읽는다('연결' 유무).

    통과 조건(전부 만족해야 함):
      1. 번호 접두가 없다 — `29. 현금흐름표` 같은 **주석 헤딩을 여기서 떨군다**.
      2. 배제어(분할·합병·요약·명세·부속·주석·감사보고서)가 없다.
      3. 공백 제거 후 **재무제표명으로 시작**한다(수식어 접두만 허용).
         문장 속 언급('…리스와 관련하여 연결재무상태표에 인식된…')이 여기서 떨어진다.
      4. 재무제표명 **직후**가 기간/단위 마커이거나(표제에 기간이 인라인된 서식),
         **명칭만 있는 단독 헤딩**이다(기간이 다음 형제 표에 있는 서식).
         → 4의 두 갈래가 실측된 두 하위서식이다:
            · A형 `연결 재무상태표 제 30 기 반기말 2014.09.30 현재 … (단위 : 원)` (73건)
            · B형 `<P>반 기 연 결 재 무 상 태 표` + 다음 표에 기간/단위 (14건)
         명칭 뒤에 **다른 한글이 이어지면 거부**한다 — '현금흐름표의 현금은 …' 같은
         주석 문장이 B형으로 위장하는 것을 막는다.

    include_sce: 계층2(report_lines) 전용 opt-in. 기본 False 는 자본변동표를 배제한다
        (fact_v2/std_v2 구 체인이 SCE 의 '연결당기순이익' 행을 IS 로 흡수하면 순이익 오염).
    """
    if not text:
        return None
    t = re.sub(r"\s+", "", text)
    if not t or _LEGACY_ENUM_PREFIX.match(t):
        return None
    if _LEGACY_EXCLUDE.search(t[:45]):
        return None
    m = _LEGACY_HEAD.match(t)
    if m is None:
        return None
    stmt = _LEGACY_NAME_TO_CODE[m.group(1)]
    if stmt == "SCE" and not include_sce:
        return None

    rest = t[m.end():].lstrip("：:·-—")
    if rest:
        # A형: 기간/단위 마커가 곧바로 따라와야 한다. 그 외 문자가 이어지면 표제가 아니다.
        if not _LEGACY_PERIOD_AFTER.match(rest):
            return None
    # rest == "" 이면 B형(명칭 단독 헤딩) — 조건 1~3 을 이미 통과했다.

    basis = "consolidated" if "연결" in t[:m.start(1)] else "separate"
    return (basis, stmt)


def classify_statement_title(title: str) -> tuple[str, str] | None:
    """표제 → (basis, statement) 또는 None(본문 재무제표 표 아님).

    basis ∈ {"consolidated","separate"}, statement ∈ {"BS","IS","CF"}.
    """
    if not title or not _PERIOD_MARK.search(title):
        return None
    head = title[:45]
    if _TITLE_EXCLUDE.search(head):
        return None
    # ★ statement 명이 표제 **시작**에 와야 본문 face(주석 문장 속 언급 배제).
    m = _FACE_TITLE_START.match(title)
    if m is None:
        return None
    stmt = _STMT_NAME[m.group(1)]
    basis = "consolidated" if _CONSOL_TITLE.search(title) else "separate"
    return (basis, stmt)
