"""B3 · 대주주/지분 현황 수집 — DART hyslrSttus/hyslrChgSttus/mrhlSttus.

사업보고서(11011) 기준 corp+fiscal_year 단위로 최대주주(+특수관계인) 지분, 최대주주 변동이력,
소액주주(float 근사치) 현황을 채운다. 각 corp+연도 delete-then-insert(멱등).
collect_executives.py 와 동일 패턴(샘플/재개/기업지정).

usage:
  python scripts/collect_shareholders.py --sample 20 --year 2024
  python scripts/collect_shareholders.py --corps 00126380,00164779 --year 2024
  python scripts/collect_shareholders.py --year 2024 --skip-existing   # 전 활성기업(장시간, 재개)
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
from collector.models import MajorShareholder, RetailOwnership, ShareholderChange


def _t(v, n: int):
    if not v:
        return None
    s = str(v).strip()
    return s[:n] if s else None


def _parse_int(v) -> int | None:
    if not v or v == "-":
        return None
    try:
        return int(str(v).replace(",", "").strip())
    except ValueError:
        return None


def _parse_pct(v) -> float | None:
    if not v or v == "-":
        return None
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def _map_shareholder(corp_code: str, year: int, row: dict) -> dict:
    return {
        "corp_code": corp_code, "fiscal_year": year,
        "name": _t(row.get("nm"), 100) or "?",
        "relation": _t(row.get("relate"), 50),
        "stock_kind": _t(row.get("stock_knd"), 20),
        "shares_begin": _parse_int(row.get("bsis_posesn_stock_co")),
        "pct_begin": _parse_pct(row.get("bsis_posesn_stock_qota_rt")),
        "shares_end": _parse_int(row.get("trmend_posesn_stock_co")),
        "pct_end": _parse_pct(row.get("trmend_posesn_stock_qota_rt")),
        "remark": _t(row.get("rm"), 200),
        "fetched_at": datetime.utcnow(),
    }


def _map_change(corp_code: str, year: int, row: dict) -> dict:
    return {
        "corp_code": corp_code, "fiscal_year": year,
        "change_on": _t(row.get("change_on"), 20),
        "holder_name": _t(row.get("mxmm_shrholdr_nm"), 100),
        "shares": _parse_int(row.get("posesn_stock_co")),
        "pct": _parse_pct(row.get("qota_rt")),
        "cause": _t(row.get("change_cause"), 200),
        "fetched_at": datetime.utcnow(),
    }


def _map_retail(corp_code: str, year: int, row: dict) -> dict:
    return {
        "corp_code": corp_code, "fiscal_year": year,
        "holder_count": _parse_int(row.get("shrholdr_co")),
        "holder_total_count": _parse_int(row.get("shrholdr_tot_co")),
        "holder_rate_pct": _parse_pct(row.get("shrholdr_rate")),
        "held_shares": _parse_int(row.get("hold_stock_co")),
        "total_shares": _parse_int(row.get("stock_tot_co")),
        "held_rate_pct": _parse_pct(row.get("hold_stock_rate")),
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
            "SELECT DISTINCT corp_code FROM major_shareholders WHERE fiscal_year = :y"),
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
    logger.info(f"[shr] 대상 {len(corps)}사 · {args.year} 사업보고서")

    agg = {"corps": 0, "shr_rows": 0, "chg_rows": 0, "retail_rows": 0, "empty": 0, "err": 0}
    for i, corp in enumerate(corps, 1):
        try:
            shr_raw = client.get_major_shareholders(corp, args.year, "11011")
            chg_raw = client.get_shareholder_changes(corp, args.year, "11011")
            retail_raw = client.get_minority_shareholders(corp, args.year, "11011")
        except DartApiError as e:
            if e.status not in ("013", "020"):
                agg["err"] += 1
                logger.warning(f"[shr] {corp}: DART [{e.status}] {e.message}")
            continue
        except Exception as e:  # noqa: BLE001
            agg["err"] += 1
            logger.warning(f"[shr] {corp}: {type(e).__name__}: {e}")
            continue

        if not shr_raw and not chg_raw and not retail_raw:
            agg["empty"] += 1
            continue

        shr_recs = [_map_shareholder(corp, args.year, r) for r in shr_raw if (r.get("nm") or "").strip()]
        chg_recs = [_map_change(corp, args.year, r) for r in chg_raw if (r.get("change_on") or "-") != "-"]
        retail_recs = [_map_retail(corp, args.year, r) for r in retail_raw]

        try:
            with get_session() as s:
                s.execute(text("DELETE FROM major_shareholders WHERE corp_code=:c AND fiscal_year=:y"),
                          {"c": corp, "y": args.year})
                if shr_recs:
                    s.execute(pg_insert(MajorShareholder).values(shr_recs).on_conflict_do_nothing())

                s.execute(text("DELETE FROM shareholder_changes WHERE corp_code=:c AND fiscal_year=:y"),
                          {"c": corp, "y": args.year})
                if chg_recs:
                    s.execute(ShareholderChange.__table__.insert(), chg_recs)

                s.execute(text("DELETE FROM retail_ownership WHERE corp_code=:c AND fiscal_year=:y"),
                          {"c": corp, "y": args.year})
                if retail_recs:
                    s.execute(pg_insert(RetailOwnership).values(retail_recs).on_conflict_do_nothing())
                s.commit()
        except Exception as e:  # noqa: BLE001
            agg["err"] += 1
            logger.warning(f"[shr] {corp} 적재 실패: {type(e).__name__}: {e}")
            continue

        agg["corps"] += 1
        agg["shr_rows"] += len(shr_recs)
        agg["chg_rows"] += len(chg_recs)
        agg["retail_rows"] += len(retail_recs)
        if i % 50 == 0 or i == len(corps):
            logger.info(f"  ..{i}/{len(corps)} (기업 {agg['corps']} 대주주행 {agg['shr_rows']:,} "
                       f"변동 {agg['chg_rows']} 소액주주 {agg['retail_rows']} 빈 {agg['empty']} 오류 {agg['err']})")

    client.close()
    logger.success(f"[shr] 완료 — 기업 {agg['corps']} · 대주주행 {agg['shr_rows']:,} · "
                   f"변동 {agg['chg_rows']} · 소액주주 {agg['retail_rows']} · 빈 {agg['empty']} · 오류 {agg['err']}")


if __name__ == "__main__":
    main()
