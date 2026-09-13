"""연결 비대상(non-consolidation-scope) 확정 근거 추출 (2026-09-13, Track 1).

배경: `docs/plans/consolidation_scope_confirmation_design_2026-09-13.md`. `basis_fallback`
(`fin2/layer3/combine.py`)은 "요청 basis의 report_lines 행이 0건이고 반대 basis만 있다"는
기계적 폴백일 뿐, (a) 이 회사/기간이 **진짜로 연결 작성 대상이 아닌 것**과 (b) 원문엔 연결
표가 있는데 **파서가 못 잡은 결함**을 구분하지 못한다. 이 모듈은 원문에서 직접 읽은 증거로
(a)만 확정한다 — 짐작하지 않는다. 증거 없으면 NULL(호출측이 `fallback_unconfirmed`로 둠).

설계 원칙(`fin2/extract/ifrs_evidence.py`와 동일 — F7): **연도로 추측하지 않는다. 원문에서
읽은 증거가 있을 때만 값을 채운다.**

Track 1(이 모듈이 구현하는 범위, era 분산 표본 원문대조 §2-1-A로 확정) — DART 정형 서식의
`SECTION-2` 중 `TITLE`이 정확히 **"2. 연결재무제표"**인 섹션 본문에 "해당사항"+"없" 토큰이
함께 있으면 → 그 필링의 그 기간엔 연결재무제표 자체가 없다고 원문이 직접 선언한 것.
실측 확인된 변형 6종(§2-1-A): "해당사항없음.", "해당사항 없음.", "당사는 보고서
작성기준일 현재 해당사항이 없습니다.", "보고서 제출일 현재 해당사항이 없습니다.",
"※ 해당사항 없습니다.", "본 보고서 제출 기준일 현재 해당사항 없습니다." — 전부 이 두
토큰을 포함한다.

★이 섹션이 2011~2014 전환기 서식엔 아예 없음(§2-1-B, 실측 확인) — Track 1은 이 섹션이
도입된 이후(2015+, 정확한 도입 연도는 미확정)에만 유효하다. pre-2015는 Track 2(종속회사
목록, 미구현)와 그 시대 작성의무 규칙(R63/버킷A·B)을 결합해야 하며 이 모듈의 범위 밖이다.

★Track 1은 "종속회사가 없다"를 직접 보는 게 아니라 "연결재무제표 섹션 자체가 해당사항
없다"를 본다 — §2-1-C(에넥스 반례: 종속회사는 있어도 그 시대엔 인터림 연결 작성의무가
없어 결측인 경우)와 달리, 이 신호는 **그 필링이 실제로 "이 기간은 연결재무제표 해당사항
없음"이라고 선언한 경우만** 잡으므로 그 반례에 걸리지 않는다(2015+엔 이미 인터림 연결
작성의무가 있으므로 "해당사항없음"은 곧 종속회사가 없다는 뜻과 사실상 동치).
"""

from __future__ import annotations

import re

EVIDENCE_NO_CONSOLIDATED_FS = "no_consolidated_fs_track1"

# "2. 연결재무제표" TITLE — 실측(§2-1-A) 전 표본에 공통, AASSOCNOTE="D-0-3-2-0"도 흔하지만
# 속성값에 의존하지 않고 텍스트 자체로 앵커한다(서식 버전에 따라 속성이 빠질 수 있어 더
# 안전 — 아센디오 2016 표본은 AASSOCNOTE 없이 TITLE 텍스트만 있었다).
_SECTION_TITLE_RE = re.compile(r'<TITLE[^>]*>\s*2\.\s*연결재무제표\s*</TITLE>')
# 이 SECTION-2 의 닫는 태그(또는 다음 SECTION-2 시작) — 못 찾으면 _WINDOW 로 하드캡.
# ★<TITLE\b 는 경계로 쓰지 않는다 — 진짜 연결데이터가 있으면 그 안(TABLE-GROUP)에 표
# 자체의 하위 TITLE("2-1. 연결 재무상태표" 등)이 또 나오는데, 이걸 경계로 오인하면
# 본문이 그 직전에서 잘려 "텅 빈 것처럼" 보인다 — 실측 중 발견한 오탐 원인(대조군
# 16/60 오탐, 전부 이 버그였음. 수정 후 재검증 0건).
_NEXT_BOUNDARY_RE = re.compile(r'</SECTION-2>|<SECTION-2\b')
_WINDOW = 800

