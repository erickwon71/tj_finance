"""P0-5 · 부채총계=자산총계 매핑오류 교정 (외부평가 2026-07-15).

구형 K-GAAP 공시(2006~2013 등)에서 BS 우변합계 라벨의 **변형("부채와자본총계" 등 및↔와)**이
스킵리스트를 우회해 `total_liabilities` 에 자산총계 값이 그대로 들어간 행이 있다(예: 한국석유공업
2011 부채=자산=236,295,082,168, 자본=100,573,058,272 → 부채는 assets−equity 여야 함).
이로 인해 자산≠부채+자본 항등식이 깨지고 부채비율이 왜곡된다.

교정: **회계 항등식 기반 재구성** — total_assets·total_equity 를 신뢰하고
`total_liabilities = total_assets − total_equity` 로 복원한다(정확일치 + equity>0 = 매핑오류 확정).
소비계층 정합을 위해 세 테이블 모두 교정: std_financials_v2(회사 시각화)·standard_financials
(스크리너/피어)·std_financials_calendar(분기 변화). 재발방지는 table_extractor 스킵리스트 보강(별도).

usage:
  python scripts/fix_bs_liability_mapping.py            # 진단(기본)
  python scripts/fix_bs_liability_mapping.py --apply    # 실제 교정
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session

# (테이블, 추가 WHERE) — 정확일치 + equity>0 자체가 매핑오류 판별식이라 추가 필터는 최소화.
_TARGETS = [
    ("std_financials_v2", "AND version = 1"),
    ("standard_financials", ""),
    ("std_financials_calendar", "AND version = 1"),
]

_PRED = ("total_assets IS NOT NULL AND total_liabilities IS NOT NULL "
         "AND total_equity IS NOT NULL AND total_assets = total_liabilities "
         "AND total_equity > 0")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 교정(미지정 시 진단만)")
    args = ap.parse_args()

    total_fixed = 0
    with get_session() as s:
        for table, extra in _TARGETS:
            cnt = s.execute(text(
                f"SELECT count(*) FROM {table} WHERE {_PRED} {extra}")).scalar() or 0
            if cnt == 0:
                logger.info(f"[fix-bs] {table}: 대상 0 행 — 스킵")
                continue
            if not args.apply:
                logger.info(f"[fix-bs] {table}: (dry-run) 교정 대상 {cnt} 행 — --apply 로 실행")
                continue
            res = s.execute(text(
                f"UPDATE {table} SET total_liabilities = total_assets - total_equity "
                f"WHERE {_PRED} {extra}"))
            logger.success(f"[fix-bs] {table}: {res.rowcount} 행 부채총계 재구성"
                           f"(= 자산−자본)")
            total_fixed += res.rowcount

    if args.apply:
        logger.success(f"[fix-bs] 완료 — 총 {total_fixed} 행 교정. 항등식(자산=부채+자본) 복원.")
    else:
        logger.info("[fix-bs] 진단 완료(변경 없음). 실제 교정은 --apply")


if __name__ == "__main__":
    main()
