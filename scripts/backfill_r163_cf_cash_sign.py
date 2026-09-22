#!/usr/bin/env python
"""R163 백필 — CF 현금 조정 부호가 깨진 필링을 재추출해 재적재한다.

후보는 `scripts/scan_cf_cash_sign_loss.py` 와 같은 판정(항등식이 깨졌고 양수 셀 하나를
뒤집으면 정확히 닫힘)으로 고른다. 실측(2026-09-22): **61건**.

★재적재는 그 필링 전체를 다시 쓴다 — 그래서 R162(SCE)까지 함께 반영된다. 로그는
CF/SCE 를 나눠 보여 준다.

`store_report_lines()` 의 수동입력·R139 원문대조-pass 보호는 **끄지 않는다**.

    python scripts/backfill_r163_cf_cash_sign.py
    python scripts/backfill_r163_cf_cash_sign.py --apply
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
    _NET_CHANGE_RE, _OPENING_RE, repair_cf_cash_sign_loss,
)
from fin2.extract.report_lines import extract_report_lines, store_report_lines
from fin2.extract.sce_sign_repair import repair_sce_sign_loss

_L2R = Path(__file__).resolve().parent / "layer2_review.py"

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


def _candidates(session):
    groups = defaultdict(list)
    info = {}
    for r in session.execute(text(_SQL)).mappings():
        key = (r["rcept_no"], r["basis"], r["table_seq"])
        groups[key].append(_Row(r["label_raw"], int(r["value_won"]),
                                r["row_order"]))
        info[r["rcept_no"]] = (r["corp_code"], r["corp_name"] or r["corp_code"])

    out = {}
    for (rcept, _basis, _t), rows in groups.items():
        rows.sort(key=lambda x: (x.row_order if x.row_order is not None else 0))
        opening = _one(rows, _OPENING_RE)
        closing = _one(rows, _CLOSING_RE)
        net = _one(rows, _NET_CHANGE_RE, _NET_CHANGE_EXCLUDE_RE)
        fx = _one(rows, _FX_EFFECT_RE, _FX_EXCLUDE_RE)
        if not (opening and closing and net and fx):
            continue
        if opening.value_won < 0 or closing.value_won < 0:
            continue
        base = opening.value_won + net.value_won + fx.value_won
        if base == closing.value_won:
            continue
        winners = [x for x in (fx, net) if x.value_won > 0
                   and base - 2 * x.value_won == closing.value_won]
        if len(winners) == 1:
            out[rcept] = info[rcept]
    return out


def _resolve_source_fn():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_l2r", _L2R)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._resolve_source


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    resolve_source = _resolve_source_fn()
    n_applied = n_blocked = 0
    cf_cells = sce_cells = 0

    with get_session() as s:
        cands = _candidates(s)
        print(f"후보 {len(cands)}필링\n")
        for rcept, (corp_code, corp_name) in sorted(cands.items()):
            it = s.execute(text("""
                SELECT fiscal_year, fiscal_period, status
                FROM layer2_review_queue WHERE rcept_no = :r"""),
                {"r": rcept}).mappings().first()
            if not it:
                print(f"  {rcept}  {corp_name}  (큐에 없음 — 건너뜀)")
                continue
            try:
                _kind, path = resolve_source(s, rcept)
                lines = extract_report_lines(
                    path, rcept_no=rcept, corp_code=corp_code,
                    report_fiscal_year=it["fiscal_year"],
                    report_fiscal_period=it["fiscal_period"])
            except Exception as exc:                              # noqa: BLE001
                print(f"  {rcept}  {corp_name}  ERROR "
                      f"{type(exc).__name__}: {exc}")
                continue

            # 이미 추출 안에서 복원됐다 — 두 번째 호출은 0 이어야 한다(멱등성).
            assert not repair_cf_cash_sign_loss(lines)
            assert not repair_sce_sign_loss(lines)

            # ★CF 는 col_index=0 만 DB 로 간다(_is_loadable / _PERIOD_AXIS_
            # STATEMENTS). 추출기 전체 출력과 DB 를 비교하면 비교연도 열까지 세어
            # 델타가 부풀려진다 — "추출됐다 ≠ DB 에 실린다".
            n_cf_neg = sum(1 for l in lines if l.statement == "CF"
                           and (l.col_index or 0) == 0
                           and (l.value_won or 0) < 0)
            db_cf_neg = s.execute(text("""
                SELECT count(*) FROM report_lines
                WHERE rcept_no=:r AND statement='CF' AND value_won < 0"""),
                {"r": rcept}).scalar_one()
            n_sce_neg = sum(1 for l in lines if l.statement == "SCE"
                            and (l.value_won or 0) < 0)
            db_sce_neg = s.execute(text("""
                SELECT count(*) FROM report_lines
                WHERE rcept_no=:r AND statement='SCE' AND value_won < 0"""),
                {"r": rcept}).scalar_one()
            d_cf = n_cf_neg - db_cf_neg
            d_sce = n_sce_neg - db_sce_neg
            cf_cells += max(d_cf, 0)
            sce_cells += max(d_sce, 0)
            print(f"  {rcept}  {corp_name[:16]:18} "
                  f"CF 음수 {db_cf_neg}→{n_cf_neg} (+{d_cf})  "
                  f"SCE {db_sce_neg}→{n_sce_neg} (+{d_sce})  "
                  f"status={it['status']}")

            if args.apply:
                try:
                    store_report_lines(s, rcept, lines)
                    s.commit()
                    n_applied += 1
                except ValueError as guard:
                    s.rollback()
                    n_blocked += 1
                    print(f"       ⚠ 보호됨(덮지 않음): {str(guard)[:110]}")

    mode = "적재" if args.apply else "검사만(DB 미변경)"
    print(f"\n[{mode}] CF +{cf_cells}셀 · SCE +{sce_cells}셀 · "
          f"적재 {n_applied}건 · 보호됨 {n_blocked}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