# 60건 표본 검증(§2-1 후속, 2026-09-13 구현 중) 중 최초 카탈로그("해당사항"+"없")로 60건
# 중 10건이 빠져 원문을 직접 대조해 보강한 변형들 — 전부 실제 필링에서 발견:
#   - 공백변형: "해당 사항 없습니다"(해당/사항 사이 공백, 플레이디 20210318000703)
#   - 축약형: "해당 없음"(사항 생략, 큐렉소 20220513000945)
#   - 자회사 서술형: "연결대상에 해당하는 자회사가 없으므로 ... 작성의무가 없음"
#     (일신석재 20181114001442), "종속기업을 보유하고 있지 않습니다"(참좋은여행 20241106000231)
#   - 명시적 부작성 서술형: "연결재무제표를 작성하지 않고 별도재무제표만을 작성"(참좋은여행)
# 어느 패턴이든 이 좁은(≤_WINDOW) 섹션 본문 안에서만 찾는다 — 문서 전체에 흔한 상투어라
# 넓은 범위에서 찾으면 오탐 위험이 크다(§2-1-B에서 이미 확인된 함정).
_NA_PATTERNS = [
    re.compile(r'해\s*당\s*사?\s*항?\s*[이가]?\s*없\s*음?\s*습?\s*니?\s*다?'),  # 해당(사항)(이/가) 없(음/습니다) — 글자당 공백을 넣는 옛 강조체("해 당 사 항 없 음")까지 포괄
    re.compile(r'(?:종속회사|종속기업|종속법인|자회사)[^.<]{0,20}없'),  # 종속회사(가) 없음/없으므로
    re.compile(r'(?:보유|보유하고)\s*있지\s*않'),               # 종속기업을 보유하고 있지 않습니다
    # ★R106(2026-09-13, 사용자 질문으로 발견) — 원래는 그냥 `작성\s*(?:하지|치)\s*않`
    # 였는데, 이 좁은 window 안에도 "전기 실적은 이를 소급적용하여 재작성하지
    # 않았습니다"(IFRS1109/1115 도입 시 소급재작성 안 함을 알리는 흔한 각주, 연결
    # 존재여부와 무관) 같은 문장이 같이 들어올 수 있어 오탐(52건 실측, 웅진씽크빅
    # 20190401005063 등 — report_lines에 진짜 연결 BS/IS/CF 수백행이 있는데도 "확정"
    # 판정됨). "재무제표"가 바로 앞에 붙어야만(≤15자) 매칭하도록 좁혀 오탐 제거,
    # 참좋은여행류 진짜 케이스("연결재무제표를 작성하지 않고")는 그대로 잡음.
    # ★R107(2026-09-13, R106 잔여 41건 원문대조 중 발견) — R106 수정 후에도 "OO재무제표를
    # **재작성**하지 않았습니다"(같은 IFRS1109/1115 각주, "재무제표"가 "재작성" 바로
    # 앞이라 ≤15자 조건을 그대로 통과) 28건이 여전히 오탐(인텍플러스 00479787
    # 20190401003585 등 — report_lines에 당기 연결 BS 실측 존재, basis_fallback 아님).
    # "재작성"은 "다시 짓다"라는 고정 복합어라 "작성" 바로 앞 1글자가 "재"인 경우만
    # 배제하면 됨 — `(?<!재)`. 참좋은여행/아이퀘스트류("...를 작성하지 않고")는 "작성"
    # 앞이 "를 "/"재무제표" 자체라 그대로 잡힘(회귀 없음, 상세: `docs/plans/
    # consolidation_scope_confirmation_design_2026-09-13.md` §10).
    re.compile(r'재무제표[^.<]{0,15}(?<!재)작성\s*(?:하지|치)\s*않'),
    re.compile(r'작성\s*의무[가는]?\s*없'),                    # (연결재무제표) 작성의무(가) 없음
    re.compile(r'대상[^.<]{0,10}해당(?:되지|하지)\s*않'),      # (작성)대상(법인)에 해당(되지/하지) 않습니다
    re.compile(r'관련(?:된|되는)?\s*사항[이가]?\s*없'),        # (연결재무제표와) 관련된 사항이 없습니다
    re.compile(r'개별재무제표\s*작성\s*기준'),                 # 당사는 개별재무제표 작성 기준입니다(긍정형 — 별도기준임을 직접 선언)
]
# 태그를 지우고 남는 텍스트가 이 길이 미만이면 "완전 공백"으로 본다(§2-1 표본 3건 —
# 세우글로벌/동화약품/파세코 — 실측: 이 섹션에 <P></P> 뿐 아무 문구도 없이 결측을
# 표시하는 서식도 있음. 모두 진짜 basis_fallback=True 였고, 대조군[basis_fallback=False]
# 60건 표본엔 이 패턴의 오탐이 0건이었다 — 즉 이 섹션이 실제 연결데이터를 담을 때는
# 반드시 표/텍스트가 있어 비어 있지 않다).
_TAG_RE = re.compile(r'<[^>]+>')
_EMPTY_THRESHOLD = 3


def _section_body(text: str) -> str | None:
    """"2. 연결재무제표" TITLE 뒤 본문 텍스트(다음 섹션/타이틀 경계까지, 없으면 _WINDOW
    글자 하드캡). 이 TITLE이 문서에 없으면 None(그 서식엔 이 섹션 자체가 없음 — pre-2015
    전환기 등, §2-1-B)."""
    m = _SECTION_TITLE_RE.search(text)
    if m is None:
        return None
    tail = text[m.end():]
    b = _NEXT_BOUNDARY_RE.search(tail)
    end = b.start() if b is not None else _WINDOW
    return tail[:min(end, _WINDOW)]


