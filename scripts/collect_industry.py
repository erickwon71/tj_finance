"""업종코드 수집 — DART company.json → corporations.induty_code (섹터/피어 그룹핑용).

활성 보통주의 업종코드(KSIC)를 채운다. 섹터 그룹핑은 앱에서 induty_code 접두(2자리=중분류)로 수행.
멱등: 기존 값 덮어씀. --skip-existing 로 중단 후 재개.

usage:
  python scripts/collect_industry.py --sample 20
  python scripts/collect_industry.py                 # 전 활성기업(장시간)
  python scripts/collect_industry.py --skip-existing  # 재개
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.dart_client import DartClient, DartApiError
from collector.db import get_session


def _pick(session, args) -> list[str]:
    if args.corps:
        raw = args.corps
        if Path(raw).exists():
            raw = Path(raw).read_text()
        return [c.strip() for c in raw.replace("\n", ",").split(",") if c.strip()]
    q = ("SELECT corp_code FROM corporations WHERE is_active AND stock_code IS NOT NULL "
         + ("AND induty_code IS NULL " if args.skip_existing else "") + "ORDER BY corp_code")
    corps = [r[0] for r in session.execute(text(q)).fetchall()]
    if args.sample:
        random.Random(args.seed).shuffle(corps)
        corps = corps[: args.sample]
    return corps


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corps")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    client = DartClient()
    with get_session() as s:
        corps = _pick(s, args)
    logger.info(f"[industry] 대상 {len(corps)}사")

    agg = {"ok": 0, "empty": 0, "err": 0}
    for i, corp in enumerate(corps, 1):
        try:
            d = client.get_company(corp)
        except DartApiError as e:
            if e.status != "020":
                agg["err"] += 1
                logger.warning(f"[industry] {corp}: DART [{e.status}] {e.message}")
            continue
        except Exception as e:  # noqa: BLE001
            agg["err"] += 1
            logger.warning(f"[industry] {corp}: {type(e).__name__}: {e}")
            continue
        code = (d.get("induty_code") or "").strip()[:6] or None
        if not code:
            agg["empty"] += 1
            continue
        with get_session() as s:
            s.execute(text("UPDATE corporations SET induty_code=:i WHERE corp_code=:c"),
                      {"i": code, "c": corp})
            s.commit()
        agg["ok"] += 1
        if i % 100 == 0 or i == len(corps):
            logger.info(f"  ..{i}/{len(corps)} (ok {agg['ok']} 빈 {agg['empty']} 오류 {agg['err']})")
    client.close()
    logger.success(f"[industry] 완료 — ok {agg['ok']} · 빈 {agg['empty']} · 오류 {agg['err']}")


if __name__ == "__main__":
    main()
