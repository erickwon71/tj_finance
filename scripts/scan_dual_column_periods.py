#!/usr/bin/env python
"""한 기간을 물리적으로 2열(내역칸/잔액칸)로 찍는 표에서 **양쪽이 다 찬 행**을 센다.

## 왜 세는가

`select_by_header_columns()` 는 구분 텍스트(subtype)가 없는 병합군에서 "행별 유일값"
규칙을 쓴다 — 실값이 정확히 1개면 채택, **2개 이상이면 판정불가로 그 rank 를 건너뛴다**
(R6 "오염보다 결측"). 그 결과 양쪽이 다 찬 행은 `pairs` 가 비어 **행 자체가 흔적 없이
사라진다**.

실측(티로보틱스 20180402000209 별도 대차대조표, FY2017): 구형 서식이라 한 연도가
[내역칸, 잔액칸] 2열이고, 대부분 행은 한쪽만 채우지만 **그룹 마감행**(평가충당금·
감가상각누계액·국고보조금·신주인수권조정·퇴직연금운영자산)은 양쪽을 다 채운다:

    원  재  료          2,348,042,580
    원재료평가충당금       30,712,381    2,317,330,199   ← 통째로 유실

산수로 어느 칸이 그 행의 값인지는 확정된다(건물 2,939,077,158 − 감가상각누계액
470,337,475 = 2,468,739,683 = 잔액칸). 즉 왼쪽=그 행 자신의 금액, 오른쪽=직전 그룹의
잔액이다. 그래도 규칙을 바꾸기 전에 **영향 범위를 먼저 안다** — R6 정책을 건드리는
변경이고 같은 코드 경로를 보험·증권사 명세/소계 서식도 쓰기 때문이다.

★`is_ifrs` 로는 못 잰다. 2015+ 에 K-GAAP **회계기준** 필링은 사실상 0건인데(실측:
2016년 링크제니시스 2건뿐) 티로보틱스는 IFRS 필링이면서 **인쇄 서식**만 구형이다.
그래서 회계기준이 아니라 구조로 센다.

## 사용법

    python scripts/scan_dual_column_periods.py --limit 300 --breadth
    python scripts/scan_dual_column_periods.py --limit 300 --corp 00981192
    python scripts/scan_dual_column_periods.py --report

센서스와 같은 재개 규약: JSONL 로 append 하고 다시 돌리면 처리한 rcept 는 건너뛴다.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.table_extractor import (extract_rows, parse_header_columns,
                                        select_by_header_columns)
import fin2.extract.text as _text

_OUT = Path(__file__).resolve().parents[1] / "docs/qa/dual_column_scan.jsonl"
_L2R = Path(__file__).resolve().parent / "layer2_review.py"

# 본문 재무제표 그룹 → (basis, statement). SCE 는 열축이 기간이 아니라 자본 구성요소라
# 이 규칙의 대상이 아니다(`select_by_header_columns` 도 SCE 는 안 탄다).
_SCOPES = {
    "BS_C": ("consolidated", "BS"), "IS_C": ("consolidated", "IS"),
    "CF_C": ("consolidated", "CF"),
    "BS_S": ("separate", "BS"), "IS_S": ("separate", "IS"),
    "CF_S": ("separate", "CF"),
}


def _resolve_source_fn():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_l2r", _L2R)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._resolve_source


_TARGETS_SQL = """
    SELECT rcept_no, corp_code, corp_name, corp_rank, fiscal_year, fiscal_period
    FROM layer2_review_queue
    WHERE fiscal_year >= 2015
      {corp_filter}
    ORDER BY corp_rank NULLS LAST, corp_code, fiscal_year DESC, rcept_no
"""

_BREADTH_SQL = """
    SELECT DISTINCT ON (corp_code)
           rcept_no, corp_code, corp_name, corp_rank, fiscal_year, fiscal_period
    FROM layer2_review_queue
    WHERE fiscal_year >= 2015
      {corp_filter}
    ORDER BY corp_code, fiscal_year ASC, rcept_no
