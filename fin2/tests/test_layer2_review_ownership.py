"""세션 소유권(owner) 회귀 테스트 — `pass`/`fail`/`redo` 의 기본 대상이 **이 세션이
재적재한 건**으로 한정되는지 검증한다.

## 무엇을 막는 테스트인가

예전엔 `_current()` 가 `status='reloaded'` 중 **전역에서 가장 최근**을 집었다. 큐를
만지는 세션이 둘(캠페인 진행 + 결함조사·백필)이라, 조사 세션이 어떤 건을 재적재한
직후 캠페인 세션이 `pass` 를 부르면 **자기가 본 적 없는 건에 통과 판정이 찍혔다.**
`pass` 는 R139 보호가 걸리는 되돌리기 어려운 관문이라 대가가 크다.

실측 사고: `redo` 를 `--rcept` 없이 불러 캠페인 세션의 현재 항목을 가로챘다
(2026-09-20). 그 뒤로 "백필에 `redo` 를 쓰지 않는다"는 **규약**으로만 회피했는데,
규약은 autocompact 를 못 견딘다 — 그래서 코드로 막았다.

설계: `docs/plans/layer2_review_session_ownership_design_2026-09-21.md`

실행: pytest fin2/tests/test_layer2_review_ownership.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest                                                      # noqa: E402
from sqlalchemy import create_engine, text                         # noqa: E402
from sqlalchemy.orm import Session                                 # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]

# ★`scripts/layer2_review.py` 는 패키지가 아니라 스크립트라 경로 로드한다
#   (다른 조사 스크립트들도 같은 방식을 쓴다).
_spec = importlib.util.spec_from_file_location(
    "_l2r_own", _ROOT / "scripts/layer2_review.py")
l2r = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(l2r)

_ME = "/tmp/worktree_me"
_OTHER = "/tmp/worktree_other"


@pytest.fixture()
def session():
    """★Layer2ReviewQueue 의 **전체 컬럼**을 만든다 — 일부만 만들면
    "table has no column named ..." 로 깨진다(`verified_scopes` 추가 때 실제로 4건이
    이렇게 깨졌다). `owner` 도 반드시 포함.
    """
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE layer2_review_queue (
                rcept_no TEXT PRIMARY KEY, corp_code TEXT, corp_name TEXT, market TEXT,
                corp_rank INTEGER, market_cap INTEGER, seq_in_corp INTEGER,
                fiscal_year INTEGER, fiscal_period TEXT, report_type TEXT, filed_at TEXT,
                report_nm TEXT, is_amendment INTEGER, is_attachment_amendment INTEGER,
                source_kind TEXT, reloaded_at TEXT, n_lines INTEGER, n_lines_by_scope TEXT,
                check_status TEXT, checks TEXT, screen_severity INTEGER, screen_flags TEXT,
                screened_at TEXT, owner TEXT, csv_path TEXT, status TEXT,
                reviewed_at TEXT, note TEXT, verified_scopes TEXT
            )
        """))
    with Session(engine) as s:
        yield s


def _add(session, rcept, *, status, owner, reloaded_at, corp="00000001",
         name="테스트사"):
    session.execute(text("""
        INSERT INTO layer2_review_queue
            (rcept_no, corp_code, corp_name, status, owner, reloaded_at,
             fiscal_year, fiscal_period, seq_in_corp, corp_rank)
        VALUES (:r, :c, :n, :s, :o, :t, 2020, 'FY', 1, 1)
    """), {"r": rcept, "c": corp, "n": name, "s": status, "o": owner,
           "t": reloaded_at})
    session.commit()


# ───────────────────────── _owner() 자체 ──────────────────────────

def test_owner_defaults_to_worktree_path():
    """기본값은 워크트리 경로 — 프로세스마다 죽는 PID 가 아니라 실행 사이 안정적인 키."""
    assert l2r._owner() == str(_ROOT)


def test_owner_env_override(monkeypatch):
    monkeypatch.setenv(l2r._OWNER_ENV, "  custom-label  ")
    assert l2r._owner() == "custom-label"


def test_owner_env_blank_falls_back(monkeypatch):
    """빈 문자열/공백만 넣은 경우는 미설정과 같게 본다."""
    monkeypatch.setenv(l2r._OWNER_ENV, "   ")
    assert l2r._owner() == str(_ROOT)


def test_owner_label_is_short_and_handles_none():
    assert l2r._owner_label("/a/b/camp_err_review") == "camp_err_review"
    assert l2r._owner_label(None) == "미지정"


# ─────────────────── _current() 의 소유자 한정 ────────────────────

def test_current_picks_my_item_not_the_globally_newest(session):
    """★핵심 — 남의 세션 건이 **더 최신**이어도 내 건이 잡혀야 한다.

    예전 동작이라면 `_OTHER` 의 건(더 최신)이 잡혀 거기에 판정이 찍혔다.
    """
    _add(session, "11111111111111", status="reloaded", owner=_ME,
         reloaded_at="2026-09-21 10:00:00")
    _add(session, "22222222222222", status="reloaded", owner=_OTHER,
         reloaded_at="2026-09-21 23:59:59")          # 더 최신
    item = l2r._current(session, owner=_ME)
    assert item is not None
    assert item["rcept_no"] == "11111111111111"


def test_current_returns_none_when_only_other_sessions_item_exists(session):
    """남의 것만 있으면 **아무것도 잡히지 않는다**(무판정이 오판정보다 낫다)."""
    _add(session, "22222222222222", status="reloaded", owner=_OTHER,
         reloaded_at="2026-09-21 10:00:00")
    assert l2r._current(session, owner=_ME) is None


