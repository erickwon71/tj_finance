"""복구된 구형 레이아웃 filing 을 **원문과 1:1 대조**한다 (R9 — 집계로 끝내지 않는다).

`verify_legacy_detector.py` 는 "표가 몇 개 잡혔나"까지만 본다. 표가 잡혔다는 것과
**값이 원문 그대로인가**는 다른 문제다. 여기서는 실제 계층2 추출기
(`extract_report_lines`)를 돌려 나온 행을, 같은 문서에서 직접 읽은 원문 셀과 대조한다.

대조 방식 — 추출된 (statement, label, col0 값)을 원문 표의 (라벨행, 첫 금액셀)과 맞춘다.
값이 다르거나 원문에 없는 라벨이 나오면 **오파싱**이고, 원문에 있는데 안 나오면 **거짓 부재**다.
둘 다 R0 의 감시 대상이다.

사용:
    python scripts/verify_legacy_against_source.py --rcept 20141128001023
    python scripts/verify_legacy_against_source.py --sample 12
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (
    table_direct_rows, assign_tables_to_dart_sections, SEC_CONSOL_FS, SEC_SEP_FS,
)
from parser.xml.table_extractor import _get_cells
from fin2.extract.report_lines import extract_report_lines
from fin2.extract.text import _detect_body_statement_tables, _detect_fin_type

from scripts.probe_legacy_layout_gap import SQL_GAP

_AMOUNT = re.compile(r"^\(?-?\d{1,3}(?:,\d{3})+\)?$")


def _amount_of(cell: str, unit: int) -> int | None:
    """'(1,234)' / '-1,234' → 부호 있는 정수 × 단위. 금액셀이 아니면 None."""
    if not _AMOUNT.match(cell):
        return None
    neg = cell.startswith("(") or cell.startswith("-")
    digits = re.sub(r"[^\d]", "", cell)
    if not digits:
        return None
    v = int(digits) * (unit or 1)
    return -v if neg else v


def norm_label(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def source_cells(root, fin_type: str) -> dict[str, dict[str, set]]:
    """감지기가 고른 표들에서 (섹션코드 → {정규화라벨: {그 행의 금액값 집합}}) 를 직접 읽는다.

    ★ 열 위치로 대조하지 않는다 — 원문 표는 [당기3개월, 당기누적, 전기…] 처럼 열 구성이
      제각각이라, 위치를 가정하면 **대조기 자신이 틀린다**(2026-08-04 세션에서 실제로 겪음).
      "적재된 당기값이 그 행의 원문 금액 중 하나인가"만 묻는다.
    """
    out: dict[str, dict[str, set]] = {}
    groups = _detect_body_statement_tables(root, fin_type, include_sce=True)
    for code, tables in groups.items():
        if code.startswith("SCE"):
            continue                       # SCE 는 열이 기간축이 아니라 별도 규약 — 대조 제외
        d = out.setdefault(code, {})
        for tbl, unit, _kind in tables:
            for tr in table_direct_rows(tbl):
                cells = [c.strip() for c in _get_cells(tr)]
                label = next((c for c in cells if c and not _AMOUNT.match(c)), None)
                if not label:
                    continue
                vals = {v for c in cells if (v := _amount_of(c, unit or 1)) is not None}
                if vals:
                    d.setdefault(norm_label(label), set()).update(vals)
    return out


def check(rcept: str, fpth: str, corp_code: str, fy: int, fp: str) -> tuple[int, int, int]:
    root = _parse_xml_file(Path(fpth))
    src = source_cells(root, _detect_fin_type(root))
    lines = extract_report_lines(fpth, rcept_no=rcept, corp_code=corp_code,
                                 report_fiscal_year=fy, report_fiscal_period=fp)

    # 추출 행 → {섹션코드: {라벨: {값들}}} (당기 col0 만)
    got: dict[str, dict[str, set]] = {}
    for ln in lines:
        if ln.statement in ("note", "SCE") or (ln.col_index or 0) != 0:
            continue
        if ln.value_won is None:
            continue                       # 단위 미확정 등으로 보류된 칸 — 값 대조 대상 아님
        code = f"{ln.statement}_{'C' if ln.basis == 'consolidated' else 'S'}"
        got.setdefault(code, {}).setdefault(norm_label(ln.label_raw), set()).add(ln.value_won)

    n_match = n_diff = n_missing = 0
    for code, cells in src.items():
        g = got.get(code, {})
        for label, amounts in cells.items():
            if label not in g:
                n_missing += 1
                if n_missing <= 5:
                    print(f"   거짓부재 {code} {label!r} 원문={sorted(amounts)[:3]}")
                continue
            loaded = g[label]
            if loaded & amounts:
                n_match += 1
            else:
                n_diff += 1
                if n_diff <= 5:
                    print(f"   불일치  {code} {label!r} "
                          f"원문={sorted(amounts)[:4]} 적재={sorted(loaded)[:4]}")
    return n_match, n_diff, n_missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rcept")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--legacy-only", action="store_true",
                    help="구형 레이아웃(본문섹션 없음) 문서만 대조")
    ap.add_argument("--control", type=int, default=0,
                    help="통제군: 이미 적재된 현대 서식 N건에 같은 대조기를 건다. "
                         "대조기 자신의 잡음 수준을 재기 위한 것")
    args = ap.parse_args()

    with get_session() as s:
        tasks = {r[0]: r[1] for r in s.execute(text(
            "SELECT rcept_no, file_path FROM download_tasks")).fetchall()}
        if args.rcept:
            rows = s.execute(text("""
                SELECT corp_code, corp_name, fiscal_year, fiscal_period, report_type,
                       rcept_no, filed_at FROM filings WHERE rcept_no=:r
            """), {"r": args.rcept}).fetchall()
        elif args.control:
            rows = [(r[0], r[1], r[2], r[3], None, r[4], None) for r in s.execute(text("""
                SELECT f.corp_code, f.corp_name, f.fiscal_year, f.fiscal_period, f.rcept_no
                  FROM filings f
                 WHERE f.fiscal_year >= 2015
                   AND EXISTS (SELECT 1 FROM report_lines r WHERE r.rcept_no = f.rcept_no)
                 ORDER BY md5(f.rcept_no) LIMIT :n
            """), {"n": args.control}).fetchall()]
        else:
            rows = s.execute(text(SQL_GAP)).fetchall()

    tot_m = tot_d = tot_x = 0
    done = 0
    worst: list[tuple] = []
    for corp_code, corp_name, fy, fp, rt, rcept, filed in rows:
        fpth = tasks.get(rcept)
        if not fpth or not Path(fpth).exists():
            continue
        root = _parse_xml_file(Path(fpth))
        if root is None:
            continue
        sec = assign_tables_to_dart_sections(root)
        is_legacy = not sec.get(SEC_CONSOL_FS) and not sec.get(SEC_SEP_FS)
        if args.legacy_only and not is_legacy:
            continue
        if not _detect_body_statement_tables(root, _detect_fin_type(root), include_sce=True):
            continue
        print(f"── {corp_name} {fy}{fp} {rcept} legacy={is_legacy}")
        m, d, x = check(rcept, fpth, corp_code, fy, fp)
        print(f"   일치={m} 불일치={d} 거짓부재={x}")
        tot_m += m
        tot_d += d
        tot_x += x
        worst.append((x, d, corp_name, fy, fp, rcept, is_legacy))
        done += 1
        if args.sample and done >= args.sample:
            break

    print("\n=== 거짓부재 상위 10 ===")
    for x, d, corp_name, fy, fp, rcept, lg in sorted(worst, reverse=True)[:10]:
        print(f"  부재={x:5d} 불일치={d:4d}  {corp_name} {fy}{fp} {rcept} legacy={lg}")

    print(f"\n=== 합계 {done}건 ===")
    print(f"  일치     : {tot_m}")
    print(f"  불일치   : {tot_d}  (오파싱 — 0 이어야 함)")
    print(f"  거짓부재 : {tot_x}  (원문에 있는데 미적재 — 0 이어야 함)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
