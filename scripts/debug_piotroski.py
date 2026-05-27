"""Piotroski 스크리닝에서 실패 원인 확인"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from analyzer.screener import _load_screening_data
from analyzer.ratio_engine import compute_ratios
from analyzer.buffett_engine import compute_buffett

companies = _load_screening_data()
# 처음 3개만 테스트
for co in companies[:3]:
    cc = co["corp_code"]
    curr = co["curr"]
    prev = co.get("prev")
    mktcap = co.get("market_cap")
    try:
        sf_list = [curr] + ([prev] if prev else [])
        bm = compute_buffett(sf_list, mktcap)
        print(f"{cc} {co['corp_name']}: piotroski={bm.piotroski_score}")
    except Exception as e:
        print(f"{cc} {co['corp_name']}: ERROR {type(e).__name__}: {e}")
