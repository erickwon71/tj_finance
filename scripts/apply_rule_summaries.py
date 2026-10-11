#!/usr/bin/env python
"""Step D3 of docs/plans/parsing_rules_split_2026-10-11.md — put the reviewed summary block
(규칙 / 판정 예 / 하지 않는 것 / 코드 / 충돌·불명확·코드 확인) under each rule's status line.

The blocks come from docs/plans/parsing_rules_d3_blocks.md (one "### R…" entry per rule, the
reviewed result of two independent model drafts checked against the rule text). The rule body
below is not touched; a re-run replaces the block instead of adding a second one.

    python scripts/apply_rule_summaries.py            # dry run
    python scripts/apply_rule_summaries.py --apply
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKS = ROOT / "docs/plans/parsing_rules_d3_blocks.md"
FIELDS = ("> **규칙**", "> **판정 예**", "> **하지 않는 것**", "> **코드**", "> **충돌·불명확**",
          "> **코드 확인**")
STATUS = ("> **상태**", "> **종류**")


def load_blocks() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for chunk in re.split(r"\n(?=### R)", BLOCKS.read_text(encoding="utf-8")):
        m = re.match(r"### (R\S+)", chunk.strip())
        if not m:
            continue
        lines = [l.rstrip() for l in chunk.strip().split("\n")[1:] if l.startswith(FIELDS)]
        if lines:
            out[m.group(1)] = lines
    return out


def _rid(head: str) -> str | None:
    m = re.match(r"## (R[\w-]+?)(?:[.\s(]|$)", head)
    return m.group(1) if m else None


def apply(text: str, blocks: dict[str, list[str]]) -> tuple[str, list[str]]:
    lines = text.split("\n")
    out, done, i = [], [], 0
    while i < len(lines):
        out.append(lines[i])
        rid = _rid(lines[i]) if lines[i].startswith("## R") else None
        if rid in blocks and i + 2 < len(lines) and lines[i + 1] == "" and lines[i + 2].startswith(STATUS):
            out += lines[i + 1:i + 3]
            j = i + 3
            # drop an earlier summary block (re-run): '>' spacer + field lines
            if j < len(lines) and lines[j] == ">":
                k = j + 1
                while k < len(lines) and lines[k].startswith(FIELDS):
                    k += 1
                if k > j + 1:
                    j = k
            out += [">"] + blocks[rid]
            done.append(rid)
            i = j
            continue
        i += 1
    return "\n".join(out), done


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    blocks = load_blocks()
    seen: list[str] = []
    for p in sorted((ROOT / "docs/rules").glob("*.md")):
        text = p.read_text(encoding="utf-8")
        new, done = apply(text, blocks)
        seen += done
        if done:
            print(f"{p.name}: {len(done)}")
        if a.apply and new != text:
            p.write_text(new, encoding="utf-8")
    missing = sorted(set(blocks) - set(seen))
    print(f"blocks {len(blocks)} · applied {len(seen)} · not found {missing}")
