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
)

_LG = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00120021_LG/annual/2025/20260318001025.xml"
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
