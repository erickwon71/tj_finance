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
from parser.xml.section_detector import table_has_amount_rows, table_direct_rows

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
    # K-GAAP 전용(이익잉여금처분계산서/결손금처리계산서) — pre-2015 계층2 2차 패스 전용
    # (`fin2/extract/legacy_pre2015.py`). 현재 스키마(BS/IS/CF/SCE)에 대응 항목이 없어 신규
    # 코드로 가산(사용자 결정 Q1=포함, docs/plans/pre2015_layer2_backfill_todo_2026-08-10.md).
    # `report_lines.statement` 는 CHECK 제약 없는 varchar(10) — DB 마이그레이션 불요(실측 확인).
    ("consolidated", "APPR"): "APPR_C", ("separate", "APPR"): "APPR_S",
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


# ── T4(R28 후속) M3 — 표제/계정구분 중복 마커 스킵 (2026-08-16) ────────────
# docs/plans/eps_r28_followup_tracks_design_2026-08-16.md §5-6·§5-7-1(T4) 실측 근거.
# `doc_default` 로 떨어진 667그룹을 전수 재파싱해보니, 30그룹(288행)이 "표제표(단위
# 선언 보유)"와 "데이터표" 사이에 **내용 없는 중복 캡션**(같은 재무제표 이름만
# 되풀이하는 형제, 또는 은행업 계정구분 괄호라벨)이 끼어 `declaration_text()`/
# `inherited_declaration_text()`의 "재무제표명을 만나면 멈춘다"는 안전판(LVMC 회귀
# 방지용, `text.py` 참고)에 **의도치 않게 걸려** 진짜 선언에 닿지 못하는 패턴이었다.
# 원문 실측: 위아(00106623) '현 금 흐 름 표' 단독 캡션 · 기업은행(00149646) 대차대조표
# 앞 '(은행계정)' · 다수사 자본변동표 앞 '연 결 자 본 변 동 표'/'(3) 연결자본변동표
# (연결잉여금계산서)' · APPR 다수사 '이익잉여금처분계산서'/'결손금처리계산서'.
# **다른 재무제표로 건너간 게 아니다** — 이름이 정확히 같은 재무제표의 되풀이일
# 뿐이라 여기서 멈추면 안 된다. 단 기간·단위·계정명 등 **다른 정보가 조금이라도
# 섞이면** 아래 정규식이 매칭하지 않는다(끝까지 소비 못 함) — 그런 텍스트는 여전히
# "완전한 문장"으로 보고 멈춘다(LVMC 류 회귀 방지, 안전판은 그대로 유지).
_BARE_TITLE_NAME = re.compile(
    r"^(?:연결|별도|개별|반기|분기|중간|당|전)*"
    r"(?:재무상태표|대차대조표|포괄손익계산서|손익계산서|현금흐름표|자본변동표|"
    r"이익잉여금처분계산서|결손금처리계산서)"
    r"(?:[(（][^)）]{0,20}[)）])?$")
_BARE_TITLE_NUM_PREFIX = re.compile(r"^[(（]?\s*\d+\s*[)）.]?")
# 은행/보험업 특유 계정구분 라벨(기업은행 실측). [[std-v3-side-findings-trust-account-net-income-2026-08-09]]
# 가 다룬 "신탁계정 오귀속"과 같은 계열 구조 — 표시 자체는 별개 문제라 여기선 스킵 대상으로만 취급.
_BARE_ACCOUNT_SUBHEADER = frozenset({"은행계정", "신탁계정", "보험계정", "특별계정"})


def _is_bare_structural_marker(txt: str) -> bool:
    """단위 룩백 도중 만난 형제가 **내용 없는 표제/계정구분 중복 캡션**뿐인가.

    True 면 "재무제표명을 만나면 멈춘다"는 안전판의 **예외**로 취급해 건너뛴다 —
    재무제표명이 있어도 그게 전부(기간·단위 등 다른 정보가 없음)면 다른 재무제표로
    넘어간 게 아니라 **같은 재무제표 표제의 되풀이**이기 때문이다. TABLE 형제(제목+
    단위가 한 표에 묶인 경우)는 이 함수를 거치지 않는다 — LVMC 회귀는 그 경로였고
    (`text.py` `inherited_declaration_text` 주석 참고), 이 함수는 **텍스트 전용
    형제**에만 적용된다.
    """
    if not txt:
        return False
    compact = re.sub(r"\s+", "", txt).strip("()（）")
    if compact in _BARE_ACCOUNT_SUBHEADER:
        return True
    stripped = _BARE_TITLE_NUM_PREFIX.sub("", re.sub(r"\s+", "", txt))
    return bool(_BARE_TITLE_NAME.match(stripped))


