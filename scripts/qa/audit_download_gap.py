"""Download-pipeline status audit (read-only).

Compares DART's periodic-disclosure list (pblntf_ty=A) for a date window against
what `filings` / `download_tasks` hold, so we can see exactly which reports are
missing or undownloaded as of today.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text

from collector.db import get_session
from collector.dart_client import DartClient

PERIODIC = ("사업보고서", "반기보고서", "분기보고서")


def fetch_dart(bgn: str, end: str) -> list[dict]:
    client = DartClient()
    items: list[dict] = []
    page = 1
    try:
        while page <= 200:
            data = client._api_get_json("/list.json", {
                "bgn_de": bgn, "end_de": end, "pblntf_ty": "A",
                "page_no": page, "page_count": 100,
            })
            batch = data.get("list", []) or []
            items.extend(batch)
            total_page = int(data.get("total_page", 1) or 1)
            if page >= total_page or not batch:
                break
            page += 1
    finally:
        client.close()
    return items


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=20)
    args = ap.parse_args()

    end = date.today()
    bgn = end - timedelta(days=args.days)
    bgn_s, end_s = bgn.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    print(f"DART 조회 창: {bgn_s} ~ {end_s}")

    items = fetch_dart(bgn_s, end_s)
    print(f"정기공시(A) 총 {len(items):,}건")

    with get_session() as s:
        active = {r[0] for r in s.execute(
            text("SELECT corp_code FROM corporations WHERE is_active")).fetchall()}
        have = {r[0] for r in s.execute(
            text("SELECT rcept_no FROM filings WHERE filed_at >= :b"),
            {"b": bgn}).fetchall()}
        downloaded = {r[0] for r in s.execute(
            text("SELECT rcept_no FROM download_tasks WHERE status='completed'")).fetchall()}

    # 우리 유니버스(활성 보통주) + 정기 3종만
    target = [it for it in items
              if it.get("corp_code") in active
              and any(k in (it.get("report_nm") or "") for k in PERIODIC)]
    amend = [it for it in target if "정정" in (it.get("report_nm") or "")]
    print(f"우리 유니버스 대상: {len(target):,}건 (그중 정정 {len(amend):,}건)")

    missing_filing = [it for it in target if it["rcept_no"] not in have]
    in_db_not_dl = [it for it in target
                    if it["rcept_no"] in have and it["rcept_no"] not in downloaded]

    print(f"\n① filings 테이블에 없음(미탐지): {len(missing_filing):,}건")
    for it in sorted(missing_filing, key=lambda x: x["rcept_dt"])[:40]:
        print(f"   {it['rcept_dt']} {it['rcept_no']} {it['corp_name']:<14} {it['report_nm']}")
    if len(missing_filing) > 40:
        print(f"   ... 외 {len(missing_filing) - 40}건")

    print(f"\n② filings 에는 있으나 다운로드 미완료: {len(in_db_not_dl):,}건")
    for it in sorted(in_db_not_dl, key=lambda x: x["rcept_dt"])[:40]:
        print(f"   {it['rcept_dt']} {it['rcept_no']} {it['corp_name']:<14} {it['report_nm']}")


if __name__ == "__main__":
    main()
