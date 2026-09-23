#!/usr/bin/env python
"""R159 batch — classify every dot-typo cell that already carries STRONG evidence
(twin or a multi-component row identity) and derive its correction value.

User instruction (2026-09-23): "일괄 확인으로 진행해" (batch-confirm and proceed) —
after reviewing that 358/463 scanned dot-typo cells already carry evidence
(twin or additive-identity) per `docs/qa/dot_typo_candidates_2026-09-23.md`.

## Why not just trust every cell the candidates doc marks "evidenced"

Two of the report script's evidence signals are weaker than they look on paper:

1. **Trivial identity** — `_find_identity()`'s `t == mi` branch (mine is itself a
   subtotal) and the `size == 0` case of the `t > mi` branch (mine equals the
   total with NO other component) both accept "mine alone equals some other
   column" as a match. That is sometimes just two columns coincidentally
   holding a duplicate/rowspan-inherited copy of the same text, not a real
   additive identity. ★Real example found while writing this: 신라젠
   `20151130001214` row 15 `(11,928,954,639.0)` — the SAME raw text sits in
   BOTH col 5 and col 6 of that row (duplicated cell), so the "identity"
   `mine == mine` is circular, not evidence. Its digit-concat correction
   (`11,928,954,639,0` — a malformed 1-digit final group) is itself a red flag
   that this is not a genuine comma-typo. Excluded: only identities whose
   matched component count is **>= 2** are trusted here.

2. **Cell-text keying collides across rows** — `_SOURCE_TYPO_CELL_FIXES` and
   `apply_source_typo_fixes()` key a correction by `(rcept_no, raw_cell_text)`
   alone, not by row/column. If the SAME raw text needs a DIFFERENT correction
   in two different rows of the same filing, a single dict entry cannot
   express that — applying either value would silently corrupt the other row.
   This script detects any such conflict and drops BOTH occurrences from the
   batch (reported separately for manual handling), rather than guessing.

## Value derivation

  - **Twin evidence** — use the twin's own digit string (`full`, already
    zero-padded to the twin's length by the report script's prefix+trailing-
    zeros match) reformatted with thousands commas, wrapped in the SAME sign
    style (`(...)`, `-`, `−`, or plain) as the original cell. This is the
    strongest evidence: an independently printed integer elsewhere in the
    filing.
  - **Identity evidence** (no twin, component count >= 2) — use the hypothesis
    value (`콤마` = `_as_int`, `절삭` = `_as_trunc`) the report script already
    verified closes the row's own additive identity, reformatted the same way.
  - If both exist, twin wins (more literal); if they disagree, exclude and flag.

Usage:
    python scripts/scan_r159_batch_evidence.py --write
        writes docs/qa/r159_batch_evidence_2026-09-23.md (audit trail) and
        scripts/_r159_batch_entries.py (generated dict literal to review before
        pasting into table_extractor.py — nothing is written to source code by
        this script).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

_ROOT = Path(__file__).resolve().parents[1]
_SCAN = _ROOT / "docs/qa/decimal_cell_scan.jsonl"
_OUT_MD = _ROOT / "docs/qa/r159_batch_evidence_2026-09-23.md"
_OUT_PY = _ROOT / "scripts/_r159_batch_entries.py"

_spec = importlib.util.spec_from_file_location(
    "_rep", _ROOT / "scripts/report_dot_typo_candidates.py")
_rep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rep)


def _identity_size(left_str: str) -> int:
    return left_str.count("+") + 1


# ★안전장치 — 짧은 숫자는 우연히 다른 값과 자릿수가 겹칠 확률이 무시 못 할 만큼
#   크다. 실측(2026-09-23, 이 스캔 첫 실행): `"7.28"` 이 `[연결] 현금흐름표 "2.
#   이자 수취" = "24,27"` 과 짝지어졌는데, 그 "정수판" 자체가 `24,27`(끝자리 그룹이
#   2자리) — 콤마 자릿수 규칙이 깨진 값이다. 더 심한 예: 한화생명 `2.1` 이
#   `보험계약자산 = 21` 과 짝지어졌다 — 초대형 보험사의 그 계정이 21원일 리 없다.
#   둘 다 트윈 탐색이 "숫자열이 접두사로 일치+뒤가 전부 0" 만 보고, **짝으로 찾은
#   정수 자체가 제대로 그룹핑됐는지는 안 봤기** 때문에 생긴 오탐이다. 실제 확정된
#   진짜 사례의 최소 자릿수는 5자리(`"41.423"`→"41423")였다 — 그보다 짧으면
#   배치에서 제외하고, 트윈으로 지목된 정수 자체도 올바른 3자리 그룹핑인지 검증한다.
_MIN_DIGITS = 5
_WELL_GROUPED_RE = re.compile(r"^[(\[]?\s*[-−]?\s*\d{1,3}(,\d{3})*\s*[)\]]?$")


def _fmt_like(original: str, value: int) -> str:
    """Reformat `value` with thousands commas, wrapped like `original`'s sign."""
    o = original.strip()
    digits = "{:,}".format(abs(value))
    if o.startswith("(") or o.startswith("（"):
        return f"({digits})"
    if o.startswith("−"):
        return f"−{digits}"
    if o.startswith("-") and value < 0:
        return f"-{digits}"
    return digits