# ★R142(2026-09-19) — SCE 등 재무제표 하나가 기간대역별 하위표 2개로 쪼개질 때, 뒤쪽
# 하위표의 표제가 재무제표명을 아예 반복하지 않는 서식("(2) 개별재무제표(2015년 및
# 2016년)")이 있다. `_is_bare_structural_marker`(위)는 재무제표명이 **있어야** 되풀이로
# 인정하는데, 이 표제는 재무제표명이 **없다** — "이 표는 앞 표와 같은 재무제표의 다른
# 기간대역"이라는 사실을 순번+기간만으로 전달할 뿐이다. 실측 삼성바이오로직스
# 20170331005571 별도 자본변동표: "다.자본변동표(1)별도재무제표(2013년및2014년)"
# [데이터19행] "(2)개별재무제표(2015년및2016년)" [데이터26행, 당기(2016) 데이터 포함] —
# 뒤쪽 표제가 `classify_statement_in_body_section`에서 어떤 statement 명과도 매치되지
# 않아 stmt=None → 당기 데이터 26행이 통째로 유실됨(layer2 review campaign fail #3).
# 호출측(`text.py::_detect_body_statement_tables`)이 "직전에 성공적으로 분류된
# statement"를 이 표지를 만난 표에 그대로 물려주는 폴백을 쓴다 — 이 함수는 그 폴백을
# 발동해도 되는 표지인지만 판정한다(무엇을 물려줄지는 모른다).
_SUBSTATEMENT_MARKER_RE = re.compile(
    r"^[(（]\d{1,2}[)）](?:개별|별도|연결)재무제표[(（][^)）]{0,20}[)）]$")


def is_substatement_marker(txt: str) -> bool:
    """표제가 "(N) 개별/별도/연결재무제표(기간)" 형태의 **기간대역 구분 표지**뿐인가
    (재무제표명 자체는 없음 — `_is_bare_structural_marker`와 반대의 결핍)."""
    if not txt:
        return False
    compact = re.sub(r"\s+", "", txt)
    return bool(_SUBSTATEMENT_MARKER_RE.match(compact))


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


def title_text_owned(tbl) -> str:
    """**분류용** 직전 형제 표제 — 그 형제가 남의 재무제표 몸통이면 빈 문자열.

    `title_text` 는 단위 획득(`declared_unit`)에도 쓰이므로 원문을 그대로 돌려줘야 한다.
    분류는 요구가 달라서, 여기서 경계를 한 겹 더 씌운다.

    ★ 왜 필요한가(2026-08-05 실측, 대원 20200330003731 등 264 filing):

        [TABLE-GROUP: 현금흐름표 제목표 + CF 데이터표 104행]
        [표] '주) 제46기는 종전 기준서인 K-IFRS …'   ← 각주표(데이터 없음)
        [표] '이 익 잉 여 금 처 분 계 산 서'          ← 처분계산서 제목표
        [표] '제 48 기 2019년 1월 1일부터 …'          ← 기간표
        [표] 처분계산서 데이터 10행

      각주표의 **직전 형제가 TABLE-GROUP** 이라 `title_text` 가 그 안의 '현금흐름표 …' 를
      표제로 읽어 **CF 로 분류**했다. 각주표엔 데이터가 없으니 '제목표/데이터표 분리 서식'
      분기가 발동해 앞으로 스캔했고, 그 결과 **처분계산서 데이터가 CF 로 붙었다.**
      (2026-08-04 에 `title_text_for_classify` 에만 경계를 넣어 이 경로가 남아 있었다.)
    """
    prev = tbl.getprevious()
    if prev is None or _is_data_boundary(prev):
        return ""
    return title_text(tbl)


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
# R4-2: title_text_owned/title_text_for_classify 가 **둘 다 실패**했을 때만 시도하는
# 최후 폴백 2종 — "제목+데이터 병합 표"(§3-A) · "제목 자체가 없는 표"(§3-B).
# 근거·census·안전성 검증: docs/plans/merged_title_data_table_r4-2_2026-08-05.md
# ══════════════════════════════════════════════════════════════════════════

