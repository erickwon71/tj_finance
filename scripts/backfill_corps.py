"""지정 기업의 정기보고서를 **전 기간** 수집한다(B3 — 신규 상장 등).

데일리(`collect_new.py`)는 최근 N일 공시 창으로 탐지하므로, **신규 상장기업의 과거
보고서**는 영원히 안 들어온다. 상장 전에도 등록법인으로 사업보고서를 내던 회사가 많고,
상장 직후 첫 분기보고서 전까지는 데일리 창에도 안 걸린다.

이 스크립트는 corp_code 를 직접 받아 DART 공시목록을 전 기간 동기화하고 다운로드까지 한다.
파싱·표준화는 하지 않는다(계층3 재설계 중 — 계획 §5.1 의 download-only 원칙).

사용:
    python scripts/backfill_corps.py --corps 01370517,01596221
    python scripts/backfill_corps.py --zero-filings       # 정기보고서 0건인 활성기업 전부
    python scripts/backfill_corps.py --zero-filings --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.storage_guard import StorageContractError, assert_storage


def zero_filing_corps() -> list[tuple[str, str]]:
    """활성인데 정기보고서가 0건인 기업 — 신규 상장 후 미수집분."""
    with get_session() as s:
        return [(r[0], r[1]) for r in s.execute(text("""
            SELECT c.corp_code, c.corp_name
            FROM corporations c
            WHERE c.is_active
              AND c.delisting_status IS DISTINCT FROM 'confirmed'
              AND NOT EXISTS (SELECT 1 FROM filings f WHERE f.corp_code = c.corp_code)
            ORDER BY c.created_at
        """)).fetchall()]


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--corps", type=str, help="쉼표구분 corp_code")
    g.add_argument("--zero-filings", action="store_true",
                   help="정기보고서 0건인 활성기업 전부")
    ap.add_argument("--dry-run", action="store_true", help="대상만 출력하고 종료")
    args = ap.parse_args()

    if args.zero_filings:
        targets = zero_filing_corps()
    else:
        codes = [c.strip() for c in args.corps.split(",") if c.strip()]
        with get_session() as s:
            targets = [(r[0], r[1]) for r in s.execute(text(
                "SELECT corp_code, corp_name FROM corporations WHERE corp_code = ANY(:c)"),
                {"c": codes}).fetchall()]

    if not targets:
        logger.success("대상 없음 — 할 일이 없다.")
        return

    print(f"대상 {len(targets)}개 기업:")
    for code, name in targets:
        print(f"  {code}  {name}")
    if args.dry_run:
        print("\n[드라이런] 수집하지 않음.")
        return

    # 원문을 쓰기 전에 저장소 계약 확인 — 엉뚱한 볼륨에 받으면 안 된다.
    try:
        assert_storage(require_backup=False)
    except StorageContractError as exc:
        logger.error(f"저장소 계약 위반 — 중단\n{exc}")
        sys.exit(1)

    from collector.downloader import run_downloads
    from collector.filing_collector import sync_filings

    codes = [c for c, _ in targets]

    logger.info(f"① 공시목록 전 기간 동기화 — {len(codes)}개 기업")
    r1 = sync_filings(corp_codes=codes, force=True)
    logger.info(f"   {r1.get('processed', 0)}개 기업 처리 (API {r1.get('api_calls', 0)}콜)")

    with get_session() as s:
        found = s.execute(text(
            "SELECT count(*) FROM filings WHERE corp_code = ANY(:c)"), {"c": codes}).scalar()
    logger.info(f"   → filings {found:,}건 등록됨")

    if not found:
        logger.warning("정기보고서가 하나도 없다 — 상장 직후라 아직 제출 전일 수 있다.")
        return

    logger.info("② 다운로드")
    r2 = run_downloads(only_corp_codes=codes)
    logger.info(f"   완료 {r2.get('completed', 0)} / 실패 {r2.get('failed', 0)} / "
                f"스킵 {r2.get('skipped', 0)} (큐 {r2.get('total_queued', 0)})")

    # 기업별 결과 — 0건인 곳은 실제로 제출 이력이 없는지 사람이 판단할 수 있게 남긴다.
    with get_session() as s:
        rows = s.execute(text("""
            SELECT c.corp_code, c.corp_name,
                   count(f.rcept_no) FILTER (WHERE f.rcept_no IS NOT NULL) n_filings,
                   count(d.rcept_no) FILTER (WHERE d.status = 'completed') n_downloaded
            FROM corporations c
            LEFT JOIN filings f ON f.corp_code = c.corp_code
            LEFT JOIN download_tasks d ON d.rcept_no = f.rcept_no
            WHERE c.corp_code = ANY(:c)
            GROUP BY 1, 2 ORDER BY 2
        """), {"c": codes}).fetchall()
    print("\n기업별 결과:")
    for code, name, n_f, n_d in rows:
        flag = "" if n_f else "   ← 제출 이력 없음(상장 직후 정상일 수 있음)"
        print(f"  {code} {name:18s} 공시 {n_f:>3} · 다운로드 {n_d:>3}{flag}")


if __name__ == "__main__":
    main()
