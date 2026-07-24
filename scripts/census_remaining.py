"""잔여 금융 KSIC census — 일반매퍼가 뽑는 revenue 와 IS 구조를 훑어 결함 탐지.

각 섹터별로 firm → 산출 revenue(combine) / 프로파일 / 영업수익·매출액 총계 유무 / IS 상위 라인.
'총계 있음·매퍼가 그걸 집음' = 정상. '총계 없는데 성분 하나 오선택' 또는 '값 미세/이상' = 결함 후보.
읽기 전용.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from collector.db import SessionLocal
from fin2.layer3.combine import build_merged_lines, combine_full
from fin2.layer3.industry_profiles import norm

s = SessionLocal()

# (섹터라벨, KSIC 정확일치 리스트)
SECTORS = [
    ("창투·VC·PE",   ["64209", "6491", "64991", "64919"]),
    ("인프라·PEF",    ["64201"]),
    ("신탁·자산신탁",  ["642"]),
    ("보험대리·보증",  ["66202", "65122"]),
    ("핀테크·결제·기타", ["64999", "66199", "661"]),
]
TOTAL_N = {norm(x) for x in ["영업수익", "매출액", "매출"]}

for label, ksics in SECTORS:
    print(f"\n{'='*70}\n### {label}  (KSIC {','.join(ksics)})\n{'='*70}")
    rows = s.execute(text("""
        SELECT corp_code, corp_name, induty_code FROM corporations
        WHERE is_active AND induty_code = ANY(:ks) ORDER BY induty_code, corp_name
    """), {"ks": ksics}).fetchall()
    for corp, name, induty in rows:
        merged = build_merged_lines(s, corp, 2025, "FY")
        if not merged:
            print(f"  {name:16s} [{induty}] merged 없음(2025 미보고)"); continue
        basis = "consolidated"
        is_lines = [r for r in merged if r["statement"] == "IS" and r["basis"] == basis]
        if not is_lines:
            basis = "separate"
            is_lines = [r for r in merged if r["statement"] == "IS" and r["basis"] == basis]
        col, _, prov = combine_full(s, corp, 2025, "FY", basis, merged=merged)
        rev = col.get("revenue")
        rev_s = f"{rev/1e12:.4f}조" if rev is not None else "NULL"
        # 총계 라인 존재?
        totals = [(r["label_raw"], r["value_won"]) for r in is_lines
                  if norm(r["label_raw"]) in TOTAL_N and r["value_won"]]
        tot_s = f"총계 {max(totals,key=lambda x:abs(x[1]))[1]/1e12:.3f}조" if totals else "총계없음"
        prof = (prov.get("industry_lines") or {}).get("profile", "-")
        bt = "별도" if basis == "separate" else "연결"
        flag = ""
        # 결함 후보: 총계 있는데 revenue 가 총계와 크게 다르거나, revenue 가 최상위라인보다 훨씬 작음
        tops = sorted((r for r in is_lines if r["value_won"]), key=lambda r: -abs(r["value_won"]))
        top1 = tops[0]["value_won"] if tops else None
        if rev is not None and top1 and abs(rev) < abs(top1) * 0.5 and not totals:
            flag = "  ⚠결함후보(revenue<<최상위라인)"
        elif totals and rev is not None and abs(abs(rev) - abs(max(totals,key=lambda x:abs(x[1]))[1])) > abs(rev)*0.05:
            flag = "  ⚠결함후보(revenue≠총계)"
        print(f"  {name:16s} [{induty},{bt}] rev={rev_s:10s} prof={prof:5s} {tot_s}{flag}")
        # 상위 3라인
        seen = set(); shown = 0
        for r in tops:
            k = (r["label_raw"], r["value_won"])
            if k in seen: continue
            seen.add(k)
            print(f"         · {r['label_raw'][:32]:32s} {r['value_won']/1e12:10.4f}조")
            shown += 1
            if shown >= 3: break

s.close()
