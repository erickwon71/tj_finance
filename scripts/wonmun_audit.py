"""원문 대조 감사 — 금융섹터 revenue 표준.

각 (기업, 연도)에 대해 build_merged_lines(combine 과 동일한 원문 IS 병합)로 실제 공시 라인을
뽑아, 프로파일이 산출한 revenue 와 그 성분 라인을 원문 대비 대조한다. source_rcept 는 DART 접수
번호(dart.fss.or.kr 에서 원 보고서 확인용). 읽기 전용.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from collector.db import SessionLocal
from fin2.layer3.combine import build_merged_lines, combine_full
from fin2.layer3.industry_profiles import norm, apply_revenue_profile

s = SessionLocal()

# 대조할 관심 라벨(원문에서 확인하고 싶은 총계·성분)
KEY = ["영업수익", "영업이익", "영업손익", "판매관리비", "판매비와관리비", "판매비및관리비",
       "판매및일반관리비", "판매와관리비", "이자수익", "수수료수익", "기타영업수익",
       "보험영업수익", "보험서비스수익", "투자영업수익", "투자서비스수익", "순이자손익"]
KEYN = {norm(k) for k in KEY}

SAMPLES = [
    # (name, [years])  — 여신전문 4사
    ("삼성카드", [2023, 2025]),
    ("한국캐피탈", [2025]),
    ("메이슨캐피탈", [2025]),
    ("푸른저축은행", [2025]),
    # 다올 override
    ("다올투자증권", [2025]),
    # 증권 net 표본 (라벨 드리프트 위해 다년)
    ("삼성증권", [2025]),
    ("NH투자증권", [2019, 2025]),
    ("미래에셋증권", [2025]),
    ("키움증권", [2025]),
    # 증권 gross_fallback
    ("대신증권", [2025]),
    ("한화투자증권", [2025]),
    # 보험·은행 앵커 (무회귀 확인)
    ("삼성생명", [2025]),
    ("신한지주", [2025]),
]

def corp_of(name):
    return s.execute(text("SELECT corp_code, induty_code FROM corporations "
                          "WHERE corp_name=:n AND is_active"), {"n": name}).fetchone()

for name, years in SAMPLES:
    row = corp_of(name)
    if not row:
        print(f"\n### {name}: 미상장/없음"); continue
    corp, induty = row
    for y in years:
        merged = build_merged_lines(s, corp, y, "FY")
        if not merged:
            print(f"\n### {name} FY{y}: merged 없음"); continue
        basis = "consolidated"
        is_lines = [r for r in merged if r["statement"] == "IS" and r["basis"] == basis]
        if not is_lines:
            basis = "separate"
            is_lines = [r for r in merged if r["statement"] == "IS" and r["basis"] == basis]
        col, _, prov = combine_full(s, corp, y, "FY", basis, merged=merged)
        rev = col.get("revenue")
        il = prov.get("industry_lines")
        applied = apply_revenue_profile(is_lines, induty, corp)
        rcepts = sorted({r["source_rcept"] for r in is_lines if r.get("source_rcept")})
        rev_s = f"{rev/1e12:.4f}조" if rev is not None else "NULL"
        bt = "별도" if basis == "separate" else "연결"
        print(f"\n### {name} FY{y} [{bt}] induty={induty} → revenue={rev_s}")
        print(f"    profile={il.get('profile') if il else '(일반매퍼)'}  rcept={rcepts}")
        if il:
            print(f"    산출성분: {il}")
        # 원문 관심라인 덤프 (중복 라벨은 max-abs 로 대표)
        seen = {}
        for r in is_lines:
            nn = norm(r["label_raw"])
            if nn in KEYN and r["value_won"] is not None:
                if nn not in seen or abs(r["value_won"]) > abs(seen[nn][1]):
                    seen[nn] = (r["label_raw"], r["value_won"])
        print("    ── 원문 관심라인 ──")
        for nn, (lab, v) in sorted(seen.items(), key=lambda x: -abs(x[1][1])):
            print(f"      {lab[:30]:30s} {v/1e12:10.4f}조")

s.close()
