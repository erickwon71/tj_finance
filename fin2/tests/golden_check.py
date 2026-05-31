"""
golden 러너 — fin2/tests/golden/golden.yaml 의 손수검증 정답을 standard_financials
(또는 향후 std_financials_v2 기반 view)에 대해 평가한다.

두 가지를 검증:
  1) 각 assert 가 현재 테이블에서 pass/fail 인지.
  2) 그 결과가 케이스의 `current:`(pass|fail) 기대와 일치하는지.
     → 불일치 시 golden 인코딩 오류이거나 파이프라인 상태 변동 신호.

fin2 전환 후에는 모든 케이스(현재 fail 포함)가 pass 여야 한다.

사용:
    python -m fin2.tests.golden_check            # 전체 케이스 평가
    python -m fin2.tests.golden_check --id rimed_2023_con_oversupersede
    python -m fin2.tests.golden_check --strict   # current 기대와 불일치하면 비0 종료
"""
from __future__ import annotations

import sys
import argparse
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from collector.db import get_session  # noqa: E402
from sqlalchemy import text  # noqa: E402

GOLDEN_PATH = Path(__file__).parent / "golden" / "golden.yaml"


def _fetch(corp_code: str, year: int, period: str, basis: str) -> dict | None:
    sql = """
        SELECT * FROM standard_financials
        WHERE corp_code=:cc AND fiscal_year=:fy AND fiscal_period=:fp
          AND statement_type=:basis
        ORDER BY version DESC LIMIT 1
    """
    with get_session() as session:
        row = session.execute(text(sql), {
            "cc": corp_code, "fy": year, "fp": period, "basis": basis,
        }).mappings().first()
    return dict(row) if row else None


def _eval_assert(a: dict, row: dict | None) -> tuple[bool, str]:
    """단일 assert 평가 → (pass?, 설명)."""
    col = a["column"]
    op = a.get("op", "approx")
    actual = row.get(col) if row else None

    if op == "nonnull":
        return (actual is not None, f"{col}={actual} (nonnull)")
    if op == "null":
        return (actual is None, f"{col}={actual} (null)")
    if actual is None:
        return (False, f"{col}=NULL (expected {op} {a.get('value')})")

    val = a["value"]
    if op == "approx":
        tol = a.get("tol", 0.02)
        denom = max(abs(val), abs(actual)) or 1
        rel = abs(actual - val) / denom
        return (rel <= tol, f"{col}={actual:,} vs {val:,} (rel={rel:.4f}≤{tol})")
    if op == "gt":
        return (actual > val, f"{col}={actual:,} > {val:,}")
    if op == "lt":
        return (actual < val, f"{col}={actual:,} < {val:,}")
    if op == "eq":
        return (actual == val, f"{col}={actual:,} == {val:,}")
    return (False, f"unknown op {op}")


def evaluate(case_filter: str | None = None) -> list[dict]:
    spec = yaml.safe_load(GOLDEN_PATH.read_text())
    results = []
    for case in spec["cases"]:
        if case_filter and case["id"] != case_filter:
            continue
        # assert 를 (year,period,basis) 별로 묶어 한 번만 조회
        cache: dict[tuple, dict | None] = {}
        details, all_pass = [], True
        for a in case["asserts"]:
            k = (case["corp_code"], a["year"], a["period"], a["basis"])
            if k not in cache:
                cache[k] = _fetch(*k)
            ok, desc = _eval_assert(a, cache[k])
            all_pass = all_pass and ok
            details.append((ok, desc))
        expected = case.get("current", "pass")
        observed = "pass" if all_pass else "fail"
        results.append({
            "id": case["id"], "edge_class": case["edge_class"],
            "expected": expected, "observed": observed,
            "match": observed == expected, "details": details,
        })
    return results


def main(argv=None):
    p = argparse.ArgumentParser(description="fin2 golden runner")
    p.add_argument("--id", help="특정 케이스만 평가")
    p.add_argument("--strict", action="store_true",
                   help="current 기대와 불일치 시 비0 종료")
    args = p.parse_args(argv)

    results = evaluate(args.id)
    mism = 0
    for r in results:
        flag = "OK " if r["match"] else "MISMATCH"
        print(f"[{flag}] {r['id']:<34} {r['edge_class']:<20} "
              f"current expected={r['expected']} observed={r['observed']}")
        for ok, desc in r["details"]:
            print(f"        {'✓' if ok else '✗'} {desc}")
        if not r["match"]:
            mism += 1

    print(f"\n{len(results)} cases, {mism} mismatch(es) vs current expectation.")
    if args.strict and mism:
        sys.exit(1)


if __name__ == "__main__":
    main()
