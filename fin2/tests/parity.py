"""
파리티 하네스 — 신 파이프라인(std_financials_v2 기반 view) vs 현 파이프라인의
`standard_financials` 출력을 (corp, fy, fp, stmt, version) × 컬럼 단위로 비교한다.

역할
----
- `capture`: 현재 `standard_financials` 전 컬럼을 스냅샷(JSON)으로 고정.
  fin2 전환 전 "현 파이프라인 baseline"을 잡아 둔다.
- `diff`: baseline 스냅샷 vs (라이브 테이블 | 다른 스냅샷) 비교.
  컬럼별로 added / removed / changed / null_flip 으로 분류.
- pytest: 커밋된 baseline 대비 라이브 출력의 **회귀(좋은 값→손실/변동)** 가
  허용 목록 밖에서 발생하면 실패.

Phase 0 시점에는 신 파이프라인이 없으므로 baseline=현 출력이며, parity는
P4/P5(std_v2 → 호환 view)에서 신 출력이 들어왔을 때 본격 작동한다.

기존 scripts/snapshot_metrics.py 는 핵심 22개 지표만 담지만, 파리티는 컬럼
계약 전체를 봐야 하므로 information_schema 로 숫자 컬럼을 자동 수집한다.

사용:
    python -m fin2.tests.parity capture --label baseline774 --out fin2/tests/parity_baseline.json
    python -m fin2.tests.parity diff fin2/tests/parity_baseline.json --live
    python -m fin2.tests.parity diff before.json after.json --tol 0.005
"""
from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from collector.db import get_session  # noqa: E402
from sqlalchemy import text  # noqa: E402


# 키를 구성하는 식별 컬럼 (비교 대상에서 제외)
KEY_COLS = ("corp_code", "fiscal_year", "fiscal_period", "statement_type", "version")

# 값 비교에서 제외하는 메타 컬럼 (타임스탬프/연원 등 비결정적·비재무)
NON_VALUE_COLS = {
    "period_end", "is_ifrs", "rcept_no",
    "superseded_at", "calculated_at",
}


