#!/usr/bin/env python
"""단위 배수가 걸린 재무제표 표에서 **소수점 표기 셀**을 찾는다 — 정밀도 유실 규모 측정.

## 왜 세는가

`parse_amount()` 는 소수부를 **단위 배수 적용 전에** 버린다. 그래서 `(단위: 백만원)`
표에 소수 표기가 있으면 조용히 값이 깎인다:

    '1,234.5'  백만원 → 1,234,000,000  (정확값 1,234,500,000)
    '0.5'      백만원 → 0              (정확값 500,000)   ← 통째로 사라진다

결측이 아니라 **값 왜곡**이라 기존 검산이 못 잡는다(그럴듯한 값이 들어 있다).

★함께 세는 다른 계열 — 엘에스일렉트릭 20260318001243(캠페인 이슈#22): 단위 선언이
**아예 없는** 표인데 한 열 안에서 원 단위 정수와 백만원 소수 표기가 **섞여** 있다.
그 경우 소수 셀은 10⁶ 배 작게 적재된다. 배수가 1 인 표의 소수 셀도 따로 센다.

★`(69.0)` → -69 처럼 **소수부 절삭이 맞는 경우도 있다**(EPS, 주당 단위는 원 단위
소수가 정상이다). 그래서 EPS 로 보이는 라벨은 제외한다 — 일반 규칙화의 함정이다.

## 사용법

    python scripts/scan_decimal_cells.py --limit 300 --breadth
    python scripts/scan_decimal_cells.py --corp 00105855
    python scripts/scan_decimal_cells.py --report
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.table_extractor import _get_cells
from parser.xml.section_detector import table_direct_rows
import fin2.extract.text as _text

_OUT = Path(__file__).resolve().parents[1] / "docs/qa/decimal_cell_scan.jsonl"
_L2R = Path(__file__).resolve().parent / "layer2_review.py"

_SCOPES = ("BS_C", "IS_C", "CF_C", "SCE_C", "BS_S", "IS_S", "CF_S", "SCE_S")

# 금액처럼 보이면서 **소수점**을 가진 셀. 천단위 콤마가 있거나 4자리 이상인 것만 —
# '0.5' 같은 작은 값도 대상이므로 콤마를 요구하지는 않는다.
_DECIMAL_CELL_RE = re.compile(
    r"^[(\[]?\s*[-−△▲]?\s*\d{1,3}(?:,\d{3})*\.\d+\s*[)\]]?$"
    r"|^[(\[]?\s*[-−△▲]?\s*\d+\.\d+\s*[)\]]?$")

# ★EPS 류는 제외 — 주당 금액은 원 단위 소수가 정상이고, 절삭이 오히려 맞다.
_EPS_LABEL_RE = re.compile(r"주당|per\s*share", re.I)


def _resolve_source_fn():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_l2r", _L2R)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._resolve_source


_TARGETS_SQL = """
    SELECT rcept_no, corp_code, corp_name, corp_rank, fiscal_year, fiscal_period
    FROM layer2_review_queue
    WHERE fiscal_year >= 2015 {corp_filter}
    ORDER BY corp_rank NULLS LAST, corp_code, fiscal_year DESC, rcept_no
"""

_BREADTH_SQL = """
    SELECT DISTINCT ON (corp_code)
           rcept_no, corp_code, corp_name, corp_rank, fiscal_year, fiscal_period
    FROM layer2_review_queue
    WHERE fiscal_year >= 2015 {corp_filter}
    ORDER BY corp_code, fiscal_year DESC, rcept_no
"""


def scan_one(path: str) -> list[dict]:
    root = _parse_xml_file(path)
    ft = _text._detect_fin_type(root, file_path=path)
    groups = _text._detect_body_statement_tables(root, ft, include_sce=True)

    hits: list[dict] = []
    for key in _SCOPES:
        for entry in groups.get(key, []):
            table = entry[0] if isinstance(entry, (tuple, list)) else entry
            if table is None:
                continue
            # 표의 선언 단위(`declared_unit`). 표 자체에 선언이 없으면 None —
            # 엘에스일렉트릭류(선언 없음 + 열 안에서 표기 혼재)가 그 경우다.
            try:
                unit = _text.declared_unit(table)
            except Exception:                                     # noqa: BLE001
                unit = None
            for tr in table_direct_rows(table):
                cells = _get_cells(tr)
                if not cells:
                    continue
                label = cells[0].strip()
                if not label or _EPS_LABEL_RE.search(label):
                    continue
                for ci, cell in enumerate(cells[1:], start=1):
                    txt = (cell or "").strip()
                    if not txt or not _DECIMAL_CELL_RE.match(txt):
                        continue
                    hits.append({"scope": key, "label": label[:60],
                                 "cell_index": ci, "cell": txt,
                                 "declared_unit": unit})
    return hits


def report() -> None:
    if not _OUT.exists():
        print("아직 스캔 결과가 없습니다.")
        return
    n = hit_files = n_cells = 0
    by_corp, by_scope, by_unit, errors = Counter(), Counter(), Counter(), Counter()
    with _OUT.open() as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            n += 1
            if rec.get("error"):
                errors[rec["error"][:60]] += 1
                continue
            hits = rec.get("hits") or []
            if not hits:
                continue
            hit_files += 1
            n_cells += len(hits)
            by_corp[rec["corp_name"]] += len(hits)
            for h in hits:
                by_scope[h["scope"]] += 1
                by_unit[str(h.get("declared_unit"))] += 1
    print(f"스캔 {n:,}건 · 발화 {hit_files:,}건"
          f"{f' ({hit_files / n:.1%})' if n else ''} · 소수셀 {n_cells:,} · "
          f"오류 {sum(errors.values()):,}건")
    print(f"\n회사별(상위 20): {by_corp.most_common(20)}")
    print(f"\n재무제표별: {by_scope.most_common()}")
    print(f"\n선언단위별: {by_unit.most_common()}")
    if errors:
        print(f"\n오류: {errors.most_common(5)}")


def load_done() -> set[str]:
    if not _OUT.exists():
        return set()
    done = set()
    with _OUT.open() as fh:
        for line in fh:
            try:
                done.add(json.loads(line)["rcept_no"])
            except (ValueError, KeyError):
                continue
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--breadth", action="store_true")
    ap.add_argument("--corp")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    if args.report:
        report()
        return 0

    resolve_source = _resolve_source_fn()
    done = load_done()
    sql = (_BREADTH_SQL if args.breadth else _TARGETS_SQL).format(
        corp_filter="AND corp_code = :corp" if args.corp else "")

    n = n_hit = 0
    with get_session() as s, _OUT.open("a") as out:
        rows = s.execute(text(sql),
                         {"corp": args.corp} if args.corp else {}).mappings().all()
        for r in rows:
            if n >= args.limit:
                break
            if r["rcept_no"] in done:
                continue
            rec = {"rcept_no": r["rcept_no"], "corp_code": r["corp_code"],
                   "corp_name": r["corp_name"], "fiscal_year": r["fiscal_year"]}
            try:
                _kind, path = resolve_source(s, r["rcept_no"])
                rec["hits"] = scan_one(path)
            except Exception as exc:                              # noqa: BLE001
                rec["error"] = f"{type(exc).__name__}: {exc}"
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            n += 1
            if rec.get("hits"):
                n_hit += 1
            if n % 25 == 0:
                print(f"  ... {n}/{args.limit} (발화 {n_hit})", flush=True)

    print(f"\n이번 실행: {n:,}건 처리, 발화 {n_hit:,}건 → {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
