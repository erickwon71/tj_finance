"""B4→Phase 3 · 부문·수출/내수 매출실적 백필 — 사업보고서 본문표 → biz_metrics(metric='sales').

매출 파서는 fin2/extract/biz_section.parse_biz_metrics 에 통합돼 생산지표와 함께 방출되므로
이 스크립트는 collect_biz_metrics.py 와 동일한 sync(sync_biz_metrics, rcept 단위 delete-then-insert
멱등)를 재사용한다. 차이는 **--skip-existing 이 metric='sales' 존재 여부로 판정**하는 점 —
기존 B4 생산 백필로 이미 biz_metrics 가 있는 기업이라도 아직 sales 행이 없으면 재파싱해서
매출을 추가한다(재파싱은 생산행도 동일하게 재적재하지만 멱등이라 무해).

전수 백필(로컬 파일, DART API 미호출 — 쿼터 무관, 수 시간):
  python scripts/collect_sales_metrics.py --latest --skip-existing

usage:
  python scripts/collect_sales_metrics.py --corps 00126380,00138279     # 지정 기업(전 연도)
  python scripts/collect_sales_metrics.py --sample 50 --latest          # 표본 50사 최신 사업보고서
  python scripts/collect_sales_metrics.py --latest --skip-existing       # 재개(장시간)
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.biz_metrics import sync_biz_metrics
from collector.db import get_session


def _pick(session, args) -> list[str]:
    if args.corps:
        raw = args.corps
        if Path(raw).exists():
            raw = Path(raw).read_text()
        return [c.strip() for c in raw.replace("\n", ",").split(",") if c.strip()]
    corps = [r[0] for r in session.execute(text(
        "SELECT corp_code FROM corporations WHERE is_active AND stock_code IS NOT NULL "
        "ORDER BY corp_code")).fetchall()]
    if args.skip_existing:
        done = {r[0] for r in session.execute(text(
            "SELECT DISTINCT corp_code FROM biz_metrics WHERE metric = 'sales'")).fetchall()}
        corps = [c for c in corps if c not in done]
    if args.sample:
        random.Random(args.seed).shuffle(corps)
        corps = corps[: args.sample]
    return corps


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corps", help="쉼표구분 corp_code 또는 파일경로")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--year", type=int, help="특정 사업연도만(미지정 시 전 연도)")
    ap.add_argument("--latest", action="store_true", help="기업별 최신 사업보고서 1건만")
    ap.add_argument("--skip-existing", action="store_true",
                    help="이미 sales 행 있는 기업 건너뜀(중단 후 재개용)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    with get_session() as s:
        corps = _pick(s, args)
    scope = f"{args.year} 사업보고서" if args.year else ("최신 사업보고서" if args.latest else "전 연도 사업보고서")
    logger.info(f"[sales] 대상 {len(corps)}사 · {scope} (매출+생산 재적재, rcept 멱등)")

    agg = sync_biz_metrics(corps, year=args.year, latest_only=args.latest)
    with get_session() as s:
        sales_rows = s.execute(text(
            "SELECT count(*) FROM biz_metrics WHERE metric='sales' AND corp_code = ANY(:c)"),
            {"c": corps}).scalar() if corps else 0
    logger.success(f"[sales] 완료 — 기업 {agg['corps']} · 보고서 {agg['reports']} · 표 {agg['tables']} · "
                   f"전체지표행 {agg['metric_rows']:,}(그중 sales {sales_rows:,}) · 빈 {agg['empty']} · "
                   f"파일없음 {agg['missing_file']} · 오류 {agg['err']}")


if __name__ == "__main__":
    main()
