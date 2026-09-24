#!/usr/bin/env python
"""Telegram decision bot — records button taps / replies into verification.decisions.

Runs from the main checkout (admin DB role) under launchd:
    ~/Library/LaunchAgents/com.taejin.claude.decision-bot.plist
Only updates from TELEGRAM_CHAT_ID are accepted; the token is never logged.
Design: docs/plans/verification_schema_two_worktree_design_2026-09-24.md §2.7
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fin2.verification.decisions import run_bot  # noqa: E402

if __name__ == "__main__":
    run_bot()