_MERGED_TITLE_STMT = {
    "재무상태표": "BS", "대차대조표": "BS",
    "포괄손익계산서": "IS", "손익계산서": "IS",
    "현금흐름표": "CF", "자본변동표": "SCE",
}


def owned_merged_title(tbl, include_sce: bool = False) -> str | None:
    """표 자신의 **첫 행**이 재무제표명 하나뿐이면 그 statement 코드(BS/IS/CF/SCE).

    '재무제표_직접작성' 수기입력 서식(실측 특수건설 20151116001903·팬엔터테인먼트
    20181114002948)은 제목·기간·회사명·단위·헤더·데이터가 **한 TABLE 안에** 전부
    들어있어, 직전 형제를 보는 `title_text_owned`/`title_text_for_classify` 가 표제를
    못 찾는다. 이 함수는 표 자신의 내용을 직접 읽는다.

    ★★ 호출측 필수 조건 — 반드시 **`table_has_amount_rows(tbl)` 가 참인 표에만** 호출할
    것. 표제/데이터표가 **분리된** 정상 서식의 순수 제목표(예 '이 익 잉 여 금 처 분
    계 산 서' 한 줄뿐, 데이터는 다음 형제 표)도 첫 행이 재무제표명뿐이라 이 함수에
    걸린다 — 그런 제목표에 적용하면 그 표의 진짜 데이터가 (a) 이 함수의 forward-scan
    경로와 (b) 다음 idx 에서 도는 정상 title_text_owned 경로 **양쪽**에서 잡혀 같은
    데이터표가 그룹에 중복 append 된다(표본 대다수가 이 분리 서식이라 광범위하게
    번진다 — 반드시 데이터 보유 표로 좁힐 것).
    """
    trs = table_direct_rows(tbl)
    if not trs:
        return None
    first_txt = " ".join("".join(trs[0].itertext()).split())
    compact = re.sub(r"\s+", "", first_txt).strip("()（）")
    stmt = _MERGED_TITLE_STMT.get(compact)
    if stmt == "SCE" and not include_sce:
        return None
    return stmt


_HEADER_LABEL_RE = re.compile(r"^(과\s*목|계\s*정\s*과\s*목|계\s*정\s*명)$")
# 헤더 다음 행의 "첫 계정명"으로 오인하면 안 되는 기간/날짜 패턴. "과목" 헤더 셀이
# ROWSPAN=2(과목/기간 2단 헤더)를 쓰면 다음 TR 은 1열이 통째로 없어져 그 TR 의 첫 TD 가
# 이미 2열째 값(날짜)이 된다 — 실측 포시에스: 이 패턴 없이는 "2017-09-30" 을 계정명으로
# 오인해 BS 판정이 실패했다.
_PERIOD_ROW_RE = re.compile(
    r"^\d{4}[-.]\d{1,2}([-.]\d{1,2})?$|^제\s*\d+\s*\(?[당전]?\)?기|^\d+\s*기")


def _row_first_cell_text(tr) -> str:
    for td in tr:
        tag = td.tag.upper() if isinstance(td.tag, str) else ""
        if tag in ("TD", "TE", "TH"):
            return " ".join("".join(td.itertext()).split())
    return ""


