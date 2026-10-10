"""Batch reloads refuse a worktree whose HEAD is behind origin/main (2026-10-10): an old HEAD
(e.g. before R0-2) is on origin/main too, and would reload layer 2 with the old parser."""
from __future__ import annotations

import subprocess

import pytest

from fin2.verification import ops
from fin2.verification.ops import VqError


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def repos(tmp_path, monkeypatch):
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
        _git(work, "config", k, v)
    _git(work, "checkout", "-q", "-b", "main")
    _git(work, "commit", "-q", "--allow-empty", "-m", "a")
    _git(work, "push", "-q", "origin", "main")
    monkeypatch.setattr(ops, "REPO_ROOT", work)
    monkeypatch.setattr(ops, "parser_commit", lambda: "abc")
    return origin, work


def test_current_head_passes(repos):
    assert ops.require_clean_pushed_head() == "abc"


def test_head_behind_origin_main_is_refused(repos):
    _, work = repos
    _git(work, "commit", "-q", "--allow-empty", "-m", "b")
    _git(work, "push", "-q", "origin", "main")
    _git(work, "reset", "-q", "--hard", "HEAD~1")      # still on origin/main, but behind it
    with pytest.raises(VqError, match="뒤처졌다"):
        ops.require_clean_pushed_head()
