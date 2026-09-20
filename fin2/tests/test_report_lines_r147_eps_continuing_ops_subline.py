"""R147 — EPS 자식행(계속영업/중단영업 세부이익)이 라벨에 `주당` 이 없어 통째로
결측되던 결함.

설계·근거: `docs/qa/eps_continuing_ops_subline_gap_r147_2026-09-20.md`
발견 경위: 계층2 원문대조 캠페인(camp_run 워크트리)이 두산에너빌리티 5건에서
[연결] 손익계산서 EPS 세부항목 4개(기본/희석 × 계속영업/중단영업) 결측을 반복 발견.
선행: R144(EPS 이중전사 방지), R145(EPS 구조 판정 A∪B∪C∪D).

핵심 주장:
  1. `기본주당이익(손실) (단위 : 원)` 아래 중첩된 `계속영업이익(손실) (단위 : 원)`/
     `중단영업이익(손실) (단위 : 원)` 은 라벨 자체에 `주당` 이 없어도 EPS 로 인정된다
     — 조상 체인이 EPS 절이고(`C`) 원(₩)을 스스로 선언했으면(`E`).
  2. 같은 라벨의 **본문**(EPS 절 밖) 행(`계속영업이익(손실)` 총액, 억원대)은 여전히
     EPS 로 오판되지 않는다 — 원(₩) 선언이 없기 때문.
  3. 희석 쪽에도 같은 라벨이 반복돼도(원문 관행) 둘 다 개별 보존된다(R1, dedup 없음).
"""
from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.report_lines import (  # noqa: E402
    _emit_section_lines, _is_eps_label)


def _run(xml: str, *, fy: int = 2019, period: str = "Q3", unit: int = 1):
    out: list = []
    _emit_section_lines(
        "IS_C", [(etree.fromstring(xml), unit, None)], emit=out.append,
        corp_code="TESTCORP", rcept_no="R147-0000000001",
        report_fiscal_year=fy, report_fiscal_period=period,
        doc_default_unit=(None, None), section_unit_cache={})
    return out


def _eps(rows):
    return [l for l in rows if l.source_ref.startswith("eps/")]


def _body(rows):
    return [l for l in rows if not l.source_ref.startswith("eps/")]


# --------------------------------------------------------------- label rule

def test_eps_child_without_judang_substring_is_eps_when_declared_and_nested():
    """`E` — 조상 체인이 EPS 절이고 원(₩) 을 스스로 선언했으면 `주당` 없이도 EPS."""
    assert _is_eps_label(
        "계속영업이익(손실) (단위 : 원)",
        section_path="지배기업 소유주지분 주당손익>기본주당이익(손실) (단위 : 원)",
        report_fiscal_year=2019)
    assert _is_eps_label(
        "중단영업이익(손실) (단위 : 원)",
        section_path="지배기업 소유주지분 주당손익>희석주당이익(손실) (단위 : 원)",
        report_fiscal_year=2019)


def test_eps_child_without_judang_and_without_section_is_not_eps():
    """본문 손익계산서의 진짜 `계속영업이익(손실)` 총액 행 — EPS 절 밖이라 `E` 불성립."""
    assert not _is_eps_label(
        "계속영업이익(손실)", section_path=None, report_fiscal_year=2019)
    assert not _is_eps_label(
        "중단영업이익(손실)", section_path="당기순이익(손실)의 귀속",
        report_fiscal_year=2019)


def test_eps_section_without_won_declaration_does_not_rescue_unlabeled_child():
    """`C` 단독 인정 안 함(R145 원 원칙 유지) — EPS 절 안이어도 원(₩) 선언이 없는
    자식(예: 가중평균유통보통주식수, 단위 '주')은 여전히 `주당` 없이는 EPS 아님."""
    assert not _is_eps_label(
        "가중평균유통보통주식수 (단위 : 주)",
        section_path="지배기업 소유주지분 주당손익>기본주당이익(손실) (단위 : 원)",
        report_fiscal_year=2019)


def test_e_has_no_effect_before_2015():
    """pre-2015 는 literal `"주당"` 부분문자열 그대로 — `E` 는 2015+ 전용."""
    assert not _is_eps_label(
        "계속영업이익(손실) (단위 : 원)",
        section_path="주당손익>기본주당이익(손실) (단위 : 원)",
        report_fiscal_year=2014)


# ------------------------------------------------------------------ end-to-end

