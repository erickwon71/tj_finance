"""P3-1 depth 우선 결함 수정 검증 — 30건(6개사) 각각에 대해 combine_full() 을
실제로 재실행해서, 결과가 이제 '더 나중 필링(amended)' 값과 일치하는지 확인한다.

용법: .venv/bin/python scripts/verify_p3_depth_bug_fix.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from fin2.layer3.combine import build_merged_lines, combine_full, _period_filings_chrono

eng = create_engine("postgresql://localhost/tj_finance")
Session = sessionmaker(bind=eng)
session = Session()

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


def _depth(sp):
    sp = (sp or "").strip()
    return 0 if not sp else sp.count(">") + 1


EPS = 0.001
n_checked = 0
n_now_matches_amended = 0
n_still_wrong = 0
mismatches = []

for corp, fy, period, stype in violated:
    try:
        merged = build_merged_lines(session, corp, fy, period)
    except Exception:
        continue
    chrono = _period_filings_chrono(session, corp, fy, period)
    if len(chrono) < 2:
        continue
    order = {rc: i for i, (rc, _) in enumerate(chrono)}
    cells = [m for m in merged if m["basis"] == stype]
    by_label = defaultdict(list)
    for m in cells:
        by_label[(m["statement"], m["label_raw"])].append(m)

    for (stmt, label), group in by_label.items():
        vals = {g["value_won"] for g in group}
        if len(vals) < 2:
            continue
        hi, lo = max(vals, key=abs), min(vals, key=abs)
        if hi != 0 and (hi > 0) == (lo > 0) and abs(hi - lo) / abs(hi) <= EPS:
            continue
        depths = [(g, _depth(g.get("section_path"))) for g in group]
        min_d = min(d for _, d in depths)
        shallow = [g for g, d in depths if d == min_d]
        if len(shallow) != 1:
            continue
        winner = shallow[0]
        later = [g for g in group if g is not winner
                 and order.get(g["source_rcept"], -1) > order.get(winner["source_rcept"], -1)]
        if not later:
            continue
        # 이 라벨이 depth 결함 재현 대상이다 — 실제 combine_full() 결과 확인
        n_checked += 1
        latest_rcept, _ = chrono[-1]
        expected_value = max(later, key=lambda g: order[g["source_rcept"]])["value_won"]
        col, conflicts, _prov = combine_full(session, corp, fy, period, stype)
        # 어떤 canonical 컬럼인지는 모르니 col 전체에서 expected_value 가 등장하는지 확인
        matched_cols = [k for k, v in col.items() if v == expected_value]
        if matched_cols:
            n_now_matches_amended += 1
        else:
            n_still_wrong += 1
            mismatches.append((corp, fy, period, stype, stmt, label, expected_value, dict(col)))

print(f"검사한 (라벨) 케이스: {n_checked}")
print(f"이제 정정본(더 나중 필링) 값과 일치: {n_now_matches_amended}")
print(f"여전히 불일치: {n_still_wrong}")
for m in mismatches[:10]:
    print("  ", m[:7])
