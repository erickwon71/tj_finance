#!/usr/bin/env python
"""마침표 셀 중 **내가 판단할 수 없는 것**만 DART 링크·화면 위치와 함께 뽑는다.

`report_dot_typo_candidates.py` 는 마침표 셀 467개 전부를 근거와 함께 싣는다. 그 중
301개는 근거(정수판 / 행 항등식)가 붙어 정정값이 사실상 확정된다. 남은 **166개는 내가
정할 수 없다** — 원문을 봐야 한다. 이 스크립트는 그 166개만 따로 모아, 사용자가 DART
화면에서 **바로 그 칸을 찾을 수 있도록** 위치를 적는다.

★종전 목록은 칸을 `6` 처럼 **번호**로만 적어 화면에서 찾기 어려웠다. 여기서는 헤더에서
**열 이름**을 복원해 같이 적는다(`_build_col_labels`, 계층2 적재가 `col_label` 로 쓰는
바로 그 값). 그리고 DART 좌측 목차에서 어느 항목으로 들어가야 하는지도 적는다.

Usage:
    python scripts/report_dot_typo_needs_dart.py --write
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

_ROOT = Path(__file__).resolve().parents[1]
_SCAN = _ROOT / "docs/qa/decimal_cell_scan.jsonl"
_OUT = _ROOT / "docs/qa/dot_typo_needs_dart_2026-09-23.md"

_spec = importlib.util.spec_from_file_location(
    "_rep", _ROOT / "scripts/report_dot_typo_candidates.py")
_rep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rep)

from fin2.extract.report_lines import _build_col_labels  # noqa: E402

# DART 좌측 목차에서 들어가는 길. 연결/별도가 갈린다.
_NAV = {
    "BS_C": "III. 재무에 관한 사항 → 2. 연결재무제표 → 연결 재무상태표",
    "IS_C": "III. 재무에 관한 사항 → 2. 연결재무제표 → 연결 손익계산서(포괄손익계산서)",
    "CF_C": "III. 재무에 관한 사항 → 2. 연결재무제표 → 연결 현금흐름표",
    "SCE_C": "III. 재무에 관한 사항 → 2. 연결재무제표 → 연결 자본변동표",
    "BS_S": "III. 재무에 관한 사항 → 4. 재무제표 → 재무상태표",
    "IS_S": "III. 재무에 관한 사항 → 4. 재무제표 → 손익계산서(포괄손익계산서)",
    "CF_S": "III. 재무에 관한 사항 → 4. 재무제표 → 현금흐름표",
    "SCE_S": "III. 재무에 관한 사항 → 4. 재무제표 → 자본변동표",
}


def _col_labels_for(path: str, scope: str) -> dict:
    """그 scope 표의 {열 인덱스: 열 이름}. 실패하면 빈 dict."""
    try:
        from fin2.extract.report_lines import _detect_fin_type, _parse_xml_file
        from fin2.extract.text import _detect_body_statement_tables
        root = _parse_xml_file(Path(path))
        if root is None:
            return {}
        groups = _detect_body_statement_tables(
            root, _detect_fin_type(root, file_path=path), include_sce=True)
        out: dict = {}
        for entry in groups.get(scope, []):
            table = entry[0] if isinstance(entry, (tuple, list)) else entry
            if table is None:
                continue
            try:
                out.update(_build_col_labels(table) or {})
            except Exception:                                   # noqa: BLE001
                continue
        return out
    except Exception:                                           # noqa: BLE001
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    hits = set()
    for line in _SCAN.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("hits"):
            hits.add(rec["rcept_no"])

    resolve_source = _rep._resolve_source_fn()
    found: list[dict] = []
    with get_session() as s:
        rows = s.execute(text("""
            SELECT rcept_no, corp_code, corp_name, fiscal_year, fiscal_period,
                   report_nm, csv_path
            FROM layer2_review_queue
            WHERE rcept_no = ANY(:r)
            ORDER BY corp_rank NULLS LAST, corp_code, fiscal_year DESC"""),
            {"r": sorted(hits)}).mappings().all()
        for i, r in enumerate(rows, 1):
            try:
                _kind, path = resolve_source(s, r["rcept_no"])
                cells = _rep.scan_one(path, r["rcept_no"])
            except Exception:                                   # noqa: BLE001
                continue
            unknown = [c for c in cells
                       if not c.get("twin") and not c.get("identity")]
            if not unknown:
                continue
            labels_by_scope: dict = {}
            for c in unknown:
                sc = c["scope"]
                if sc not in labels_by_scope:
                    labels_by_scope[sc] = _col_labels_for(path, sc)
                c["col_label"] = labels_by_scope[sc].get(c["col"] - 1) or ""
            found.append({"row": dict(r), "cells": unknown})
            if i % 25 == 0:
                print("  ... %d/%d (필링 %d)" % (i, len(rows), len(found)),
                      flush=True)

    n_cells = sum(len(f["cells"]) for f in found)
    out = [
        "# 마침표 셀 — **내가 판단할 수 없는 것** (DART 확인 요청, 2026-09-23)",
        "",
        f"필링 **{len(found)}건** · 셀 **{n_cells}개**.",
        "",
        "전체 마침표 셀 467개 중 **근거가 붙은 301개는 제외**했습니다"
        "(`docs/qa/dot_typo_candidates_2026-09-23.md` 에 정정값 후보와 함께 있습니다).",
        "여기 있는 것은 같은 필링 안에 정수판도 없고 행 항등식도 닫히지 않아,",
        "**DART 원문을 봐야만** 판정이 되는 칸입니다.",
        "",
        "판정해 주실 것: **오타인가**, 그리고 **정정값이 무엇인가**.",
        "",
        "`열` 은 그 표 헤더에서 복원한 이름입니다 — 화면에서 그 열을 찾으시면 됩니다.",
        "`행` 은 표 안 순번이라 화면 순번과 다를 수 있으니 **행 라벨**로 찾으십시오.",
        "",
        "---",
        "",
    ]
    for f in found:
        r = f["row"]
        out += [
            f"## {r['corp_name']} — {r['report_nm']}",
            "",
            f"- DART: https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcept_no']}",
            f"- rcept `{r['rcept_no']}` · corp_code `{r['corp_code']}` · "
            f"{r['fiscal_year']}{r['fiscal_period'] or ''}",
            f"- CSV: `{r['csv_path']}`",
            "",
            "| 찾아가는 길 | 재무제표 | 행 라벨 | 열 | 단위 | 원문 셀 |",
            "|---|---|---|---|---|---|",
        ]
        for c in f["cells"]:
            unit_ko = {1: "원", 1000: "천원", 1000000: "백만원"}.get(
                c.get("unit"), str(c.get("unit")))
            nav = _NAV.get(c["scope"], "")
            col = c.get("col_label") or f"(칸 {c['col']})"
            out.append(
                f"| {nav} | {_rep._SCOPE_KO.get(c['scope'], c['scope'])} | "
                f"`{c['label'][:26]}` | `{re.sub(r'^자본>', '', col)[:30]}` | "
                f"{unit_ko} | `{c['cell']}` |")
        out += ["", "---", ""]

    out += [
        "확정해 주시면 `parser/xml/table_extractor.py::_SOURCE_TYPO_CELL_FIXES` 에",
        "근거 주석과 함께 등재하고 `scripts/backfill_r158_dot_grouped.py --apply` 로",
        "백필합니다.",
        "",
    ]
    text_out = "\n".join(out)
    if args.write:
        _OUT.write_text(text_out, encoding="utf-8")
        print("\n문서 생성: %s" % _OUT)
    else:
        print(text_out[:3000])
    print("\n필링 %d건 · 셀 %d개" % (len(found), n_cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
