"""R21 Phase 3 부수발견 — 00143527 2025 Q1 원문대조에서 `_cogs_additive_labels()`가 쓰는
`norm()`(fin2/layer3/industry_profiles.py)이 중간에 괄호가 오는 라벨(`"기타수익(매출액)에
대한 매출원가"` vs `"기타수익(매출액)"`)을 같은 정규화 키("기타수익")로 충돌시켜, 서로 다른
계정(진짜 COGS 서브라인 vs 매출액 세부내역)이 뒤섞이는 실버그를 발견했다(diff=3,816,667,167
= 정확히 두 값의 차이).

이 스크립트는 `_COGS_ADDITIVE_OVERRIDE`(19개사·319키) 전체에 대해 같은 충돌 패턴이 몇 건이나
더 있는지 스캔한다 — 각 키의 (corp,fy,period,basis)에 대응하는 IS rcept를 찾아, want-라벨
집합의 각 정규화 키에 **서로 다른 raw label_raw 가 2개 이상** 매칭되는지 확인한다(둘 다
table_seq=0/col_index=0, 즉 _cogs_additive_labels() 가 실제로 보는 후보 풀).

읽기전용(DB 미변경).

Usage: python scripts/probe_cogs_additive_label_collision_2026-08-15.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from collector.db import get_session
from fin2.layer3.combine import _COGS_ADDITIVE_OVERRIDE
from fin2.layer3.industry_profiles import norm as norm_label


def main():
    with get_session() as session:
        # 각 override 키의 IS rcept 를 std_financials_v3 에서 조회
        keys = list(_COGS_ADDITIVE_OVERRIDE.keys())
        print(f"override 키 {len(keys)}개(19개사) 스캔")

        collisions = []
        no_rcept = []
        checked = 0
        for corp, fy, period, basis in keys:
            row = session.execute(text("""
                SELECT source_rcepts FROM std_financials_v3
                WHERE corp_code=:c AND fiscal_year=:fy AND fiscal_period=:fp
                  AND statement_type=:basis
            """), {"c": corp, "fy": fy, "fp": period, "basis": basis}).fetchone()
            if not row or not row.source_rcepts or not row.source_rcepts.get("IS"):
                no_rcept.append((corp, fy, period, basis))
                continue
            rc = row.source_rcepts["IS"]
            checked += 1

            lines = session.execute(text("""
                SELECT label_raw, value_won FROM report_lines
                WHERE rcept_no=:rc AND statement='IS' AND basis=:basis
                  AND table_seq=0 AND col_index=0 AND value_won IS NOT NULL
            """), {"rc": rc, "basis": basis}).fetchall()

            want = set(_COGS_ADDITIVE_OVERRIDE[(corp, fy, period, basis)])
            by_norm: dict[str, set[tuple[str, int]]] = defaultdict(set)
            for ln in lines:
                nk = norm_label(ln.label_raw)
                if nk in want:
                    by_norm[nk].add((ln.label_raw, ln.value_won))

            for nk, variants in by_norm.items():
                distinct_labels = {v[0] for v in variants}
                if len(distinct_labels) > 1:
                    collisions.append({
                        "key": (corp, fy, period, basis), "norm_key": nk,
                        "variants": sorted(variants),
                    })

        print(f"\nIS rcept 조회 성공 {checked}/{len(keys)}건 (source_rcepts 없음/미매치 {len(no_rcept)}건)")
        print(f"\n라벨 충돌(같은 정규화키에 서로 다른 raw label 2개+) = {len(collisions)}건")
        for c in collisions:
            print(f"  key={c['key']} norm_key={c['norm_key']!r}")
            for label, val in c["variants"]:
                print(f"      {label!r} = {val}")

        if no_rcept:
            print(f"\nsource_rcepts 없음(참고, 별도 원인 — 이 스캔 범위 밖) {len(no_rcept)}건:")
            for k in no_rcept[:20]:
                print(f"  {k}")


if __name__ == "__main__":
    main()
