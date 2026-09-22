#!/usr/bin/env python
"""재무제표의 **마침표 오타 셀** 후보를 사용자 확인용 목록 문서로 만든다.

## 왜 문서로 뽑는가

사용자 정책(2026-09-22): *"재무문서에 '.' 으로 되어 있는 큰 금액 오타를 반올림해서
적재하거나 그대로 하지 말고, 오타로 보고해서 나에게 확인 요청할 리스트 문서를
제공하라."*

종전 동작은 어느 쪽이든 **정밀해 보이는 틀린 값**을 DB 에 남겼다(절삭이면 10³~10⁶ 배
작고, R157 반올림이면 ±1 만 움직이고 여전히 10³ 배 작다). 값이 그럴듯하니 검산도
통과한다. 그래서 R160 이 그런 칸을 **결측**으로 남기고, 이 스크립트가 **확인 요청
목록**을 만든다. 사용자가 확정하면 R159 예외목록(`_SOURCE_TYPO_CELL_FIXES`)에 등재하고
백필한다.

## 근거를 같이 뽑는다 — 사용자가 원문을 덜 뒤지게

셀마다 두 종류의 근거를 자동으로 찾아 붙인다(R159 등재 조건과 같은 두 갈래):

  (가) **정수판이 원문 다른 곳에 있다** — 같은 행·같은 열·다른 표·반대 basis 어디든,
       숫자열이 접두사로 일치하고 남는 꼬리가 전부 0 인 정수 셀.
  (나) **그 행의 합계 항등식이 닫힌다** — 마침표를 콤마로 되돌린 값으로 구성요소 두
       개를 더해 마지막 열(합계)과 정확히 일치하는 조합.

둘 다 없으면 "근거 없음"으로 표시한다 — 그런 셀은 사용자가 DART 원문을 직접 봐야 한다.

★근거가 있어도 **자동 등재하지 않는다.** 등재는 사람 확인 후 수동이다(R6 취지).

## 사용법

    python scripts/report_dot_typo_candidates.py --limit 300 --breadth
    python scripts/report_dot_typo_candidates.py --corp 00119140
    python scripts/report_dot_typo_candidates.py --write      # 문서 생성

출력: `docs/qa/dot_typo_candidates_<날짜>.md`
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.table_extractor import (_get_cells, _DOT_GROUPED_RE,
                                        _SOURCE_TYPO_CELL_FIXES,
                                        _repair_dot_grouped_cells,
                                        apply_source_typo_fixes,
                                        unresolved_dot_cell_indices)
from parser.xml.section_detector import table_direct_rows
import fin2.extract.text as _text

_OUT_DIR = Path(__file__).resolve().parents[1] / "docs/qa"
_L2R = Path(__file__).resolve().parent / "layer2_review.py"
_DART = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept}"

_SCOPE_KO = {
    "BS_C": "[연결] 재무상태표", "BS_S": "[별도] 재무상태표",
    "IS_C": "[연결] 손익계산서", "IS_S": "[별도] 손익계산서",
    "CF_C": "[연결] 현금흐름표", "CF_S": "[별도] 현금흐름표",
    "SCE_C": "[연결] 자본변동표", "SCE_S": "[별도] 자본변동표",
    "APPR_C": "[연결] 이익잉여금처분계산서", "APPR_S": "[별도] 이익잉여금처분계산서",
}
# ★주당손익 배제는 **파서와 같은 판정**을 써야 한다. 초판은 이 스크립트가 자기
#   정규식(`주당` 만)을 들고 있어, 파서가 정상 처리한 에스티아이
#   `'희석당기순이익 (단위 : 원)'` 4셀을 "적재 안 됨"으로 잘못 보고했다 — 확인
#   요청 문서가 멀쩡한 셀을 물어보게 된다. `unresolved_dot_cell_indices()` 를
#   그대로 호출해 단일 판정원을 유지한다(R144/R153 교훈).


def _resolve_source_fn():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_l2r", _L2R)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._resolve_source


def _digits(t: str) -> str:
    return re.sub(r"[^\d]", "", t or "")


def _as_int(t: str):
    """마침표를 콤마로 되돌렸다고 가정한 정수값(부호 유지)."""
    t = (t or "").strip()
    d = _digits(t)
    if not d:
        return None
    v = int(d)
    return -v if t.startswith("(") or t.startswith("-") else v


def scan_one(path: str, rcept_no: str) -> list[dict]:
    """이 필링의 미해결 마침표 셀 + 근거를 모아 반환한다."""
    root = _parse_xml_file(path)
    ft = _text._detect_fin_type(root, file_path=path)
    groups = _text._detect_body_statement_tables(root, ft, include_sce=True)

    broken: list[dict] = []
    intact: dict[str, tuple[str, str, str]] = {}

    for key in _SCOPE_KO:
        for entry in groups.get(key, []):
            table = entry[0] if isinstance(entry, (tuple, list)) else entry
            if table is None:
                continue
            try:
                unit = _text.declared_unit(table)
            except Exception:                                     # noqa: BLE001
                unit = None
            for ri, tr in enumerate(table_direct_rows(table)):
                cells = _get_cells(tr)
                if not cells:
                    continue
                label = cells[0].strip()
                # ★파서 파이프라인과 **같은 순서**로 통과시킨 뒤 남는 칸만 보고한다:
                #   R159(오타 교정) → R158(행 안 정수 짝 복원) → R160(남은 것 결측).
                #   초판은 원본 셀에 바로 R160 판정을 걸어, R158 이 이미 복원하는
                #   칸(코오롱 '(138,959.866)' 등)까지 "적재 안 됨"으로 보고했다 —
                #   확인 요청 문서가 멀쩡한 셀을 물어보게 된다.
                amts = apply_source_typo_fixes(list(cells[1:]), rcept_no)
                amts = _repair_dot_grouped_cells(amts, label)
                unresolved = set(unresolved_dot_cell_indices(amts, label))
                for ci, c in enumerate(cells[1:], start=1):
                    t = (c or "").strip()
                    if not t:
                        continue
                    if _DOT_GROUPED_RE.match(t):
                        if ci - 1 not in unresolved:
                            continue
                        broken.append({"scope": key, "row": ri + 1, "col": ci,
                                       "label": label, "cell": t,
                                       "row_cells": cells, "unit": unit})
                    elif "." not in t and _digits(t):
                        intact.setdefault(_digits(t), (key, label, t))

    # 근거 붙이기
    for b in broken:
        d = _digits(b["cell"])
        b["twin"] = None
        for full, where in intact.items():
            if (len(full) >= len(d) and full.startswith(d)
                    and set(full[len(d):]) <= {"0"}):
                b["twin"] = (full, where)
                break
        # (나) 합계 항등식 — ★**깨진 셀의 가설값이 실제로 그 식에 들어갈 때만** 근거다.
        #   초판은 행 안에서 합이 맞는 아무 두 값을 잡았고, 그 결과 깨진 셀과 무관한
        #   조합을 근거처럼 보여줬다(실측: 핸즈코퍼레이션 자본금 칸에
        #   `93,409,170,815 + 208,771 = 93,409,379,586` 이 붙었다 — 지배지분+비지배지분
        #   합계 항등식이고 자본금과 상관없다). 확인 요청 문서에 무관한 산수를 근거로
        #   싣는 것은 판단을 흐린다.
        b["identity"] = None
        mine = _as_int(b["cell"])
        vals = [_as_int(c) for c in b["row_cells"][1:]]
        if mine and len(vals) >= 3 and vals[-1] is not None:
            comp = [v for v in vals[:-1] if v]
            total = vals[-1]
            for i in range(len(comp)):
                for j in range(i + 1, len(comp)):
                    if comp[i] + comp[j] != total:
                        continue
                    if mine not in (comp[i], comp[j]):
                        continue            # 내 값이 안 들어간 식은 근거가 아니다
                    b["identity"] = (comp[i], comp[j], total)
                    break
                if b["identity"]:
                    break
    return broken


_TARGETS_SQL = """
    SELECT rcept_no, corp_code, corp_name, fiscal_year, fiscal_period, report_nm
    FROM layer2_review_queue
    WHERE fiscal_year >= 2015 {corp_filter}
    ORDER BY corp_rank NULLS LAST, corp_code, fiscal_year DESC, rcept_no