"""


def _dual_ranks(header_cols) -> dict[int, list[int]]:
    """구분 텍스트 없는 2열 이상 병합군 → {period_rank: [물리열 위치…]}.

    subtype 이 하나라도 붙어 있으면(3개월/누적) 이 규칙의 대상이 아니다 — 그건
    R116/R144 가 다루는 전혀 다른 축이다.
    """
    by_rank: dict[int, list] = {}
    for hc in header_cols or []:
        if hc.is_note:
            continue
        by_rank.setdefault(hc.period_rank, []).append(hc)
    out = {}
    for rank, cols in by_rank.items():
        if len(cols) >= 2 and all(c.subtype is None for c in cols):
            out[rank] = sorted(c.position for c in cols)
    return out


def scan_one(path: str, fiscal_year: int) -> list[dict]:
    """이 필링에서 '양쪽 다 찬 행'을 모아 반환한다(없으면 빈 리스트)."""
    root = _parse_xml_file(path)
    ft = _text._detect_fin_type(root, file_path=path)
    groups = _text._detect_body_statement_tables(root, ft, include_sce=False)

    hits: list[dict] = []
    for key, (basis, statement) in _SCOPES.items():
        for entry in groups.get(key, []):
            table = entry[0] if isinstance(entry, (tuple, list)) else entry
            if table is None:
                continue
            header_cols = parse_header_columns(
                table, allow_duplicate_subtype=(fiscal_year >= 2015))
            ranks = _dual_ranks(header_cols)
            if not ranks:
                continue
            n_cols = max(c.position for c in header_cols) + 1
            for row in extract_rows(table, multiplier=1, num_cols=n_cols,
                                    direct_only=True, skip_junk=False,
                                    keep_all_amount_cells=True):
                label = (row.account_name or "").strip()
                if not label:
                    continue
                # ★판정 오라클은 프로덕션 함수 자신이다 — "버려졌다"를 내가 다시
                #   추측하면 정상 적재 행까지 센다(초판 실측: 자산총계·유동자산 등
                #   138행 과탐). 실제로 그 rank 가 결과에서 빠졌는지만 본다.
                picked = select_by_header_columns(
                    header_cols, row.amounts, raw_amounts=row.raw_amounts)
                for rank, positions in ranks.items():
                    # ★rank 0(당기)만 진짜 유실이다 — `store_report_lines()` 는
                    #   BS/IS/CF 를 `_PERIOD_AXIS_STATEMENTS` 정책대로 col_index=0
                    #   만 적재하므로, 전기/전전기가 안 뽑혀도 DB 에서 잃는 것이
                    #   없다. 이 필터 없이 세면 티로보틱스 FY2018/FY2019 처럼
                    #   **정상 적재된 필링**이 123행 유실로 잡힌다(실측 확인:
                    #   유동자산·자산총계 둘 다 col=0 으로 멀쩡히 적재돼 있었다).
                    if rank != 0 or rank in picked:
                        continue
                    real = [row.amounts[p] for p in positions
                            if p < len(row.amounts) and row.amounts[p] is not None]
                    # 실값이 2개 이상 서로 다르게 있는데 채택이 없다 = R6 판정불가로
                    # 버려진 행(값이 전부 같으면 R131 이 이미 채택하므로 유실 아님).
                    if len(real) >= 2 and len(set(real)) > 1:
                        hits.append({
                            "basis": basis, "statement": statement,
                            "rank": rank, "label": label,
                            "values": [str(v) for v in real],
                        })
                        break
    return hits


def report() -> None:
    if not _OUT.exists():
        print("아직 스캔 결과가 없습니다.")
        return
    n = hit_files = 0
    by_corp, by_scope, by_label, errors = Counter(), Counter(), Counter(), Counter()
    n_rows = 0
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
            n_rows += len(hits)
            by_corp[rec["corp_name"]] += 1
            for h in hits:
                by_scope[f'{h["basis"][:3]}/{h["statement"]}'] += 1
                by_label[h["label"]] += 1
    print(f"스캔 {n:,}건 · 발화 {hit_files:,}건"
          f"{f' ({hit_files / n:.1%})' if n else ''} · 유실행 {n_rows:,} · "
          f"오류 {sum(errors.values()):,}건")
    print(f"\n회사별 발화(상위 20): {by_corp.most_common(20)}")
    print(f"\n재무제표별: {by_scope.most_common()}")
    print(f"\n라벨별(상위 25): {by_label.most_common(25)}")
    if errors:
        print(f"\n오류 유형: {errors.most_common(5)}")


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
    ap.add_argument("--breadth", action="store_true",
                    help="회사별 1건씩 넓게(계열 탐색용, 권장)")
    ap.add_argument("--corp", help="corp_code 한정")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    if args.report:
        report()
        return 0

    resolve_source = _resolve_source_fn()
    done = load_done()
    sql = _BREADTH_SQL if args.breadth else _TARGETS_SQL
    sql = sql.format(corp_filter="AND corp_code = :corp" if args.corp else "")

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
                   "corp_name": r["corp_name"], "fiscal_year": r["fiscal_year"],
                   "fiscal_period": r["fiscal_period"]}
            try:
                _kind, path = resolve_source(s, r["rcept_no"])
                rec["hits"] = scan_one(path, r["fiscal_year"] or 2015)
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
    print("이어서 돌리려면 같은 명령을 다시 실행하세요(처리한 건은 건너뜁니다).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