def titleless_bs_start(tbl) -> bool:
    """표에 제목이 **전혀 없이** 곧바로 헤더행("과목" 등)으로 시작하고, 헤더 다음 첫
    계정명이 "자산"이면 BS 시작 신호로 인정한다(실측 포시에스 20171114002836 BS —
    "4.재무제표"/"2.연결재무제표" 섹션 아래 표 안 어디에도 "재무상태표" 문구가 없다).

    ★★ 호출측 필수 조건 — 반드시 **그 표가 속한 DART 섹션(`2.연결재무제표`/`4.재무제표`)
    안에서 첫 번째 금액표일 때만**(위치) 호출할 것. 이 함수 자체는 표 구조만 보고
    위치를 모른다 — 사용자 확정 census(2026-08-05, 398건 전수) 결과 위치 조건 없이
    "과목으로 바로 시작"만 걸면 주석/CF/IS 표까지 9건이 오검출됐고(미래아이앤지·메지온·
    올리패스·라파스·이엔플러스·한탑 등), 위치 조건을 더하니 포시에스 2표만 남았다.
    """
    trs = table_direct_rows(tbl)
    if not trs:
        return False
    if not _HEADER_LABEL_RE.match(re.sub(r"\s+", "", _row_first_cell_text(trs[0]))):
        return False
    for tr in trs[1:]:
        compact = re.sub(r"\s+", "", _row_first_cell_text(tr))
        if not compact or _PERIOD_ROW_RE.match(compact):
            continue
        return compact == "자산"
    return False


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
# 이익잉여금처분계산서/결손금처리계산서 표지(공백 제거 후). **4대 재무제표가 아니다.**
#
# ★ 왜 이름 매칭만으로는 부족한가(2026-08-05 실측) — 본문 섹션 안에 처분계산서가 함께 오는데,
#   그 표제가 다른 재무제표 이름을 달고 있는 경우가 실재한다:
#     · 비에이치 20190515000715 — 제출사가 제목을 잘못 씀:
#       '현금흐름표 제 21 기 : … **처분확정일**: - 제 20 기 : …'  (내용은 미처분이익잉여금)
#     · 삼성화재 20190515002191 — 분류에 쓰인 각주 문장이
#       '註) 당분기 **현금흐름표**는 … 소급재작성되지 아니하였습니다. **이익잉여금처분계산서**'
#   둘 다 '현금흐름표' 라는 낱말 때문에 CF 로 분류돼 처분계산서 데이터가 CF 에 붙었다.
#   그래서 이름보다 **먼저** 이 표지를 본다 — 처분/처리 확정·예정일은 처분계산서 고유 어휘다.
_APPROPRIATION_RE = re.compile(
    r"이익잉여금처분계산서|결손금처리계산서|이익잉여금처분|결손금처리"
    r"|처분확정일|처분예정일|처리확정일|처리예정일")
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

    ★2026-09-19(R141) — 재무제표명이 **둘 이상** 섞인 표제는 **마지막(=표에 가장 가까운)
    이름**을 채택한다(list 순서상 먼저 오는 이름이 아니라). DART 는 "[N번 재무제표 각주]
    [N+1번 재무제표 헤딩]"을 같은 형제 텍스트로 병합해두는 서식이 있다(예: "주) 당반기말
    연결재무상태표는...소급재작성되지 아니함 나. 연결손익계산서(포괄손익계산서)") — 이 표는
    "나. 연결손익계산서"가 지배하는 IS 데이터 표인데, 옛 로직은 `_BODY_STMT_ORDER` 리스트
    순서상 먼저 나오는 이름(BS)이 텍스트 어디에 있든 그것부터 찾아 무조건 BS로 오분류했다
    (텍스트 내 실제 위치 무관). 실측: KB금융 20180814002480 외 3건(2018 Q1/H1 + 기재정정
    2건, layer2 review campaign fail #5~#8) — 연결 손익계산서 표 전체가 BS 로 잘못 붙어
    IS 가 통째로 유실됐다. 이 원리는 브라우저 스크레이퍼(`bucketOfLine()`)가 이미
    "마지막으로 매치되는 헤딩 줄" 방식으로 검증해 적용 중인 것과 동일하다 — 여기서도
    같은 원칙(표에 물리적으로 가장 가까운 이름이 그 표의 진짜 표제)을 적용한다.
    """
    if not title:
        return None
    t = re.sub(r"\s+", "", title)
    if _APPROPRIATION_RE.search(t):
        return None                 # 이익잉여금처분계산서/결손금처리계산서 — 4대 재무제표 아님
    if _SCE_RE.search(t):
        return "SCE" if include_sce else None
    best_code: str | None = None
    best_pos = -1
    for name, code in _BODY_STMT_ORDER:
        pos = t.rfind(name)
        if pos > best_pos:
            best_pos = pos
            best_code = code
    return best_code


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
# ★R69(2026-09-05) — 위 숫자/로마숫자 접두와 의미가 다르다: 이 레이아웃에서 숫자 접두는
# 여전히 주석 항목번호(그대로 거부)지만, 한글 가나다 접두("가.대차대조표")는 "XI.부속명세서"
# 컨테이너의 재무제표 목록 전용 열거기호다(실측 근거: docs/plans/category_c_legacy_
# appendix_variant_design_2026-09-05.md §1). 한 글자만 벗기고(중첩 없음) 재판정 —
# 벗긴 뒤에도 재무제표명이 안 걸리면(예 "가.대손충당금설정내역") 그대로 거부되므로 새
# 오탐 경로가 생기지 않는다.
_LEGACY_KO_ENUM_PREFIX = re.compile(r"^[가나다라마바사아자차카타파하]\s*[.．)）]")
# ★R100(2026-09-13) — SBI인베스트먼트(20120329001048, fy2011) 실측: 이 회사는 "XI.
# 재무제표 등" 안에서 4대 재무제표를 여닫는 괄호숫자로 순번매김한다("(1)연결재무상태표"
# "(2)연결포괄손익계산서" … "(4)연결현금흐름표", 별도 쪽도 동일하게 (1)(2)(4)). 위
# `_LEGACY_ENUM_PREFIX`("29.", "1)")는 **여는 괄호 없이** 숫자로 시작하는 것만 걸러
# 노트 항목번호를 떨구는 규칙이라 이 형태("(1)"처럼 양쪽 괄호)는 애초에 그 필터에
# 걸리지 않는다 — 별도 처리 없이 그냥 미인식이었을 뿐. 한 겹만 벗기고(중첩 없음)
# 재무제표명이 안 걸리면 그대로 거부되므로(위 KO 접두와 같은 안전판) 새 오탐 경로가
# 생기지 않는다 — "(1)유동자산" 같은 주석 항목은 벗긴 뒤 재무제표명이 없어 계속 거부됨.
_LEGACY_PAREN_NUM_PREFIX = re.compile(r"^[(（]\d{1,2}[)）]")
# 본문 face 가 아닌 것(첫 45자 기준). '주석' 은 여기서도 배제한다.
# ★C-1(2026-09-05, 실측 — 삼성증권 20140515001582) — "요약"이 재무제표명 바로 앞
# 수식어로만 쓰이면(증권/보험 분기보고서 관행: "요약분기연결재무상태표"가 완전한 본문표,
# 축약표 아님) 배제하지 않는다. 그 외 위치("연결재무제표 요약", "요약재무정보" 단독)는
# 계속 배제 — 이 함수가 보는 텍스트는 이미 SEC_LEGACY_FS/APPENDIX 본문 컨테이너 안이므로
# (`_detect_legacy_body_statement_tables`), SEC_SUMMARY 섹션 자체는 이 함수에 안 들어온다.
# 설계문서: category_c_fy2004_2006_section3_and_summary_prefix_design_2026-09-05.md §1-3.
_LEGACY_EXCLUDE = re.compile(
    r"분할|합병|명세|부속|주석|검토보고서|감사보고서|"
    r"요약(?!(?:연결|별도|개별|반기|분기|중간|당|전)*"
    r"(?:재무상태표|대차대조표|포괄손익계산서|손익계산서|현금흐름표|자본변동표))"
)
# 재무제표명 앞에 붙을 수 있는 수식어. 공백 제거 후 판정하므로 '반 기 연 결' 도 흡수된다.
# ★C-2(2026-09-05) — "요약" 추가(위 _LEGACY_EXCLUDE 예외와 짝 — 그쪽에서 통과된 것만
# 여기 걸린다).
_LEGACY_HEAD = re.compile(
    r"^(?:요약|연결|별도|개별|반기|분기|중간|당|전)*"
    r"(재무상태표|대차대조표|포괄손익계산서|손익계산서|현금흐름표|자본변동표)"
)
# ★R69(2026-09-05) — IFRS 전환기 신·구 명칭 병기("재무상태표(대차대조표)"). 실측
# (부속명세서 버킷 40건): BS 헤딩의 92.5%가 이 형태. 괄호 안이 6종 재무제표명 중
# 하나면 통째로 표제의 일부로 보고 소비한다 — 사람이 참고용으로 구명칭을 덧붙인
# 표기 관행일 뿐 새 정보가 아니다(짐작이 아니라 관행 그 자체).
_LEGACY_ALT_NAME_PAREN = re.compile(
    r"^[（(](?:연결|별도|개별)?"
    r"(?:재무상태표|대차대조표|포괄손익계산서|손익계산서|현금흐름표|자본변동표)[)）]"
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


def _classify_legacy_heading_core(
    t: str, include_sce: bool, *, bare_only: bool = False,
) -> tuple[str, str] | None:
    """`classify_legacy_statement_heading` 의 판정 본체 — **이미 공백이 제거된**
    문자열 `t`에 대해서만 동작한다(호출측이 whitespace-strip 을 책임진다).

    bare_only=True 면 B형(명칭 단독 헤딩, `rest==""`)만 인정한다 — R101 꼬리표제
    폴백 전용(아래 `classify_legacy_statement_heading` 참고), 문장 중간에서 잘라낸
    조각이라 그 뒤에 다른 문자가 더 있어도 되는 A형까지 인정하면 오탐 위험이 커진다.
    """
    if not t or _LEGACY_ENUM_PREFIX.match(t):
        return None
    # R69(2026-09-05) — 한글 가나다 열거접두 제거(위 상수 docstring 참고). 벗긴 뒤에도
    # 재무제표명이 안 걸리면 아래 _LEGACY_HEAD.match 에서 그대로 거부된다.
    t = _LEGACY_KO_ENUM_PREFIX.sub("", t, count=1)
    # R100(2026-09-13) — 괄호숫자 순번접두 제거(위 상수 docstring 참고). 같은 안전판.
    t = _LEGACY_PAREN_NUM_PREFIX.sub("", t, count=1)
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
        # R69(2026-09-05) — 괄호 병기("(대차대조표)") 소비, 나머지로 재판정.
        alt = _LEGACY_ALT_NAME_PAREN.match(rest)
        if alt:
            rest = rest[alt.end():]
    if rest:
        if bare_only:
            return None
        # A형: 기간/단위 마커가 곧바로 따라와야 한다. 그 외 문자가 이어지면 표제가 아니다.
        if not _LEGACY_PERIOD_AFTER.match(rest):
            return None
    # rest == "" 이면 B형(명칭 단독 헤딩) — 조건 1~3 을 이미 통과했다.

    basis = "consolidated" if "연결" in t[:m.start(1)] else "separate"
    return (basis, stmt)


# R101(2026-09-13) — 문장 종결 뒤 꼬리표제 폴백 전용 분리자. ★단순 "." 전체가 아니라
# **"다." (한글 종결어미 '-다' + 마침표)** 로 좁힌다 — 실측 회귀(`test_rejects_
# numbered_note_heading`): 단순 "."로 자르면 "29. 현금흐름표" 의 "29." 도 분리돼
# 뒷부분 "현금흐름표"만 남아 오탐(주석 헤딩이 본문으로 오인식)이 재현됐다. "-습니다.
# "/"-되었다." 류 서술어 종결과 "29."/"(1)." 류 열거번호는 마침표 앞 글자로 구분된다
# (전자는 항상 '다', 후자는 숫자) — 이 안전판이 없으면 R101 자체가 R69/R100 이
# 막아온 걸 그대로 뚫는다.
_LEGACY_SENTENCE_SPLIT = re.compile(r"다\.")


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

    ── R101(2026-09-13) 꼬리표제 폴백 ──────────────────────────────────────
    SBI인베스트먼트(20120329001048) 실측: BS 표제("(1)연결재무상태표")가 독립
    요소가 아니라 K-IFRS 재작성 공시문구("※당사의…재작성되었으며,…감사를받지
    않았습니다.") **뒤에 같은 요소 안에 이어붙어** 있다(IS/CF 표제는 독립 요소라
    이 문제가 없음). 전체 텍스트로 판정해 실패하면, **마지막 문장부호 뒤 조각만**
    다시 판정한다 — 단, 오탐 방지를 위해 그 조각은 **B형(명칭 단독, `rest==""`)
    만** 인정한다(문장 중간을 잘라낸 조각이라 A형까지 허용하면 위험이 커짐). 이
    조각도 같은 안전판(번호접두 거부·배제어·괄호숫자 벗기기)을 전부 통과해야
    한다 — 그냥 "포함"이 아니라 **그 조각 전체가 정확히** 헤딩이어야 한다.
    """
    if not text:
        return None
    t = re.sub(r"\s+", "", text)
    result = _classify_legacy_heading_core(t, include_sce)
    if result is not None:
        return result

    parts = _LEGACY_SENTENCE_SPLIT.split(t)
    if len(parts) > 1:
        tail = parts[-1]
        if tail and tail != t:
            return _classify_legacy_heading_core(tail, include_sce, bare_only=True)
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
