"""R219 — store_report_tables() must not wipe note table meta on body-only reloads.

Before R219 the function deleted every `report_tables` row of the rcept and re-inserted only
what `lines` carried. Body-only callers (`include_notes=False` reload scripts, the daily XBRL
instance sync) therefore erased the note meta, and note_lines lost their note titles
(`section_path`), which layer-3 note interpretation (D&A, ...) joins on. Measured 2026-10-05:
77,672 filings (2015+) with note_lines but no note meta. SQLite in-memory, production
Postgres untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from fin2.extract.report_lines import ReportLineRow, store_report_tables

RCEPT = "20250318001186"


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE report_tables (
                rcept_no TEXT, statement TEXT, basis TEXT, table_seq INTEGER,
                table_title TEXT, section_path TEXT, unit_decl_raw TEXT,
                declared_unit INTEGER, unit_kind TEXT, unit_inherited INTEGER,
                parsed_at TEXT, currency TEXT,
                PRIMARY KEY (rcept_no, statement, basis, table_seq)
            )
        """))
    with Session(engine) as s:
        yield s


def _row(statement: str, table_seq: int, section_path: str | None = None) -> ReportLineRow:
    return ReportLineRow(
        corp_code="00126955", rcept_no=RCEPT,
        report_fiscal_year=2024, report_fiscal_period="FY",
        statement=statement, basis="consolidated",
        section_path=section_path, table_seq=table_seq, row_order=0, depth=0, node_role="P",
        label_raw="감가상각비", col_index=0, col_label=None,
        context_fiscal_year=2024, period_kind="duration", is_cumulative=True,
        value_won=1, value_raw="1", adecimal=-3,
        unit_source="declared", currency=None, unit_decl_raw="(단위: 천원)",
        header_hint=None, source_ref=None, context_raw=None,
    )


def _meta(session) -> set[tuple]:
    return {tuple(r) for r in session.execute(text(
        "SELECT statement, table_seq, section_path FROM report_tables WHERE rcept_no = :r"),
        {"r": RCEPT})}


def _seed_full(session) -> None:
    store_report_tables(session, RCEPT, [_row("IS", 0), _row("note", 5, "17. 비용의 성격별 분류")])


def test_body_only_lines_keep_note_meta(session):
    _seed_full(session)
    store_report_tables(session, RCEPT, [_row("IS", 0), _row("CF", 1)])
    assert _meta(session) == {("IS", 0, None), ("CF", 1, None),
                              ("note", 5, "17. 비용의 성격별 분류")}


def test_note_scope_keeps_body_meta(session):
    _seed_full(session)
    store_report_tables(session, RCEPT, [_row("IS", 0), _row("note", 7, "18. 금융비용")],
                        scope="note")
    assert _meta(session) == {("IS", 0, None), ("note", 7, "18. 금융비용")}


def test_lines_with_notes_rewrite_everything(session):
    _seed_full(session)
    store_report_tables(session, RCEPT, [_row("BS", 2), _row("note", 9, "9. 유형자산")])
    assert _meta(session) == {("BS", 2, None), ("note", 9, "9. 유형자산")}


def test_explicit_all_clears_notes_even_without_note_lines(session):
    # Callers that also run store_note_lines() pass scope='all' so an empty note
    # extraction leaves no orphan note meta behind (note_lines were deleted too).
    _seed_full(session)
    store_report_tables(session, RCEPT, [_row("IS", 0)], scope="all")
    assert _meta(session) == {("IS", 0, None)}


def test_unknown_scope_rejected(session):
    with pytest.raises(ValueError):
        store_report_tables(session, RCEPT, [_row("IS", 0)], scope="notes")
