"""B4a · 생산능력/생산실적/가동률 수집 — 사업보고서 본문 표 → biz_metrics.

로컬 저장 사업보고서(annual) XML 을 파싱해 biz_section_tables(원본 grid) + biz_metrics
(구조화 long-format)에 적재. corp+rcept 단위 delete-then-insert(멱등).
collect_shareholders.py 와 동일 패턴(샘플/재개/기업지정).

usage:
  python scripts/collect_biz_metrics.py --corps 00126380,00138279          # 지정 기업(전 연도)
  python scripts/collect_biz_metrics.py --sample 50 --latest               # 표본 50사 최신 사업보고서
  python scripts/collect_biz_metrics.py --year 2024                        # 전 활성기업 2024 사업보고서
  python scripts/collect_biz_metrics.py --skip-existing --latest           # 재개(장시간)
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
            "SELECT DISTINCT corp_code FROM biz_metrics")).fetchall()}
        corps = [c for c in corps if c not in done]
    if args.skip_catalog_existing:
        # B5 카탈로그 백필 재개용 — 기존 생산/매출 지표가 있어도 **카탈로그 metric 이 없으면**
        # 다시 파싱한다. `--skip-existing` 은 biz_metrics 존재 여부만 보므로 신규 항목 백필에
        # 그대로 쓰면 전 기업이 스킵된다(파서 추가 시 늘 걸리는 함정).
        from fin2.extract.biz_catalog import CATALOG
        metrics = sorted({m for m, _, _ in CATALOG})
        done = {r[0] for r in session.execute(text(
            "SELECT DISTINCT corp_code FROM biz_metrics WHERE metric = ANY(:m)"),
            {"m": metrics}).fetchall()}
        corps = [c for c in corps if c not in done]
    if args.shard:
        # 전수 백필 병렬화 — 파싱이 CPU 바운드라 코어 수만큼 갈라 쓰면 벽시계 시간이 그만큼 준다.
        # 기업 단위로 나누므로 샤드끼리 **rcept_no 가 겹치지 않는다** → delete-then-insert 가
        # 서로 침범하지 않고, 각 샤드는 독립적으로 재개 가능하다(corps 는 corp_code 정렬이라
        # 분할이 결정적).
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
                    help="이미 biz_metrics 있는 기업 건너뜀(중단 후 재개용)")
    ap.add_argument("--skip-catalog-existing", action="store_true",
                    help="B5 카탈로그 metric 이 이미 있는 기업만 건너뜀(신규 항목 백필 재개용)")
    ap.add_argument("--shard", metavar="i/n",
                    help="전수 백필 병렬 분할(예: 0/8). 기업 단위라 샤드끼리 겹치지 않음")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    with get_session() as s:
        corps = _pick(s, args)
    scope = f"{args.year} 사업보고서" if args.year else ("최신 사업보고서" if args.latest else "전 연도 사업보고서")
    logger.info(f"[biz] 대상 {len(corps)}사 · {scope}")

    agg = sync_biz_metrics(corps, year=args.year, latest_only=args.latest)
    logger.success(f"[biz] 완료 — 기업 {agg['corps']} · 보고서 {agg['reports']} · 표 {agg['tables']} · "
                   f"지표행 {agg['metric_rows']:,} · 빈 {agg['empty']} · 파일없음 {agg['missing_file']} · "
                   f"오류 {agg['err']}")


if __name__ == "__main__":
    main()
