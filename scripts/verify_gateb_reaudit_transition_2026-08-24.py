"""
Gate B 전수 재감사(2026-08-23 밤~08-24 새벽 완료) 전/후 등급 전이 분석.

[[gateb-full-reaudit-is-required-to-close]] ④단계: 스냅샷(face_audit_snap_20260823,
D 카테고리 tax_expense 수정 백필 직전) 대비 재감사 후 face_audit(v3) 를 비교해서
- tax_expense fail_a -> pass 전이가 설계문서 §1-7 실측(85/89)과 일치하는지
- 그 외 필드에서 예상치 못한 회귀(pass/fail_b -> fail_a)가 없는지
확인한다. 표본이 아니라 전수 비교([[feedback-verify-against-source]] 원칙).

usage: python scripts/verify_gateb_reaudit_transition_2026-08-24.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text

ENGINE = create_engine("postgresql://localhost/tj_finance")

KEY_COLS = ["corp_code", "fiscal_year", "fiscal_period", "statement_type", "is_stub"]


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
        before = fetch(conn, "face_audit_snap_20260823")
        after = fetch(conn, "face_audit", "WHERE source_version='v3'")

    print(f"before rows: {len(before):,}  after rows: {len(after):,}")

    only_before = set(before) - set(after)
    only_after = set(after) - set(before)
    print(f"key only in snapshot (dropped): {len(only_before)}")
    print(f"key only in current (new): {len(only_after)}")

    # ── overall gate_status transition matrix ──────────────────────────────
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

    # ── tax_expense field-level transition ─────────────────────────────────
    def has_field(entry, field):
        return field in entry[1]

    tx_before_fail_a = {k for k in common if before[k][0] == "fail_a" and has_field(before[k], "tax_expense")}
    print(f"\n=== tax_expense: before gate_status=fail_a 건수: {len(tx_before_fail_a)} ===")
    tx_after_status = Counter(after[k][0] for k in tx_before_fail_a)
    for status, n in tx_after_status.most_common():
        print(f"  -> after {status:<8}: {n}")
    tx_still_fail_a_with_field = [k for k in tx_before_fail_a
                                   if after[k][0] == "fail_a" and has_field(after[k], "tax_expense")]
    print(f"  여전히 fail_a + tax_expense 포함: {len(tx_still_fail_a_with_field)}")
    if tx_still_fail_a_with_field:
        for k in sorted(tx_still_fail_a_with_field)[:20]:
            print(f"    {k}")

    # ── regression check: pass/fail_b -> fail_a on ANY field (fy>=2024 focus, but check all) ──
    regressions = [k for k in common
                   if before[k][0] in ("pass", "fail_b") and after[k][0] == "fail_a"]
    print(f"\n=== 회귀 후보: before pass/fail_b -> after fail_a (전체): {len(regressions)} ===")
    if regressions:
        reg_fields = Counter()
        for k in regressions:
            for f in after[k][1]:
                reg_fields[f] += 1
        print("  회귀 건의 fail_fields 분포(상위):")
        for f, n in reg_fields.most_common(20):
            print(f"    {f}: {n}")
        fy2024_regressions = [k for k in regressions if k[1] >= 2024]
        print(f"  이 중 fy>=2024: {len(fy2024_regressions)}")
        print("  fy>=2024 회귀 표본(최대 20건):")
        for k in sorted(fy2024_regressions)[:20]:
            print(f"    {k}  before_fields={before[k][1]}  after_fields={after[k][1]}")

    # ── improvement check: fail_a -> pass/fail_b (any field), fy>=2024 ─────
    improvements = [k for k in common
                    if before[k][0] == "fail_a" and after[k][0] in ("pass", "fail_b")]
    print(f"\n=== 개선: before fail_a -> after pass/fail_b (전체): {len(improvements)} ===")
    fy2024_improvements = [k for k in improvements if k[1] >= 2024]
    print(f"  이 중 fy>=2024: {len(fy2024_improvements)}")


if __name__ == "__main__":
    main()
