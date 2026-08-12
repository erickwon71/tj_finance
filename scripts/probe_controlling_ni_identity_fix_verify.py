"""Phase 2 verification (§4-2-2/§4-2-3) for the controlling_ni identity-trigger fix.

docs/plans/std_v3_controlling_ni_oci_section_fix_design_2026-08-12.md §4-2. Re-runs the
*actual* (already-patched) fin2/layer3/combine.py code — no monkeypatching — against:

  (A) the 404 fail_a rows (source_version=v3, fail_fields ∋ controlling_ni) → compare the
      new classification against the §3-1 simulation's expected split (321 raw conflict /
      301 identity-resolved / 20 still held / 83 raw-single-value, unaffected).
  (B) a sample of the currently-PASS population (consolidated, controlling_ni NOT NULL,
      excluding the 404 fail_a keys) → measure how many values change, and split into
      NULL-conversion vs re-confirmed-to-a-different-value, to compare against the §3-2
      simulation's ~3.12%(156/5000) estimate.

Read-only throughout: never writes to std_financials_v3 or face_audit.
"""
from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from collector.db import get_session
from fin2.layer3.combine import build_merged_lines, _map_rows, _resolve, _resolve_ni_attribution

SEED = "controlling-ni-phase2-verify-2026-08-12"
PASS_SAMPLE_N = 5000


def _classify(session, corp, fy, fp, basis):
    """Run the real production path (build_merged_lines → _map_rows → _resolve →
    _resolve_ni_attribution) for one (corp,fy,fp,basis) and report what happened to
    is.controlling_ni. Returns a dict or None if the canonical has no candidates at all
    (e.g. filing genuinely lacks the line — out of scope for this fix)."""
    merged = build_merged_lines(session, corp, fy, fp)
    cands = _map_rows(merged, fp, basis, ("BS", "IS", "CF"))
    if "is.controlling_ni" not in cands:
        return None
    raw_vals = {r["value"] for r in cands["is.controlling_ni"]}
    confirmed, conflicts = _resolve(cands)
    held_before_identity = "is.controlling_ni" in conflicts
    val_before_identity = confirmed.get("is.controlling_ni")
    _resolve_ni_attribution(cands, confirmed, conflicts)
    return {
        "raw_conflict": len(raw_vals) > 1,
        "held_before_identity": held_before_identity,
        "val_before_identity": val_before_identity,
        "resolved_after_identity": "is.controlling_ni" in confirmed,
        "val_after_identity": confirmed.get("is.controlling_ni"),
        "still_held": "is.controlling_ni" in conflicts,
    }


def part_a(session):
    print("=" * 70)
    print("(A) fail_a 404건 재현 — 실제 코드 diff")
    print("=" * 70)
    rows = session.execute(text("""
        SELECT corp_code, fiscal_year, fiscal_period, statement_type
        FROM face_audit
        WHERE gate_status='fail_a' AND source_version='v3' AND fail_fields ? 'controlling_ni'
        ORDER BY corp_code, fiscal_year, fiscal_period
    """)).fetchall()
    print(f"모집단: {len(rows)}건 (설계 §3-1 실측 당시 404건)")

    bucket = Counter()
    resolved_examples = []
    still_held_examples = []
    for r in rows:
        c = _classify(session, r.corp_code, r.fiscal_year, r.fiscal_period, r.statement_type)
        if c is None:
            bucket["no_candidate"] += 1
            continue
        if not c["raw_conflict"]:
            bucket["raw_single_value"] += 1
            continue
        bucket["raw_conflict"] += 1
        if c["resolved_after_identity"]:
            bucket["raw_conflict.identity_resolved"] += 1
            if len(resolved_examples) < 5:
                resolved_examples.append((r.corp_code, r.fiscal_year, r.fiscal_period, c))
        else:
            bucket["raw_conflict.still_held"] += 1
            if len(still_held_examples) < 5:
                still_held_examples.append((r.corp_code, r.fiscal_year, r.fiscal_period, c))

    print("\n결과 분류:")
    for k in ("raw_single_value", "raw_conflict", "raw_conflict.identity_resolved",
              "raw_conflict.still_held", "no_candidate"):
        print(f"  {k:40s} {bucket[k]:5d}")
    n_conflict = bucket["raw_conflict"]
    n_resolved = bucket["raw_conflict.identity_resolved"]
    if n_conflict:
        print(f"\n  identity 해결율: {n_resolved}/{n_conflict} "
              f"({100*n_resolved/n_conflict:.1f}%)  (설계 §3-1 실측: 301/321 = 93.8%)")
    print(f"  raw_single_value(§2-3, 이 수정으로 미해결): {bucket['raw_single_value']} "
          f"(설계 §3-1 실측: 83)")

    print("\n예시 — identity로 해결됨:")
    for corp, fy, fp, c in resolved_examples:
        print(f"  {corp} {fy} {fp}: {c['val_before_identity']} → {c['val_after_identity']}")
    print("예시 — 여전히 결측(identity도 애매):")
    for corp, fy, fp, c in still_held_examples:
        print(f"  {corp} {fy} {fp}: raw held, identity도 미확정")
    return bucket


