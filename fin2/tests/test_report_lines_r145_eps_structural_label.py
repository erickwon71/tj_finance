"""R145 — EPS 행 판정을 `"주당"` 부분문자열에서 구조 패턴(A∪B∪C)으로 교체.

설계: `docs/plans/eps_label_structural_rule_r145_design_2026-09-19.md`
선행: R144(EPS 이중전사), R27(값크기 게이트), R28(K-GAAP 헤드라인 curated 키)

핵심 주장 셋을 고정한다.
  1. 함정 라벨(`지배주주당기순이익` 류 = 지배+주주+당기순이익)은 **총액으로 본류에**
     남는다 — R27 이 "라벨로는 원리적 구분 불가"라 한 지점.
  2. 진짜 EPS(`보통주주당이익` 등)는 여전히 EPS 경로로 간다.
  3. EPS 섹션 헤더가 **없는** 표에서도 라벨 구조만으로 EPS 가 인정된다(실측 0.68%).
"""
from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.report_lines import (  # noqa: E402
    _emit_section_lines, _indent_stack_paths, _is_eps_label)


def _run(xml: str, *, fy: int = 2020, period: str = "FY", unit: int = 1):
    out: list = []
    _emit_section_lines(
        "IS_C", [(etree.fromstring(xml), unit, None)], emit=out.append,
        corp_code="TESTCORP", rcept_no="R145-0000000001",
        report_fiscal_year=fy, report_fiscal_period=period,
        doc_default_unit=(None, None), section_unit_cache={})
    return out


def _eps(rows):
    return [l for l in rows if l.source_ref.startswith("eps/")]


def _body(rows):
    return [l for l in rows if not l.source_ref.startswith("eps/")]


# ---------------------------------------------------------------- label rule

def test_ni_attribution_trap_is_not_eps():
    """`지배주주당기순이익` = 지배+주주+당기순이익. `주당` 부분문자열이 우연히 생긴
    **총액**이라 EPS 가 아니다 — R27 이 구분 불가라고 결론낸 바로 그 쌍."""
    for trap in ("지배주주당기순이익", "비지배주주당기순이익",
                 "지배기업주주당기순이익(손실)"):
        assert not _is_eps_label(trap, section_path=None, report_fiscal_year=2020), trap


def test_real_eps_labels_are_eps():
    for good in ("보통주주당이익", "기본주당이익", "희석주당이익",
                 "기본주당기순이익", "주당순손실", "기본보통주당순이익 주석37>",
                 "계속영업기본주당이익(손실)"):
        assert _is_eps_label(good, section_path=None, report_fiscal_year=2020), good


def test_spaced_out_label_still_matches():
    """옛 강조체가 글자마다 공백을 넣는다(R111) — 자간 공백 제거 후 매칭."""
    assert _is_eps_label("기 본 주 당 순 이 익", section_path=None,
                         report_fiscal_year=2020)


def test_label_without_주당_is_never_eps():
    assert not _is_eps_label("당기순이익", section_path="XV. 주당이익",
                             report_fiscal_year=2020)


def test_section_context_rescues_ambiguous_label():
    """C — 라벨 구조로는 못 가르는 `주당+기순이익` 형태도 EPS 절 안이면 EPS."""
    assert _is_eps_label("우선주당기순이익", section_path="XV. 주당이익(단위:원)",
                         report_fiscal_year=2020)
    assert not _is_eps_label("우선주당기순이익", section_path="당기순이익의 귀속",
                             report_fiscal_year=2020)


def test_section_context_matches_anywhere_in_chain():
    """말단이 아니라 **체인 전체**를 본다 — `주당이익(단위 : 원)>계속영업` 류가
    흔해서 말단만 보면 97.54%, 체인 전체면 98.89%(설계문서 §6-2)."""
    assert _is_eps_label("우선주당기순이익",
                         section_path="주당이익(단위 : 원)>계속영업",
                         report_fiscal_year=2020)


def test_pre2015_keeps_legacy_substring_behaviour():
    """pre-2015 에 적용하면 진짜 EPS 1,834행 회귀 + K-GAAP 블럽 11,519행 오염
    (설계문서 §4) — 경계 아래에서는 기존 `"주당"` 부분문자열 동작을 그대로 둔다."""
    assert _is_eps_label("지배주주당기순이익", section_path=None,
                         report_fiscal_year=2014)
    assert not _is_eps_label("지배주주당기순이익", section_path=None,
                             report_fiscal_year=2015)


# ------------------------------------------------------------- section paths

def test_indent_stack_builds_ancestor_chain():
    paths = _indent_stack_paths([(0, "당기순이익의 귀속"), (2, "지배주주"), (2, "비지배")])
    assert paths == [None, "당기순이익의 귀속", "당기순이익의 귀속"]