# 두산에너빌리티 20191114002511 [연결] IS EPS 블록 축약 재현(값은 원문 그대로).
_DOOSAN_EPS_TABLE = """<TABLE>
<TR><TD>지배기업 소유주지분 주당손익</TD><TD></TD></TR>
<TR><TD>　기본주당이익(손실) (단위 : 원)</TD><TD>(699)</TD></TR>
<TR><TD>　　계속영업이익(손실) (단위 : 원)</TD><TD>(786)</TD></TR>
<TR><TD>　　중단영업이익(손실) (단위 : 원)</TD><TD>87</TD></TR>
<TR><TD>　희석주당이익(손실) (단위 : 원)</TD><TD>(699)</TD></TR>
<TR><TD>　　계속영업이익(손실) (단위 : 원)</TD><TD>(786)</TD></TR>
<TR><TD>　　중단영업이익(손실) (단위 : 원)</TD><TD>87</TD></TR>
</TABLE>"""

# 같은 종류의 라벨이 EPS 절 밖(본문)에 실제 IS 총액으로도 존재하는 표 — 오염 방지 확인.
_BODY_AND_EPS_TABLE = """<TABLE>
<TR><TD>계속영업이익(손실)</TD><TD>207,943,198,507</TD></TR>
<TR><TD>중단영업이익(손실)</TD><TD>-86,600,644,054</TD></TR>
<TR><TD>지배기업 소유주지분 주당손익</TD><TD></TD></TR>
<TR><TD>　기본주당이익(손실) (단위 : 원)</TD><TD>(699)</TD></TR>
<TR><TD>　　계속영업이익(손실) (단위 : 원)</TD><TD>(786)</TD></TR>
<TR><TD>　　중단영업이익(손실) (단위 : 원)</TD><TD>87</TD></TR>
</TABLE>"""


def test_all_six_doosan_rows_are_captured():
    """★핵심 회귀 — 원문 6행(기본/희석 × 총계/계속영업/중단영업) 전부 살아야 한다.
    수정 전엔 기본/희석 2행만 남고 나머지 4행이 통째로 결측됐다."""
    rows = _run(_DOOSAN_EPS_TABLE, unit=1)
    eps = _eps(rows)
    counts: dict[str, int] = {}
    for l in eps:
        counts[l.label_raw.strip()] = counts.get(l.label_raw.strip(), 0) + 1
    assert counts.get("기본주당이익(손실) (단위 : 원)") == 1
    assert counts.get("희석주당이익(손실) (단위 : 원)") == 1
    # 계속영업/중단영업은 기본·희석 양쪽 부모에 각각 한 번씩 나타나 원문 그대로 2번씩.
    assert counts.get("계속영업이익(손실) (단위 : 원)") == 2
    assert counts.get("중단영업이익(손실) (단위 : 원)") == 2
    values = {(l.label_raw.strip(), l.section_path): l.value_won for l in eps}
    assert values[("계속영업이익(손실) (단위 : 원)",
                   "지배기업 소유주지분 주당손익>기본주당이익(손실) (단위 : 원)")] == -786
    assert values[("중단영업이익(손실) (단위 : 원)",
                   "지배기업 소유주지분 주당손익>희석주당이익(손실) (단위 : 원)")] == 87


def test_body_totals_are_not_swallowed_into_eps():
    """★함정 방지 — EPS 절 밖의 진짜 손익계산서 총액(억원대, 원(₩) 선언 없음)은
    여전히 본류에 남는다. `E` 가 본문 행까지 삼키면 총액이 유실된다."""
    rows = _run(_BODY_AND_EPS_TABLE, unit=1)
    body_labels = {l.label_raw.strip(): l.value_won for l in _body(rows)}
    assert body_labels["계속영업이익(손실)"] == 207_943_198_507
    assert body_labels["중단영업이익(손실)"] == -86_600_644_054
    # EPS 쪽 세부행은 여전히 원/주 그대로 살아 있다.
    eps_labels = {l.label_raw.strip() for l in _eps(rows)}
    assert "계속영업이익(손실) (단위 : 원)" in eps_labels
    assert "중단영업이익(손실) (단위 : 원)" in eps_labels


def test_no_duplicate_emission_across_paths_r147():
    """R144 본체 — 새 자식행도 두 경로에 중복으로 담기면 안 된다."""
    rows = _run(_DOOSAN_EPS_TABLE, unit=1)
    keys = [(l.label_raw.strip(), l.section_path, l.col_index) for l in rows]
    assert len(keys) == len(set(keys)), keys
