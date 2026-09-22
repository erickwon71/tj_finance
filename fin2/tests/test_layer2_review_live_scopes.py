"""pass 의 scope 검사가 **낡은 큐 캐시가 아니라 report_lines 실측**을 보는지 고정한다.

배경(2026-09-22): `_check_verified_scopes()` 가 `layer2_review_queue.n_lines_by_scope`
(JSONB 캐시)를 "적재된 scope" 의 근거로 썼다. 그 캐시는 `_run_target()` 재적재 때만
갱신되므로, 백필이 `store_report_lines()` 로 직접 `report_lines` 를 바꾸면 낡는다
(R147 EPS 세부행 · R162 SCE 부호 · R163 CF 부호).

실측 pass 1,241건: 완전 일치 1,133 · **SCE 키 누락 89** · 행수만 다름 19.
89건은 SCE 를 정직하게 원문대조한 검토자에게 "적재 안 된 scope 를 주장했다"며 pass 를
거짓 거부했다.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "_l2r_live", _ROOT / "scripts/layer2_review.py")
l2r = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(l2r)

_ALL8 = "sep-bs,sep-is,sep-cf,sep-sce,con-bs,con-is,con-cf,con-sce"


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE report_lines (
                rcept_no TEXT, basis TEXT, statement TEXT, label_raw TEXT,
                col_index INTEGER, value_won INTEGER
            )
        """))
    with Session(engine) as s:
        yield s


def _load(session, rcept, scopes):
    """scopes = {(basis, statement): 행수}"""
    for (basis, stmt), n in scopes.items():
        for i in range(n):
            session.execute(text("""
                INSERT INTO report_lines
                    (rcept_no, basis, statement, label_raw, col_index, value_won)
                VALUES (:r, :b, :s, :l, 0, 1)
            """), {"r": rcept, "b": basis, "s": stmt, "l": f"항목{i}"})
    session.commit()


def _all_eight():
    return {(b, s): 3 for b in ("separate", "consolidated")
            for s in ("BS", "IS", "CF", "SCE")}


# ───────────────────── 실측 조회 자체 ──────────────────────

def test_loaded_scopes_come_from_report_lines(session):
    _load(session, "R1", _all_eight())
    assert l2r._loaded_scope_codes(session, "R1") == _ALL8.split(",")


def test_loaded_scopes_omit_absent_statements(session):
    _load(session, "R1", {("separate", "BS"): 2, ("separate", "IS"): 2})
    assert l2r._loaded_scope_codes(session, "R1") == ["sep-bs", "sep-is"]


def test_loaded_scopes_empty_for_unknown_filing(session):
    assert l2r._loaded_scope_codes(session, "없는건") == []


# ───────────── 낡은 캐시가 판정을 바꾸지 못한다 ──────────────

def test_stale_cache_missing_sce_no_longer_rejects(session):
    """★이 테스트가 이번 수정의 핵심 — 캐시엔 SCE 가 없지만 실데이터엔 있다.

    종전 동작: 검토자가 sep-sce/con-sce 를 정직하게 열거하면 "적재돼 있지 않다"며
    거짓 거부. 실측 89건이 이 상태였다(SK하이닉스·삼성전자 등).
    """
    _load(session, "R1", _all_eight())
    item = {
        "rcept_no": "R1",
        # 캐시는 SCE 가 없던 시절의 스냅샷이다
        "n_lines_by_scope": {"separate": {"BS": 3, "IS": 3, "CF": 3},
                             "consolidated": {"BS": 3, "IS": 3, "CF": 3}},
    }
    ok, msg = l2r._check_verified_scopes(session, item, _ALL8)
    assert ok, msg


def test_stale_cache_with_extra_scope_does_not_force_a_claim(session):
    """반대 방향 — 캐시엔 SCE 가 있는데 실데이터엔 없다(백필이 지웠거나 오탐).

    이때 SCE 를 열거하지 않은 것을 '누락'으로 막으면 안 된다. 판정은 실데이터 기준.
    """
    _load(session, "R1", {(b, s): 3 for b in ("separate", "consolidated")
                          for s in ("BS", "IS", "CF")})
    item = {"rcept_no": "R1",
            "n_lines_by_scope": {"separate": {"BS": 3, "IS": 3, "CF": 3, "SCE": 9},
                                 "consolidated": {"BS": 3, "IS": 3, "CF": 3, "SCE": 9}}}
    ok, msg = l2r._check_verified_scopes(
        session, item, "sep-bs,sep-is,sep-cf,con-bs,con-is,con-cf")
    assert ok, msg


def test_cache_is_ignored_entirely(session):
    """캐시가 None 이어도 실데이터가 있으면 정상 판정된다(옛 항목 호환)."""
    _load(session, "R1", _all_eight())
    ok, msg = l2r._check_verified_scopes(
        session, {"rcept_no": "R1", "n_lines_by_scope": None}, _ALL8)
    assert ok, msg


# ────────── 기존 안전장치가 그대로 살아 있는지 ──────────

def test_missing_scope_still_rejected(session):
    """적재된 scope 를 다 열거하지 않으면 여전히 거부한다(대조 미완)."""
    _load(session, "R1", _all_eight())
    ok, msg = l2r._check_verified_scopes(
        session, {"rcept_no": "R1", "n_lines_by_scope": None},
        "sep-bs,sep-is,sep-cf,sep-sce")
    assert not ok
    assert "열거되지 않은" in msg
    assert "con-sce" in msg


def test_source_only_scope_still_routed_to_fail(session):
    """원문엔 있는데 적재가 0행인 scope 주장은 여전히 '결함 신고'로 안내한다(R141/R148)."""
    _load(session, "R1", {("separate", "BS"): 3})
    ok, msg = l2r._check_verified_scopes(
        session, {"rcept_no": "R1", "n_lines_by_scope": None}, "sep-bs,con-is")
    assert not ok
    assert "결함 신고" in msg
    assert "fail --rcept R1" in msg


def test_nothing_loaded_still_rejected(session):
    """적재가 하나도 없으면 여전히 pass 를 막는다(빈 건 조용한 통과 금지)."""
    ok, msg = l2r._check_verified_scopes(
        session, {"rcept_no": "R1", "n_lines_by_scope": None}, "sep-bs")
    assert not ok
    assert "하나도 없습니다" in msg


def test_unknown_scope_code_still_rejected(session):
    _load(session, "R1", _all_eight())
    ok, msg = l2r._check_verified_scopes(
        session, {"rcept_no": "R1", "n_lines_by_scope": None}, "sep-xx")
    assert not ok
    assert "알 수 없는 scope" in msg


def test_check_signature_takes_a_session(session):
    """★서명이 session 을 받는다는 계약을 고정한다 — 호출부 배선 누락 방지.

    `_run_target`/`cmd_pass` 가 session 없이 부르면 즉시 TypeError 가 나야 한다.
    """
    import inspect
    params = list(inspect.signature(l2r._check_verified_scopes).parameters)
    assert params[0] == "session"
