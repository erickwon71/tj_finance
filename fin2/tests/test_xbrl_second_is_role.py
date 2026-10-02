"""
R199 — an XBRL filing that files the income statement and the statement of comprehensive income as two
statements has two IS roles per basis ([D310000] 손익계산서 + [D410000] 포괄손익계산서). The extractor kept only
the first, so every other-comprehensive-income row was missing (verification missing_row issues on
현대코퍼레이션 ×2 · 피노 · 코스모화학 · LS마린솔루션).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fin2.extract.report_lines_xbrl as X  # noqa: E402
from parser.xbrl_instance.role_map import RoleInfo, extra_core_roles, index_core_roles  # noqa: E402

_RAW = Path(__file__).resolve().parents[2] / "raw_report"


def _role(role_id: str, statement: str, basis: str) -> RoleInfo:
    return RoleInfo(role_uri=f"http://x/{role_id}", role_id=role_id, statement=statement, basis=basis,
                    definition_ko="", definition_en="")


def test_extra_core_roles_returns_only_the_skipped_ones():
    roles = {r.role_uri: r for r in (
        _role("D210000", "BS", "consolidated"), _role("D310000", "IS", "consolidated"),
        _role("D410000", "IS", "consolidated"), _role("D310005", "IS", "separate"),
        _role("D410005", "IS", "separate"))}
    assert [r.role_id for r in extra_core_roles(roles)] == ["D410000", "D410005"]
    assert index_core_roles(roles)[("IS", "consolidated")].role_id == "D310000"


def test_single_is_role_has_no_extra():
    roles = {r.role_uri: r for r in (_role("D310000", "IS", "consolidated"), _role("D610000", "SCE", "consolidated"))}
    assert extra_core_roles(roles) == []


def _extract(rel: str, rcept: str, corp: str, fy: int, fp: str, ped: date, on: bool):
    path = _RAW / rel
    if not path.exists():
        return None
    X._EMIT_EXTRA_IS_ROLES = on
    try:
        return X.extract_report_lines_xbrl(path, rcept_no=rcept, corp_code=corp, report_fiscal_year=fy,
                                           report_fiscal_period=fp, period_end_date=ped)
    finally:
        X._EMIT_EXTRA_IS_ROLES = True


def test_hyundai_corp_2019h1_separate_oci_rows_present():
    """이슈 #86889 — 원문 별도 포괄손익계산서 '기타포괄손익' 9,796,327,982 가 적재되지 않았다."""
    args = ("KOSPI/00164812_현대코퍼레이션/half/2019/20190809000488.zip", "20190809000488", "00164812", 2019, "H1",
            date(2019, 6, 30))
    off = _extract(*args, on=False)
    if off is None:
        return
    on = _extract(*args, on=True)

    def oci(lines):
        return [l for l in lines if l.statement == "IS" and l.basis == "separate" and l.value_won == 9796327982]

    assert not oci(off)
    assert oci(on) and all(l.table_seq >= 1 for l in oci(on))
    # additive only: every cell the primary role produced is unchanged — except a missing-total fallback
    # cell whose concept the extra role now prints itself (R208 drops that duplicate)
    key = lambda l: (l.statement, l.basis, l.table_seq, l.row_order, l.col_index, l.value_won)  # noqa: E731
    on_keys = {key(l) for l in on}
    lost = [l for l in off if key(l) not in on_keys]
    assert all((l.source_ref or "").endswith("/xbrl_tree_gap_total") for l in lost)
    concepts_on = {(l.basis, l.col_index, l.value_won, l.source_ref.split("/")[1]) for l in on}
    assert all((l.basis, l.col_index, l.value_won, l.source_ref.split("/")[1]) in concepts_on for l in lost)


def test_extra_role_rows_never_duplicate_the_primary_role():
    args = ("KOSDAQ/00276083_피노/half/2015/20150827000392.zip", "20150827000392", "00276083", 2015, "H1",
            date(2015, 6, 30))
    off = _extract(*args, on=False)
    if off is None:
        return
    on = _extract(*args, on=True)

    def keys(lines):
        return [(l.basis, l.label_raw, l.col_index, l.value_won) for l in lines if l.statement == "IS"]

    primary = set(keys(off))
    added = [k for k in keys(on)[len(keys(off)):]]
    assert added and not (set(added) & primary)
    assert len(added) == len(set(added))


def test_dup_key_keeps_same_label_and_value_under_a_different_concept():
    """R199-b — 순이익 귀속 '비지배지분' and 총포괄손익 귀속 '비지배지분' share label and value but are
    different concepts; the extra role's row must not be dropped as a duplicate of the primary's."""
    from types import SimpleNamespace as NS

    def row(concept, value=-13998845):
        return NS(basis="consolidated", label_raw="비지배지분", col_index=0, value_won=value,
                  source_ref=f"IS_consolidated/{concept}")

    ni = row("ProfitLossAttributableToNoncontrollingInterests")
    ci = row("ComprehensiveIncomeAttributableToNoncontrollingInterests")
    assert X._extra_role_dup_key(ni) != X._extra_role_dup_key(ci)
    # the same concept (ProfitLoss printed in both statements) is still a duplicate, and a
    # gap-fill suffix on source_ref does not change the concept
    assert X._extra_role_dup_key(row("ProfitLoss")) == X._extra_role_dup_key(row("ProfitLoss"))
    gap = row("ProfitLoss")
    gap.source_ref = "IS_consolidated/ProfitLoss/xbrl_tree_gap_total"
    assert X._extra_role_dup_key(gap) == X._extra_role_dup_key(row("ProfitLoss"))


def test_hanwha_ocean_2024q1_comprehensive_income_noncontrolling_row_present():
    """이슈 #86985 — 원문 연결 포괄손익의 귀속 '비지배지분' (13,998,845) 가 순이익 귀속 행과 같은 라벨·값이라
    중복으로 버려졌다."""
    args = ("KOSPI/00111704_한화오션/quarter/2024/20240514001522.zip", "20240514001522", "00111704", 2024, "Q1",
            date(2024, 3, 31))
    on = _extract(*args, on=True)
    if on is None:
        return
    hit = [l for l in on if l.statement == "IS" and l.basis == "consolidated" and l.label_raw == "비지배지분"
           and l.col_index == 0 and l.table_seq >= 1]
    assert [l.value_won for l in hit] == [-13998845]