def _derive(b: dict):
    """Return (corrected_text, reason, strength) or None if not strong enough."""
    if b.get("twin"):
        full, (wk, wl, wt) = b["twin"]
        d = _rep._digits(b["cell"])
        # ★핵심 안전장치는 **깨진 셀 자신의 자릿수**다 — 짧으면(예: "4.5"->"45")
        #   패딩 허용 폭이 넓어서 무관한 큰 정수와 우연히 접두어가 맞기 쉽다.
        #   `full`(정수판 쪽) 길이를 봤던 초판은 이 위험을 못 걸렀다("4.5"->"45"가
        #   "4,500,000"과 우연히 맞은 실측 오탐).
        if len(d) < _MIN_DIGITS or not _WELL_GROUPED_RE.match(wt.strip()):
            return None
        value = int(full)
        if (b["cell"].strip().startswith("(") or b["cell"].strip().startswith("−")
                or b["cell"].strip().startswith("-")):
            value = -value
        corrected = _fmt_like(b["cell"], value)
        reason = f"twin: {_rep._SCOPE_KO.get(wk, wk)} `{wl[:24]}` = `{wt}`"
        return corrected, reason, "twin"
    if b.get("identity"):
        left, total = b["identity"]
        if _identity_size(left) < 2:
            return None
        tag, mine = b["hypothesis"]
        if len(str(abs(mine))) < _MIN_DIGITS:
            return None
        corrected = _fmt_like(b["cell"], mine)
        reason = f"항등식({tag}): {left} = {total:,}"
        return corrected, reason, "identity"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    hits = []
    with _SCAN.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("hits"):
                hits.append(rec["rcept_no"])

    resolve_source = _rep._resolve_source_fn()
    # (rcept, cell_text) -> list of (corrected, reason, strength, scope, label, col)
    proposals: dict[tuple, list] = defaultdict(list)
    n_scanned = n_weak = n_no_evidence = 0

    with get_session() as s:
        rows = s.execute(text("""
            SELECT rcept_no, corp_code, corp_name, fiscal_year, fiscal_period,
                   report_nm
            FROM layer2_review_queue
            WHERE rcept_no = ANY(:r)
            ORDER BY corp_rank NULLS LAST, corp_code, fiscal_year DESC"""),
            {"r": sorted(hits)}).mappings().all()
        meta = {r["rcept_no"]: dict(r) for r in rows}

        for i, rcept in enumerate(hits, 1):
            m = meta.get(rcept)
            if not m:
                continue
            try:
                _kind, path = resolve_source(s, rcept)
                cells = _rep.scan_one(path, rcept)
            except Exception:                                      # noqa: BLE001
                continue
            for b in cells:
                n_scanned += 1
                got = _derive(b)
                if got is None:
                    if b.get("twin") or b.get("identity"):
                        n_weak += 1
                    else:
                        n_no_evidence += 1
                    continue
                corrected, reason, strength = got
                proposals[(rcept, b["cell"])].append(
                    (corrected, reason, strength, b["scope"], b["label"], b["col"]))
            if i % 25 == 0:
                print("  ... %d/%d" % (i, len(hits)), flush=True)

    # Split into clean (single agreed correction) vs conflicting.
    clean: dict[tuple, tuple] = {}
    conflicts: dict[tuple, set] = {}
    for key, entries in proposals.items():
        corrections = {e[0] for e in entries}
        if len(corrections) == 1:
            clean[key] = entries[0]
        else:
            conflicts[key] = corrections

    by_rcept: dict[str, list] = defaultdict(list)
    for (rcept, cell), (corrected, reason, strength, scope, label, col) in clean.items():
        by_rcept[rcept].append((cell, corrected, reason, strength, scope, label, col))

    print(f"\n스캔한 셀 {n_scanned}개")
    print(f"  근거 있음(트윈/항등식) 중 배치 확정: {len(clean)}건")
    print(f"  약함(단일성분/자기순환 항등식)이라 제외: {n_weak}건")
    print(f"  같은 셀 텍스트가 다른 값으로 충돌해 제외: {len(conflicts)}건")
    print(f"  근거 전혀 없음(needs_dart): {n_no_evidence}건")
    print(f"  대상 필링: {len(by_rcept)}건")

    if conflicts:
        print("\n충돌(같은 원문 셀이 서로 다른 값으로 요구됨) — 수동 확인 필요:")
        for (rcept, cell), vals in list(conflicts.items())[:20]:
            print(f"  {rcept}  {cell!r}  -> {sorted(vals)}")

    if args.write:
        _write_outputs(by_rcept, conflicts, meta)
        print(f"\n문서 생성: {_OUT_MD}")
        print(f"생성된 dict 초안: {_OUT_PY}")
    return 0


