#!/usr/bin/env python
"""R163 규모 스캐너 — CF 현금 조정 항등식이 깨진 (필링, basis) 를 센다.

판정: `기초 + 순증감 + 환율효과 = 기말` 이 안 맞는데, 양수 셀 하나를 뒤집으면 정확히
맞는 경우. 부호만으로는 절대 못 잡는다 — 환율변동효과는 **양수가 정상인 경우가 더
많다**(2015+ 실측 양수 114,412셀 / 음수 83,639셀).

★DB 는 CF 의 `col_index=0`(당기)만 적재하므로 이 스캔은 당기 열만 본다. 비교연도 열의
같은 결함은 재추출 때 교정된다(수정이 `extract_report_lines` 안에 있다).

    python scripts/scan_cf_cash_sign_loss.py
    python scripts/scan_cf_cash_sign_loss.py --list 40
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.cf_cash_sign_repair import (
    _CLOSING_RE, _FX_EFFECT_RE, _FX_EXCLUDE_RE, _NET_CHANGE_EXCLUDE_RE,
    _NET_CHANGE_RE, _OPENING_RE,
)

_SQL = """
SELECT rl.rcept_no, rl.corp_code, c.corp_name, rl.basis, rl.table_seq,
       rl.row_order, rl.label_raw, rl.value_won
FROM report_lines rl
LEFT JOIN corporations c ON c.corp_code = rl.corp_code
WHERE rl.statement = 'CF' AND rl.col_index = 0
  AND rl.report_fiscal_year >= 2015
  AND rl.value_won IS NOT NULL
  AND (rl.label_raw LIKE '%현금%' OR rl.label_raw LIKE '%환율변동%')
"""


class _Row:
    __slots__ = ("label_raw", "value_won", "row_order")

    def __init__(self, label_raw, value_won, row_order):
        self.label_raw = label_raw
        self.value_won = value_won
        self.row_order = row_order


def _one(rows, pattern, exclude=None):
    hits = [r for r in rows
            if pattern.search((r.label_raw or "").strip())
            and not (exclude and exclude.search((r.label_raw or "").strip()))]
    return hits[0] if len(hits) == 1 else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", type=int, default=0)
    args = ap.parse_args()

    groups = defaultdict(list)
    meta = {}
    with get_session() as s:
        for r in s.execute(text(_SQL)).mappings():
            key = (r["rcept_no"], r["basis"], r["table_seq"])
            groups[key].append(_Row(r["label_raw"], int(r["value_won"]),
                                    r["row_order"]))
            meta[key] = (r["corp_name"] or r["corp_code"])

    n_scanned = n_broken = n_fixable = 0
    fixable = []
    for key, rows in groups.items():
        rows.sort(key=lambda x: (x.row_order if x.row_order is not None else 0))
        opening = _one(rows, _OPENING_RE)
        closing = _one(rows, _CLOSING_RE)
        net = _one(rows, _NET_CHANGE_RE, _NET_CHANGE_EXCLUDE_RE)
        fx = _one(rows, _FX_EFFECT_RE, _FX_EXCLUDE_RE)
        if not (opening and closing and net and fx):
            continue
        if opening.value_won < 0 or closing.value_won < 0:
            continue
        n_scanned += 1
        if opening.value_won + net.value_won + fx.value_won == closing.value_won:
            continue
        n_broken += 1
        winners = []
        for cand in (fx, net):
            if cand.value_won <= 0:
                continue
            total = (opening.value_won + net.value_won + fx.value_won
                     - 2 * cand.value_won)
            if total == closing.value_won:
                winners.append(cand)
        if len(winners) == 1:
            n_fixable += 1
            fixable.append((key, meta[key], winners[0]))

    print(f"4행 전부 식별된 (필링,basis,표): {n_scanned:,}")
    print(f"  항등식 깨짐:            {n_broken:,}")
    print(f"  ★단일 셀 뒤집기로 닫힘:   {n_fixable:,}   ← R163 대상")
    print(f"  (닫히지 않음 = 다른 원인:  {n_broken - n_fixable:,})")

    if args.list and fixable:
        print(f"\n상위 {args.list}건:")
        for (rcept, basis, _t), name, row in fixable[:args.list]:
            print(f"  {rcept}  {basis[:3]}  {name[:16]:18} "
                  f"{row.label_raw[:28]:30} {row.value_won:>18,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
