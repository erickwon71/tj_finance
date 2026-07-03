"""임원 현황 수집 — DART exctvSttus → executives 테이블(지배구조 패널용).

미사용이던 executives 테이블을 채운다. 사업보고서(11011) 기준 임원 로스터(성명·직위·등기/상근·
담당업무·주요경력·최대주주관계·재직기간). corp+fiscal_year 단위 delete-then-insert(멱등).
보수(compensation)는 개별 5억+ 공시라 대부분 NULL — 여기선 로스터만 적재.

usage:
  python scripts/collect_executives.py --sample 20 --year 2024
  python scripts/collect_executives.py --corps 00126380,00164779 --year 2024
  python scripts/collect_executives.py --year 2024            # 전 활성기업(장시간)
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from collector.dart_client import DartClient, DartApiError
from collector.db import get_session
from collector.models import Executive


def _reg(v: str | None) -> bool | None:
    if not v:
        return None
    return ("등기" in v) and ("미등기" not in v)


def _fte(v: str | None) -> bool | None:
    if not v:
        return None
    if "비상근" in v:
        return False
    if "상근" in v:
        return True
    return None


def _t(v, n: int):
    """컬럼 길이 초과 방지 절삭(공백 정리). None 보존."""
    if not v:
        return None
    s = str(v).strip()
    return s[:n] if s else None


def _map(corp_code: str, year: int, row: dict) -> dict:
    return {
        "corp_code": corp_code, "fiscal_year": year,
        "name": _t(row.get("nm"), 50) or "?",
        "gender": _t(row.get("sexdstn"), 4),
        "birth_ym": _t(row.get("birth_ym"), 10),
        "position": _t(row.get("ofcps"), 150),
        "is_registered": _reg(row.get("rgist_exctv_at")),
        "is_fulltime": _fte(row.get("fte_at")),
        "responsibility": _t(row.get("chrg_job"), 300),
        "main_career": _t(row.get("main_career"), 500),
        "shareholder_rel": _t(row.get("maxmm_shrholdr_relate"), 100),
        "tenure_period": _t(row.get("hffc_pd"), 60),
        "tenure_end": _t(row.get("tenure_end_date"), 20),
        "fetched_at": datetime.utcnow(),
    }


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
            "SELECT DISTINCT corp_code FROM executives WHERE fiscal_year = :y"),
            {"y": args.year}).fetchall()}
        corps = [c for c in corps if c not in done]
    if args.sample:
        random.Random(args.seed).shuffle(corps)
        corps = corps[: args.sample]
    return corps


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corps")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--year", type=int, default=2024, help="사업연도(기본 2024)")
    ap.add_argument("--skip-existing", action="store_true",
                    help="해당 연도 이미 수집된 기업 건너뜀(중단 후 재개용)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    client = DartClient()
    with get_session() as s:
        corps = _pick(s, args)
    logger.info(f"[exec] 대상 {len(corps)}사 · {args.year} 사업보고서")

    agg = {"corps": 0, "rows": 0, "empty": 0, "err": 0}
    for i, corp in enumerate(corps, 1):
        try:
            rows = client.get_executive_status(corp, args.year, "11011")
        except DartApiError as e:
            if e.status not in ("013", "020"):
                agg["err"] += 1
                logger.warning(f"[exec] {corp}: DART [{e.status}] {e.message}")
            continue
        except Exception as e:  # noqa: BLE001
            agg["err"] += 1
            logger.warning(f"[exec] {corp}: {type(e).__name__}: {e}")
            continue
        if not rows:
            agg["empty"] += 1
            continue
        recs = [_map(corp, args.year, r) for r in rows if (r.get("nm") or "").strip()]
        try:
            with get_session() as s:
                s.execute(text("DELETE FROM executives WHERE corp_code=:c AND fiscal_year=:y"),
                          {"c": corp, "y": args.year})
                if recs:
                    # (corp,year,name,position) 중복(동명·동직위) → 스킵.
                    s.execute(pg_insert(Executive).values(recs).on_conflict_do_nothing())
                s.commit()
        except Exception as e:  # noqa: BLE001
            agg["err"] += 1
            logger.warning(f"[exec] {corp} 적재 실패: {type(e).__name__}: {e}")
            continue
        agg["corps"] += 1
        agg["rows"] += len(recs)
        if i % 50 == 0 or i == len(corps):
            logger.info(f"  ..{i}/{len(corps)} (기업 {agg['corps']} 임원 {agg['rows']:,} 빈 {agg['empty']} 오류 {agg['err']})")
    client.close()
    logger.success(f"[exec] 완료 — 기업 {agg['corps']} · 임원 {agg['rows']:,} · 빈 {agg['empty']} · 오류 {agg['err']}")


if __name__ == "__main__":
    main()
