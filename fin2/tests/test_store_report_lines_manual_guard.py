"""store_report_lines() 수동입력/원문대조완료 보호 가드 회귀 테스트.

배경(2026-09-08) — `store_manual_report_lines()`(manual_report_lines.py)는
자동추출 산출물을 지우려면 `overwrite=True`를 요구하지만, 반대 방향(자동추출 경로가 사람이
검증한 `unit_source='manual'` 행을 지우는 것)은 아무 보호가 없었다 — 15개+ 자동경로 호출부
(데일리 파이프라인·백필 스크립트) 전부가 이 취약점에 노출. `store_report_lines()`에 신설된
가드(rcept에 manual 행이 하나라도 있으면 기본 거부)를 SQLite 인메모리 DB로 검증한다(운영
Postgres 안 건드림, ReportLine 하나만 별도 엔진에 create — JSONB 없는 테이블이라 가능).

★R139(2026-09-18, 사용자 지시) 추가 — `layer2_review_queue.status='pass'`(원문대조
캠페인에서 사람/에이전트가 이 rcept를 통과시킨 표시)도 같은 이유로 보호해야 한다: 그 표시는
layer2_review_queue 테이블에만 남고 report_lines 에는 아무 흔적이 없어, 이 가드 없이는
어떤 재적재 경로든 검증된 상태를 조용히 무효화할 수 있었다(기존엔 딱 2개 스크립트만 각자
`WHERE status <> 'pass'`를 복붙해뒀을 뿐, 나머지 15개+ 호출부는 이 상태를 몰랐다).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from collector.models import Layer2ReviewQueue, ReportLine
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
        # FK 제약은 걸지 않는다(기존 report_lines DDL과 동일한 관례) — SQLite는
        # PRAGMA foreign_keys=ON 을 켜지 않는 한 어차피 강제하지 않는다.
        # ★ORM insert는 매핑된 모델의 전체 컬럼을 대상으로 하므로(값을 안 줘도 None으로
        #   INSERT 문에 포함됨), Layer2ReviewQueue 전체 컬럼을 다 만들어야 한다 — 일부만
        #   만들면 "table has no column named ..." 로 실패한다.
        conn.execute(text("""
            CREATE TABLE layer2_review_queue (
                rcept_no TEXT PRIMARY KEY, corp_code TEXT, corp_name TEXT, market TEXT,
                corp_rank INTEGER, market_cap INTEGER, seq_in_corp INTEGER,
                fiscal_year INTEGER, fiscal_period TEXT, report_type TEXT, filed_at TEXT,
                report_nm TEXT, is_amendment INTEGER, is_attachment_amendment INTEGER,
                source_kind TEXT, reloaded_at TEXT, n_lines INTEGER, n_lines_by_scope TEXT,
                check_status TEXT, checks TEXT, screen_severity INTEGER, screen_flags TEXT,
                screened_at TEXT, csv_path TEXT, status TEXT, reviewed_at TEXT, note TEXT,
                verified_scopes TEXT
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


def _mark_reviewed(session, rcept_no="20020814000872"):
    session.add(Layer2ReviewQueue(rcept_no=rcept_no, corp_code="00307222", status="pass"))
    session.commit()


def test_refuses_to_overwrite_when_marked_reviewed(session):
    _mark_reviewed(session)
    with pytest.raises(ValueError, match="marked reviewed"):
        store_report_lines(session, "20020814000872", [_row()])
    # 거부됐으니 report_lines 자체가 비어 있어야 한다(delete도 실행 안 됨).
    remaining = session.query(ReportLine).filter_by(rcept_no="20020814000872").all()
    assert len(remaining) == 0


def test_overwrite_reviewed_flag_allows_replacement(session):
    _mark_reviewed(session)
    n = store_report_lines(session, "20020814000872", [_row()], overwrite_reviewed=True)
    assert n == 1


def test_no_reviewed_mark_proceeds_normally(session):
    # layer2_review_queue 에 행 자체가 없으면(또는 status != 'pass') 가드가 발동하지 않는다.
    n = store_report_lines(session, "20020814000872", [_row()])
    assert n == 1


def test_reviewed_guard_is_scoped_to_this_rcept_only(session):
    # 다른 rcept의 pass 표시는 이 rcept 적재를 막지 않는다.
    _mark_reviewed(session, rcept_no="OTHER_RCEPT_01")
    n = store_report_lines(session, "20020814000872", [_row()])
    assert n == 1


def test_manual_and_reviewed_guards_are_independent(session):
    # manual 가드만 풀고 reviewed 가드는 그대로 두면 여전히 거부돼야 한다.
    _insert_manual_row(session)
    _mark_reviewed(session)
    with pytest.raises(ValueError, match="marked reviewed"):
        store_report_lines(session, "20020814000872", [_row()], overwrite_manual=True)