"""

_BREADTH_SQL = """
    SELECT DISTINCT ON (corp_code)
           rcept_no, corp_code, corp_name, fiscal_year, fiscal_period, report_nm
    FROM layer2_review_queue
    WHERE fiscal_year >= 2015 {corp_filter}
    ORDER BY corp_code, fiscal_year DESC, rcept_no
"""


def _render(found: dict[str, dict]) -> str:
    n_cells = sum(len(v["cells"]) for v in found.values())
    out = [
        f"# 마침표 오타 셀 — 확인 요청 목록 ({date.today()})",
        "",
        f"필링 **{len(found)}건** · 셀 **{n_cells}개**.",
        "",
        "재무제표 금액 칸에 천단위 구분자 자리에 **마침표**가 찍힌 셀입니다.",
        "이 칸들은 **DB 에 적재하지 않았습니다**(R160) — 절삭도 반올림도 틀린 값을",
        "남기기 때문입니다. 아래를 확인해 주시면 R159 예외목록에 등재하고 백필합니다.",
        "",
        "★단위 선언으로 예외를 두지 않습니다 — 천원/백만원 표의 소수가 정상이라는",
        "증거가 없어(실측 0건) 똑같이 확인 대상으로 올립니다. `단위` 열에 표시했습니다.",
        "",
        "판정해 주실 것: **오타인가**, 그리고 **정정값이 무엇인가**.",
        "",
        "- `정수판` = 같은 필링 원문 다른 곳에 인쇄된 정수(근거 가)",
        "- `항등식` = 그 행 합계가 정확히 닫히는 조합(근거 나)",
        "- 둘 다 없으면 DART 원문을 직접 보셔야 합니다.",
        "",
    ]
    for rcept, v in sorted(found.items()):
        out += [
            f"## {v['corp_name']} — {v['report_nm'] or ''}",
            "",
            f"- DART: {_DART.format(rcept=rcept)}",
            f"- rcept `{rcept}` · corp_code `{v['corp_code']}` · "
            f"{v['fiscal_year']}{v['fiscal_period']}",
            "",
            "| 재무제표 | 행 | 행 라벨 | 칸 | 단위 | 원문 셀 | 정수판(근거 가) | 항등식(근거 나) |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for b in v["cells"]:
            twin = "—"
            if b["twin"]:
                full, (wk, wl, wt) = b["twin"]
                twin = f"`{wt}` ← {_SCOPE_KO.get(wk, wk)} `{wl[:20]}`"
            ident = "—"
            if b["identity"]:
                a, c, t = b["identity"]
                ident = f"{a:,} + {c:,} = {t:,}"
            unit_ko = {1: "원", 1000: "천원", 1000000: "백만원"}.get(
                b.get("unit"), str(b.get("unit")))
            out.append(
                f"| {_SCOPE_KO.get(b['scope'], b['scope'])} | {b['row']} | "
                f"`{b['label'][:26]}` | {b['col']} | {unit_ko} | `{b['cell']}` | "
                f"{twin} | {ident} |")
        out.append("")
    out += [
        "---",
        "",
        "확정해 주시면 `parser/xml/table_extractor.py::_SOURCE_TYPO_CELL_FIXES` 에",
        "근거 주석과 함께 등재하고 `scripts/backfill_r158_dot_grouped.py --apply` 로",
        "백필합니다.",
        "",
    ]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--breadth", action="store_true")
    ap.add_argument("--corp")
    ap.add_argument("--write", action="store_true", help="문서 파일로 저장")
    args = ap.parse_args()

    resolve_source = _resolve_source_fn()
    sql = (_BREADTH_SQL if args.breadth else _TARGETS_SQL).format(
        corp_filter="AND corp_code = :corp" if args.corp else "")

    found: dict[str, dict] = {}
    n = 0
    with get_session() as s:
        rows = s.execute(text(sql),
                         {"corp": args.corp} if args.corp else {}).mappings().all()
        for r in rows:
            if n >= args.limit:
                break
            n += 1
            try:
                _kind, path = resolve_source(s, r["rcept_no"])
                cells = scan_one(path, r["rcept_no"])
            except Exception:                                     # noqa: BLE001
                continue
            if cells:
                found[r["rcept_no"]] = {
                    "corp_name": r["corp_name"], "corp_code": r["corp_code"],
                    "fiscal_year": r["fiscal_year"],
                    "fiscal_period": r["fiscal_period"],
                    "report_nm": r["report_nm"], "cells": cells}
            if n % 25 == 0:
                print(f"  ... {n}/{args.limit} (필링 {len(found)})", flush=True)

    doc = _render(found)
    if args.write:
        out = _OUT_DIR / f"dot_typo_candidates_{date.today()}.md"
        out.write_text(doc, encoding="utf-8")
        print(f"\n문서 생성: {out}")
    else:
        print(doc)
    print(f"\n스캔 {n:,}건 · 확인 요청 필링 {len(found)}건 · "
          f"셀 {sum(len(v['cells']) for v in found.values())}개")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
