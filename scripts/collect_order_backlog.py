"""B1(→B4) · 수주상황 수집 — 사업보고서 본문 표 → order_backlog.

로컬 저장 사업보고서(annual) XML 을 파싱해 order_backlog(기존 스키마, collector/models.py)
에 적재. corp+rcept 단위 delete-then-insert(멱등). collect_biz_metrics.py 와 동일 패턴.

⚠ v1 범위(2026-07-05 설계): 집계형(사업부문/품목별 수주총액·기납품액·수주잔고)과 프로젝트
상세형("계약잔액" 명시, 합산)만 지원. 계약잔액 없이 진행률%만 있는 표(대우건설/한화오션류
"진행률적용 수주계약 현황")는 backlog 파생 신뢰도가 낮아 자연 스킵(빈 결과) — 후속 과제.

usage:
  python scripts/collect_order_backlog.py --corps 00126478,00164478    # 지정 기업(전 연도)
  python scripts/collect_order_backlog.py --sample 50 --latest          # 표본 50사 최신 사업보고서
  python scripts/collect_order_backlog.py --year 2024                   # 전 활성기업 2024 사업보고서
  python scripts/collect_order_backlog.py --skip-existing --latest      # 재개(장시간)
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.order_backlog import sync_order_backlog


def _pick(session, args) -> list[str]:
    if args.corps:
        raw = args.corps
        try:
            is_file = Path(raw).exists()
        except OSError:
            is_file = False  # 콤마 리스트가 길면 Path().exists() 가 "파일명 너무 김" 으로 크래시
        if is_file:
            raw = Path(raw).read_text()
        return [c.strip() for c in raw.replace("\n", ",").split(",") if c.strip()]
    corps = [r[0] for r in session.execute(text(
        "SELECT corp_code FROM corporations WHERE is_active AND stock_code IS NOT NULL "
        "ORDER BY corp_code")).fetchall()]
    if args.skip_existing:
        done = {r[0] for r in session.execute(text(
            "SELECT DISTINCT corp_code FROM order_backlog")).fetchall()}
        corps = [c for c in corps if c not in done]
    if args.shard:
        # 전수 백필 병렬화 — collect_biz_metrics.py 와 동일 규약. 기업 단위로 나누므로
        # 샤드끼리 (corp, fiscal_year) 삭제 범위가 겹치지 않는다.
        idx, total = (int(x) for x in args.shard.split("/"))
        if not (0 <= idx < total):
            raise SystemExit(f"--shard {args.shard}: 0 <= i < n 이어야 함")
        corps = [c for i, c in enumerate(corps) if i % total == idx]
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
                    help="이미 order_backlog 있는 기업 건너뜀(중단 후 재개용)")
    ap.add_argument("--shard", metavar="i/n",
                    help="전수 백필 병렬 분할(예: 0/8). 기업 단위라 샤드끼리 겹치지 않음")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    with get_session() as s:
        corps = _pick(s, args)
    scope = f"{args.year} 사업보고서" if args.year else ("최신 사업보고서" if args.latest else "전 연도 사업보고서")
    logger.info(f"[order] 대상 {len(corps)}사 · {scope}")

    agg = sync_order_backlog(corps, year=args.year, latest_only=args.latest)
    logger.success(f"[order] 완료 — 기업 {agg['corps']} · 보고서 {agg['reports']} · "
                   f"행 {agg['rows']:,} · 빈 {agg['empty']} · 파일없음 {agg['missing_file']} · "
                   f"오류 {agg['err']}")


if __name__ == "__main__":
    main()
