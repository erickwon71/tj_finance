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
