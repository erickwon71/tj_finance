"""
HTML↔PDF 결과 신뢰도 조정(T1/T2/T3) — Track C 잔여 93건 스코프.

배경: `docs/plans/html_viewer_extractor_design_2026-09-07.md` §8-8 — Track C
93건 스코프에서 HTML을 PDF보다 먼저 시도하기로 했는데, HTML은 PDF의
`[014]`처럼 명확한 실패 신호가 없다(항상 200 OK, 파싱 자체는 "성공"해도
값이 틀리거나 불완전할 수 있음). 그래서 "다음 방법(PDF)으로 넘어가는 조건"을
응답 유무가 아니라 **결과의 신뢰도**로 정의한다. 93건 실측(fail19+missing74,
§8-4~8-6)에서 실제로 관찰된 패턴 그대로 3등급:

  T1(확신)    별도(separate) 기준 자산총계=부채총계+자본총계 항등식이
              정확히 성립. 실측 45건 전부 이 조건 하나로 걸러졌다(그중
              다수가 "기존에 이미 맞던 값은 그대로 보존한 채 나머지만
              정확히 채움" — 우연이 아니라는 근거, §8-6). → HTML 채택,
              PDF는 아예 시도 안 함(계산 절약).
  T2(완전공백)  그랜드토탈 3개(자산/부채/자본 총계)가 하나도 없음. →
              PDF로 폴백 — HTML이 못 찾았으니 PDF가 이미 갖고 있던 값이
              더 나을 수 있다(원인B 두 필링이 실제로 이 경로).
  T3(애매함)   값은 일부 나왔으나 항등식 불성립, 또는 연결(consolidated —
              외부주주지분 등 3자분할이 가능해 이 항등식 검증 자체가
              원리적으로 약함, 제일기획 연결 3건이 실증). → PDF도 마저
              시도해 PDF가 T1이면, HTML과 겹치는 항목(둘 다 값을 찾은
              그랜드토탈)이 서로 일치하는지 **교차검증**한 뒤에만 PDF 채택
              (§8-11 — "항등식 성립"은 필요조건일 뿐 충분조건이 아니다,
              라벨-값이 뒤바뀌어도 우연히 셈이 맞을 수 있다: KD swap-bug
              패턴 실증). 교차검증 실패하거나 PDF도 T1이 아니면 **자동
              채택 안 함**("결측이 오염보다 낫다" 원칙 — 사람이 원문대조로
              확정하기 전엔 어느 쪽도 std_financials_v3에 싣지 않는다).

이 모듈은 그 판정·조정 로직만 담당한다(DB 미의존, 순수 함수 위주 —
`fin2/tests/test_extract_reconcile.py`가 가짜 facts 리스트로 검증 — 파일명
★주의: `fin2/tests/test_reconcile.py`는 완전히 다른 기존 모듈 `fin2/reconcile.py`
[기재정정 select_source]의 테스트라 basename 충돌, 분리했다). 파이프라인
(`collector/pdf_lines_sync.py::recover_one()`)에는 아직 배선 안 됨 — §5
런북 체크리스트·백필은 별도 지시 대기(계획 후 대기 원칙).
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from enum import Enum

from fin2.extract.html_viewer import extract_html_facts, find_statement_nodes, parse_toc_tree
from fin2.extract.pdf import extract_pdf_facts
from fin2.extract.xbrl import ExtractedFact

_TOTAL_CANONS = ("bs.total_assets", "bs.total_liabilities", "bs.total_equity")


class Confidence(str, Enum):
    T1_CONFIDENT = "T1"
    T2_EMPTY = "T2"
    T3_AMBIGUOUS = "T3"


def _totals(facts: list[ExtractedFact], basis: str) -> dict[str, int | None]:
    out: dict[str, int | None] = {c: None for c in _TOTAL_CANONS}
    for f in facts:
        if f.basis == basis and f.canonical_account in _TOTAL_CANONS and f.amount_won is not None:
            out[f.canonical_account] = f.amount_won
    return out


def _conflicting_totals(html_facts: list[ExtractedFact], pdf_facts: list[ExtractedFact],
                         basis: str) -> list[str]:
    """HTML·PDF 둘 다 값을 찾은(non-None) 그랜드토탈 항목 중 서로 값이 다른 것.

    2026-09-07 후속(§8-11) — "PDF가 T1이면 무조건 채택"의 위험: 항등식 성립은
    필요조건일 뿐 충분조건이 아니다(라벨-값이 뒤바뀌어도 우연히 셈이 맞을 수
    있음, KD swap-bug 패턴이 실증). PDF를 자동 채택하기 전에 HTML과 겹치는
    항목끼리 값이 일치하는지 교차검증한다 — 겹치는 항목이 하나라도 불일치하면
    PDF의 "확신"을 못 믿는다(사람 확인으로 넘김). HTML은 T3 판정을 받은
    이상 최소 1개는 값을 찾은 상태라(T2 는 0개일 때만) 겹치는 항목은 항상
    최소 1개 존재한다.
    """
    h = _totals(html_facts, basis)
    p = _totals(pdf_facts, basis)
    return [c for c in _TOTAL_CANONS if h[c] is not None and p[c] is not None and h[c] != p[c]]


def classify_confidence(facts: list[ExtractedFact], basis: str) -> Confidence:
    """BS 그랜드토탈 3종 기준, 한 basis 의 facts 신뢰도 등급 판정.

    연결(consolidated)은 항등식이 성립해도 T1로 승격하지 않는다(§8-8 — 3자
    분할 가능성 때문에 검증이 약함, 지금은 보수적으로 전부 T3로 묶는다는
    설계 결정 — 별도 승격 기준은 다음 세션 논의 대상, 미결정 그대로 유지).
    """
    t = _totals(facts, basis)
    n_found = sum(1 for v in t.values() if v is not None)
    if n_found == 0:
        return Confidence.T2_EMPTY
    if (basis == "separate" and n_found == 3
            and t["bs.total_assets"] == t["bs.total_liabilities"] + t["bs.total_equity"]):
        return Confidence.T1_CONFIDENT
    return Confidence.T3_AMBIGUOUS


@dataclass
class ReconcileResult:
    corp_code: str
    rcept_no: str
    basis: str
    decision: str  # "html" | "pdf" | "unresolved"
    html_confidence: Confidence
    pdf_confidence: Confidence | None  # None = PDF 시도 자체를 안 함(T1이라 생략)
    html_facts: list[ExtractedFact]
    pdf_facts: list[ExtractedFact] | None
    reason: str


def reconcile_basis(
    basis: str,
    html_facts: list[ExtractedFact],
    get_pdf_facts,
    *, corp_code: str, rcept_no: str,
) -> ReconcileResult:
    """한 basis(별도/연결)에 대한 HTML→PDF 조정.

    `get_pdf_facts`: `() -> list[ExtractedFact]` — PDF가 실제로 필요할
    때만(T1이 아닐 때만) 호출되는 지연 콜백. 별도/연결 두 basis 모두 PDF가
    필요한 경우에도 호출자가 캐싱하면 PDF는 한 번만 받으면 된다(파일 I/O·
    파싱 재사용) — 그래서 `get_pdf_facts()`가 반환하는 리스트는 **문서 전체**
    (별도+연결 다 섞인) 사실이고, 이 함수가 `basis`로 걸러서 쓴다. `html_facts`
    는 `reconcile()`이 호출 전에 이미 basis로 걸러 넘겨준다 — 대칭을 맞추기
    위해 `pdf_facts`도 여기서 걸러서 `ReconcileResult`에 담는다(2026-09-07
    reconcile_store 스모크테스트로 발견 — 안 걸렀을 때 KD 연결행의 pdf_values
    에 별도 basis 금액이 새어 들어가는 버그가 실측됨. `classify_confidence()`
    는 내부에서 자체 필터링을 하므로 이 버그의 영향을 안 받았지만, `Reconcile
    Result.pdf_facts`를 그대로 쓰는 하류 소비자는 오염된 값을 받았다).
    """
    html_conf = classify_confidence(html_facts, basis)

    if html_conf == Confidence.T1_CONFIDENT:
        return ReconcileResult(
            corp_code=corp_code, rcept_no=rcept_no, basis=basis,
            decision="html", html_confidence=html_conf, pdf_confidence=None,
            html_facts=html_facts, pdf_facts=None,
            reason="HTML T1(항등식 성립) — PDF 시도 안 함",
        )

    # get_pdf_facts() 는 문서 전체(별도+연결) 리스트를 캐시로 반환한다 — 이
    # 함수 안에서 basis 로 걸러서 html_facts 와 동일한 불변조건을 맞춘다.
    pdf_facts = [f for f in get_pdf_facts() if f.basis == basis]
    pdf_conf = classify_confidence(pdf_facts, basis)

    if html_conf == Confidence.T2_EMPTY:
        if pdf_conf != Confidence.T2_EMPTY:
            return ReconcileResult(
                corp_code=corp_code, rcept_no=rcept_no, basis=basis,
                decision="pdf", html_confidence=html_conf, pdf_confidence=pdf_conf,
                html_facts=html_facts, pdf_facts=pdf_facts,
                reason="HTML T2(완전공백) — PDF 채택",
            )
        return ReconcileResult(
            corp_code=corp_code, rcept_no=rcept_no, basis=basis,
            decision="unresolved", html_confidence=html_conf, pdf_confidence=pdf_conf,
            html_facts=html_facts, pdf_facts=pdf_facts,
            reason="HTML·PDF 둘 다 완전공백 — 결측 유지",
        )

    # html_conf == T3_AMBIGUOUS
    if pdf_conf == Confidence.T1_CONFIDENT:
        # PDF T1("항등식 성립")은 필요조건일 뿐 충분조건이 아니다 — 라벨-값이
        # 뒤바뀌어도 우연히 셈이 맞을 수 있다(KD swap-bug 패턴 실증, §8-11).
        # HTML과 겹치는 항목끼리 값이 일치하는지 교차검증한 뒤에만 신뢰한다.
        conflicts = _conflicting_totals(html_facts, pdf_facts, basis)
        if not conflicts:
            return ReconcileResult(
                corp_code=corp_code, rcept_no=rcept_no, basis=basis,
                decision="pdf", html_confidence=html_conf, pdf_confidence=pdf_conf,
                html_facts=html_facts, pdf_facts=pdf_facts,
                reason="HTML T3(애매함), PDF T1(항등식 성립)이고 HTML과 겹치는 "
                       "항목 전부 일치(교차검증 통과) — PDF 채택",
            )
        return ReconcileResult(
            corp_code=corp_code, rcept_no=rcept_no, basis=basis,
            decision="unresolved", html_confidence=html_conf, pdf_confidence=pdf_conf,
            html_facts=html_facts, pdf_facts=pdf_facts,
            reason=f"HTML T3(애매함), PDF T1(항등식 성립)이지만 HTML과 겹치는 "
                   f"항목 중 {conflicts} 불일치(교차검증 실패) — PDF 확신을 못 믿음, "
                   f"자동 채택 안 함, 사람 확인 대기",
        )
    return ReconcileResult(
        corp_code=corp_code, rcept_no=rcept_no, basis=basis,
        decision="unresolved", html_confidence=html_conf, pdf_confidence=pdf_conf,
        html_facts=html_facts, pdf_facts=pdf_facts,
        reason="HTML·PDF 둘 다 T1 아님(애매함) — 자동 채택 안 함, 사람 확인 대기",
    )


def reconcile(
    scraper,
    rcept_no: str,
    *, corp_code: str, report_fiscal_year: int, report_fiscal_period: str,
) -> list[ReconcileResult]:
    """rcept_no 하나 → basis별(별도/연결) ReconcileResult 리스트.

    HTML은 항상 먼저 fetch(1회). PDF는 basis별 판정이 T1이 아닐 때만
    지연 fetch(한 번만 받아서 캐시 — 별도·연결 둘 다 PDF가 필요해도 PDF
    파일 요청·파싱은 한 번뿐).

    `scraper`: `collector.legacy_downloader.LegacyDartScraper` 인스턴스.
    """
    # ★실측 발견(일성건설 00146232, 2026-09-07 T3 구현 중) — bases_present 를
    # html_facts 에서 뽑으면 안 된다. TOC엔 "4. 연결재무제표" 노드가 분명히
    # 있는데(연결재무제표가 실제로 존재), 원인B(§8-5) 때문에 그 표에서 세부
    # 항목까지 전부 0건이 되면 "연결" basis 자체가 html_facts 에서 통째로
    # 사라져 reconcile 대상에서 빠져버렸다(PDF 폴백 기회 자체를 놓침). TOC
    # 노드 유무로 "이 basis 가 존재하는가"를 판정해야 한다 — extract_html_
    # facts() 내부와 같은 TOC 조회를 한 번 더 하는 비효율은 있지만(main.do
    # 재요청 1회), 93건 스코프에서는 무시할 수준.
    toc_text = scraper.fetch_toc_page(rcept_no)
    fs_nodes = find_statement_nodes(parse_toc_tree(toc_text)) if toc_text else []
    bases_present = sorted({"consolidated" if "연결" in n.text else "separate" for n in fs_nodes})
    if not bases_present:
        # TOC 조회 자체가 실패(네트워크 오류 등) — basis 자체를 모르니
        # 별도/연결 둘 다 시도한다(T2 판정으로 자연히 PDF에 넘어감).
        bases_present = ["separate", "consolidated"]

    html_facts = extract_html_facts(
        scraper, rcept_no, corp_code=corp_code,
        report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
    )

    pdf_facts_cache: list[list[ExtractedFact] | None] = [None]

    def get_pdf_facts() -> list[ExtractedFact]:
        if pdf_facts_cache[0] is None:
            pdf_bytes = scraper.fetch_pdf_bytes(rcept_no)
            if pdf_bytes:
                with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
                    tmp.write(pdf_bytes)
                    tmp.flush()
                    pdf_facts_cache[0] = extract_pdf_facts(
                        tmp.name, corp_code=corp_code, rcept_no=rcept_no,
                        report_fiscal_year=report_fiscal_year,
                        report_fiscal_period=report_fiscal_period,
                    )
            else:
                pdf_facts_cache[0] = []
        return pdf_facts_cache[0]

    return [
        reconcile_basis(
            basis, [f for f in html_facts if f.basis == basis], get_pdf_facts,
            corp_code=corp_code, rcept_no=rcept_no,
        )
        for basis in bases_present
    ]
