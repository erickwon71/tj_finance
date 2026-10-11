#!/usr/bin/env python
"""Step C of docs/plans/parsing_rules_split_2026-10-11.md — move PARSING_RULES.md sections into
docs/rules/*.md by the reviewed classification (docs/plans/parsing_rules_classification.tsv).

Pure move: every '## ' section keeps its exact text (verified below by comparing the multiset
of section texts). R numbers are untouched. PARSING_RULES.md stays the single entry point:
its preamble, the governing principles (R0, R0-2, R0-1, R2, R6, R9) and the old index stay there,
followed by a generated index R number -> file / layer / status.

    python scripts/split_parsing_rules.py --out <dir>     # write into <dir> (dry run)
    python scripts/split_parsing_rules.py --apply         # write into docs/
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs/PARSING_RULES.md"
TSV = ROOT / "docs/plans/parsing_rules_classification.tsv"

FILES = {
    "layer2": ("10_layer2_parse.md", "계층2 — 원문을 읽어 `report_lines` 에 싣는 규칙",
               "원문에서 **무엇을 어떻게 읽는가**(표·열·기간·단위 판정, 표기 해석, 행·표 인식, 싣지 않는 것). "
               "인쇄된 숫자와 다른 값을 만드는 규칙은 여기 없다(R0-2 → 20_layer3_map.md)."),
    "layer3": ("20_layer3_map.md", "계층3 — 계층2 를 표준 계정으로 바꾸고 값을 보정하는 규칙",
               "계정 매핑·정정본 병합·정규화, 그리고 인쇄된 숫자와 **다른 값**을 만드는 모든 규칙"
               "(부호 복원·숫자 교정·빈칸 채움·행 이동·다른 원천 덮어쓰기 — R0-2). 코드가 `fin2/extract` 에 "
               "있어도 `as_printed` STEPS 뒤에서 `layer3_cell_corrections` 로만 나간다."),
    "audit": ("30_audit_verify.md", "검증 — 데이터를 쓰지 않고 판정만 하는 규칙",
              "Gate B·face_audit·verify(기계대조·모델 검증)·감사 스크립트."),
    "ops": ("40_ops_pipeline.md", "운영 — 수집 대상·파이프라인 배선·재적재 규약", ""),
    "case_log": ("90_case_log.md", "사례 기록 — 판정 문장이 없는 경위·측정·배치 기록",
                 "규칙이 아니다. 판정에 쓰지 않는다."),
    "index": ("99_appendix.md", "부록 — 원출처·미결 현황·rcept 예외목록 카탈로그", ""),
}
LAYER = {"layer2": "2", "layer3": "3", "audit": "검증", "ops": "운영", "case_log": "사례",
         "principles": "원칙", "index": "부록"}


def _sections(text: str) -> tuple[str, list[str]]:
    lines = text.split("\n")
    heads = [i for i, l in enumerate(lines) if l.startswith("## ")]
    pre = "\n".join(lines[:heads[0]])
    secs = []
    for k, i in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else len(lines)
        secs.append("\n".join(lines[i:end]).rstrip("\n"))
    return pre.rstrip("\n"), secs


def _rows() -> list[dict]:
    with TSV.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _clean(s: str, n: int) -> str:
    s = re.sub(r"\*\*|`|\|", "", s).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def build() -> dict[str, str]:
    pre, secs = _sections(SRC.read_text(encoding="utf-8"))
    rows = _rows()
    assert len(rows) == len(secs), (len(rows), len(secs))
    for r, s in zip(rows, secs):
        head = s.split("\n", 1)[0][3:]
        assert head.startswith(r["rule"].split(" ")[0][:6]), (r["rule"], head[:40])
    out: dict[str, list[str]] = {k: [] for k in FILES}
    xbrl: list[str] = []
    entry_secs: list[str] = []
    index_rows: list[str] = []
    for r, s in zip(rows, secs):
        cat = r["final"]
        head = s.split("\n", 1)[0][3:]
        if cat in ("principles",) or head.startswith("0. 규칙 색인"):
            entry_secs.append(s)
            where = "이 문서"
        elif cat == "layer2" and r["group"] == "xbrl_fallback":
            xbrl.append(s)
            where = f"[{FILES['layer2'][0]}](rules/{FILES['layer2'][0]}) · XBRL 폴백"
        else:
            out[cat].append(s)
            where = f"[{FILES[cat][0]}](rules/{FILES[cat][0]})"
        if head.startswith("0. 규칙 색인"):
            continue
        note = []
        if r["impl"].startswith("★"):
            note.append("★코드 이행 대기")
        elif r["impl"].startswith("as_printed"):
            note.append("as_printed STEP")
        index_rows.append(f"| {_clean(head.split('.')[0] if head.startswith('R') else head, 14)} "
                          f"| {_clean(head, 70)} | {where} | {LAYER[cat]} | {_clean(r['status'], 60)} "
                          f"| {' · '.join(note)} |")
    files: dict[str, str] = {}
    banner = ("> 이 파일은 `docs/PARSING_RULES.md` 에서 **내용을 바꾸지 않고 옮긴** 절들이다(2026-10-12, "
              "`scripts/split_parsing_rules.py`). 규칙 번호·본문은 그대로이고, 분류 기준은 "
              "[판정 순서](../plans/parsing_rules_split_2026-10-11.md#분류-기준--판정-순서-사용자-확정-2026-10-11). "
              "새 규칙도 같은 판정 순서로 파일을 고르고 머리에 `적용 계층:` 을 적는다.\n"
              "> 규칙 문서 수정은 **main 과 camp_err_review 에서만** 한다(사용자 결정 2026-10-11).")
    for cat, (name, title, desc) in FILES.items():
        body = out[cat]
        parts = [f"# {title}", "", banner] + (["", desc] if desc else []) + ["", "---", ""]
        parts.append("\n\n".join(body))
        if cat == "layer2" and xbrl:
            parts += ["", "", "---", "",
                      "# XBRL 폴백 경로 (본문 XML 도 웹뷰 인쇄본도 없을 때만)", "",
                      "> 2026-10-10 정책(PARSING_RULES.md R0-2 절): 본문 XML 이 없으면 **웹뷰 인쇄본**"
                      "(`<rcept>.viewer.xml`)이 계층2 원천이고 XBRL 은 계층3 증거다. 아래 규칙은 웹뷰도 없어 "
                      "XBRL instance 를 계층2 에 실어야 하는 필링에만 쓰인다. 산수 증명으로 부호를 바꾸는 XBRL 규칙"
                      "(R170-d·R176·R200·R227)은 20_layer3_map.md 에 있다.", "",
                      "\n\n".join(xbrl)]
        files[f"rules/{name}"] = "\n".join(parts).rstrip("\n") + "\n"
    guide = [
        "## 0-0. 이 문서와 docs/rules/ (2026-10-12 분리)", "",
        "이 문서는 **단일 진입점**이다 — 지배 원칙(R0·R0-2·R0-1·R2·R6·R9)과 전체 색인을 둔다. "
        "나머지 규칙 본문은 아래 파일로 **내용 그대로** 옮겼다(R 번호 불변). 계층은 코드 위치가 아니라 "
        "**규칙이 무엇을 결정하는가**로 정한다(판정 순서: `docs/plans/parsing_rules_split_2026-10-11.md`).", "",
        "| 파일 | 담는 것 |", "|---|---|",
        *[f"| [{FILES[c][0]}](rules/{FILES[c][0]}) | {FILES[c][1]} |" for c in FILES], "",
        "- 규칙을 찾을 때: 아래 **0-1 전체 색인**에서 R 번호로 파일을 찾는다. grep 은 `docs/PARSING_RULES.md docs/rules/` 를 함께 본다.",
        "- 규칙 문서 수정은 **main 과 camp_err_review 에서만**(사용자 결정 2026-10-11). 다른 worktree 는 받기만 한다.",
        "- 상태 `대체됨(→R..)` 인 규칙은 판정에 쓰지 않는다 — 화살표의 규칙을 본다.",
    ]
    index = ["## 0-1. 전체 색인 (자동 생성 — `scripts/split_parsing_rules.py`)", "",
             "| R | 제목 | 파일 | 적용 계층 | 상태 | 비고 |", "|---|---|---|---|---|---|", *index_rows]
    entry = [pre, "", "\n\n".join(entry_secs[:3]), "", "\n".join(guide), "", "\n".join(index), "",
             "\n\n".join(entry_secs[3:])]
    files["PARSING_RULES.md"] = "\n".join(entry).rstrip("\n") + "\n"
    _verify(secs, files)
    return files


def _verify(secs: list[str], files: dict[str, str]) -> None:
    """Every source section appears exactly once, byte-identical, across the output files."""
    h = lambda s: hashlib.sha1(s.encode()).hexdigest()
    want = Counter(h(s) for s in secs)
    got: Counter = Counter()
    for text in files.values():
        lines = text.split("\n")
        heads = [i for i, l in enumerate(lines) if l.startswith("## ")]
        for k, i in enumerate(heads):
            end = heads[k + 1] if k + 1 < len(heads) else len(lines)
            chunk = "\n".join(lines[i:end]).rstrip("\n")
            # strip the trailing scaffolding that follows a file's last section
            chunk = re.split(r"\n\n---\n\n# ", chunk)[0].rstrip("\n")
            got[h(chunk)] += 1
    missing = want - got
    assert not missing, f"{sum(missing.values())} sections changed or missing"
    extra = {k for k in got if k not in want}
    assert len(extra) == 2, f"unexpected new sections: {len(extra)}"   # 0-0 guide + 0-1 index


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    files = build()
    base = ROOT / "docs" if a.apply else Path(a.out)
    for rel, text in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        print(f"{rel}: {text.count(chr(10))} lines, {text.count(chr(10) + '## ')} sections")
    print("verified: every section moved unchanged")
