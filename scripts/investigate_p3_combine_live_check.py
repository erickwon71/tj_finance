"""P3-1 후속 — combine.py 를 지금 라이브로 재실행해서 std_v3(db_won) 과 실제 산출물,
Gate B report_won 셋을 나란히 비교. 고려아연(00102858) FY2023 consolidated 표본.

용법: .venv/bin/python scripts/investigate_p3_combine_live_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from fin2.layer3.combine import build_merged_lines, _period_filings_chrono

eng = create_engine("postgresql://localhost/tj_finance")
Session = sessionmaker(bind=eng)
session = Session()

corp, fy, period = "00102858", 2023, "FY"

chrono = _period_filings_chrono(session, corp, fy, period)
print(f"=== _period_filings_chrono({corp}, {fy}, {period}) ===")
for rcept, is_amend in chrono:
    print(f"  {rcept}  is_amendment={is_amend}")

merged = build_merged_lines(session, corp, fy, period)
print(f"\n총 merged 셀: {len(merged)}건")

# BS consolidated total_assets 라벨 찾기 (label_raw 로 직접 필터 — canonical 매핑 전 단계라
# label_raw 로 자산총계류를 훑는다)
targets = [c for c in merged if c["statement"] == "BS" and c["basis"] == "consolidated"
           and c["label_raw"] in ("자산총계", "자산 총계")]
print("\n=== BS consolidated 자산총계 관련 셀 ===")
for c in targets:
    print(f"  label={c['label_raw']!r} value={c['value_won']:,} source_rcept={c['source_rcept']} "
          f"amended={c['amended']} amended_by={c['amended_by']}")

with eng.connect() as conn:
    db = conn.execute(text("""
        SELECT total_assets FROM std_financials_v3
        WHERE corp_code=:c AND fiscal_year=:fy AND fiscal_period=:p AND statement_type='consolidated'
    """), {"c": corp, "fy": fy, "p": period}).scalar()
print(f"\nstd_financials_v3.total_assets(db_won) = {db:,}")

print("\n=== section_path 상세 (deepth 계산용) ===")
for c in targets:
    sp = c.get("section_path") or ""
    depth = 0 if not sp else sp.count(">") + 1
    print(f"  source_rcept={c['source_rcept']} section_path={sp!r} depth={depth} value={c['value_won']:,}")

print("\n=== combine_full() 실제 프로덕션 경로 재현 ===")
from fin2.layer3.combine import combine_full
col, conflicts, prov = combine_full(session, corp, fy, period, "consolidated")
print("bs.total_assets 대응 col['total_assets'] =", col.get("total_assets"))
if "bs.total_assets" in conflicts:
    print("bs.total_assets CONFLICT(hold) candidates:")
    for r in conflicts["bs.total_assets"]:
        print(f"    {r}")
else:
    print("(conflicts 에 bs.total_assets 없음 — confirmed 로 확정됐다는 뜻)")
