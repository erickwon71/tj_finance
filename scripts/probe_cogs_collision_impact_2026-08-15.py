"""Follow-up to probe_cogs_additive_label_collision_2026-08-15.py — for each of the 31
colliding override keys, run the REAL `_cogs_additive_labels()` (via `build_merged_lines()`,
same call path as `combine_full()`) to see which raw label actually won the overwrite, and
whether the resulting `is.cogs` value currently in std_financials_v3 is right or wrong
(right = matches the "기타수익(매출액)에 대한 매출원가" COGS-subline variant, confirmed by
direct source read as the true target in the 2026-08-15 Q1 investigation).

Read-only (DB unaffected) — build_merged_lines() only reads.

Usage: python scripts/probe_cogs_collision_impact_2026-08-15.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from collector.db import get_session
from fin2.layer3.combine import (
    _COGS_ADDITIVE_OVERRIDE, _cogs_additive_labels, build_merged_lines,
)
from fin2.layer3.industry_profiles import norm as norm_label

_TRUE_COGS_SUFFIX = "에 대한 매출원가"   # confirmed true-target raw-label pattern (Q1 investigation)


def main():
    with get_session() as session:
        keys = [k for k in _COGS_ADDITIVE_OVERRIDE if k[0] in ("00143527", "00163673")]
        print(f"대상 키 {len(keys)}개(2개사)")

        n_wrong = 0
        n_right = 0
        n_no_target = 0
        for corp, fy, period, basis in keys:
            row = session.execute(text("""
                SELECT source_rcepts, cogs, sga FROM std_financials_v3
                WHERE corp_code=:c AND fiscal_year=:fy AND fiscal_period=:fp
                  AND statement_type=:basis
            """), {"c": corp, "fy": fy, "fp": period, "basis": basis}).fetchone()
            if not row:
                continue
            rc_is = (row.source_rcepts or {}).get("IS")
            if not rc_is:
                continue

            lines = session.execute(text("""
                SELECT label_raw, value_won FROM report_lines
                WHERE rcept_no=:rc AND statement='IS' AND basis=:basis
                  AND table_seq=0 AND col_index=0 AND value_won IS NOT NULL
            """), {"rc": rc_is, "basis": basis}).fetchall()

            want = set(_COGS_ADDITIVE_OVERRIDE[(corp, fy, period, basis)])
            by_norm: dict[str, dict[str, int]] = {}
            for ln in lines:
                nk = norm_label(ln.label_raw)
                if nk in want:
                    by_norm.setdefault(nk, {})[ln.label_raw] = ln.value_won

            merged = build_merged_lines(session, corp, fy, period)
            picked = _cogs_additive_labels(merged, period, basis, tuple(want))

            for nk, variants in by_norm.items():
                if len(variants) < 2:
                    continue
                target_label = next((l for l in variants if l.endswith(_TRUE_COGS_SUFFIX)), None)
                winner_val = picked.get(nk)
                if target_label is None:
                    n_no_target += 1
                    status = "NO_TARGET_LABEL"
                elif winner_val == variants[target_label]:
                    n_right += 1
                    status = "right"
                else:
                    n_wrong += 1
                    status = "**WRONG**"
                print(f"  {corp} {fy} {period} {basis} norm={nk!r} picked={winner_val} "
                      f"target={variants.get(target_label) if target_label else None} [{status}]")

        print(f"\n총계: right={n_right} wrong={n_wrong} no_target_label={n_no_target}")


if __name__ == "__main__":
    main()
