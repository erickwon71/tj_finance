"""
R28 회귀 테스트 — `_emit_eps_lines` K-GAAP 구서식 헤드라인 순이익 skip 게이트.

docs/plans/report_lines_eps_kgaap_legacy_label_unit_fallback_fix_design_2026-08-15.md
§8 Phase 2-5. curated 키 목록(`fin2/extract/data/eps_kgaap_headline_not_eps_keys_
2026-08-15.json`)에 매칭되는 행은 EPS 패스를 skip 하고 본류가 표 단위를 적용해
일반 행으로 전사한다 — 실제 프로덕션 키가 아니라 합성 표로 메커니즘 자체를 검증한다
(프로덕션 키가 바뀌어도 이 테스트는 흔들리지 않아야 한다, monkeypatch 로 격리).

실행: python -m fin2.tests.test_eps_kgaap_headline_gate_r28  또는  pytest fin2/tests/
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree  # noqa: E402

import fin2.extract.report_lines as report_lines  # noqa: E402
from fin2.extract.report_lines import _emit_section_lines  # noqa: E402

_RCEPT = "TESTR28-0000000001"
_HEADLINE_LABEL = "ⅩⅢ.당기순이익(주당순이익:당기 100원 전기 90원)"
_NORMAL_EPS_LABEL = "기본주당순이익"


def _make_table(label: str, amounts: list[str]) -> etree._Element:
    cells = "".join(f"<TD>{a}</TD>" for a in amounts)
    xml = f"<TABLE><TR><TD>{label}</TD>{cells}</TR></TABLE>"
    return etree.fromstring(xml)


def _run(table, *, unit: int, table_seq: int = 0):
    lines: list = []
    _emit_section_lines(
        "IS_S", [(table, unit, "(단위 : 천원)")],
        emit=lines.append, corp_code="TESTCORP", rcept_no=_RCEPT,
        report_fiscal_year=2004, report_fiscal_period="FY",
    )
    return lines


def test_curated_key_row_skips_eps_and_is_picked_up_by_main_pass(monkeypatch):
    """(a) curated 키에 든 가짜 표 → 주당손익 행 0개(전 컬럼) + 본류 행(당기, col_index=0)."""
    table = _make_table(_HEADLINE_LABEL, ["50,000", "40,000"])
    key = (_RCEPT, "IS", "separate", 0, _HEADLINE_LABEL)
    monkeypatch.setattr(report_lines, "_EPS_KGAAP_HEADLINE_NOT_EPS_KEYS", frozenset([key]))

    lines = _run(table, unit=1000, table_seq=0)

    eps_rows = [l for l in lines if l.section_path == "주당손익"]
    body_row = next(l for l in lines
                     if l.label_raw == _HEADLINE_LABEL and l.section_path != "주당손익"
                     and l.col_index == 0)
    assert eps_rows == [], eps_rows
    # 무손실 불변식(설계 §4-A) — 본류 값은 raw × table_unit.
    assert body_row.value_won == 50_000 * 1000, body_row.value_won


def test_non_curated_normal_eps_label_unaffected(monkeypatch):
    """(b) 키 밖의 정상 EPS 라벨 → 기존과 동일하게 EPS 행 emit(회귀 없음)."""
    table = _make_table(_NORMAL_EPS_LABEL, ["500", "450"])
    monkeypatch.setattr(report_lines, "_EPS_KGAAP_HEADLINE_NOT_EPS_KEYS", frozenset())

    lines = _run(table, unit=1000, table_seq=0)

    eps_rows = [l for l in lines if l.section_path == "주당손익" and l.label_raw == _NORMAL_EPS_LABEL]
    assert len(eps_rows) >= 1, lines
    assert eps_rows[0].value_won == 500, eps_rows[0].value_won  # 라벨 단위(원/주) 그대로, 표단위 미적용


def test_key_table_seq_mismatch_leaves_row_untouched(monkeypatch):
    """(c) 키에 들었지만 table_seq 가 다른 표 → 기존 동작 유지(키 granularity 회귀 가드)."""
    table = _make_table(_HEADLINE_LABEL, ["50,000", "40,000"])
    # 키는 table_seq=0 을 겨냥하지만 실제 표는 table_seq=1로 emit 된다(아래 monkeypatch).
    key = (_RCEPT, "IS", "separate", 0, _HEADLINE_LABEL)
    monkeypatch.setattr(report_lines, "_EPS_KGAAP_HEADLINE_NOT_EPS_KEYS", frozenset([key]))
    # doc_seq 는 문서 내 표 순서로 결정되므로, table_seq=1을 만들려면 앞에 더미 표를 하나 더 둔다.
    dummy = _make_table("더미행", ["1", "1"])
    lines: list = []
    _emit_section_lines(
        "IS_S", [(dummy, 1000, None), (table, 1000, None)],
        emit=lines.append, corp_code="TESTCORP", rcept_no=_RCEPT,
        report_fiscal_year=2004, report_fiscal_period="FY",
    )
    # 실제 매칭된 표의 table_seq 를 확인 — 더미 표가 table_seq=0, 대상 표가 table_seq=1.
    eps_rows = [l for l in lines if l.section_path == "주당손익" and l.label_raw == _HEADLINE_LABEL]
    assert eps_rows, lines  # 키 미매칭(table_seq 불일치) → 기존 EPS 경로 그대로 emit
    assert all(l.table_seq == 1 for l in eps_rows), eps_rows
    eps_row0 = next(l for l in eps_rows if l.col_index == 0)
    assert eps_row0.value_won == 50_000, eps_row0.value_won  # 라벨 자체 단위선언 없음 → unit=1


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
