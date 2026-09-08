"""
is_ifrs 판정 근거 추출 (2026-09-08, docs/plans/is_ifrs_v3_design_2026-09-08.md).

배경: `standard_financials` 뷰(`collector/db.py`)와 `calendar_v3.py`는 지금까지
`is_ifrs`를 `TRUE` 상수로 채웠다("v3는 2015+만 있고 전량 IFRS 의무화 이후"). 그 근거는
Category C 소급백필(1999~)로 깨졌다 — 실측(2026-09-08) pre-2015 132,026행(41%)이 이
가정이 안 맞는 구간인데도 TRUE로 노출 중이었다.

설계 원칙(★2026-07-17 F7, `fin2/standardize/build.py::_derive_is_ifrs()` 원칙 재사용):
**연도로 추측하지 않는다. 원문에서 읽은 증거가 있을 때만 값을 채운다.** 증거 없으면 NULL
(소비 측 `curr.get('is_ifrs', True)`가 이미 NULL을 IFRS로 표시하는 관례라 하위호환 안전).

우선순위(§5-3 확정) — 위에서부터 먼저 성립하는 신호를 채택, 짐작 금지:
  1. Track A  — document.xml에 ACODE(ifrs-full_/dart_)+ACONTEXT 셀이 있음
     (`fin2/audit/face_audit.py::read_report_face_xbrl()`과 같은 판정 기준이지만,
     값 해석 없이 존재유무만 보는 훨씬 가벼운 텍스트 검사로 대체 — 이 모듈은 계층2
     원칙[[architecture-report-read-layer2-only]]대로 account_mapper/canonical 매핑을
     전혀 안 한다).
  2. Track D  — 이 rcept가 XBRL instance zip 경로(`report_lines_xbrl.py`)로 추출됨.
     instance zip 자체가 IFRS 택소노미만 담으므로 소스 트랙 자체가 곧 증거.
  3. 기준서 번호 — 원문에 "기업회계기준서 제N호" 언급이 있고, 번호 자릿수가
     상호배타적으로 갈림(대규모 표본 실측, §5-2): 구 K-GAAP 기준서=제1~30호대,
     신 K-IFRS 기준서=**제1001호부터**(IAS 번호 대응, 예 제1027호=IAS27). 둘 다
     나오면(전환기 비교공시 등) 짐작하지 않고 mixed로 남겨 수동검토 후보로 표시한다.
     ★대조군 실측: "한국채택국제회계기준"/"K-IFRS" **단어 자체**는 2009년 이후 전
     구간에서 100% 등장해(전환 예고 각주 때문) 변별력이 0임을 확인 — 이 단어 매칭은
     쓰지 않는다.
  4. 없음 — 이 문서에서 판정 불가. 호출측이 NULL로 남긴다.
"""

from __future__ import annotations

import re

EVIDENCE_TRACK_A = "track_a"
EVIDENCE_TRACK_D = "track_d"
EVIDENCE_STD_NO_KGAAP = "std_no_kgaap"
EVIDENCE_STD_NO_KIFRS = "std_no_kifrs"
EVIDENCE_STD_NO_MIXED = "std_no_mixed"

# K-IFRS 기준서는 제1001호부터(IAS 번호 대응) — 대규모 표본 실측(§5-2) 확정 임계값.
_STD_NO_KIFRS_THRESHOLD = 1000

_TRACK_A_ACODE_RE = re.compile(r'ACODE\s*=\s*"(?:ifrs-full_|dart_)[^"]*"')
_ACONTEXT_RE = re.compile(r'\bACONTEXT\s*=')
_STD_NO_ANCHOR_RE = re.compile(r'기업회계기준서')
_STD_NO_BARE_RE = re.compile(r'제\s*(\d+)\s*호')
# "기업회계기준서 제1호 내지 제17호(제11호 및 제18호는 제외)"류 나열/범위 표기가 실측
# (§5-2)에서 확인됨 — "기업회계기준서"가 목록의 각 항목마다 반복되지 않는다. anchor
# 뒤 이 길이 안의 "제N호"는 같은 나열의 일부로 본다(원문 실측 기준 범위 설정, 문단
# 경계를 넘는 오탐 방지를 위해 넉넉하되 무한하지 않게 제한).
_STD_NO_WINDOW = 150


