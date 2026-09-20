#!/usr/bin/env python
"""R154 백필 — Q1 필링을 재추출해 EPS 행이 새로 복원되는 건만 골라 적재한다.

## 왜 후보를 좁히는가

"Q1 이고 EPS 행이 0건"인 필링은 2015+ 에 907건(505개사)이지만, 그 전부가 R154 패턴은
아니다 — 애초에 원문에 EPS 행이 없는 필링이 많다. 그래서 **재추출 결과로 판정한다**:
지금 코드로 다시 뽑았을 때 EPS 행이 나오면 그게 R154 가 구제한 건이다.

## --apply 없이는 DB 를 건드리지 않는다

기본은 **검사만**(dry-run) — 몇 건이 복원되는지 세어 보고한 뒤 사용자가 확인하면
`--apply` 로 적재한다.

★`layer2_review.py redo` 를 쓰지 않는다 — `_current()` 계열 함수는 **전역 최신 항목**을
집어 캠페인 세션(camp_run)이 보고 있는 항목을 가로챈다(실제 사고 발생). 적재는
`store_report_lines()` 를 직접 부르고 큐 상태는 UPDATE 로만 바꾼다.

## 사용법

    python scripts/backfill_r154_q1_eps.py --limit 300              # 검사만
    python scripts/backfill_r154_q1_eps.py --limit 300 --apply      # 적재
    python scripts/backfill_r154_q1_eps.py --report
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
from fin2.extract.report_lines import extract_report_lines

_OUT = Path(__file__).resolve().parents[1] / "docs/qa/r154_backfill.jsonl"
_L2R = Path(__file__).resolve().parent / "layer2_review.py"

# ★EPS 행이 0건인 Q1 필링만 본다. 이미 EPS 가 실린 필링은 R154 와 무관하다.
_CANDIDATES_SQL = """
WITH is_q1 AS (
    SELECT rcept_no, corp_code, report_fiscal_year, report_fiscal_period,
           COUNT(*) FILTER (WHERE source_ref LIKE 'eps/%') AS n_eps
    FROM report_lines
    WHERE statement = 'IS'
      AND report_fiscal_period = 'Q1'
      AND report_fiscal_year >= 2015
    GROUP BY rcept_no, corp_code, report_fiscal_year, report_fiscal_period
)
SELECT q.rcept_no, q.corp_code, q.report_fiscal_year AS fiscal_year,
       q.report_fiscal_period AS fiscal_period, c.corp_name
FROM is_q1 q LEFT JOIN corporations c ON c.corp_code = q.corp_code
WHERE q.n_eps = 0
ORDER BY q.rcept_no DESC
"""


def _resolve_source_fn():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_l2r", _L2R)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._resolve_source


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


def report() -> None:
    if not _OUT.exists():
        print("아직 결과가 없습니다.")
        return
    n = recovered = applied = blocked = 0
    by_corp, errors = Counter(), Counter()
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
            if rec.get("n_eps"):
                recovered += 1
                n_rows += rec["n_eps"]
                by_corp[rec["corp_name"]] += 1
            if rec.get("applied"):
                applied += 1
            if rec.get("blocked"):
                blocked += 1
    print(f"검사 {n:,}건 · EPS 복원 {recovered:,}건"
          f"{f' ({recovered / n:.1%})' if n else ''} · 복원행 {n_rows:,} · "
          f"적재 {applied:,}건 · 보호됨 {blocked:,}건 · "
          f"오류 {sum(errors.values()):,}건")
    print(f"\n회사별 복원(상위 20): {by_corp.most_common(20)}")
    if errors:
        print(f"\n오류 유형: {errors.most_common(5)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--apply", action="store_true", help="DB 에 실제로 적재")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    if args.report:
        report()
        return 0

    resolve_source = _resolve_source_fn()
    done = load_done()
    n = n_recovered = n_applied = 0

    with get_session() as s, _OUT.open("a") as out:
        rows = s.execute(text(_CANDIDATES_SQL)).mappings().all()
        print(f"후보 {len(rows):,}건 (처리 완료 {len(done):,}건 제외)")
        for r in rows:
            if n >= args.limit:
                break
            if r["rcept_no"] in done:
                continue
            rec = {"rcept_no": r["rcept_no"], "corp_code": r["corp_code"],
                   "corp_name": r["corp_name"], "fiscal_year": r["fiscal_year"]}
            try:
                _kind, path = resolve_source(s, r["rcept_no"])
                lines = extract_report_lines(
                    path, rcept_no=r["rcept_no"], corp_code=r["corp_code"],
                    report_fiscal_year=r["fiscal_year"],
                    report_fiscal_period=r["fiscal_period"])
                # ★"추출됐다"와 "DB 에 실린다"는 다르다 — IS 는
                #   `_PERIOD_AXIS_STATEMENTS` 정책상 col_index=0(당기)만 적재된다.
                #   전기(col=1)만 복원된 건은 DB 가 하나도 안 바뀌므로 백필 대상이
                #   아니다(실측: 이화공영·로보티즈는 원문 당기 칸이 공란이라 전기만
                #   나온다 — 결함이 아니라 원문에 당기 EPS 가 없는 것).
                eps = [l for l in lines if l.statement == "IS"
                       and "주당" in (l.label_raw or "")]
                eps_loadable = [l for l in eps if (l.col_index or 0) == 0]
                rec["n_eps_extracted"] = len(eps)
                rec["n_eps"] = len(eps_loadable)
                rec["n_lines"] = len(lines)
                if eps:
                    rec["sample"] = [
                        {"basis": l.basis, "label": l.label_raw,
                         "col": l.col_index, "value": l.value_won}
                        for l in eps[:4]]
                if eps_loadable and args.apply:
                    from fin2.extract.report_lines import store_report_lines
                    try:
                        # ★가드를 절대 끄지 않는다(overwrite_* 기본 False 유지):
                        #   수동입력 보호와 R139 원문대조-pass 보호 둘 다 사용자
                        #   지시로 세워진 것이다. pass 로 보호된 건은 "이미 사람이
                        #   통과시킨" 건이므로 여기서 조용히 덮으면 안 되고,
                        #   캠페인 세션이 재검토하도록 목록으로 넘긴다.
                        store_report_lines(s, r["rcept_no"], lines)
                        s.commit()
                        rec["applied"] = True
                        n_applied += 1
                    except ValueError as guard:
                        s.rollback()
                        rec["blocked"] = str(guard)[:200]
            except Exception as exc:                              # noqa: BLE001
                s.rollback()
                rec["error"] = f"{type(exc).__name__}: {exc}"
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            n += 1
            if rec.get("n_eps"):
                n_recovered += 1
            if n % 25 == 0:
                print(f"  ... {n}/{args.limit} (복원 {n_recovered})", flush=True)

    mode = "적재" if args.apply else "검사만(DB 미변경)"
    print(f"\n이번 실행[{mode}]: {n:,}건 처리, EPS 복원 {n_recovered:,}건, "
          f"적재 {n_applied:,}건 → {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
