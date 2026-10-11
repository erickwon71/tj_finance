#!/usr/bin/env python
"""Consistency check for the parsing-rule documents (docs/PARSING_RULES.md + docs/rules/*.md).

1. no wrapped heading: every '## ' heading is one line (a '##' line without a rule number
   directly continuing a rule heading is the step-A defect);
2. index <-> files: every rule heading in docs/rules/ is listed in the 0-1 index of
   PARSING_RULES.md with that file, and every index row points at a file that has it;
3. worktrees: the rule documents (and verify_prompt.md) of every git worktree equal main's
   — rule documents are edited only in main and camp_err_review (user decision 2026-10-11),
   so a difference means a worktree has not pulled, or someone edited where they should not.

    python scripts/check_rules_sync.py            # exit 1 on any finding
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "docs/PARSING_RULES.md"
DOCS = [ENTRY, *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "docs/rules").glob("*.md")),
        "docs/verification/verify_prompt.md"]
# R numbers that are legitimately repeated as headings (sub-sections of one rule)
_REPEATED_OK = {"R58", "R148"}


def _rid(head: str) -> str | None:
    m = re.match(r"## (R[\w-]+?)(?:[.\s(]|$)", head)
    return m.group(1) if m else None


def check_headings(problems: list[str]) -> None:
    for rel in DOCS[:-1]:
        lines = (ROOT / rel).read_text(encoding="utf-8").split("\n")
        for i, l in enumerate(lines[1:], 1):
            if l.startswith("##") and not l.startswith("###") and not l.startswith("## ") :
                problems.append(f"{rel}:{i + 1}: heading without a space")
            if (l.startswith("## ") and not _rid(l) and lines[i - 1].startswith("## R")):
                problems.append(f"{rel}:{i + 1}: heading continues the previous rule heading (wrapped)")


def check_index(problems: list[str]) -> None:
    entry = (ROOT / ENTRY).read_text(encoding="utf-8")
    idx = entry.split("## 0-1.", 1)
    if len(idx) < 2:
        problems.append(f"{ENTRY}: 0-1 index section missing")
        return
    listed: Counter = Counter()
    for row in idx[1].split("\n## ", 1)[0].splitlines():
        m = re.match(r"\| (R[\w-]+?)(?:[.\s(][^|]*)? \|.*?\| (?:\[([\w.]+)\]|이 문서)", row)
        if m:
            listed[(m.group(1), m.group(2) or "PARSING_RULES.md")] += 1
    have: Counter = Counter()
    for rel in DOCS[:-1]:
        name = Path(rel).name
        for l in (ROOT / rel).read_text(encoding="utf-8").splitlines():
            rid = _rid(l) if l.startswith("## R") else None
            if rid:
                have[(rid, name)] += 1
    for k in sorted(set(have) | set(listed)):
        if have[k] != listed[k]:
            problems.append(f"index: {k[0]} in {k[1]} — headings {have[k]}, index rows {listed[k]}")
    dup = [r for r, n in Counter(r for r, _ in have.elements()).items() if n > 1 and r not in _REPEATED_OK]
    for r in sorted(dup):
        problems.append(f"duplicate rule heading {r}")


def check_worktrees(problems: list[str]) -> None:
    out = subprocess.run(["git", "-C", str(ROOT), "worktree", "list", "--porcelain"],
                         capture_output=True, text=True).stdout
    trees = [l[9:] for l in out.splitlines() if l.startswith("worktree ")]
    digest = lambda p: hashlib.sha1(p.read_bytes()).hexdigest() if p.exists() else None
    main = {rel: digest(ROOT / rel) for rel in DOCS}
    for t in trees:
        tp = Path(t)
        if tp.resolve() == ROOT.resolve() or not tp.exists() or "/jobs/" in t:
            continue
        for rel in DOCS:
            if digest(tp / rel) != main[rel]:
                problems.append(f"worktree {tp.name}: {rel} differs from main")


if __name__ == "__main__":
    problems: list[str] = []
    check_headings(problems)
    check_index(problems)
    if "--no-worktrees" not in sys.argv:
        check_worktrees(problems)
    for p in problems:
        print(p)
    print(f"{len(problems)} finding(s)")
    sys.exit(1 if problems else 0)