def _value_columns() -> list[str]:
    """standard_financials 의 숫자형 값 컬럼 목록을 동적으로 수집."""
    sql = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'standard_financials'
          AND data_type IN ('bigint', 'integer', 'smallint', 'numeric')
        ORDER BY ordinal_position
    """
    with get_session() as session:
        cols = [r[0] for r in session.execute(text(sql)).fetchall()]
    # 키 컬럼(fiscal_year/version 등 숫자)과 메타 컬럼 제거
    return [c for c in cols if c not in KEY_COLS and c not in NON_VALUE_COLS]


def _key(row: dict) -> str:
    return "|".join(str(row[c]) for c in KEY_COLS)


def capture(label: str, out_path: str, since_year: int = 1999) -> dict:
    """standard_financials 전 컬럼 스냅샷을 JSON 으로 저장."""
    value_cols = _value_columns()
    select_cols = ", ".join(f"sf.{c}" for c in (*KEY_COLS, *value_cols))
    sql = f"""
        SELECT {select_cols}
        FROM standard_financials sf
        WHERE sf.fiscal_year >= :since_year
    """
    data: dict[str, dict] = {}
    with get_session() as session:
        result = session.execute(text(sql), {"since_year": since_year})
        keys = result.keys()
        for r in result.fetchall():
            row = dict(zip(keys, r))
            data[_key(row)] = {c: row[c] for c in value_cols}

    snapshot = {
        "label": label,
        "created_at": date.today().isoformat(),
        "since_year": since_year,
        "value_columns": value_cols,
        "count": len(data),
        "data": data,
    }
    Path(out_path).write_text(json.dumps(snapshot, ensure_ascii=False))
    print(f"captured {len(data):,} rows × {len(value_cols)} cols → {out_path}")
    return snapshot


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text())


def _rel_diff(a, b) -> float:
    """상대 변화율. 둘 다 0/None 이면 0."""
    if a is None or b is None:
        return float("inf")
    denom = max(abs(a), abs(b))
    if denom == 0:
        return 0.0
    return abs(a - b) / denom


def diff(baseline: dict, current: dict, tol: float = 0.0) -> dict:
    """
    두 스냅샷을 비교. 반환:
      summary: {added, removed, changed, null_flip} 키 개수
      by_column: 컬럼별 변동 건수
      cases: 변동 키별 상세(컬럼/before/after)
    null_flip = 한쪽만 None (값 손실/획득) — 회귀 탐지의 핵심 신호.
    """
    b_data, c_data = baseline["data"], current["data"]
    value_cols = baseline.get("value_columns") or current.get("value_columns")

    b_keys, c_keys = set(b_data), set(c_data)
    added = sorted(c_keys - b_keys)
    removed = sorted(b_keys - c_keys)

    by_column: dict[str, int] = {}
    cases: list[dict] = []
    null_flip_keys: set[str] = set()
    changed_keys: set[str] = set()

    for k in sorted(b_keys & c_keys):
        bv, cv = b_data[k], c_data[k]
        deltas = []
        for col in value_cols:
            x, y = bv.get(col), cv.get(col)
            if x is None and y is None:
                continue
            if (x is None) != (y is None):
                deltas.append({"col": col, "before": x, "after": y, "kind": "null_flip"})
                by_column[col] = by_column.get(col, 0) + 1
                null_flip_keys.add(k)
            elif _rel_diff(x, y) > tol:
                deltas.append({"col": col, "before": x, "after": y, "kind": "changed"})
                by_column[col] = by_column.get(col, 0) + 1
                changed_keys.add(k)
        if deltas:
            cases.append({"key": k, "deltas": deltas})

    return {
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "null_flip": len(null_flip_keys),
            "changed": len(changed_keys - null_flip_keys),
            "compared_keys": len(b_keys & c_keys),
        },
        "added_keys": added,
        "removed_keys": removed,
        "by_column": dict(sorted(by_column.items(), key=lambda kv: -kv[1])),
        "cases": cases,
    }


def _print_report(report: dict, limit: int = 30) -> None:
    s = report["summary"]
    print("=== parity summary ===")
    print(f"  compared keys : {s['compared_keys']:,}")
    print(f"  added         : {s['added']:,}")
    print(f"  removed       : {s['removed']:,}")
    print(f"  null_flip     : {s['null_flip']:,}  (값 손실/획득 — 회귀 후보)")
    print(f"  changed       : {s['changed']:,}")
    if report["by_column"]:
        print("--- by column ---")
        for col, n in report["by_column"].items():
            print(f"  {col:<22} {n:,}")
    if report["cases"]:
        print(f"--- cases (first {limit}) ---")
        for case in report["cases"][:limit]:
            for d in case["deltas"]:
                print(f"  {case['key']:<45} {d['col']:<18} "
                      f"{d['before']} → {d['after']}  [{d['kind']}]")


def _cmd_capture(args):
    capture(args.label, args.out, since_year=args.since)


def _cmd_diff(args):
    baseline = _load(args.baseline)
    if args.live:
        current = capture("__live__", "/dev/null" if sys.platform != "win32" else "nul",
                          since_year=baseline.get("since_year", 1999))
    else:
        current = _load(args.current)
    report = diff(baseline, current, tol=args.tol)
    _print_report(report, limit=args.limit)
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"\nreport → {args.out}")


def main(argv=None):
    p = argparse.ArgumentParser(description="fin2 parity harness")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("capture", help="현 standard_financials 스냅샷 저장")
    pc.add_argument("--label", required=True)
    pc.add_argument("--out", required=True)
    pc.add_argument("--since", type=int, default=1999)
    pc.set_defaults(func=_cmd_capture)

    pd = sub.add_parser("diff", help="baseline vs (live|snapshot) 비교")
    pd.add_argument("baseline")
    pd.add_argument("current", nargs="?")
    pd.add_argument("--live", action="store_true", help="라이브 테이블과 비교")
    pd.add_argument("--tol", type=float, default=0.0, help="상대 허용오차(예: 0.005=0.5%%)")
    pd.add_argument("--limit", type=int, default=30)
    pd.add_argument("--out", help="리포트 JSON 저장 경로")
    pd.set_defaults(func=_cmd_diff)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
