"""R157·R158(2026-09-22) 회귀 테스트 — 소수 표기 금액의 두 가지 결함.

## R157 — 소수부를 **단위 배수 적용 전에** 버렸다

`parse_amount()` 가 `int(float(s))` 로 소수부를 잘라낸 뒤 배수를 곱했다. 그래서
단위가 선언된 표에서 소수부만큼이 조용히 사라졌다:

    '1,234.5' 백만원 → 1,234,000,000  (정확값 1,234,500,000)
    '0.5'     백만원 → 0              ← 값이 통째로 사라진다

결측이 아니라 **값 왜곡**이라 기존 검산이 못 잡는다. 배수를 먼저 적용하고
ROUND_HALF_UP 으로 반올림한다. 배수 1 인 EPS 소수('69.0'·'343.0')는 결과 불변.

## R158 — 천단위 구분자가 **마침표**로 깨진 셀

캠페인 이슈#22(엘에스일렉트릭 20260318001243). 재무제표 셀의 콤마 하나가 마침표로
렌더돼 소수점처럼 보이고, 그걸 소수로 읽으면 값이 10³~10⁶ 배 작아진다.

결정적 증거 — 트리니티항공 20260515001132 은 **같은 값**이 연결 표엔
`'41,106,779.959'`, 별도 표엔 `'41,106,779,959'` 로 찍혔다. 코오롱 20260515002605
은 한 행 안에 나란히 있다: `'393,211,876'`, `'393,211.866'`.

★복원은 추측이 아니다 — 정확한 값이 **같은 행 다른 칸에 정수로** 들어 있고, 그
자릿수만 가져온다. 짝이 없으면 손대지 않는다(주당손익처럼 원 단위 소수가 정상인
값 보호).

★두 추출 경로 **모두**에 적용해야 한다 — `extract_rows`(BS/IS/CF)와
`report_lines.py` 의 SCE 그리드 경로. 처음에 전자만 고쳤더니 SCE 는 왜곡값이 그대로
남았다(R144/R153 의 교훈: 같은 판정을 두 경로가 각자 하면 갈린다).

실행: pytest fin2/tests/test_r157_r158_dot_grouped_amounts.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest                                                      # noqa: E402

from parser.common.amount_normalizer import parse_amount           # noqa: E402
from parser.xml.table_extractor import (                           # noqa: E402
    _repair_dot_grouped_cells as repair,
    _SOURCE_TYPO_CELL_FIXES, apply_source_typo_fixes,
    unresolved_dot_cell_indices as unresolved,
)
from fin2.extract.report_lines import extract_report_lines         # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_LS_2025FY = (_ROOT / "raw_report/KOSPI/00105855_엘에스일렉트릭"
                      "/annual/2025/20260318001243.xml")
_HD_SHIPBUILDING_2025Q1 = (
    _ROOT / "raw_report/KOSPI/00164830_HD한국조선해양"
            "/quarter/2025/20250515002500.xml")


# ─────────────────────────── R157 ───────────────────────────

@pytest.mark.parametrize("cell,mult,want", [
    ("1,234.5", 1_000_000, 1_234_500_000),
    ("1,234.56", 1_000, 1_234_560),
    ("0.5", 1_000_000, 500_000),            # ★종전엔 0 이었다
    ("0.5", 1_000, 500),
    ("82,196.9288", 1_000_000, 82_196_928_800),
])
def test_fraction_survives_the_unit_multiplier(cell, mult, want):
    assert parse_amount(cell, multiplier=mult) == want


@pytest.mark.parametrize("cell,want", [
    ("69.0", 69), ("(69.0)", -69), ("343.0", 343), ("213.00", 213),
])
def test_eps_decimals_are_unchanged(cell, want):
    """배수 1 인 주당손익 소수는 종전과 같은 값이어야 한다(회귀 방지)."""
    assert parse_amount(cell, multiplier=1) == want


def test_large_integers_still_avoid_float():
    """정수 경로는 float 를 거치지 않는다 — 15자리 넘는 값이 틀어지면 안 된다."""
    assert parse_amount("1,343,128,415,152", multiplier=1) == 1_343_128_415_152


def test_garbage_still_returns_none():
    for cell in ("", "-", "N/A", "가나다"):
        assert parse_amount(cell, multiplier=1) is None


# ─────────────────────────── R158 ───────────────────────────

@pytest.mark.parametrize("cells,idx,want", [
    # 정확히 일치하는 짝
    (["0", "0", "0", "(6,105.268746)", "(6,105,268,746)"], 3, "(6105268746)"),
    (["0", "0", "0", "(14.876)", "(14,876)"], 3, "(14876)"),
    # 뒤 0 이 잘린 짝 — 텍스트만으로는 배율을 못 정하고 대조로만 알 수 있다
    (["0", "0", "(7,066,808.32)", "0", "(7,066,808,320)"], 2, "(7066808320)"),
    (["0", "0", "0", "(10,590,556.9)", "(10,590,556,900)"], 3, "(10590556900)"),
    # 두 그룹이 깨진 경우
    (["0", "2,168.045996", "(2,168,045,996)"], 1, "2168045996"),
])
def test_repairs_using_the_row_s_own_integer_twin(cells, idx, want):
    assert repair(cells)[idx] == want


def test_leaves_eps_like_decimals_alone():
    """짝이 없으면 손대지 않는다 — 에스티아이 '희석당기순이익 (단위 : 원)' 실측."""
    cells = ["343.0", "343.0", "213.0", "213.00"]
    assert repair(cells) == cells


def test_leaves_cell_alone_when_no_twin_in_the_row():
    """트리니티항공 실측 — 정확한 값이 **반대 basis 표**에 있어 행 안에는 짝이 없다."""
    cells = ["107,689,488,000", "41,106,779.959", "133,785,146"]
    assert repair(cells) == cells


def test_ambiguous_twins_are_left_alone():
    """접두사가 맞는 후보가 둘 이상이면 판정불가로 둔다(R6)."""
    cells = ["(14.876)", "(14,876)", "(14,876,000)"]
    assert repair(cells) == cells


def test_rows_without_any_dot_cell_are_untouched():
    cells = ["0", "1,000", "(2,000)", ""]
    assert repair(cells) is cells or repair(cells) == cells


# ──────────────────── 실제 필링 원문 대조 ─────────────────────

@pytest.mark.skipif(not _LS_2025FY.exists(), reason="원문 XML 없음")
def test_ls_electric_sce_values_match_the_source():
    """캠페인 이슈#22 — 별도 SCE 6개 셀이 원문 값으로 복원되고 왜곡값이 안 남는지.

    ★SCE 는 `extract_rows` 가 아니라 report_lines 의 그리드 경로를 타므로, 이
      테스트가 그 경로의 배선까지 같이 지킨다.
    """
    lines = extract_report_lines(
        str(_LS_2025FY), rcept_no="20260318001243", corp_code="00105855",
        report_fiscal_year=2025, report_fiscal_period="FY")
    got = {l.value_won for l in lines
           if l.statement == "SCE" and l.basis == "separate"}
    for want in (-82_196_928_800, 213_382_825_983, -6_105_268_746,
                 -86_133_656_900, 293_824_766_256, -5_999_574_561):
        assert want in got, want
    # 10⁻⁶ 로 깎인 값이 하나도 남지 않아야 한다
    for bad in (-82_196, -86_133, 213_382, -6_105, 293_824, -5_999):
        assert bad not in got, bad


@pytest.mark.skipif(not _HD_SHIPBUILDING_2025Q1.exists(), reason="원문 XML 없음")
def test_hd_shipbuilding_nci_values_match_the_source():
    """R159 — HD한국조선해양 20250515002500 연결SCE 비지배지분 3셀.

    사용자가 DART 원문을 직접 확인해 콤마 오타로 확정했다(2026-09-23).
    복원값은 그 행 자신의 항등식으로도 검산된다 —
    지배기업 소유주지분 합계 + 비지배지분 = 자본 총계 합계.
    """
    lines = extract_report_lines(
        str(_HD_SHIPBUILDING_2025Q1), rcept_no="20250515002500",
        corp_code="00164830", report_fiscal_year=2025,
        report_fiscal_period="Q1")
    got = {l.value_won for l in lines
           if l.statement == "SCE" and l.basis == "consolidated"}
    for want in (-41_423_000, -1_259_803_000, 3_082_923_000):
        assert want in got, want
    # 10⁻³ 로 깎인 소수-오독값이 하나도 남지 않아야 한다
    for bad in (-41, -1_259, 3_082):
        assert bad not in got, bad


def test_both_extraction_paths_are_wired():
    """상수·함수명이 바뀌면 조용히 깨지므로 배선 자체를 소스에서 확인한다."""
    te = (_ROOT / "parser/xml/table_extractor.py").read_text(encoding="utf-8")
    rl = (_ROOT / "fin2/extract/report_lines.py").read_text(encoding="utf-8")
    # ★라벨 인자까지 넘기는지 확인한다 — 안 넘기면 EPS 가드가 조용히 무력화된다.
    assert "_repair_dot_grouped_cells(amount_cells, label)" in te
    assert "_repair_dot_grouped_cells(raw_amounts, label)" in rl


# ─────────────────── R158 EPS 가드 · R159 원문 오타 교정 ───────────────────

def test_eps_rows_are_skipped_by_label():
    """★주당손익 행은 라벨로 배제한다 — 짝처럼 보이는 배치가 실제로 나온다.

    실측(핸즈코퍼레이션 20260515002776 연결IS): `'(1,500.00)'` 과 `'(1,500)'` 이 한
    행에 있다. 자릿수가 하나만 달라지면 EPS 를 1,500,000 으로 **날조**한다.
    """
    cells = ["(1,500.00)", "(1,500,000)"]
    assert repair(cells, "계속영업 기본주당순손실 (단위 : 원)") == cells
    # 라벨이 없으면(구 호출부) 종전 동작 — 가드는 라벨을 줄 때만 작동한다
    assert repair(list(cells)) != cells


def test_non_eps_rows_still_repaired_with_label():
    cells = ["0", "(42,549.493)", "(42,549,493)"]
    assert repair(cells, "확정급여제도의 재측정손익")[1] == "(42549493)"


def test_source_typo_fix_applies_only_to_listed_rcept():
    """R159 — rcept 예외목록에 등재된 셀만 교정한다."""
    cells = ["10,937,873.5", "92,662,328,851"]
    fixed = apply_source_typo_fixes(cells, "20260515002776")
    assert fixed[0] == "10,937,873,500"
    assert fixed[1] == "92,662,328,851"
    # 다른 필링·rcept 없음이면 손대지 않는다
    assert apply_source_typo_fixes(cells, "99999999999999") == cells
    assert apply_source_typo_fixes(cells, None) == cells


def test_source_typo_fix_hanwha_investment_missing_digit():
    """검증 이슈 #84907 — 콤마 그룹핑 결손("27" 그룹이 2자리)으로 자릿수 하나가

    통째로 빠졌다(dot-typo 계열이 아니라 comma-grouping 계열이지만 같은 예외목록
    메커니즘으로 교정한다 — 등재 조건은 정정값이 원문 다른 곳에 인쇄돼 있는지일 뿐,
    깨짐의 형태는 무관하다).
    """
    cells = ["I. 영업수익", "637,930,27,772", "598,928,031,581"]
    fixed = apply_source_typo_fixes(cells, "20180515001426")
    assert fixed[1] == "637,930,827,772"
    assert fixed[2] == "598,928,031,581"          # 다른 셀은 그대로
    assert apply_source_typo_fixes(cells, "20180515002604") == cells  # 정정신고 rcept엔 미적용


def test_source_typo_fix_samsung_ena_dot_plus_digit_typo():
    """검증 이슈 #18060/#18208 — 마침표 오타에 숫자 하나까지 틀린 칸('278.632').

    R158 행 안 정수 짝(숫자열 불일치)도 R160 이 먼저 결측 처리하므로, 예외목록이
    유일한 복원 경로다. 원본·기재정정 두 rcept 모두 등재돼야 한다.
    """
    cells = ["0", "633,492,278.632", "0", "633,492,277,632"]
    for rcept in ("20240313000522", "20240314001768"):
        fixed = apply_source_typo_fixes(cells, rcept)
        assert fixed[1] == "633,492,277,632"
        assert unresolved(fixed, "당기순이익(손실)") == []
    # 등재 전(다른 rcept)엔 R160 결측 대상 그대로
    assert unresolved(cells, "당기순이익(손실)") == [1]


def test_typo_fix_entries_carry_a_reason_comment():
    """등재 조건: 정정값이 원문 다른 곳에 인쇄돼 있을 때만. 근거 주석을 강제한다.

    ★dict **리터럴 영역**만 잘라서 본다 — 초판은 함수 본문을 보고 있어서(같은 이름이
      네 번 나온다) 우연히 통과했다. 항목을 추가했을 때 비로소 드러났다.
    """
    te = (_ROOT / "parser/xml/table_extractor.py").read_text(encoding="utf-8")
    head = "_SOURCE_TYPO_CELL_FIXES = {"
    assert head in te
    block = te.split(head, 1)[1].split("\n}", 1)[0]
    for (rcept, _cell) in _SOURCE_TYPO_CELL_FIXES:
        assert rcept in block, f"{rcept} 항목에 근거 주석이 없다"
        # 근거는 "원문 어디에 정수로 있다"를 밝혀야 한다 — 값만 적고 넘어가는 것 방지
        assert "→" in block or "->" in block, "근거에 정정 출처 표기가 없다"


def test_typo_fix_is_wired_into_both_paths():
    te = (_ROOT / "parser/xml/table_extractor.py").read_text(encoding="utf-8")
    rl = (_ROOT / "fin2/extract/report_lines.py").read_text(encoding="utf-8")
    assert "apply_source_typo_fixes(amount_cells, rcept_no)" in te
    assert "apply_source_typo_fixes(raw_amounts, rcept_no)" in rl
    # 오타 교정이 **복원보다 먼저** 와야 한다(교정 후엔 정상 정수라 복원 대상 아님)
    assert te.index("apply_source_typo_fixes(amount_cells") < \
        te.index("_repair_dot_grouped_cells(amount_cells")
    assert rl.index("apply_source_typo_fixes(raw_amounts") < \
        rl.index("_repair_dot_grouped_cells(raw_amounts")


# ───────────── R160 미해결 마침표 셀은 적재하지 않는다 ─────────────

def test_unresolved_dot_cell_is_reported_not_stored():
    """★사용자 정책(2026-09-22): 담지도 반올림하지도 말고 결측으로 남긴다."""
    assert unresolved(["0", "41,106,779.959", "133,785,146"], "기말자본") == [1]


def test_unit_declaration_is_not_an_exception():
    """★B안 — 천원/백만원 선언 표라고 예외를 두지 않는다.

    초판은 `multiplier != 1` 을 "소수가 정상 표기"라며 제외했는데, 그건 **관측 없이
    단정한** 것이었다(전수 스캔 32셀 전부 단위 '원', 천원/백만원 표의 소수는 0건).
    시그니처에서 multiplier 를 아예 없애 실수로 예외가 생기지 않게 했다.
    """
    import inspect
    assert "multiplier" not in inspect.signature(unresolved).parameters


def test_eps_rows_are_never_nulled():
    """주당손익 소수는 정상이므로 결측으로 만들지 않는다."""
    assert unresolved(["343.0", "213.00"], "희석당기순이익 (단위 : 원)") == []
    assert unresolved(["(1,500.00)", "(1,500)"], "계속영업 기본주당순손실") == []


def test_resolved_cells_are_not_nulled():
    """R159/R158 이 해결한 셀은 정상 정수 텍스트라 이 패턴에 안 걸린다."""
    assert unresolved(["0", "41,106,779,959", "133,785,146"], "기말자본") == []


def test_nulling_is_wired_into_both_paths():
    te = (_ROOT / "parser/xml/table_extractor.py").read_text(encoding="utf-8")
    rl = (_ROOT / "fin2/extract/report_lines.py").read_text(encoding="utf-8")
    assert "unresolved_dot_cell_indices(amount_cells, label)" in te
    assert "unresolved_dot_cell_indices(raw_amounts, label)" in rl
