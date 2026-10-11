#!/usr/bin/env python
"""Step D2 of docs/plans/parsing_rules_split_2026-10-11.md — put one status line under every
rule heading in docs/rules/*.md, from the reviewed classification table. No rule text changes:
the line is inserted right after the heading and is recognisable (`> **상태**`), so a re-run
replaces it instead of adding a second one.

    > **상태** 유효 · **적용 계층** 3 · as_printed STEP
    > **상태** 대체됨(→R168) · **적용 계층** 2
    > **종류** 사례 기록 — 판정에 쓰지 않는다

Sections that still carry the old "판정 기준은 R0-1 ... R0-1 이 이긴다" note get a pointer that
this wording is replaced by R0-2 for 2015+ (R0-1's own head says so).

    python scripts/stamp_rule_status.py            # dry run: counts only
    python scripts/stamp_rule_status.py --apply
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TSV = ROOT / "docs/plans/parsing_rules_classification.tsv"
MARK = "> **상태**"
CASE = "> **종류**"
LAYER = {"layer2": "2", "layer3": "3", "audit": "검증", "ops": "운영"}
_R01_NOTE = re.compile(r"판정 기준은 R0-1")


def _table() -> dict[str, dict]:
    out: dict[str, dict] = {}
    with TSV.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            key = r["title"][:80]
            assert key not in out, f"ambiguous title key: {key}"
            out[key] = r
    return out


def _line(r: dict, body: str) -> str:
    if r["final"] == "case_log":
        return f"{CASE} 사례 기록 — 판정에 쓰지 않는다(경위·측정·배치 기록)"
    parts = [f"{MARK} {r['status']}", f"**적용 계층** {LAYER.get(r['final'], r['final'])}"]
    if r["group"] == "xbrl_fallback":
        parts.append("XBRL 폴백 경로 전용(본문 XML·웹뷰 인쇄본이 모두 없을 때)")
    if r["impl"].startswith("as_printed"):
        parts.append("코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections`")
    elif r["impl"].startswith("★"):
        parts.append("★코드 이행 대기")
    if _R01_NOTE.search(body):
        parts.append("이 절 안의 \"판정 기준은 R0-1 … R0-1 이 이긴다\" 문구는 2015+ 에서 **R0-2 로 대체됨**"
                     "(PARSING_RULES.md 맨 위 표)")
    return " · ".join(parts)


def stamp(text: str, table: dict[str, dict]) -> tuple[str, int]:
    lines = text.split("\n")
    heads = [i for i, l in enumerate(lines) if l.startswith("## ")]
    out, n, prev = [], 0, 0
    for k, i in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else len(lines)
        out += lines[prev:i + 1]
        rest = lines[i + 1:end]
        r = table.get(lines[i][3:][:80])
        if r is not None and r["final"] != "index":     # appendix sections are not rules
            # drop an earlier stamp (re-run) — it sits right after the heading, after one blank line
            if len(rest) >= 2 and rest[0] == "" and rest[1].startswith((MARK, CASE)):
                rest = rest[2:]
            out += ["", _line(r, "\n".join(rest))]
            n += 1
        out += rest
        prev = end
    out += lines[prev:] if not heads else []
    return "\n".join(out), n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    table = _table()
    total = 0
    for p in sorted((ROOT / "docs/rules").glob("*.md")):
        text = p.read_text(encoding="utf-8")
        new, n = stamp(text, table)
        total += n
        print(f"{p.name}: {n} stamped")
        if a.apply and new != text:
            p.write_text(new, encoding="utf-8")
    print(f"total {total}{'' if a.apply else ' (dry run)'}")
