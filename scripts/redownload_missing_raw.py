"""원문 파일이 실재하지 않는 filing 을 찾아 재다운로드한다(2015+ 계층2 공백 복구).

배경 — 데일리(`collect_new.py` ⑦ `_audit_completeness`)의 유실 복구는
`completed_at >= current_date - 1` 창만 본다. 그래서 **오래 전에 사라진 원문**은
`download_tasks.status='completed'` 인 채로 영원히 재수집 큐에 들어가지 않는다.
2026-08-04 계층2 감사에서 report_lines 가 통째로 비어 있는 기간 중 15건이
이 상태였다(원문 없음 → 파싱 불가 → 영구 공백).

검사 대상은 `raw_report` 심링크(= PRIMARY/NAS)다. 미러(dart_data)가 아니다 —
미러는 증분 복사라 지연될 수 있어 '없음'의 근거가 되지 못한다. 그래서 실행 전
`assert_storage()` 로 PRIMARY 가 실제로 마운트돼 있는지부터 확인한다.

기본은 조회만 한다. `--apply` 를 줘야 download_tasks 를 pending 으로 되돌리고
다운로드를 실행한다.

사용:
    python scripts/redownload_missing_raw.py                 # 조회만
    python scripts/redownload_missing_raw.py --apply         # 리셋 + 재다운로드
    python scripts/redownload_missing_raw.py --scope all     # 2015+ 전 filing 대상
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

# report_lines 가 통째로 비어 있는 (기업·연도·기간·보고서종류) 의 filing 들.
# download-only 창(2026-07-10 이후 제출분)은 제외한다 — 그건 아직 파싱을 안 돌린
# 것이지 원문이 없는 게 아니다.
SQL_GAP = """
WITH grp AS (
  SELECT f.corp_code, f.corp_name, f.fiscal_year, f.fiscal_period, f.report_type,
         f.rcept_no, f.filed_at,
         count(*) FILTER (
             WHERE EXISTS (SELECT 1 FROM report_lines r WHERE r.rcept_no = f.rcept_no)
         ) OVER (PARTITION BY f.corp_code, f.fiscal_year, f.fiscal_period, f.report_type)
             AS n_loaded,
         max(f.filed_at)
             OVER (PARTITION BY f.corp_code, f.fiscal_year, f.fiscal_period, f.report_type)
             AS last_filed
  FROM filings f
  WHERE f.fiscal_year >= 2015
)
SELECT corp_code, corp_name, fiscal_year, fiscal_period, report_type, rcept_no, filed_at
FROM grp
WHERE n_loaded = 0 AND last_filed <= DATE '2026-07-10'
ORDER BY corp_name, fiscal_year, fiscal_period
"""

# 2015+ 전 filing (계층2 공백 여부와 무관하게 원문 유실 전수 점검).
SQL_ALL = """
SELECT f.corp_code, f.corp_name, f.fiscal_year, f.fiscal_period, f.report_type,
       f.rcept_no, f.filed_at
FROM filings f
WHERE f.fiscal_year >= 2015
ORDER BY f.corp_name, f.fiscal_year, f.fiscal_period
"""


def find_vanished(scope: str) -> list[dict]:
    """대상 filing 중 download_tasks 원장상 파일이 있어야 하는데 실재하지 않는 건."""
    sql = SQL_ALL if scope == "all" else SQL_GAP
    with get_session() as s:
        rows = s.execute(text(sql)).fetchall()
        # 원장(file_path)은 심링크 경로로 저장돼 있다 — 그대로 존재 확인한다.
        tasks = {
            r[0]: (r[1], r[2])
            for r in s.execute(text("""
                SELECT rcept_no, status, file_path FROM download_tasks
            """)).fetchall()
        }

    out = []
    for corp_code, corp_name, fy, fp, rt, rcept, filed in rows:
        status, file_path = tasks.get(rcept, (None, None))
        if file_path and Path(file_path).exists():
            continue
        out.append({
            "corp_code": corp_code, "corp_name": corp_name,
            "fiscal_year": fy, "fiscal_period": fp, "report_type": rt,
            "rcept_no": rcept, "filed_at": filed,
            "task_status": status, "file_path": file_path,
        })
    return out


def reset_to_pending(rcept_nos: list[str]) -> int:
    """원장을 pending 으로 되돌린다. attempts 도 0 으로 — MAX 도달분을 다시 태우기 위해서."""
    with get_session() as s:
        res = s.execute(text("""
            UPDATE download_tasks
               SET status = 'pending', attempts = 0,
                   last_error = 'redownload_missing_raw: 원문 유실 확인 후 재큐'
             WHERE rcept_no = ANY(:r)
        """), {"r": rcept_nos})
        s.commit()
        return res.rowcount


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=["gap", "all"], default="gap",
                    help="gap=계층2 공백 기간만(기본) · all=2015+ 전 filing")
    ap.add_argument("--apply", action="store_true", help="원장 리셋 + 재다운로드 실행")
    args = ap.parse_args()

    try:
        assert_storage()
    except StorageContractError as exc:
        logger.error(f"[storage] 계약 위반 — 중단한다: {exc}")
        logger.error("  PRIMARY(NAS)가 마운트돼 있지 않으면 '원문 없음' 판정 자체가 무의미하다.")
        return 2

    vanished = find_vanished(args.scope)
    if not vanished:
        logger.success(f"[redownload] 원문 유실 0건 (scope={args.scope})")
        return 0

    logger.warning(f"[redownload] 원문 유실 {len(vanished)}건 (scope={args.scope})")
    for v in vanished:
        logger.info(
            f"  {v['corp_name']:16s} {v['fiscal_year']}{v['fiscal_period']:3s} "
            f"{v['report_type']:8s} {v['rcept_no']} "
            f"task={v['task_status']} path={v['file_path']}"
        )

    if not args.apply:
        logger.info("[redownload] 조회만 했다. 실제 재수집은 --apply.")
        return 0

    rcept_nos = [v["rcept_no"] for v in vanished]
    n = reset_to_pending(rcept_nos)
    logger.info(f"[redownload] download_tasks {n}건 → pending")

    corp_codes = sorted({v["corp_code"] for v in vanished})
    from collector.downloader import run_downloads
    stats = run_downloads(only_corp_codes=corp_codes)
    logger.info(f"[redownload] 다운로드 결과 {stats}")

    # 사후 확인 — 여전히 없는 건이 무엇인지 남긴다(DART 에서 내려받을 수 없는 건이 있다).
    still = find_vanished(args.scope)
    if still:
        logger.warning(f"[redownload] 재수집 후에도 원문 없음 {len(still)}건")
        for v in still:
            logger.warning(f"  {v['corp_name']} {v['fiscal_year']}{v['fiscal_period']} "
                           f"{v['rcept_no']} task={v['task_status']}")
    else:
        logger.success("[redownload] 전건 복구 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
