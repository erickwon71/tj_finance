"""P3-1 후속 — 'depth 우선 결함'(build_merged_lines 셀 키가 section_path 를 포함해
정정본의 표 재렌더링에 취약, _reduce_conflict 의 shallowest-depth 우선이 정정본을
통째로 무시하는 경우) 이 689건 단조성 위반 중 몇 건인지 전수로 센다.

방법: 689건(corp, fy, period, statement_type) 각각에 대해 build_merged_lines() 를
실제로 재실행 — 같은 (statement, label_raw) 인데 section_path 가 다르고 값도 다른
'중복 후보 쌍'이 있고, 그 중 더 얕은(depth 작은) 쪽이 **더 이전(early) 필링**에서 온
경우를 '결함 재현'으로 센다(= 정정본이 더 깊은 section_path 때문에 밀린 사례).

용법: .venv/bin/python scripts/investigate_p3_depth_bug_census.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from fin2.layer3.combine import build_merged_lines, _period_filings_chrono

eng = create_engine("postgresql://localhost/tj_finance")
Session = sessionmaker(bind=eng)

with eng.connect() as c:
    violated = c.execute(text("""
        SELECT DISTINCT f.corp_code, f.fiscal_year, f.fiscal_period, f.statement_type
        FROM face_audit_snap_20260819 s
        JOIN face_audit f
          ON f.corp_code=s.corp_code AND f.fiscal_year=s.fiscal_year AND f.fiscal_period=s.fiscal_period
         AND f.statement_type=s.statement_type AND f.is_stub=s.is_stub AND f.source_version=s.source_version
        WHERE s.gate_status='pass' AND f.gate_status IN ('fail_a','fail_b','pending')
        ORDER BY 1,2,3,4
    """)).fetchall()

print(f"대상 (corp,fy,period,statement_type) 행: {len(violated)}건")

session = Session()

def _depth(sp):
    sp = (sp or "").strip()
    return 0 if not sp else sp.count(">") + 1

EPS = 0.001
n_multi_filing = 0
n_dup_label = 0
n_depth_bug = 0
affected_rows = set()
examples = []
period_cache: dict[tuple, list] = {}

for corp, fy, period, stype in violated:
    key = (corp, fy, period)
    if key not in period_cache:
        try:
            period_cache[key] = build_merged_lines(session, corp, fy, period)
        except Exception as e:
            period_cache[key] = None
    merged = period_cache[key]
    if merged is None:
        continue

    chrono = _period_filings_chrono(session, corp, fy, period)
    if len(chrono) < 2:
        continue
    n_multi_filing += 1
    order = {rc: i for i, (rc, _) in enumerate(chrono)}  # 0=earliest

    # basis == stype (consolidated/separate) 만
    cells = [m for m in merged if m["basis"] == stype]
    by_label = defaultdict(list)
    for m in cells:
        by_label[(m["statement"], m["label_raw"])].append(m)

    row_has_dup = False
    row_has_depthbug = False
    for (stmt, label), group in by_label.items():
        if len(group) < 2:
            continue
        # value_won 이 서로 다른(진짜 충돌) 것만
        vals = {g["value_won"] for g in group}
        if len(vals) < 2:
            continue
        row_has_dup = True
        # EPS 근사중복(0.1%) 이면 어차피 max-abs 로 해소되니 결함 아님
        hi = max(vals, key=abs)
        lo = min(vals, key=abs)
        if hi != 0 and (hi > 0) == (lo > 0) and abs(hi - lo) / abs(hi) <= EPS:
            continue
        depths = [(g, _depth(g.get("section_path"))) for g in group]
        min_d = min(d for _, d in depths)
        shallow = [g for g, d in depths if d == min_d]
        if len(shallow) != 1:
            continue  # 얕은 후보가 여럿이면 depth 만으로 결정 안 됨(다른 경로)
        winner = shallow[0]
        # 승자가 '가장 이전(가장 오래된) 필링'인데, 셀 집합 안에 더 나중 필링에서 온
        # (다른 depth 의) 후보가 있으면 = 정정본이 depth 때문에 밀린 결함 재현.
        later_candidates = [g for g in group if g is not winner
                             and order.get(g["source_rcept"], -1) > order.get(winner["source_rcept"], -1)]
        if later_candidates:
            row_has_depthbug = True
            if len(examples) < 8:
                examples.append(
                    f"{corp} {fy}{period} {stype}/{stmt} label={label!r}: "
                    f"winner={winner['source_rcept']}(depth={min_d},val={winner['value_won']:,}) "
                    f"vs later={[ (g['source_rcept'], _depth(g.get('section_path')), g['value_won']) for g in later_candidates]}"
                )

    if row_has_dup:
        n_dup_label += 1
    if row_has_depthbug:
        n_depth_bug += 1
        affected_rows.add((corp, fy, period, stype))

print(f"\n필링 2개 이상(정정 가능성 있는) 행: {n_multi_filing}")
print(f"같은 라벨인데 section_path 다른 '중복 후보' 존재하는 행: {n_dup_label}")
print(f"그중 depth 우선으로 '더 나중 필링'이 밀린(결함 재현) 행: {n_depth_bug}")
print(f"영향받은 (corp,fy,period,statement_type) 수: {len(affected_rows)}")
print(f"영향받은 distinct corp 수: {len({r[0] for r in affected_rows})}")

print("\n=== 예시 ===")
for ex in examples:
    print(f"  {ex}")

print("\n=== 영향받은 corp별 건수 ===")
from collections import Counter
corp_counts = Counter(r[0] for r in affected_rows)
for corp, n in corp_counts.most_common():
    print(f"  {corp}: {n}건")