def test_indent_stack_is_not_a_one_way_latch():
    """R144 의 `in_eps_section` 은 한 번 True 면 유지되는 래치라, 총액 섹션이 EPS
    섹션 **뒤**에 오는 표에서 총액을 EPS 로 오판했다. 스택은 그렇지 않다."""
    paths = _indent_stack_paths(
        [(0, "XV. 주당이익"), (2, "기본주당이익"), (0, "당기순이익의 귀속"), (2, "지배주주")])
    assert paths[1] == "XV. 주당이익"
    assert paths[3] == "당기순이익의 귀속"      # EPS 절이 앞에 있어도 새지 않는다


# ------------------------------------------------------------------ end-to-end

_TRAP_TABLE = """<TABLE>
<TR><TD>당기순이익</TD><TD>616,201</TD></TR>
<TR><TD>당기순이익(손실)의 귀속</TD><TD></TD></TR>
<TR><TD>  지배기업주주당기순이익(손실)</TD><TD>270,700</TD></TR>
<TR><TD>  비지배지분당기순이익(손실)</TD><TD>345,501</TD></TR>
<TR><TD>XV. 주당이익(단위:원)</TD><TD></TD></TR>
<TR><TD>  기본주당이익</TD><TD>3,839</TD></TR>
</TABLE>"""


def test_trap_row_stays_in_body_with_table_unit():
    """★핵심 회귀 — 백만원 표에서 함정 행이 EPS 로 새면 값이 10⁶배 틀리고 총액이
    제 섹션에서 유실된다(실측: 00160588 20170515004474 연결IS)."""
    rows = _run(_TRAP_TABLE, unit=1_000_000)
    trap = [l for l in rows if l.label_raw.strip() == "지배기업주주당기순이익(손실)"]
    assert len(trap) == 1, trap
    assert trap[0].source_ref.startswith("IS_C/"), trap[0].source_ref
    assert trap[0].value_won == 270_700 * 1_000_000
    assert trap[0].section_path == "당기순이익(손실)의 귀속"


def test_real_eps_keeps_won_unit_in_million_table():
    rows = _run(_TRAP_TABLE, unit=1_000_000)
    eps = [l for l in _eps(rows) if l.label_raw.strip() == "기본주당이익"]
    assert len(eps) == 1, eps
    assert eps[0].value_won == 3_839          # 원/주 — 표 단위를 곱하지 않는다
    assert eps[0].adecimal == 0


def test_eps_row_carries_real_section_path_not_constant():
    """R145 — 하드코딩 `'주당손익'` 대신 원문 조상 체인. 판정 근거가 DB 에 남는다."""
    rows = _run(_TRAP_TABLE, unit=1_000_000)
    eps = [l for l in _eps(rows) if l.label_raw.strip() == "기본주당이익"]
    assert eps[0].section_path == "XV. 주당이익(단위:원)"
    assert all(l.section_path != "주당손익" for l in _eps(rows))


def test_ni_total_not_lost_when_eps_present():
    """EPS 중복제거가 총액을 삼키면 안 된다(R144 에서 한 번 밟은 지뢰)."""
    rows = _run(_TRAP_TABLE, unit=1_000_000)
    labels = {l.label_raw.strip() for l in _body(rows)}
    assert "당기순이익" in labels
    assert "지배기업주주당기순이익(손실)" in labels
    assert "비지배지분당기순이익(손실)" in labels


def test_eps_without_any_section_header():
    """실측 0.68% — EPS 섹션 헤더도 단위 선언도 없이 EPS 행만 있는 서식(설계문서
    §6-2). `C` 를 **필수**로 걸면 이 행들이 유실된다 — `A∪B` 로 구제돼야 한다."""
    rows = _run("<TABLE>"
                "<TR><TD>당기순이익</TD><TD>1,000</TD></TR>"
                "<TR><TD>기본주당순손익</TD><TD>582</TD></TR>"
                "</TABLE>", unit=1_000_000)
    eps = _eps(rows)
    assert len(eps) == 1, rows
    assert eps[0].label_raw.strip() == "기본주당순손익"
    assert eps[0].value_won == 582
    assert eps[0].section_path is None       # 헤더가 없으니 경로도 없다


def test_no_duplicate_emission_across_paths():
    """R144 본체 — 같은 행이 두 경로로 각각 담기면 안 된다."""
    rows = _run(_TRAP_TABLE, unit=1_000_000)
    keys = [(l.label_raw.strip(), l.col_index) for l in rows]
    assert len(keys) == len(set(keys)), keys


# ------------------------------------------------- D: 섹션 없는 표의 최상위 행

