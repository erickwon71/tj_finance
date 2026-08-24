"""
버그#2(dividends_paid 부호) 수정 회귀 테스트.

docs/plans/gate_b_bug2_xbrl_inline_overlay_design_2026-08-13.md §6-2 재현 —
LG(00120021) 원문(rcept 20260318001025)에서 별도기준 CF "배당금의 지급"이 텍스트
추출로는 양수(버그)였다가 오버레이 적용 후 report_won과 정확히 일치하는 음수가
되는지 확인한다. 순수 목 테스트(§2)는 `overlay_dividends_paid_sign()` 자체의
안전장치(모호하면 손대지 않음)를 검증한다.

실행: python -m fin2.tests.test_report_lines_inline_xbrl_overlay
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.report_lines import extract_report_lines  # noqa: E402
from fin2.extract.report_lines_inline_xbrl_overlay import (  # noqa: E402
    overlay_dividends_paid_sign,
    overlay_tax_expense_value,
)

_LG = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00120021_LG/annual/2025/20260318001025.xml"
)

_GUKIL_PAPER = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSDAQ/00104573_국일제지/quarter/2025/20251113000801.xml"
)


# --- §1: 실측 파일 재현(LG, 설계문서 §6-2) -----------------------------------

def test_lg_separate_dividends_paid_sign_corrected():
    """LG 별도기준 CF '배당금의 지급'이 텍스트추출(양수, 버그)에서 -632,384,000,000
    (report_won과 정확 일치)으로 오버레이된다."""
    if not _LG.exists():
        return
    lines = extract_report_lines(
        _LG, rcept_no="20260318001025", corp_code="00120021",
        report_fiscal_year=2025, report_fiscal_period="FY",
    )
    row = next(l for l in lines if l.statement == "CF" and l.basis == "separate"
               and l.col_index == 0 and l.label_raw == "배당금의 지급")
    assert row.value_won == -632_384_000_000
    assert row.source_ref.endswith(";xbrl_inline_override")


def test_lg_consolidated_dividends_paid_untouched_when_no_fact_match():
    """연결기준은 이 필링에 매칭되는 표준개념 fact가 없어 원래 텍스트값(양수) 그대로
    남는다 — 근거 없이 부호를 뒤집지 않는다(설계 §5 블랭킷 금지)."""
    if not _LG.exists():
        return
    lines = extract_report_lines(
        _LG, rcept_no="20260318001025", corp_code="00120021",
        report_fiscal_year=2025, report_fiscal_period="FY",
    )
    row = next(l for l in lines if l.statement == "CF" and l.basis == "consolidated"
               and l.col_index == 0 and l.label_raw == "배당금의 지급")
    assert row.value_won == 745_599_000_000
    assert row.source_ref is None or not row.source_ref.endswith(";xbrl_inline_override")


# --- §2: overlay_dividends_paid_sign() 자체의 안전장치(순수 목) ------------------

@dataclass
class _FakeRow:
    statement: str
    basis: str
    col_index: int
    is_cumulative: bool
    label_raw: str
    value_won: int | None
    source_ref: str | None = None


@dataclass
class _FakeFact:
    canonical: str
    statement: str
    basis: str
    is_cumulative: bool
    amount_won: int


def test_overlay_pre2024_is_noop_without_reading_file():
    """report_fiscal_year < 2024 는 파일을 열지 않고 즉시 0(no-op) — 설계 §5 근거
    (커버리지 절벽 실측)에 맞춘 백필 비용 절감."""
    rows = [_FakeRow("CF", "separate", 0, False, "배당금의 지급", 1000)]
    n = overlay_dividends_paid_sign(rows, "/nonexistent/path.xml", 2023)
    assert n == 0
    assert rows[0].value_won == 1000


def test_overlay_ambiguous_two_candidate_rows_untouched(monkeypatch):
    """같은 (basis, is_cumulative) 에 후보 텍스트행이 2개면(모호) 손대지 않는다."""
    import fin2.extract.report_lines_inline_xbrl_overlay as mod

    monkeypatch.setattr(mod, "read_report_face_xbrl", lambda fp: [
        _FakeFact("cf.dividends_paid", "CF", "separate", False, -500),
    ])
    rows = [
        _FakeRow("CF", "separate", 0, False, "보통주배당금의 지급", 300),
        _FakeRow("CF", "separate", 0, False, "우선주배당금의 지급", 200),
    ]
    n = overlay_dividends_paid_sign(rows, "dummy.xml", 2025)
    assert n == 0
    assert rows[0].value_won == 300 and rows[1].value_won == 200


def test_overlay_magnitude_mismatch_untouched(monkeypatch):
    """크기가 자릿수부터 다르면(다른 사실일 가능성) 손대지 않는다."""
    import fin2.extract.report_lines_inline_xbrl_overlay as mod

    monkeypatch.setattr(mod, "read_report_face_xbrl", lambda fp: [
        _FakeFact("cf.dividends_paid", "CF", "separate", False, -5_000_000),
    ])
    rows = [_FakeRow("CF", "separate", 0, False, "배당금의 지급", 632_384)]
    n = overlay_dividends_paid_sign(rows, "dummy.xml", 2025)
    assert n == 0
    assert rows[0].value_won == 632_384


def test_overlay_already_correct_is_noop(monkeypatch):
    """이미 부호까지 일치하면 손대지 않는다(카운트도 0)."""
    import fin2.extract.report_lines_inline_xbrl_overlay as mod

    monkeypatch.setattr(mod, "read_report_face_xbrl", lambda fp: [
        _FakeFact("cf.dividends_paid", "CF", "separate", False, -632_384),
    ])
    rows = [_FakeRow("CF", "separate", 0, False, "배당금의 지급", -632_384)]
    n = overlay_dividends_paid_sign(rows, "dummy.xml", 2025)
    assert n == 0
    assert rows[0].value_won == -632_384


# --- §3: overlay_tax_expense_value() — 버그①(컬럼오선택) 수정 ---------------------
# design docs/plans/d_category_col_misselect_ni_label_dup_design_2026-08-23.md §1

def test_00104573_tax_expense_col_misselect_corrected():
    """국일제지(00104573) 2025Q3 연결 '법인세비용(수익)'이 텍스트추출로는
    당기3개월 미공시 → 전기3개월 컬럼 오채택(-138,250,046, 버그)이었다가
    당기누적 XBRL 사실(-2,310,052,284)로 교정된다.

    ★2026-08-24: 옵션 A(파서 근본수정, `gateb_bugA_col_misselect_optionA_
    rootfix_plan_2026-08-24.md`)가 `report_lines.py::_emit_section_lines()`
    에서 이 값을 **직접** 올바르게 방출하게 되면서, 이 오버레이(옵션 B)는 이
    사례에서 더 이상 발동하지 않는다(no-op) — §5 Phase1-3에서 예고한 대로.
    오버레이 함수 자체는 다른 트리거에 대한 안전판으로 존치하되(§8-c),
    이 테스트는 "근본수정이 오버레이 없이도 정답을 낸다"로 갱신한다."""
    if not _GUKIL_PAPER.exists():
        return
    lines = extract_report_lines(
        _GUKIL_PAPER, rcept_no="20251113000801", corp_code="00104573",
        report_fiscal_year=2025, report_fiscal_period="Q3",
    )
    row = next(l for l in lines if l.statement == "IS" and l.basis == "consolidated"
               and (l.col_index or 0) == 0 and l.label_raw == "법인세비용(수익)")
    assert row.value_won == -2_310_052_284
    # 근본수정(옵션 A)이 이미 정답을 냈으므로 오버레이(옵션 B)는 no-op이어야 한다.
    assert row.source_ref is None or not row.source_ref.endswith(";xbrl_inline_override"), (
        f"오버레이가 여전히 발동함 — 근본수정이 no-op을 못 만든 회귀: {row.source_ref}")


def test_00104573_ebt_row_untouched():
    """같은 문서의 EBT 행('법인세비용차감전순이익(손실)')은 '법인세비용' 부분문자열을
    포함하지만 '차감전' 가드로 후보에서 제외돼 오버레이 대상이 아니다(account_mapper
    EBT 가드와 동일 패턴, fin2/tests/test_account_mapper_ebt.py 참고)."""
    if not _GUKIL_PAPER.exists():
        return
    lines = extract_report_lines(
        _GUKIL_PAPER, rcept_no="20251113000801", corp_code="00104573",
        report_fiscal_year=2025, report_fiscal_period="Q3",
    )
    row = next(l for l in lines if l.statement == "IS" and l.basis == "consolidated"
               and (l.col_index or 0) == 0 and l.label_raw == "법인세비용차감전순이익(손실)")
    assert row.value_won == 24_412_859  # 텍스트추출 그대로(오버레이 미적용)
    assert row.source_ref is None or not row.source_ref.endswith(";xbrl_inline_override")


def test_overlay_tax_expense_ebt_label_excluded(monkeypatch):
    """순수 목 테스트 — '차감전'을 포함한 라벨은 '법인세비용' 부분문자열을 갖더라도
    후보에서 제외된다(EBT 오염 재현 방지)."""
    import fin2.extract.report_lines_inline_xbrl_overlay as mod

    monkeypatch.setattr(mod, "read_report_face_xbrl", lambda fp: [
        _FakeFact("is.tax_expense", "IS", "consolidated", True, -2_310_052_284),
    ])
    rows = [
        _FakeRow("IS", "consolidated", 0, True, "법인세비용차감전순이익(손실)", 24_412_859),
        _FakeRow("IS", "consolidated", 0, True, "법인세비용(수익)", -138_250_046),
    ]
    n = overlay_tax_expense_value(rows, "dummy.xml", 2025)
    assert n == 1
    assert rows[0].value_won == 24_412_859  # EBT 행 — 손대지 않음
    assert rows[1].value_won == -2_310_052_284  # 진짜 tax_expense 행만 교정


def test_overlay_tax_expense_no_magnitude_gate(monkeypatch):
    """dividends_paid 오버레이와 달리 크기가 크게 어긋나도(버그의 증상 자체이므로)
    교정한다 — magnitude tolerance 게이트가 없다."""
    import fin2.extract.report_lines_inline_xbrl_overlay as mod

    monkeypatch.setattr(mod, "read_report_face_xbrl", lambda fp: [
        _FakeFact("is.tax_expense", "IS", "consolidated", True, -2_310_052_284),
    ])
    rows = [_FakeRow("IS", "consolidated", 0, True, "법인세비용(수익)", -138_250_046)]
    n = overlay_tax_expense_value(rows, "dummy.xml", 2025)
    assert n == 1
    assert rows[0].value_won == -2_310_052_284


def test_overlay_tax_expense_ambiguous_two_candidates_untouched(monkeypatch):
    """같은 (basis, is_cumulative)에 후보 텍스트행이 2개면(모호) 손대지 않는다."""
    import fin2.extract.report_lines_inline_xbrl_overlay as mod

    monkeypatch.setattr(mod, "read_report_face_xbrl", lambda fp: [
        _FakeFact("is.tax_expense", "IS", "consolidated", True, -2_310_052_284),
    ])
    rows = [
        _FakeRow("IS", "consolidated", 0, True, "법인세비용(수익)", -138_250_046),
        _FakeRow("IS", "consolidated", 0, True, "법인세비용(이익)", -1),
    ]
    n = overlay_tax_expense_value(rows, "dummy.xml", 2025)
    assert n == 0
    assert rows[0].value_won == -138_250_046 and rows[1].value_won == -1


def test_overlay_tax_expense_already_correct_is_noop(monkeypatch):
    """이미 값이 일치하면 손대지 않는다(카운트도 0)."""
    import fin2.extract.report_lines_inline_xbrl_overlay as mod

    monkeypatch.setattr(mod, "read_report_face_xbrl", lambda fp: [
        _FakeFact("is.tax_expense", "IS", "consolidated", True, -2_310_052_284),
    ])
    rows = [_FakeRow("IS", "consolidated", 0, True, "법인세비용(수익)", -2_310_052_284)]
    n = overlay_tax_expense_value(rows, "dummy.xml", 2025)
    assert n == 0


def test_overlay_tax_expense_pre2024_is_noop_without_reading_file():
    """report_fiscal_year < 2024 는 파일을 열지 않고 즉시 0(no-op)."""
    rows = [_FakeRow("IS", "consolidated", 0, True, "법인세비용(수익)", -138_250_046)]
    n = overlay_tax_expense_value(rows, "/nonexistent/path.xml", 2023)
    assert n == 0
    assert rows[0].value_won == -138_250_046