def detect_no_consolidated_fs(text: str) -> bool:
    """"2. 연결재무제표" 섹션 본문이 "이 기간 연결재무제표 없음"을 확정하면 True:
    (a) "해당사항 없음" 계열 문구가 있거나, (b) 태그를 지운 본문이 사실상 텅 비어 있으면
    (표/서술 전부 없음).

    섹션 자체가 없거나, 있어도 실제 표(진짜 연결 데이터)·설명이 있고 위 두 조건 다
    아니면 False — "표가 있다"고 긍정 판정하지 않는다(이 함수는 부재 확정 전용, 짐작
    금지). 대조군 60건(basis_fallback=False, 실제 연결데이터 있는 필링) 실측 결과
    오탐 0건.
    """
    body = _section_body(text)
    if body is None:
        return False
    if any(p.search(body) for p in _NA_PATTERNS):
        return True
    stripped = _TAG_RE.sub('', body).strip()
    return len(stripped) < _EMPTY_THRESHOLD


def compute_text_evidence(text: str) -> tuple[str | None, dict]:
    """document.xml 원문 텍스트 하나로부터 (evidence_code, detail) 계산."""
    if detect_no_consolidated_fs(text):
        return EVIDENCE_NO_CONSOLIDATED_FS, {
            "reason": '"2. 연결재무제표" section body contains 해당사항+없 tokens',
        }
    return None, {}


def resolve_filing_evidence(session, rcept_no: str, file_path=None, file_text: str | None = None) -> tuple[str | None, dict]:
    """rcept 하나의 (evidence_code, detail). Track 1은 순수 텍스트 판정이라 XBRL instance
    zip 전용(`file_type='xbrl_zip'`) 필링처럼 document.xml 자체가 없는 경우는 판정
    불가 → None(짐작 금지, `ifrs_evidence.py`의 Track D 같은 대체 확정 경로가 없다 —
    이 모듈은 §6-2 스코프 밖으로 명시적으로 남긴다).

    file_text를 이미 갖고 있으면(추출 파이프라인이 document.xml을 이미 읽은 경우) 재사용해
    파일 재오픈을 피한다 — file_path만 주어지면 이 함수가 직접 연다.
    """
    if file_text is None:
        if file_path is None:
            return None, {}
        from pathlib import Path
        p = Path(file_path)
        if p.suffix.lower() != ".xml" or not p.exists():
            return None, {}
        try:
            # ★EUC-KR 함정([[feedback-grep-euckr-locale-trap]]) — 연도로 인코딩을 추측하지
            # 않는다(이번 조사 §2-1-E에서 2020년 필링도 EUC-KR인 사례 실측 확인). 기존
            # 검증된 인코딩 감지 로직 재사용(ifrs_evidence.py와 동일 관례).
            from parser.xml.dart_xml_parser import _detect_xml_encoding
            raw = p.read_bytes()
            encoding = _detect_xml_encoding(raw)
            file_text = raw.decode(encoding, errors="replace")
        except Exception:
            return None, {}

    return compute_text_evidence(file_text)


def resolve_std_v3_no_consolidated_fs(session, source_rcepts: dict | None) -> bool | None:
    """std_financials_v3 행 하나(corp,fy,period)의 `source_rcepts`
    ({"BS": rcept, "IS": rcept, "CF": rcept, ...})로부터 "이 기간 연결재무제표 자체가
    원문상 없다고 확정됐는지" 계산한다.

    "2. 연결재무제표" 섹션은 basis 별이 아니라 그 필링 문서 전체에 하나뿐이므로, source_rcepts
    (basis-independent, `select_canonical_rcepts()`가 고른 canonical/최신 rcept — 정정본
    포함 이미 반영됨, §2-1-D 원칙)에 있는 rcept 중 **하나라도** 이 evidence가 확정돼 있으면
    True. 아무것도 확정 안 됐으면 None(짐작 금지 — 호출측이 `fallback_unconfirmed`로 둠).
    """
    if not source_rcepts:
        return None
    rcepts = sorted({r for r in source_rcepts.values() if r})
    if not rcepts:
        return None

    from sqlalchemy import bindparam, text as sa_text

    rows = session.execute(
        sa_text("SELECT consolidation_evidence FROM filings WHERE rcept_no IN :rs")
        .bindparams(bindparam("rs", expanding=True)),
        {"rs": rcepts},
    ).fetchall()
    if any(r[0] == EVIDENCE_NO_CONSOLIDATED_FS for r in rows):
        return True
    return None


def store_filing_consolidation_evidence(session, rcept_no: str, file_path=None, file_text: str | None = None) -> str | None:
    """rcept 하나의 증거를 판정해 `filings.consolidation_evidence`/
    `consolidation_evidence_detail`에 저장. 단순 UPDATE(한 rcept당 유일 값, tree 구조
    없음) — `store_filing_ifrs_evidence`와 동일 관례. 트랜잭션 커밋은 호출측 책임.
    """
    from sqlalchemy import update
    from collector.models import Filing

    evidence, detail = resolve_filing_evidence(session, rcept_no, file_path=file_path, file_text=file_text)
    session.execute(
        update(Filing).where(Filing.rcept_no == rcept_no)
        .values(consolidation_evidence=evidence, consolidation_evidence_detail=detail or None)
    )
    return evidence
