"""Equivalence gate for the ③ Fix 1 optimization in parser/common/account_mapper.py.

Fix 1 precomputes each alias's normalized form at _build_index() time instead of
recomputing the whole alias dictionary inside _fuzzy_match() on every map() call
(40% of Gate B audit wall time — docs/plans/gateb_audit_performance_design_2026-08-17.md B1).

normalize_account_name() is pure and the alias set is immutable after init, so the
optimization is semantics-preserving BY CONSTRUCTION. This script proves it EMPIRICALLY,
because get_mapper() is shared with the standardization pipeline
(fin2/layer3/combine.py:1188, fin2/extract/pdf.py:192) — a silent mapping change there
would corrupt std_v3 (design doc §6-A / §7).

Method: re-implement the PRE-Fix-1 _fuzzy_match() verbatim as a reference, bind it to a
second mapper instance, and compare full map() output — (account_code, confidence, stage,
matched_alias) — over a real label corpus for every fs_section the pipeline uses.

Pass criterion: 0 mismatches. Any mismatch => revert Fix 1.

usage:
  python scripts/verify_account_mapper_equivalence_2026-08-17.py                 # 기본 4000 rcept 표본
  python scripts/verify_account_mapper_equivalence_2026-08-17.py --rcepts 12000  # 넓힘
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text                                        # noqa: E402
from collector.db import get_session                               # noqa: E402
from parser.common.account_mapper import AccountMapper, MappingResult, _HAS_JELLYFISH  # noqa: E402
from parser.common.amount_normalizer import normalize_account_name  # noqa: E402

if _HAS_JELLYFISH:
    import jellyfish

# fs_section values the pipeline actually passes (face_audit/pdf use lowercase statement,
# combine.py passes bs/is/cf; None = merged index path).
FS_SECTIONS = (None, "bs", "is", "cf", "note")


def reference_fuzzy_match(self: AccountMapper, raw: str, normalized: str,
                          fs_section: Optional[str] = None) -> Optional[MappingResult]:
    """VERBATIM copy of _fuzzy_match() as it was BEFORE Fix 1 (git 8253c70 era).

    Only difference from the current implementation: it recomputes
    normalize_account_name(alias) inline instead of reading the precomputed pairs.
    Everything else -- iteration order, tie-breaking (`>` keeps the first match),
    thresholds, the len_ratio guard -- is byte-identical on purpose.
    """
    best_code: Optional[str] = None
    best_score: float = 0.0
    best_alias: Optional[str] = None

    for code, aliases in self._aliases_by_code.items():
        if fs_section and not code.startswith(f"{fs_section}."):
            continue

        for alias in aliases:
            alias_norm = normalize_account_name(alias)
            if not alias_norm:
                continue

            if alias_norm in normalized or normalized in alias_norm:
                len_ratio = min(len(alias_norm), len(normalized)) / max(len(alias_norm), len(normalized), 1)
                if len_ratio < 0.65 and min(len(alias_norm), len(normalized)) <= 4:
                    pass
                else:
                    score = 0.90 + len_ratio * 0.09
                    if score > best_score:
                        best_score = score
                        best_code = code
                        best_alias = alias
                continue

            if _HAS_JELLYFISH and len(alias_norm) >= 3 and len(normalized) >= 3:
                score = jellyfish.jaro_winkler_similarity(normalized, alias_norm)
                if score >= self.fuzzy_threshold and score > best_score:
                    best_score = score
                    best_code = code
                    best_alias = alias

    if best_code and best_score >= self.fuzzy_threshold:
        return MappingResult(best_code, best_score, "fuzzy", best_alias)
    return None


def load_corpus(n_rcepts: int) -> list[str]:
    """Real labels. A full DISTINCT over report_lines is impractical (hundreds of
    millions of rows), so sample rcepts across the whole range and take their distinct
    labels — the rcept_no index makes this fast and the spread covers K-GAAP legacy,
    pre-2015 and current layouts."""
    labels: set[str] = set()
    with get_session() as s:
        # ★ Spread across the WHOLE rcept range, not the first N. rcept_no sorts
        # chronologically, so a plain `ORDER BY rcept_no LIMIT n` would sample only the
        # oldest filings (K-GAAP legacy layouts) and miss current-era labels entirely.
        # row_number() % stride keeps an even spread over every era.
        # rcept 목록은 std_financials_v3.source_rcepts 에서 얻는다 — report_lines 를
        # DISTINCT 로 훑으면(2.4억행) 실용적이지 않고, 이 집합(149,888건)이 곧 "계층3이
        # 실제로 소비한 필링" 이라 코퍼스로도 정확하다.
        rcepts = [r[0] for r in s.execute(text("""
            WITH d AS (
                SELECT rcept, row_number() OVER (ORDER BY rcept) rn, count(*) OVER () tot
                FROM (SELECT DISTINCT kv.value AS rcept
                      FROM std_financials_v3,
                           LATERAL jsonb_each_text(source_rcepts) AS kv(k, value)) t
            )
            SELECT rcept FROM d
            WHERE rn % GREATEST(tot / :n, 1) = 0
            ORDER BY rcept
        """), {"n": n_rcepts})]
        print(f"  코퍼스 rcept {len(rcepts)}건에서 라벨 수집 중...")
        step = 500
        for i in range(0, len(rcepts), step):
            chunk = rcepts[i:i + step]
            for r in s.execute(text(
                    "SELECT DISTINCT label_raw FROM report_lines WHERE rcept_no = ANY(:rs)"),
                    {"rs": chunk}):
                if r[0]:
                    labels.add(r[0])
    return sorted(labels)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rcepts", type=int, default=4000, help="코퍼스로 쓸 rcept 수")
    ap.add_argument("--max-mismatch-print", type=int, default=20)
    a = ap.parse_args()

    new_mapper = AccountMapper()
    old_mapper = AccountMapper()
    # bind the pre-Fix-1 implementation to the reference instance
    old_mapper._fuzzy_match = reference_fuzzy_match.__get__(old_mapper, AccountMapper)

    print("① 별칭 사전 자체(전 alias) 대조")
    alias_labels = sorted({al for als in new_mapper._aliases_by_code.values() for al in als})
    print(f"   alias {len(alias_labels)}개")

    print("② 실제 라벨 코퍼스 수집")
    corpus = load_corpus(a.rcepts)
    print(f"   실라벨 {len(corpus)}개")

    all_labels = alias_labels + corpus
    total = 0
    mismatches = []
    t0 = time.perf_counter()
    for label in all_labels:
        for fs in FS_SECTIONS:
            total += 1
            rn = new_mapper.map(label, fs_section=fs)
            ro = old_mapper.map(label, fs_section=fs)
            kn = (rn.account_code, rn.confidence, rn.stage, rn.matched_alias)
            ko = (ro.account_code, ro.confidence, ro.stage, ro.matched_alias)
            if kn != ko:
                mismatches.append((label, fs, ko, kn))
    dt = time.perf_counter() - t0

    print(f"\n── 대조 {total:,}건 · {dt:.1f}s ──")
    if mismatches:
        print(f"❌ 불일치 {len(mismatches)}건 — Fix 1 을 철회할 것")
        for label, fs, ko, kn in mismatches[:a.max_mismatch_print]:
            print(f"   label={label!r} fs={fs}\n      old={ko}\n      new={kn}")
        sys.exit(1)
    print("✅ 불일치 0건 — 동치성 확인(통과선 충족)")


if __name__ == "__main__":
    main()