def detect_track_a_evidence(text: str) -> bool:
    """document.xml 원문 텍스트에 ACODE(ifrs-full_/dart_)+ACONTEXT 셀이 하나라도 있으면 True.

    `read_report_face_xbrl()`과 동일한 판정 기준(Track A = ACODE+ACONTEXT 존재)이지만,
    컬럼/값 해석 없이 정규식 존재 검사만 하므로 훨씬 가볍다 — 이 모듈은 "IFRS
    택소노미를 원문이 실제로 썼는가"만 알면 되고, 그 값이 뭔지는 알 필요 없다.
    """
    return bool(_TRACK_A_ACODE_RE.search(text)) and bool(_ACONTEXT_RE.search(text))


def detect_std_no_evidence(text: str) -> tuple[str | None, list[int]]:
    """"기업회계기준서 제N호"(및 그 뒤 나열/범위 표기의 "제N호"들) 전수 추출 → 번호
    자릿수로 K-GAAP/K-IFRS 판정.

    반환: (evidence_code | None, 매칭된 번호 목록[정렬·중복제거]) — 번호 목록은
    filings.ifrs_evidence_detail에 근거로 남겨 감사 가능하게 한다.
    """
    nums: set[int] = set()
    for anchor in _STD_NO_ANCHOR_RE.finditer(text):
        window = text[anchor.end(): anchor.end() + _STD_NO_WINDOW]
        nums.update(int(n) for n in _STD_NO_BARE_RE.findall(window))
    nums = sorted(nums)
    if not nums:
        return None, []
    has_kifrs = any(n >= _STD_NO_KIFRS_THRESHOLD for n in nums)
    has_kgaap = any(n < _STD_NO_KIFRS_THRESHOLD for n in nums)
    if has_kifrs and has_kgaap:
        return EVIDENCE_STD_NO_MIXED, nums
    return (EVIDENCE_STD_NO_KIFRS if has_kifrs else EVIDENCE_STD_NO_KGAAP), nums


def compute_text_evidence(text: str) -> tuple[str | None, dict]:
    """document.xml 원문 텍스트 하나로부터 (evidence_code, detail) 계산 — Track A → 기준서
    번호 순으로 시도. Track D(XBRL instance zip 출처)는 파일 텍스트로 판정 불가능해
    호출측이 DownloadTask.parser_track으로 별도 확인한다(`resolve_filing_evidence` 참고).
    """
    if detect_track_a_evidence(text):
        return EVIDENCE_TRACK_A, {"reason": "ACODE(ifrs-full_/dart_)+ACONTEXT cell(s) present"}
    std_no_evidence, nums = detect_std_no_evidence(text)
    if std_no_evidence is not None:
        return std_no_evidence, {"std_no_matches": nums}
    return None, {}


def resolve_is_ifrs(evidence: str | None) -> bool | None:
    """evidence 코드 → is_ifrs 값. mixed·None(증거불충분)은 짐작 금지 → NULL."""
    if evidence in (EVIDENCE_TRACK_A, EVIDENCE_TRACK_D, EVIDENCE_STD_NO_KIFRS):
        return True
    if evidence == EVIDENCE_STD_NO_KGAAP:
        return False
    return None