def test_d_toplevel_row_in_headerless_table_is_eps():
    """D(사용자 제안 2026-09-19) — EPS 절 제목이 없는 표에서는 **최상위** `주당` 행을
    EPS 로 인정한다. 실측: 섹션 없는 서식은 EPS 가 총포괄손익류 바로 뒤 최상위로
    붙는다(10개사 41행 전부)."""
    kw = dict(section_path=None, report_fiscal_year=2020,
              prev_toplevel_label="Ⅸ. 당기총포괄이익")
    assert _is_eps_label("주당순부가가치", table_has_eps_header=False, **kw)
    # 헤더가 있는 표에서는 D 를 안 쓴다 → A∪B∪C 로만 판정(이 라벨은 전부 불성립)
    assert not _is_eps_label("주당순부가가치", table_has_eps_header=True, **kw)


def test_d_does_not_rescue_indented_total_rows():
    """함정(총액)은 예외 없이 들여쓰기된 귀속 절 안에 있다 — 최상위가 아니라 D 밖이다.
    실측: 2015+ A∪B 거부 라벨 보유 필링 80건 전수에서 '헤더 없음+최상위' 0건."""
    assert not _is_eps_label("지배기업주주당기순이익(손실)",
                             section_path="당기순이익(손실)의 귀속",
                             report_fiscal_year=2020, table_has_eps_header=False,
                             prev_toplevel_label="당기순이익(손실)의 귀속")


def test_d_anchor_must_be_comprehensive_income():
    """★앵커가 `당기순이익` 이면 D 가 걸리면 안 된다 — 걸리면 최상위로 놓인
    `지배주주당기순이익` 총액을 EPS 로 삼켜 본류에서 유실시킨다."""
    assert not _is_eps_label("지배주주당기순이익", section_path=None,
                             report_fiscal_year=2020, table_has_eps_header=False,
                             prev_toplevel_label="당기순이익")
    assert not _is_eps_label("지배주주당기순이익", section_path=None,
                             report_fiscal_year=2020, table_has_eps_header=False,
                             prev_toplevel_label=None)   # 앵커 자체가 없는 표


def test_d_has_no_effect_before_2015():
    """pre-2015 는 literal `"주당"` 부분문자열 그대로라 `D` 가 결과를 못 바꾼다 —
    `table_has_eps_header` 를 뒤집어도 판정이 동일해야 한다(경계 아래 무변경)."""
    for label in ("주당순부가가치", "지배주주당기순이익", "기본주당이익", "당기순이익"):
        a = _is_eps_label(label, section_path=None, report_fiscal_year=2014,
                          table_has_eps_header=False,
                          prev_toplevel_label="Ⅸ. 당기총포괄이익")
        b = _is_eps_label(label, section_path=None, report_fiscal_year=2014,
                          table_has_eps_header=True,
                          prev_toplevel_label="Ⅸ. 당기총포괄이익")
        assert a == b == ("주당" in label), (label, a, b)


_HEADERLESS_TABLE = """<TABLE>
<TR><TD>Ⅸ. 당기총포괄이익</TD><TD>(294,382,602)</TD></TR>
<TR><TD>Ⅹ. 주당손익</TD><TD>(7)</TD></TR>
<TR><TD>기본 및 희석주당순이익</TD><TD>(7)</TD></TR>
</TABLE>"""


def test_headerless_table_keeps_both_sibling_rows():
    """GMI벤처 실측 — 절 제목행과 항목행이 **같은 레벨**에 금액을 각각 달고 있다.
    계층2 는 충실전사라 둘 다 보존한다(중복 판단은 계층3 몫, R1)."""
    rows = _run(_HEADERLESS_TABLE, unit=1_000_000)
    eps = {l.label_raw.strip(): l.value_won for l in _eps(rows) if l.col_index == 0}
    assert eps == {"Ⅹ. 주당손익": -7, "기본 및 희석주당순이익": -7}, eps
    # 총포괄이익은 본류에 표 단위로 남는다
    tot = [l for l in _body(rows) if l.label_raw.strip() == "Ⅸ. 당기총포괄이익"]
    assert len(tot) == 1 and tot[0].value_won == -294_382_602 * 1_000_000


def test_d_row_does_not_duplicate_into_body():
    """★D 로 걸린 행도 `eps_labels` 에 들어가야 한다 — 안 그러면 본류가 한 번 더 담아
    ×10⁶ 유령행이 생긴다(R144 가 밟은 지뢰)."""
    rows = _run("<TABLE>"
                "<TR><TD>Ⅸ. 당기총포괄이익</TD><TD>(294,382,602)</TD></TR>"
                "<TR><TD>주당순부가가치</TD><TD>(7)</TD></TR>"
                "</TABLE>", unit=1_000_000)
    hit = [l for l in rows if l.label_raw.strip() == "주당순부가가치"]
    assert len(hit) == 1, [(l.source_ref, l.value_won) for l in hit]
    assert hit[0].source_ref.startswith("eps/")
    assert hit[0].value_won == -7
