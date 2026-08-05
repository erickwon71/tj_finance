"""상장폐지 기업의 **파생 데이터**를 DB 에서 제거한다 (사용자 결정 2026-08-05).

배경 — 데일리 ⓪-4(2026-08-01)가 상장폐지 확정 기업의 원문을 NAS 아카이브로 이관하면서
원본 폴더를 지우는데, `download_tasks.file_path` 는 옛 경로 그대로다. 그래서 파서를 고쳐도
이 기업들은 로더가 **조용히 skip** 하고(파일 없음) 옛 결과가 그대로 남는다. 실측 12개사
923건 전부가 이 상태였다(원문은 아카이브에 온전하다 — 유실 아님).

유니버스가 '현재 시점 상장 보통주'(CLAUDE.md)라 상장폐지분은 앱에서 쓰지 않고, 아카이브도
언젠가 지운다는 것이 사용자 판단이다. 그래서 **경로를 고쳐 되살리는 대신 파생 데이터를 지운다.**

★ 무엇을 남기는가 — **원장은 남긴다**(`corporations`·`filings`·`download_tasks`·
  `delisting_audit`). 이것까지 지우면 "이 기업이 있었고 상장폐지됐다"는 사실이 사라져,
  수집기가 다시 후보로 올리거나 상장폐지 판정 이력을 잃을 수 있다. 지우는 것은 **파싱·집계
  산출물**뿐이다(원문이 아카이브에 있는 한 언제든 다시 만들 수 있는 것들).

사용:
    python scripts/purge_delisted_data.py              # dry-run(집계만)
    python scripts/purge_delisted_data.py --apply      # 실제 삭제
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session

# 지우지 않는다 — 원장(무엇이 있었고 왜 빠졌는지의 기록).
KEEP = {"corporations", "filings", "download_tasks", "delisting_audit"}

SQL_CORPS = "SELECT corp_code FROM corporations WHERE is_active = FALSE"


def _targets(s) -> list[tuple[str, str]]:
    """(테이블, 삭제 조건 컬럼) — corp_code 직결 우선, 없으면 rcept_no 경유."""
    out = []
    # ★ `table_type='BASE TABLE'` 필수 — 뷰를 포함하면 DELETE 가 터진다(실측:
    #   standard_financials·standard_financials_verified·calendar_financials 는 뷰다).
    #   뷰는 원본 테이블을 지우면 따라서 비므로 여기서 다룰 대상이 아니다.
    for (t,) in s.execute(text("""
        SELECT table_name FROM information_schema.tables
         WHERE table_schema='public' AND table_type='BASE TABLE'
         ORDER BY table_name""")).fetchall():
        if t in KEEP:
            continue
        cols = {c[0] for c in s.execute(text("""
            SELECT column_name FROM information_schema.columns
             WHERE table_name=:t"""), {"t": t}).fetchall()}
        if "corp_code" in cols:
            out.append((t, "corp"))
        elif "rcept_no" in cols:
            out.append((t, "rcept"))
    return out


def _where(kind: str) -> str:
    if kind == "corp":
        return f"corp_code IN ({SQL_CORPS})"
    return (f"rcept_no IN (SELECT rcept_no FROM filings "
            f"WHERE corp_code IN ({SQL_CORPS}))")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 삭제(기본은 집계만)")
    args = ap.parse_args()

    with get_session() as s:
        corps = s.execute(text("""
            SELECT corp_name, corp_code FROM corporations
             WHERE is_active=FALSE ORDER BY corp_name""")).fetchall()
        print(f"대상 기업(is_active=FALSE) {len(corps)}개:")
        for name, cc in corps:
            print(f"   {name} ({cc})")

        targets = _targets(s)
        print(f"\n{'테이블':34s} {'삭제 행':>12s}")
        total = 0
        plan = []
        for t, kind in targets:
            n = s.execute(text(f"SELECT count(*) FROM {t} WHERE {_where(kind)}")).scalar()
            if n:
                print(f"   {t:31s} {n:>12,}")
                total += n
                plan.append((t, kind, n))
        print(f"   {'합계':31s} {total:>12,}")
        print(f"\n남기는 것(원장): {', '.join(sorted(KEEP))}")

        if not args.apply:
            print("\n집계만 했다. 실제 삭제는 --apply.")
            return 0

        logger.warning(f"[purge] 삭제 시작 — {len(plan)}개 테이블 {total:,}행")
        for t, kind, n in plan:
            res = s.execute(text(f"DELETE FROM {t} WHERE {_where(kind)}"))
            logger.info(f"  {t:31s} {res.rowcount:>12,} 삭제")
        s.commit()
        logger.success("[purge] 완료 — 원장은 보존됨")

        # 사후 확인
        left = sum(s.execute(text(f"SELECT count(*) FROM {t} WHERE {_where(k)}")).scalar()
                   for t, k, _ in plan)
        print(f"\n삭제 후 잔여: {left}  (0 이어야 함)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
