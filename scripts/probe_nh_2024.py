"""NH 2024 정본 병합 IS 라인 덤프 — 영업이익/판관비 norm 매칭 확인용 일회성 probe."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector.db import SessionLocal
from fin2.layer3.combine import build_merged_lines
from fin2.layer3.industry_profiles import norm, _OP_INCOME_LABELS, _SGA_LABELS

s = SessionLocal()
corp = "00120182"  # NH투자증권
merged = build_merged_lines(s, corp, 2024, "FY")
is_c = [r for r in merged if r["statement"] == "IS" and r["basis"] == "consolidated"]
print(f"NH 2024 연결 IS 병합 라인 수: {len(is_c)}")
for r in is_c:
    lbl = r["label_raw"]
    n = norm(lbl)
    tag = ""
    if n in _OP_INCOME_LABELS:
        tag = "  <<< 영업이익 매칭"
    if n in _SGA_LABELS:
        tag = "  <<< 판관비 매칭"
    if ("영업이익" in lbl) or ("관리비" in lbl):
        v = r["value_won"]
        print(f"  raw={lbl[:34]:34s} norm={n[:28]:28s} val={(v/1e12 if v else 0):7.3f}조{tag}")
s.close()