def part_b(session):
    print()
    print("=" * 70)
    print("(B) PASS 모집단 광역 재검증 — 값 변경 규모")
    print("=" * 70)
    faila_keys = {(r.corp_code, r.fiscal_year, r.fiscal_period)
                  for r in session.execute(text("""
        SELECT corp_code, fiscal_year, fiscal_period FROM face_audit
        WHERE gate_status='fail_a' AND source_version='v3' AND fail_fields ? 'controlling_ni'
    """))}
    pop = session.execute(text("""
        SELECT corp_code, fiscal_year, fiscal_period, controlling_ni AS old_val
        FROM std_financials_v3
        WHERE statement_type='consolidated' AND controlling_ni IS NOT NULL
    """)).fetchall()
    pop = [r for r in pop if (r.corp_code, r.fiscal_year, r.fiscal_period) not in faila_keys]
    print(f"모집단(연결·controlling_ni 비NULL, fail_a 404건 제외): {len(pop)}건")

    random.seed(SEED)
    sample = random.sample(pop, min(PASS_SAMPLE_N, len(pop)))
    print(f"표본: {len(sample)}건")

    changed_to_null = []
    changed_to_other = []
    unchanged = 0
    errors = 0
    for r in sample:
        try:
            c = _classify(session, r.corp_code, r.fiscal_year, r.fiscal_period, "consolidated")
        except Exception as e:  # noqa: BLE001 — probe must not crash on one bad row
            errors += 1
            continue
        if c is None:
            errors += 1
            continue
        new_val = c["val_after_identity"]
        if new_val == r.old_val:
            unchanged += 1
        elif new_val is None:
            changed_to_null.append((r.corp_code, r.fiscal_year, r.fiscal_period, r.old_val))
        else:
            changed_to_other.append((r.corp_code, r.fiscal_year, r.fiscal_period, r.old_val, new_val))

    n_changed = len(changed_to_null) + len(changed_to_other)
    print(f"\n  unchanged:        {unchanged}")
    print(f"  changed→NULL:     {len(changed_to_null)}")
    print(f"  changed→다른값:    {len(changed_to_other)}")
    print(f"  errors/no-cand:   {errors}")
    print(f"  변경율: {n_changed}/{len(sample)} ({100*n_changed/len(sample):.2f}%)  "
          f"(설계 §3-2 실측: 156/5000 = 3.12%)")

    print("\n표본 — changed→NULL (최대 10건):")
    for row in changed_to_null[:10]:
        print(f"  {row[0]} {row[1]} {row[2]}: {row[3]} → NULL")
    print("표본 — changed→다른값 (최대 10건, 원문대조용 후보):")
    for row in changed_to_other[:10]:
        print(f"  {row[0]} {row[1]} {row[2]}: {row[3]} → {row[4]}")
    return changed_to_null, changed_to_other


def main():
    with get_session() as session:
        part_a(session)
        part_b(session)


if __name__ == "__main__":
    main()
