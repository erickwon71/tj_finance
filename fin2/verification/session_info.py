"""Per-connection identity sent to Postgres as `verification.*` settings.

The report_lines load hook (fin2/verification/schema.sql, trg_finalize_load) reads these to
stamp *who* loaded an rcept and *with which code*. They are set once per new DB connection by
collector/db.py, so every writer is covered, including ad-hoc backfill scripts.
"""
from __future__ import annotations

import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Code whose uncommitted edits make a load non-reproducible from the recorded commit.
_PARSER_PATHS = ("fin2", "parser", "collector", "scripts")


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True,
                             text=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def worktree_name() -> str:
    """'camp_run' / 'camp_err_review' for .claude/worktrees/<name>, else 'main'."""
    parts = REPO_ROOT.parts
    if len(parts) >= 3 and parts[-3:-1] == (".claude", "worktrees"):
        return parts[-1]
    return "main"


@lru_cache(maxsize=1)
def parser_commit() -> str:
    sha = _git("rev-parse", "--short=10", "HEAD")
    if not sha:
        return "unknown"
    dirty = _git("status", "--porcelain", "--untracked-files=no", "--", *_PARSER_PATHS)
    return f"{sha}-dirty" if dirty else sha


def connect_settings() -> dict[str, str]:
    reason = os.environ.get("VQ_LOAD_REASON") or Path(sys.argv[0] or "python").name
    # VQ_ACTOR lets a non-model verifier (the machine pass) sign its verdicts separately,
    # e.g. 'camp_run:machine', so machine and model verdicts stay distinguishable.
    return {
        "actor": os.environ.get("VQ_ACTOR") or worktree_name(),
        "parser_commit": parser_commit(),
        "load_reason": reason[:120],
    }