def resolve_filing_evidence(session, rcept_no: str, file_path=None, file_text: str | None = None) -> tuple[str | None, dict]:
    """rcept 하나의 (evidence_code, detail) — Track D(DB) 우선 확인 후, 없으면 파일
    텍스트를 읽어 Track A/기준서번호를 판정한다(§우선순위: Track A > Track D처럼
    보이지만, Track D는 파일이 XML이 아니라 텍스트 판정 자체가 불가능한 zip 이므로
    실질적으로 상호배타적 — 같은 rcept가 동시에 두 트랙일 수 없다).

    file_text를 이미 갖고 있으면(추출 파이프라인이 document.xml을 이미 읽은 경우) 그걸
    재사용해 파일 재오픈을 피한다 — file_path만 주어지면 이 함수가 직접 연다.
    """
    from collector.models import DownloadTask

    task = session.query(DownloadTask).filter_by(rcept_no=rcept_no).first()
    if task is not None and task.parser_track == "XBRL_INSTANCE":
        return EVIDENCE_TRACK_D, {"reason": "extracted via XBRL instance zip (report_lines_xbrl.py)"}

    if file_text is None:
        if file_path is None:
            return None, {}
        from pathlib import Path
        p = Path(file_path)
        if p.suffix.lower() != ".xml" or not p.exists():
            # PDF/HWP 등 텍스트 판정 불가한 소스 — 이번 스코프 밖(§6-2), 증거없음으로 남김.
            return None, {}
        try:
            # ★EUC-KR 함정([[feedback-grep-euckr-locale-trap]]) — 구형 DART XML은 UTF-8
            # 선언에도 실제론 EUC-KR인 경우가 많다. dart_xml_parser의 기존 검증된 인코딩
            # 감지 로직을 그대로 재사용(직접 짐작하지 않음).
            from parser.xml.dart_xml_parser import _detect_xml_encoding
            raw = p.read_bytes()
            encoding = _detect_xml_encoding(raw)
            file_text = raw.decode(encoding, errors="replace")
        except Exception:
            return None, {}

    return compute_text_evidence(file_text)


def resolve_std_v3_is_ifrs(session, source_rcepts: dict | None) -> bool | None:
    """std_financials_v3 행 하나(corp,fy,period,basis)의 `source_rcepts`
    ({"BS": rcept, "IS": rcept, "CF": rcept, ...})로부터 `is_ifrs`를 계산한다.

    여러 rcept(델타패치로 BS/IS/CF가 각기 다른 필링일 수 있음)의 `filings.ifrs_evidence`를
    모아 True/False 각각으로 확정되는 게 있는지 본다. **True와 False가 동시에 나오면
    짐작하지 않고 NULL**(§5-3 원칙 — 어느 한쪽이 더 권위있다고 가정하지 않는다).
    """
    if not source_rcepts:
        return None
    rcepts = sorted({r for r in source_rcepts.values() if r})
    if not rcepts:
        return None

    from sqlalchemy import bindparam, text as sa_text

    rows = session.execute(
        sa_text("SELECT ifrs_evidence FROM filings WHERE rcept_no IN :rs")
        .bindparams(bindparam("rs", expanding=True)),
        {"rs": rcepts},
    ).fetchall()
    resolved = {resolve_is_ifrs(r[0]) for r in rows}
    resolved.discard(None)
    if resolved == {True}:
        return True
    if resolved == {False}:
        return False
    return None   # 미상, 또는 True/False 동시 발생(충돌) — 둘 다 짐작 금지


def store_filing_ifrs_evidence(session, rcept_no: str, file_path=None, file_text: str | None = None) -> str | None:
    """rcept 하나의 증거를 판정해 `filings.ifrs_evidence`/`ifrs_evidence_detail`에 저장.

    delete-then-insert 류 재현성 패턴(store_report_lines와 동일 관례)이 아니라 단순
    UPDATE — 이 값은 한 rcept당 유일하고 tree 구조가 없어 덮어쓰기로 충분하다. 트랜잭션
    커밋은 호출측 책임(session 을 그대로 넘겨받음, 이 함수는 execute만 함).
    반환: 저장된 evidence 코드(또는 None).
    """
    from sqlalchemy import update
    from collector.models import Filing

    evidence, detail = resolve_filing_evidence(session, rcept_no, file_path=file_path, file_text=file_text)
    session.execute(
        update(Filing).where(Filing.rcept_no == rcept_no)
        .values(ifrs_evidence=evidence, ifrs_evidence_detail=detail or None)
    )
    return evidence
