"""store_report_lines() 수동입력 보호 가드(2026-09-08) 회귀 테스트.

배경: 사용자 지적(2026-09-08) — `store_manual_report_lines()`(manual_report_lines.py)는
자동추출 산출물을 지우려면 `overwrite=True`를 요구하지만, 반대 방향(자동추출 경로가 사람이
검증한 `unit_source='manual'` 행을 지우는 것)은 아무 보호가 없었다 — 15개+ 자동경로 호출부
(데일리 파이프라인·백필 스크립트) 전부가 이 취약점에 노출. `store_report_lines()`에 신설된
가드(rcept에 manual 행이 하나라도 있으면 기본 거부)를 SQLite 인메모리 DB로 검증한다(운영
Postgres 안 건드림, ReportLine 하나만 별도 엔진에 create — JSONB 없는 테이블이라 가능).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from collector.models import ReportLine
from fin2.extract.report_lines import ReportLineRow, store_report_lines


@pytest.fixture()
def session():
    # ★SQLite에서 `id INTEGER PRIMARY KEY`(대문자 그대로, BigInteger 아님)만 ROWID
    #   autoincrement alias가 된다 — ReportLine.__table__.create()를 그대로 쓰면
    #   BigInteger가 BIGINT로 컴파일돼 id가 안 채워진다. Core select/insert/delete는
    #   테이블·컬럼 이름으로 SQL을 만들 뿐이라, 이 raw DDL로 만든 물리 테이블이어도
    #   store_report_lines()가 참조하는 ORM 매핑(collector.models.ReportLine)과 그대로
    #   맞물린다(생성 방식은 무관, 이름/컬럼만 맞으면 됨) — 운영 Postgres 스키마는 무변경.
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE report_lines (
                id INTEGER PRIMARY KEY,
                corp_code TEXT, rcept_no TEXT,
                report_fiscal_year INTEGER, report_fiscal_period TEXT,
                statement TEXT, basis TEXT, section_path TEXT,
                row_order INTEGER, depth INTEGER, node_role TEXT, table_seq INTEGER,
                label_raw TEXT, col_index INTEGER, col_label TEXT,
                context_fiscal_year INTEGER, period_kind TEXT, is_cumulative INTEGER,
                value_won INTEGER, value_raw TEXT, header_hint TEXT, adecimal INTEGER,
                unit_source TEXT, source_ref TEXT, context_raw TEXT
            )
        """))
    with Session(engine) as s:
        yield s


def _row(rcept_no="20020814000872", statement="BS", label="자산총계", value=100,
         unit_source="declared"):
    return ReportLineRow(
        corp_code="00307222", rcept_no=rcept_no,
        report_fiscal_year=2002, report_fiscal_period="H1",
        statement=statement, basis="separate",
        section_path=None, table_seq=0, row_order=0, depth=0, node_role="P",
        label_raw=label, col_index=0, col_label=None,
        context_fiscal_year=None, period_kind="instant", is_cumulative=False,
        value_won=value, value_raw=str(value), adecimal=0,
        unit_source=unit_source, currency=None, unit_decl_raw=None,
        header_hint=None, source_ref=None, context_raw=None,
    )


_next_id = [1]


def _insert_manual_row(session, rcept_no="20020814000872"):
    # ★SQLite는 BigInteger PK를 native autoincrement(ROWID alias는 INTEGER PK 전용)로
    #   못 채운다 — 테스트 픽스처에서만 명시적으로 채움(운영 Postgres는 SERIAL이라 무관).
    session.add(ReportLine(
        id=_next_id[0], corp_code="00307222", rcept_no=rcept_no,
        report_fiscal_year=2002, report_fiscal_period="H1",
        statement="BS", basis="separate", label_raw="자산총계",
        col_index=0, value_won=5538000000, unit_source="manual",
    ))
    _next_id[0] += 1
    session.commit()


def test_refuses_to_overwrite_when_manual_rows_exist(session):
    _insert_manual_row(session)
    with pytest.raises(ValueError, match="manually-reviewed"):
        store_report_lines(session, "20020814000872", [_row()])
    # 거부됐으니 manual 행이 그대로 살아있어야 한다.
    remaining = session.query(ReportLine).filter_by(rcept_no="20020814000872").all()
    assert len(remaining) == 1
    assert remaining[0].unit_source == "manual"


def test_overwrite_manual_flag_allows_replacement(session):
    _insert_manual_row(session)
    n = store_report_lines(session, "20020814000872", [_row()], overwrite_manual=True)
    assert n == 1
    remaining = session.query(ReportLine).filter_by(rcept_no="20020814000872").all()
    assert len(remaining) == 1
    assert remaining[0].unit_source == "declared"


def test_no_manual_rows_proceeds_normally(session):
    # 다른 소스(declared)만 있으면 가드가 발동하지 않는다 — 기존 동작 그대로.
    session.add(ReportLine(
        id=_next_id[0], corp_code="00307222", rcept_no="20020814000872",
        report_fiscal_year=2002, report_fiscal_period="H1",
        statement="BS", basis="separate", label_raw="자산총계",
        col_index=0, value_won=1, unit_source="declared",
    ))
    _next_id[0] += 1
    session.commit()
    n = store_report_lines(session, "20020814000872", [_row(value=999)])
    assert n == 1
    remaining = session.query(ReportLine).filter_by(rcept_no="20020814000872").all()
    assert len(remaining) == 1 and remaining[0].value_won == 999


def test_guard_is_scoped_to_this_rcept_only(session):
    # 다른 rcept의 manual 행은 이 rcept 적재를 막지 않는다.
    _insert_manual_row(session, rcept_no="OTHER_RCEPT_01")
    n = store_report_lines(session, "20020814000872", [_row()])
    assert n == 1
