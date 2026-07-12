"""Phase 2 · 주주환원 + 회사 일반현황 API 6종 백필 오케스트레이터.

scripts/collect_shareholders.py 와 동일 CLI/circuit-breaker 패턴(연속 '020' 감지 시 즉시
중단 + 재개 안내, key-bugs-fixed.md #6·#7). corp × fiscal_year × api 그레인으로
periodic_api_progress 체크포인트를 조회해 --skip-existing 시 이미 처리된 조합을 건너뛴다.

usage:
    python scripts/collect_periodic_apis.py --api alotMatter --years 2020-2025 --sample 20
    python scripts/collect_periodic_apis.py --api tesstkAcqsDspsSttus --years 2020-2025 \\
        --skip-existing   # 전 활성기업(장시간, 재개)
    python scripts/collect_periodic_apis.py --api otrCprInvstmntSttus,hmvAuditAllSttus,indvdlByPay \\
        --years 2023 --corps 00126380,00164779
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
from collector.dart_periodic import API_NAMES, sync_periodic
from collector.db import get_session
from collector.rate_limiter import DailyQuotaReached

# 연속 '020'(사용한도초과) 이 이 값 이상 이어지면 일일 쿼터 소진으로 보고 즉시 중단한다.
# collect_shareholders.py 와 동일 근거(memory key-bugs-fixed.md #6·#7).
_QUOTA_STREAK_LIMIT = 5


def _parse_years(spec: str) -> list[int]:
    if "-" in spec:
        a, b = (int(x) for x in spec.split("-"))
        return list(range(a, b + 1))
    return [int(x) for x in spec.split(",") if x.strip()]


def _parse_apis(spec: str) -> list[str]:
    if spec == "all":
        return list(API_NAMES)
    apis = [a.strip() for a in spec.split(",") if a.strip()]
    unknown = [a for a in apis if a not in API_NAMES]
    if unknown:
        raise SystemExit(f"알 수 없는 API: {unknown} (허용: {API_NAMES})")
    return apis


def _pick_corps(session, args) -> list[str]:
    if args.corps:
        raw = args.corps
        if Path(raw).exists():
            raw = Path(raw).read_text()
        return [c.strip() for c in raw.replace("\n", ",").split(",") if c.strip()]
    corps = [r[0] for r in session.execute(text(
        "SELECT corp_code FROM corporations WHERE is_active AND stock_code IS NOT NULL "
        "ORDER BY corp_code")).fetchall()]
    if args.sample:
        random.Random(args.seed).shuffle(corps)
        corps = corps[: args.sample]
    return corps


def _load_skip_set(years: list[int], apis: list[str]) -> set[tuple[str, int, str]]:
    with get_session() as s:
        rows = s.execute(text(
            "SELECT corp_code, fiscal_year, api_name FROM periodic_api_progress "
            "WHERE fiscal_year = ANY(:years) AND api_name = ANY(:apis)"
        ), {"years": years, "apis": apis}).fetchall()
    return {(r[0], r[1], r[2]) for r in rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True,
                    help="쉼표구분 API명 또는 'all': " + ",".join(API_NAMES))
    ap.add_argument("--years", required=True, help="예: 2020-2025 또는 2023,2024")
    ap.add_argument("--corps")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--skip-existing", action="store_true",
                    help="periodic_api_progress 에 이미 체크포인트 있는 (corp,fy,api) 건너뜀(재개용)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    apis = _parse_apis(args.api)
    years = _parse_years(args.years)

    client = DartClient()
    with get_session() as s:
        corps = _pick_corps(s, args)

    skip_set = _load_skip_set(years, apis) if args.skip_existing else set()
    total = len(corps) * len(years) * len(apis)
    logger.info(f"[periodic] 대상 {len(corps)}사 × {years} × {apis} = {total:,}콜"
                + (f" (기확인 {len(skip_set):,}건 스킵)" if skip_set else ""))

    rows_saved = 0
    done = 0
    quota_streak = 0

    for corp in corps:
        for fy in years:
            for api in apis:
                if (corp, fy, api) in skip_set:
                    continue
                try:
                    n = sync_periodic(client, api, corp, fy)
                except DailyQuotaReached as e:
                    logger.error(f"[periodic] {e} — 중단합니다 ({done:,}/{total:,}건 처리, "
                                 f"직전 corp={corp} fy={fy} api={api}).")
                    client.close()
                    return
                except DartApiError as e:
                    # sync_periodic 은 '020'(쿼터초과)만 그대로 raise — 그 외 비-000 은 내부에서
                    # error 체크포인트를 기록하고 0 을 반환하므로 여기 도달하는 예외는 항상 020.
                    quota_streak += 1
                    if quota_streak >= _QUOTA_STREAK_LIMIT:
                        logger.error(
                            f"[periodic] 연속 {quota_streak}회 '020'(사용한도초과) — DART 서버측 "
                            f"일일 쿼터가 소진된 것으로 보여 중단합니다 ({done:,}/{total:,}건 처리). "
                            f"쿼터 리셋(보통 익일) 후 재실행: python scripts/collect_periodic_apis.py "
                            f"--api {args.api} --years {args.years} --skip-existing")
                        client.close()
                        return
                    continue

                quota_streak = 0
                done += 1
                rows_saved += n
                if done % 200 == 0 or done == total:
                    logger.info(f"  ..{done:,}/{total:,} (누적 rows={rows_saved:,})")

    client.close()

    # 정확한 ok/no_data/error 분포는 이번 실행분(corp,fy,api)에 한해 DB 체크포인트에서 재집계.
    with get_session() as s:
        breakdown = s.execute(text(
            "SELECT status, count(*) FROM periodic_api_progress "
            "WHERE corp_code = ANY(:corps) AND fiscal_year = ANY(:years) AND api_name = ANY(:apis) "
            "GROUP BY status"
        ), {"corps": corps, "years": years, "apis": apis}).fetchall()
    counts = {status: cnt for status, cnt in breakdown}
    logger.success(f"[periodic] 완료 — 처리 {done:,}/{total:,} · rows={rows_saved:,} · "
                   f"ok={counts.get('ok', 0)} no_data={counts.get('no_data', 0)} "
                   f"error={counts.get('error', 0)}")


if __name__ == "__main__":
    main()
