#!/usr/bin/env python
"""R158 백필 — 마침표 구분자 셀이 있던 필링을 재추출해 값이 바뀌는 건만 적재한다.

## 대상 선정

`scripts/scan_decimal_cells.py` 가 찾은 필링을 재추출해, **DB 현재값과 다른 행이
하나라도 있으면** 백필 대상으로 본다. "소수 셀이 있었다"만으로는 부족하다 — 주당손익
처럼 손대지 않는 셀도 스캔에 걸리기 때문이다(에스티아이 '343.0').

## --apply 없이는 DB 를 건드리지 않는다

기본은 검사만. `store_report_lines()` 의 수동입력 보호와 R139 원문대조-pass 보호는
**끄지 않는다** — 보호된 건은 덮지 않고 목록으로 남겨 캠페인 세션이 재검토하게 한다.

★`layer2_review.py redo` 를 쓰지 않는다(`_current()` 계열이 다른 세션의 현재 항목을
가로챈 사고가 있었다 — 2026-09-21 owner 도입으로 코드로도 막혔지만, 백필은 애초에
이 경로를 쓰지 않는다).

## 사용법

    python scripts/backfill_r158_dot_grouped.py              # 검사만
    python scripts/backfill_r158_dot_grouped.py --apply      # 적재
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import extract_report_lines, store_report_lines

_SCAN = Path(__file__).resolve().parents[1] / "docs/qa/decimal_cell_scan.jsonl"
_L2R = Path(__file__).resolve().parent / "layer2_review.py"

# 이슈#22 본건 — breadth 표본에는 없었으므로 명시적으로 포함한다.
_EXTRA = ("20260318001243",)


def _resolve_source_fn():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_l2r", _L2R)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._resolve_source


def _targets() -> list[str]:
    out = []
    if _SCAN.exists():
        with _SCAN.open() as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("hits"):
                    out.append(rec["rcept_no"])
    for r in _EXTRA:
        if r not in out:
            out.append(r)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="DB 에 실제로 적재")
    args = ap.parse_args()

    resolve_source = _resolve_source_fn()
    targets = _targets()
    print(f"대상 후보 {len(targets)}건\n")

    n_changed = n_applied = n_blocked = n_cosmetic_only = 0
    with get_session() as s:
        for rcept in targets:
            it = s.execute(text("""
                SELECT corp_code, corp_name, fiscal_year, fiscal_period, status
                FROM layer2_review_queue WHERE rcept_no = :r"""),
                {"r": rcept}).mappings().first()
            if not it:
                print(f"  {rcept}  (큐에 없음 — 건너뜀)")
                continue
            try:
                _kind, path = resolve_source(s, rcept)
                lines = extract_report_lines(
                    path, rcept_no=rcept, corp_code=it["corp_code"],
                    report_fiscal_year=it["fiscal_year"],
                    report_fiscal_period=it["fiscal_period"])
            except Exception as exc:                              # noqa: BLE001
                print(f"  {rcept}  {it['corp_name']}  ERROR "
                      f"{type(exc).__name__}: {exc}")
                continue

            # DB 현재값과 비교 — (statement, basis, label, col) -> value
            # ★한계: SCE 는 **같은 라벨이 연도별로 반복**되므로 이 키로는 중복이
            #   뭉개진다(실측: SOOP '분기순이익' 2개 행이 1개로). 그래서 아래 변경
            #   **건수는 과소 보고**될 수 있다. 적재 판단에는 영향이 없다 —
            #   `store_report_lines()` 가 rcept 단위 delete-then-insert 라 차이가
            #   하나라도 있으면 그 필링 전체를 현재 코드 산출로 맞추기 때문이다.
            cur = {(r["statement"], r["basis"], r["label_raw"], r["col_index"]):
                   r["value_won"]
                   for r in s.execute(text("""
                       SELECT statement, basis, label_raw, col_index, value_won
                       FROM report_lines WHERE rcept_no = :r"""),
                       {"r": rcept}).mappings()}
            new = {(l.statement, l.basis, l.label_raw, l.col_index): l.value_won
                   for l in lines if (l.col_index or 0) == 0
                   or l.statement == "SCE"}
            diffs = [(k, cur.get(k), v) for k, v in new.items()
                     if k in cur and cur[k] != v]

            # ★R157 의 반올림만으로 +-1 움직인 행은 백필 대상이 **아니다**.
            #   R158 이 짝을 못 찾은 셀(행 안에 정수 짝이 없는 경우)은 여전히 10^3~10^6
            #   배 작은데, 종전 절삭값이 반올림값으로 바뀔 뿐이라 의미 없이 데이터를
            #   덮어쓴다(실측: 핸즈코퍼레이션 10,937,873 -> 10,937,874, 진짜 값은
            #   10,937,873,500). 자릿수가 실제로 달라진 **복원만** 적재한다.
            material = [(k, o, v) for k, o, v in diffs
                        if o in (None, 0) or v in (None, 0)
                        or abs(v) / max(abs(o), 1) >= 100
                        or abs(o) / max(abs(v), 1) >= 100]
            cosmetic = len(diffs) - len(material)
            diffs = material

            if not diffs and not cosmetic:
                print(f"  {rcept}  {it['corp_name']:14} 변화 없음")
                continue
            if not diffs:
                # ★복원은 못 했지만 R157 반올림으로 값이 움직인 필링 — 그래도
                #   적재한다. `store_report_lines()` docstring 이 명시한
                #   **재추출 재현성**(DB = 현재 코드 산출) 때문이다. DB 를 예전
                #   절삭값으로 남겨두면 재추출이 영원히 불일치한다.
                #   ★단 이 필링들은 여전히 10^3~10^6 배 작다(행 안에 정수 짝이 없어
                #   R158 이 복원하지 못한다) — 알려진 잔여로 남는다.
                print(f"  {rcept}  {it['corp_name']:14} 복원 0행 "
                      f"(반올림 {cosmetic}행 — ★왜곡 잔존, 재현성 위해 적재)")
                n_cosmetic_only += 1
                if args.apply:
                    try:
                        store_report_lines(s, rcept, lines)
                        s.commit()
                        n_applied += 1
                    except ValueError as guard:
                        s.rollback()
                        n_blocked += 1
                        print(f"       보호됨(덮지 않음): {str(guard)[:120]}")
                continue
            n_changed += 1
            print(f"  {rcept}  {it['corp_name']:14} 복원 {len(diffs)}행 "
                  f"(status={it['status']}"
                  + (f", 반올림만 {cosmetic}행 무시" if cosmetic else "") + ")")
            for k, old, newv in diffs[:4]:
                print(f"       {k[0]}/{k[1][:3]} {k[2][:34]!r} col={k[3]}: "
                      f"{old:,} → {newv:,}")
            if len(diffs) > 4:
                print(f"       … 외 {len(diffs) - 4}행")

            if args.apply:
                try:
                    store_report_lines(s, rcept, lines)
                    s.commit()
                    n_applied += 1
                except ValueError as guard:
                    s.rollback()
                    n_blocked += 1
                    print(f"       ⚠ 보호됨(덮지 않음): {str(guard)[:120]}")

    mode = "적재" if args.apply else "검사만(DB 미변경)"
    print(f"\n[{mode}] 실제 복원 {n_changed}건 · 반올림만 {n_cosmetic_only}건"
          f"(★왜곡 잔존) · 적재 {n_applied}건 · 보호됨 {n_blocked}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