def _write_outputs(by_rcept, conflicts, meta):
    md = [
        "# R159 배치 근거 확정 — 트윈/항등식 근거로 자동 도출한 정정값 감사 기록",
        "",
        f"필링 **{len(by_rcept)}건** · 셀 **{sum(len(v) for v in by_rcept.values())}개**.",
        "",
        "사용자 지시(2026-09-23) `일괄 확인으로 진행해` 에 따라, 트윈(정수판) 또는",
        "2개 이상 구성요소가 닫히는 항등식으로 검증된 셀만 모았다. 단일 성분/자기순환",
        "항등식과 같은 원문 셀이 행마다 다른 값을 요구하는 충돌 건은 제외했다.",
        "",
        "---",
        "",
    ]
    py = [
        "# Auto-generated by scripts/scan_r159_batch_evidence.py — review before",
        "# pasting into parser/xml/table_extractor.py::_SOURCE_TYPO_CELL_FIXES.",
        "# Each entry's evidence is in the trailing comment.",
        "",
    ]
    for rcept in sorted(by_rcept):
        m = meta.get(rcept, {})
        md += [
            f"## {m.get('corp_name', '')} — {m.get('report_nm', '')}",
            "",
            f"- DART: https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept}",
            f"- rcept `{rcept}`",
            "",
            "| 재무제표 | 행 라벨 | 원문 셀 | 정정값 | 근거 |",
            "|---|---|---|---|---|",
        ]
        py.append(f"    # {m.get('corp_name', '')} {rcept}")
        for cell, corrected, reason, strength, scope, label, col in by_rcept[rcept]:
            md.append(
                f"| {_rep._SCOPE_KO.get(scope, scope)} | `{label[:26]}` | "
                f"`{cell}` | `{corrected}` | {reason} |")
            esc_cell = cell.replace('"', '\\"')
            esc_corrected = corrected.replace('"', '\\"')
            py.append(
                f'    ("{rcept}", "{esc_cell}"): "{esc_corrected}",'
                f"  # {reason}")
        md.append("")
    if conflicts:
        md += ["---", "", "## 충돌 — 배치에서 제외(수동 확인 필요)", "",
               "| rcept | 원문 셀 | 요구된 값들 |", "|---|---|---|"]
        for (rcept, cell), vals in conflicts.items():
            md.append(f"| `{rcept}` | `{cell}` | {', '.join(sorted(vals))} |")
        md.append("")
    _OUT_MD.write_text("\n".join(md), encoding="utf-8")
    _OUT_PY.write_text("\n".join(py) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