def test_current_ignores_null_owner_rows(session):
    """컬럼 도입 전에 만들어진 무소유 건은 **일부러 제외**한다 — 포함시키면
    막으려던 위험이 그대로 남는다. 전환기엔 `--rcept` 로 지목해 처리한다."""
    _add(session, "33333333333333", status="reloaded", owner=None,
         reloaded_at="2026-09-21 10:00:00")
    assert l2r._current(session, owner=_ME) is None


def test_current_picks_my_newest_among_mine(session):
    """내 것이 여러 개면 그중 최신."""
    _add(session, "11111111111111", status="reloaded", owner=_ME,
         reloaded_at="2026-09-21 10:00:00")
    _add(session, "44444444444444", status="reloaded", owner=_ME,
         reloaded_at="2026-09-21 20:00:00")
    assert l2r._current(session, owner=_ME)["rcept_no"] == "44444444444444"


def test_current_ignores_non_reloaded_status(session):
    """이미 판정된 건은 대상이 아니다(회귀 방지 — 소유자 조건을 넣다가
    status 조건을 잃지 않았는지)."""
    _add(session, "55555555555555", status="pass", owner=_ME,
         reloaded_at="2026-09-21 10:00:00")
    _add(session, "66666666666666", status="fail", owner=_ME,
         reloaded_at="2026-09-21 11:00:00")
    assert l2r._current(session, owner=_ME) is None


def test_current_defaults_owner_to_this_session(session, monkeypatch):
    """`owner` 를 안 넘기면 `_owner()` 를 쓴다(호출부가 대부분 이 경로)."""
    monkeypatch.setenv(l2r._OWNER_ENV, _ME)
    _add(session, "11111111111111", status="reloaded", owner=_ME,
         reloaded_at="2026-09-21 10:00:00")
    _add(session, "22222222222222", status="reloaded", owner=_OTHER,
         reloaded_at="2026-09-21 23:00:00")
    assert l2r._current(session)["rcept_no"] == "11111111111111"


# ──────────────── 소유자 불일치 경고(차단 아님) ─────────────────

def test_warns_when_judging_another_sessions_item(capsys, monkeypatch):
    """`--rcept` 로 남의 건을 지목하면 경고가 뜬다 — 백필 후 대신 처리하는 정상
    흐름이 있으므로 **차단하지는 않는다**(R154 백필 77건이 그 흐름)."""
    monkeypatch.setenv(l2r._OWNER_ENV, _ME)
    l2r._warn_if_other_owner({"owner": _OTHER}, explicit=True)
    out = capsys.readouterr().out
    assert "소유 세션" in out
    assert "worktree_other" in out


def test_no_warning_for_my_own_item(capsys, monkeypatch):
    monkeypatch.setenv(l2r._OWNER_ENV, _ME)
    l2r._warn_if_other_owner({"owner": _ME}, explicit=True)
    assert capsys.readouterr().out == ""


def test_no_warning_when_target_was_not_explicit(capsys, monkeypatch):
    """무인자 경로는 이미 소유자 범위라 경고할 일이 없다."""
    monkeypatch.setenv(l2r._OWNER_ENV, _ME)
    l2r._warn_if_other_owner({"owner": _OTHER}, explicit=False)
    assert capsys.readouterr().out == ""


def test_no_target_message_points_at_rcept(capsys):
    """대상 없음 안내가 `--rcept` 를 알려줘야 한다 — 소유자 범위로 바뀐 뒤
    "남의 것만 있는" 상황에서 사용자가 막막해지지 않도록."""
    l2r._print_no_target()
    out = capsys.readouterr().out
    assert "--rcept" in out
    assert "이 세션" in out


# ──────────────────────── 배선이 살아 있는지 ────────────────────────

def test_ownership_wiring_is_present_in_source():
    """상수·인자 이름이 바뀌면 위 테스트가 조용히 통과해버릴 수 있으므로
    배선 자체를 소스에서 확인한다(R153 테스트와 같은 장치)."""
    src = (_ROOT / "scripts/layer2_review.py").read_text(encoding="utf-8")

    # _current 가 소유자 조건을 갖고 있다
    cur = src.split("def _current(", 1)[1].split("\ndef ", 1)[0]
    assert "owner = :o" in cur

    # _run_target 의 **두** _mark(성공·blocked) 모두 owner 를 찍는다
    run = src.split("def _run_target(", 1)[1].split("\ndef ", 1)[0]
    assert run.count("owner=_owner()") == 2

    # cmd_redo 의 무인자 피커도 소유자 범위다(④ — 실제 사고를 낸 경로)
    redo = src.split("def cmd_redo(", 1)[1].split("\ndef ", 1)[0]
    assert "AND owner = :o" in redo

    # pass/fail 둘 다 경고 훅을 부른다
    for fn in ("def cmd_pass(", "def cmd_fail("):
        body = src.split(fn, 1)[1].split("\ndef ", 1)[0]
        assert "_warn_if_other_owner(" in body, fn


def test_queue_model_has_owner_column():
    """모델에도 컬럼이 있어야 `_mark`(ORM update)가 owner 를 쓸 수 있다."""
    from collector.models import Layer2ReviewQueue
    assert "owner" in Layer2ReviewQueue.__table__.columns


def test_migration_is_registered():
    """마이그레이션이 등록돼 있어야 `python run.py init` 으로 실제 DB 에 적용된다."""
    src = (_ROOT / "collector/db.py").read_text(encoding="utf-8")
    assert "2026_09_21_l2rq_owner" in src
    assert "ADD COLUMN IF NOT EXISTS owner TEXT" in src
