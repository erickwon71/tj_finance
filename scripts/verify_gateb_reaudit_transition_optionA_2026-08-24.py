"""
Gate B 전수 재감사(옵션 A 근본수정, `find_optionA_affected_filings_2026-08-24.py` 기반
소급 백필 이후) 전/후 등급 전이 분석.

`gateb_bugA_col_misselect_optionA_rootfix_plan_2026-08-24.md` §6, 사용 전제는
[[gateb-full-reaudit-is-required-to-close]]: 재감사 **직전** 스냅샷
(`face_audit_snap_20260824`, 아래 SQL 참고) 대비 재감사 후 face_audit(v3)를
비교해 **차단등급 전이(pass/fail_b -> fail_a) 0건**을 확인한다. 표본이 아니라
전수 비교([[feedback-verify-against-source]] 원칙).

스냅샷(백필+재감사 시작 전에 미리 실행해둘 것):
    psql tj_finance -c "CREATE TABLE face_audit_snap_20260824 AS \
        SELECT * FROM face_audit WHERE source_version='v3';"

usage: python scripts/verify_gateb_reaudit_transition_optionA_2026-08-24.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text

ENGINE = create_engine("postgresql://localhost/tj_finance")

SNAP_TABLE = "face_audit_snap_20260824"


def fetch(conn, table, where=""):
    rows = conn.execute(text(f"""
        SELECT corp_code, fiscal_year, fiscal_period, statement_type, is_stub,
               gate_status, fail_fields
        FROM {table} {where}
    """)).fetchall()
    out = {}
    for r in rows:
        key = (r.corp_code, r.fiscal_year, r.fiscal_period, r.statement_type, r.is_stub)
        out[key] = (r.gate_status, tuple(r.fail_fields or []))
    return out


def main():
    with ENGINE.connect() as conn:
        exists = conn.execute(text(
            "SELECT to_regclass(:t)"
        ), {"t": SNAP_TABLE}).scalar()
        if exists is None:
            print(f"스냅샷 테이블 {SNAP_TABLE} 이 없습니다 — 재감사 전에 먼저 만들어야 합니다:")
            print(f'  psql tj_finance -c "CREATE TABLE {SNAP_TABLE} AS '
                  f"SELECT * FROM face_audit WHERE source_version='v3';\"")
            sys.exit(1)
        before = fetch(conn, SNAP_TABLE)
        after = fetch(conn, "face_audit", "WHERE source_version='v3'")

    print(f"before rows: {len(before):,}  after rows: {len(after):,}")

    only_before = set(before) - set(after)
    only_after = set(after) - set(before)
    print(f"key only in snapshot (dropped): {len(only_before)}")
    print(f"key only in current (new): {len(only_after)}")

    trans = Counter()
    common = set(before) & set(after)
    for k in common:
        gb, _ = before[k]
        ga, _ = after[k]
        trans[(gb, ga)] += 1

    print("\n=== gate_status 전이 매트릭스 (before -> after, 건수) ===")
    for (gb, ga), n in sorted(trans.items(), key=lambda kv: -kv[1]):
        marker = "" if gb == ga else "  <-- 전이"
        print(f"  {gb:>8} -> {ga:<8} : {n:>8,}{marker}")

    # ★핵심 게이트 — pass/fail_b -> fail_a 전이는 0이어야 한다(차단등급 회귀).
    blocked_now = {k for k in common
                   if before[k][0] in ("pass", "fail_b") and after[k][0] == "fail_a"}
    print(f"\n=== ★차단등급 전이(pass/fail_b -> fail_a): {len(blocked_now)} 건"
          f" {'★★★ 회귀 있음 — 확인 필요' if blocked_now else '(0건, 정상)'} ===")
    for k in sorted(blocked_now)[:30]:
        print(f"    {k}  before={before[k]}  after={after[k]}")

    # fail_a -> pass/fail_b 로 개선된 건수(옵션 A 근본수정의 기대 효과) — 필드 무관 집계.
    improved = {k for k in common
                if before[k][0] == "fail_a" and after[k][0] in ("pass", "fail_b")}
    print(f"\n=== fail_a -> pass/fail_b 개선: {len(improved)} 건 ===")
    field_counter = Counter()
    for k in improved:
        for f in before[k][1]:
            field_counter[f] += 1
    for field, n in field_counter.most_common(20):
        print(f"  {field:<30}: {n}")


if __name__ == "__main__":
    main()
