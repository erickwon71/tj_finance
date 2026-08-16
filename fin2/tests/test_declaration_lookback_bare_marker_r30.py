"""T4(R28 후속) M3 회귀 테스트 — 표제/계정구분 **중복 마커**가 단위 룩백을 막던 버그.

`docs/plans/eps_r28_followup_tracks_design_2026-08-16.md` §5-6·§5-7-1(T4), `docs/PARSING_RULES.md` R30.

`doc_default` 로 떨어진 667그룹 전수 재파싱(§5-7-1) 결과, 30그룹(288행)이 표제표(단위
선언 보유)와 데이터표 사이에 **내용 없는 중복 캡션**(같은 재무제표 이름만 되풀이하는
형제, 또는 은행업 계정구분 괄호라벨)이 끼어 `declaration_text()`/
`inherited_declaration_text()`의 "재무제표명을 만나면 멈춘다"는 안전판(LVMC 회귀 방지용)
에 의도치 않게 걸려 진짜 선언에 닿지 못했다. 아래 구조는 전부 원문 실측 구조를 그대로
합성했다(위아 00106623·기업은행 00149646·서원/00122898류 APPR 다수사).

수정 후 재검증(`scripts/verify_m3_fix_2026-08-16.py`, 스크래치패드 재현): 30그룹 중
23그룹(76.7%)이 실제 프로덕션 함수로 복구됨을 확인. 나머지 7건은 이 화이트리스트
범위 밖(회사명 단독 마커·인용부호 안내문 1건씩, 표제표 단위 선언 자체가 빈 경우 등) —
의도적으로 좁게 유지했다(LVMC 류 회귀 방지, §5-8 참고).

실행: python -m pytest fin2/tests/test_declaration_lookback_bare_marker_r30.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree  # noqa: E402

from fin2.extract.statement_titles import _is_bare_structural_marker  # noqa: E402
from fin2.extract.text import declaration_text, inherited_declaration_text  # noqa: E402


def _data(*rows: tuple[str, str]) -> str:
    trs = "".join(f"<TR><TD><P>{a}</P></TD><TD><P>{b}</P></TD></TR>" for a, b in rows)
    return f"<TABLE>{trs}</TABLE>"


# ── 1) `_is_bare_structural_marker` 단위 함수 ───────────────────────────────

def test_bare_repeated_titles_are_markers():
    """이름만 있고 다른 정보(기간·단위·계정)가 없으면 True — 자간벌림 포함."""
    for t in ("현 금 흐 름 표", "대 차 대 조 표", "연 결 자 본 변 동 표",
              "이익잉여금처분계산서", "이익잉여금 처분계산서", "결손금 처리계산서",
              "반 기 대 차 대 조 표", "(3) 연결자본변동표(연결잉여금계산서)"):
        assert _is_bare_structural_marker(t) is True, t


def test_bank_account_subheaders_are_markers():
    """은행/보험업 계정구분 괄호라벨(기업은행 실측)."""
    for t in ("(은행계정)", "(신탁계정)"):
        assert _is_bare_structural_marker(t) is True, t


def test_title_with_extra_content_is_not_a_bare_marker():
    """★안전판 — 기간·단위 등 다른 정보가 섞이면 여전히 "완전한 문장"(경계 유지).

    표제표 자신(진짜 선언 후보)이 이 함수에 걸려 스킵되면 안 된다.
    """
    for t in ("현금흐름표 제 39 기 2020.01.01 부터",
              "대차대조표 제 44 기 2004. 12. 31 현재 (단위 : 백만원)",
              "위 아 주 식 회 사",              # 회사명 단독 — 화이트리스트 밖(의도적)
              "'당기 사항은 2008년 4월중 제출 예정입니다'"):  # 인용부호 안내문 — 화이트리스트 밖
        assert _is_bare_structural_marker(t) is False, t


def test_plain_text_and_empty_are_not_bare_markers():
    assert _is_bare_structural_marker("") is False
    assert _is_bare_structural_marker("상기 재무정보는 내부거래 제거 전 기준입니다.") is False


# ── 2) 통합 — 실측 구조 합성 (원문 그대로) ──────────────────────────────────

def test_bank_style_bs_recovers_declaration_past_account_subheader():
    """★핵심 회귀 — 기업은행류: [표제표(단위 보유)]<P>(은행계정)</P>[데이터표].

    실측 20050331001780(기업은행) 그대로: 표제 TABLE-GROUP 이 단위(백만원)를 들고
    있고, 바로 다음 형제가 계정구분 캡션 '(은행계정)' 이라 데이터표의 직전 형제가
    캡션이 된다 — 종전엔 여기서 멈춰 doc_default 로 떨어졌다.
    """
    doc = (
        "<SECTION-3>"
        "<TABLE-GROUP><TITLE>대 차 대 조 표</TITLE>"
        + _data(("제 44 기 2004. 12. 31 현재", ""),
                ("제 43 기 2003. 12. 31 현재", ""),
                ("(단위 : 백만원)", ""))
        + "</TABLE-GROUP>"
        "<P>(은행계정)</P>"
        + _data(("현금및예치금", "1,234,567"), ("자산총계", "9,999,999"))
        + "</SECTION-3>"
    )
    root = etree.fromstring(doc.encode())
    data_tbl = root.findall("TABLE")[-1]
    decl = declaration_text(data_tbl) or inherited_declaration_text(data_tbl)
    assert decl is not None, "은행계정 캡션에 막혀 단위 선언을 못 찾았다"
    assert "백만원" in decl


def test_appropriation_style_recovers_declaration_past_bare_title_repeat():
    """★핵심 회귀 — APPR류: [표제표(단위 보유)] 직후 데이터표(직전 형제=표제표 자체가
    아니라 표제표 **안**의 별도 TITLE 텍스트가 아니라, 표제표 자체가 곧 직전 형제인
    단순 케이스). 여기서는 표제표와 데이터표 사이에 **표제 반복 캡션**이 끼는
    변형(서원 00131197·다수 APPR 실측)을 재현한다.
    """
    doc = (
        "<SECTION-3>"
        "<TABLE-GROUP><TITLE>이 익 잉 여 금 처 분 계 산 서</TITLE>"
        + _data(("제 31 기 2001. 01. 01부터 2001. 12. 31 까지", ""),
                ("(단위 : 원)", ""))
        + "</TABLE-GROUP>"
        "<P>이익잉여금처분계산서</P>"
        + _data(("미처분이익잉여금", "110,890"), ("이익잉여금처분액", "50,000"))
        + "</SECTION-3>"
    )
    root = etree.fromstring(doc.encode())
    data_tbl = root.findall("TABLE")[-1]
    decl = declaration_text(data_tbl) or inherited_declaration_text(data_tbl)
    assert decl is not None, "표제 반복 캡션에 막혀 단위 선언을 못 찾았다"
    assert "원" in decl


def test_chained_bare_markers_both_skipped():
    """★2단 연쇄 — 서원 00131197 SCE류: 표제 반복 캡션이 **두 번** 낀 변형.

    range 3→6 확장(§T4 M3)이 없으면 스킵 두 번 만에 한도(3)를 다 써 진짜 선언에
    닿지 못한다.
    """
    doc = (
        "<SECTION-3>"
        "<TABLE-GROUP><TITLE>연 결 자 본 변 동 표</TITLE>"
        + _data(("제 19 기 (2006. 01. 01 부터 2006. 12. 31 까지)", ""),
                ("(단위 : 천원)", ""))
        + "</TABLE-GROUP>"
        "<P>(3) 연결자본변동표(연결잉여금계산서)</P>"
        "<P>연 결 자 본 변 동 표</P>"
        + _data(("2006.01.01(기초자본)", "1,000,000"))
        + "</SECTION-3>"
    )
    root = etree.fromstring(doc.encode())
    data_tbl = root.findall("TABLE")[-1]
    decl = declaration_text(data_tbl) or inherited_declaration_text(data_tbl)
    assert decl is not None, "연쇄 중복 캡션에 막혀 단위 선언을 못 찾았다"
    assert "천원" in decl


def test_footnote_table_boundary_still_holds_when_no_declaration_beyond():
    """★안전판(회귀 방지) — 반복 캡션을 건너뛰어도 그 너머에 **진짜 선언이 없으면**
    여전히 None(값을 지어내지 않는다). 빈 `(단위 : )` 표제표는 doc_default 로 남아야
    맞다(§5-6 M2, 서원 00131197 SCE 원문의 실제 결과와 일치)."""
    doc = (
        "<SECTION-3>"
        "<TABLE-GROUP><TITLE>연 결 자 본 변 동 표</TITLE>"
        + _data(("제 19 기 (2006. 01. 01 부터 2006. 12. 31 까지)", ""),
                ("(단위 : )", ""))          # ★선언 자체가 빈 값(M2) — 채우면 안 된다
        + "</TABLE-GROUP>"
        "<P>(3) 연결자본변동표(연결잉여금계산서)</P>"
        + _data(("2006.01.01(기초자본)", "1,000,000"))
        + "</SECTION-3>"
    )
    root = etree.fromstring(doc.encode())
    data_tbl = root.findall("TABLE")[-1]
    decl = declaration_text(data_tbl) or inherited_declaration_text(data_tbl)
    assert decl is None, "빈 단위선언인데도 뭔가를 찾아버렸다 — M2 를 M3 로 오염시켰다"


def test_bare_marker_skip_does_not_cross_into_unrelated_real_content():
    """★안전판(LVMC 류 회귀 방지) — 중복 캡션 너머가 **다른 재무제표의 진짜 표제+단위
    조합**이면, 그 표제엔 자간벌림이 없는 한(§본문 주석) 여전히 멈춰야 한다. 이 안전판은
    `_is_bare_structural_marker` 가 "이름만 있고 다른 정보가 전혀 없을 때만" True 를
    반환하도록 좁게 설계된 것으로 보장된다(위 `test_title_with_extra_content_is_not_a_bare_marker`)."""
    from fin2.extract.statement_titles import _is_bare_structural_marker as marker
    # 실제 표제+기간+단위가 합쳐진 텍스트는 "bare"가 아니다 — 그대로 정지 대상.
    assert marker("현금흐름표제39기2020.01.01부터2020.12.31까지(단위:원)") is False
