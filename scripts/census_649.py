import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from collector.db import SessionLocal
from fin2.layer3.combine import build_merged_lines, combine_full
from fin2.layer3.industry_profiles import norm
s = SessionLocal()
TOTAL_N = {norm(x) for x in ["영업수익","매출액","매출","수익"]}
rows = s.execute(text("""SELECT corp_code, corp_name FROM corporations
    WHERE is_active AND induty_code='649' ORDER BY corp_name""")).fetchall()
print(f"### 649 (일반지주+VC 혼재) {len(rows)}사 — revenue vs 총계 결함 스캔")
for corp, name in rows:
    merged = build_merged_lines(s, corp, 2025, "FY")
    if not merged: print(f"  {name:16s} 미보고"); continue
    basis = "consolidated"
    if not any(r["statement"]=="IS" and r["basis"]==basis for r in merged): basis="separate"
    is_lines=[r for r in merged if r["statement"]=="IS" and r["basis"]==basis]
    col,_,prov = combine_full(s, corp, 2025, "FY", basis, merged=merged)
    rev=col.get("revenue")
    totals=[r["value_won"] for r in is_lines if norm(r["label_raw"]) in TOTAL_N and r["value_won"]]
    tot=max(totals,key=abs) if totals else None
    tops=sorted((r for r in is_lines if r["value_won"]),key=lambda r:-abs(r["value_won"]))
    top1=tops[0]["value_won"] if tops else None
    flag=""
    if rev is not None and top1 and not totals and abs(rev)<abs(top1)*0.5: flag="  ⚠결함후보"
    if rev is None: flag="  (revenue NULL)"
    rs=f"{rev/1e12:.3f}조" if rev is not None else "NULL"
    ts=f"총계{tot/1e12:.3f}조" if tot else "총계없음"
    print(f"  {name:16s} rev={rs:9s} {ts}{flag}")
s.close()
