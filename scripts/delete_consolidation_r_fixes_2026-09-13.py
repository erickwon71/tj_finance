"""연결비대상 확정(Track 1, 2026-09-13) 잔여 13건 원문대조 — D유형 6건 report_lines 정리
(사용자 원문대조 확정, docs/plans/consolidation_scope_confirmation_design_2026-09-13.md §12).

대상 6건(유진로봇 4 + 디어유 1 + CSA코스믹 1) — 한 표 안에서 열마다 basis가 다른데
파서가 표 전체를 'consolidated'로만 태깅해, 실제로는 연결재무제표가 없는 당기(현재
신고기간) 데이터가 basis='consolidated'로 중복 적재됐다(§11 D유형). 사용자가 DART
원문을 직접 확인해 "연결 불필요 확정, 데이터 삭제 문제없음"으로 판정 — 이 6건의
`report_lines` 중 basis='consolidated' 행 전부를 삭제한다(사전 확인: 6건 전부
context_fiscal_year이 당기 하나뿐이고 다른 연도 진짜 연결데이터가 섞여있지 않음을
이미 확인함 — 잘못 삭제할 다른 연도 데이터 없음).

`filings.consolidation_evidence`는 이 6건 전부 이미 'no_consolidated_fs_track1'로
정확히 판정돼 있으므로(D유형은 텍스트판정 자체는 맞음) 건드리지 않는다.

--dry-run(기본): 삭제될 행 수만 보여주고 실제 삭제 안 함.
--execute: 실제로 삭제 커밋.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from collector.db import get_session

_TARGET_RCEPTS = [
    "20220321001291",  # 유진로봇 2021 사업보고서
    "20220816000350",  # 유진로봇 2022 반기보고서
    "20221114002362",  # 유진로봇 2022 분기보고서
    "20230321001380",  # 유진로봇 2022 사업보고서
    "20220318000966",  # 디어유 2021 사업보고서
    "20150515000302",  # CSA 코스믹 2015 1분기보고서
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="실제로 삭제(기본은 dry-run)")
    args = ap.parse_args()

    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT rcept_no, corp_code, statement, count(*) AS n
                FROM report_lines
                WHERE rcept_no = ANY(:rs) AND basis = 'consolidated'
                GROUP BY rcept_no, corp_code, statement
                ORDER BY rcept_no, statement
            """),
            {"rs": _TARGET_RCEPTS},
        ).fetchall()
        total = sum(r.n for r in rows)
        print(f"[delete-consolidation-r-fixes] 삭제 대상: {len(rows)}개 (rcept,statement) 조합, "
              f"총 {total:,}행")
        for r in rows:
            print(f"  {r.rcept_no} {r.corp_code} {r.statement}: {r.n}행")

        if not args.execute:
            print("\n--dry-run 모드입니다. 실제 삭제하려면 --execute 를 붙여 다시 실행하세요.")
            return

        result = session.execute(
            text("DELETE FROM report_lines WHERE rcept_no = ANY(:rs) AND basis = 'consolidated'"),
            {"rs": _TARGET_RCEPTS},
        )
        session.commit()
        print(f"\n[delete-consolidation-r-fixes] 삭제 완료: {result.rowcount:,}행")


if __name__ == "__main__":
    main()
