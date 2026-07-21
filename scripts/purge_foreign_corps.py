"""외국 회사(국내 상장) 완전 삭제 — corporations + 전 종속 테이블.

배경: 국내 증시에 상장된 **외국 기업**(중국·홀딩스 구조 등)은 재무제표 서식이 이질적이라
파싱 정합이 낮고(로스웰 73%), 사용자 결정으로 **유니버스에서 완전 제외**한다. 식별 규칙 =
**stock_code 가 '9' 로 시작**(KRX 외국기업 코드대: 900xxx·950xxx). 실측 전건이 외국기업.

이 스크립트는 그 기업들의 모든 DB 흔적을 지운다(하드 삭제). 신규 유입 차단은 sync_corporations
쪽 필터(_is_foreign_stock)가 담당 — 이 스크립트는 **기존 잔존분 정리**용.

사용:
    python scripts/purge_foreign_corps.py            # 드라이런(삭제 없이 대상·건수만)
    python scripts/purge_foreign_corps.py --apply    # 실제 삭제(트랜잭션)
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from collector.db import get_session


def _corp_dirs_from_paths(file_paths: list[str], codes: set[str]) -> set[Path]:
    """download_tasks.file_path 들에서 **기업 폴더**(raw_report/MARKET/CODE_NAME)를 유도한다.
    구조: .../raw_report/{시장}/{코드_이름}/{type}/{year}/{rcept}.xml. 기업폴더는 '조상 중
    이름이 대상 corp_code 로 시작하고 조부가 raw_report 인' 디렉터리. rmtree 안전을 위해
    **폴더명이 대상 코드로 시작하는 것만** 채택(엉뚱한 폴더 삭제 방지)."""
    dirs = set()
    for fp in file_paths:
        if not fp:
            continue
        for d in Path(fp).parents:
            gp = d.parent
            if (gp is not None and gp.parent is not None and gp.parent.name == "raw_report"
                    and any(d.name.startswith(code) for code in codes)):
                dirs.add(d)
                break
    return dirs

_FOREIGN = "stock_code ~ '^9'"   # 900xxx·950xxx = KRX 외국기업 코드대

# 삭제 순서: 자식(rcept/corp 참조) 먼저 → filings → corporations. 뷰(extended_financials) 제외.
# corp_code 로 지우는 종속 테이블(대부분).
# ※ calendar_financials·standard_financials·standard_financials_verified 는 VIEW → 제외
#   (기저 테이블 std_financials_v2·std_financials_calendar 삭제 시 뷰에 자동 반영).
_CORP_TABLES = [
    "biz_metrics", "biz_section_tables", "capital_events",
    "corp_verify_status", "dividend_facts", "employee_stats", "exec_pay_individual",
    "exec_pay_summary", "executives", "face_audit", "face_line_audit", "fact_v2",
    "major_shareholders", "order_backlog", "other_investments", "periodic_api_progress",
    "rebuild_target_track1", "regulatory_events", "report_lines", "retail_ownership",
    "shareholder_changes",
    "statement_source", "std_financials_calendar", "std_financials_v2",
    "treasury_activity", "verification_results",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 삭제(미지정=드라이런)")
    args = ap.parse_args()

    with get_session() as session:
        corps = session.execute(text(
            f"SELECT corp_code, stock_code, corp_name, market FROM corporations WHERE {_FOREIGN} "
            "ORDER BY stock_code")).fetchall()
        codes = [c.corp_code for c in corps]
        stocks = [c.stock_code for c in corps]
        print(f"대상 외국 상장기업 {len(corps)}개:")
        for c in corps:
            print(f"  {c.stock_code} {c.corp_name} ({c.market})")
        if not codes:
            print("대상 없음."); return

        # 종속 건수 집계
        print("\n삭제 예정 종속 데이터:")
        rcepts = [r[0] for r in session.execute(text(
            "SELECT rcept_no FROM filings WHERE corp_code = ANY(:c)"), {"c": codes}).fetchall()]
        file_paths = [r[0] for r in session.execute(text(
            "SELECT file_path FROM download_tasks WHERE rcept_no = ANY(:r) AND file_path IS NOT NULL"),
            {"r": rcepts}).fetchall()] if rcepts else []
        corp_dirs = _corp_dirs_from_paths(file_paths, set(codes))
        n_files = sum(1 for fp in file_paths if Path(fp).exists())
        print(f"  ※ 다운로드 원문 파일: {n_files:,}개 · 기업폴더 {len(corp_dirs)}개(폴더째 삭제)")
        for d in sorted(corp_dirs):
            print(f"      {d}")
        counts = {}
        for t in _CORP_TABLES:
            n = session.execute(text(f"SELECT count(*) FROM {t} WHERE corp_code = ANY(:c)"),
                                {"c": codes}).scalar()
            if n:
                counts[t] = n
        # rcept 전용(corp_code 없음)
        dt = session.execute(text("SELECT count(*) FROM download_tasks WHERE rcept_no = ANY(:r)"),
                             {"r": rcepts}).scalar() if rcepts else 0
        sp = session.execute(text("SELECT count(*) FROM stock_prices WHERE stock_code = ANY(:s)"),
                             {"s": stocks}).scalar()
        counts["download_tasks(by rcept)"] = dt
        counts["stock_prices(by stock)"] = sp
        counts["filings"] = len(rcepts)
        counts["corporations"] = len(codes)
        for t, n in counts.items():
            print(f"  {t:34s} {n:>8,}")

        if not args.apply:
            print("\n[드라이런] 삭제하지 않음. 실제 삭제는 --apply.")
            return

        # ── 실제 삭제(자식 → filings → corporations) ──
        deleted = {}
        for t in _CORP_TABLES:
            r = session.execute(text(f"DELETE FROM {t} WHERE corp_code = ANY(:c)"), {"c": codes})
            if r.rowcount:
                deleted[t] = r.rowcount
        if rcepts:
            r = session.execute(text("DELETE FROM download_tasks WHERE rcept_no = ANY(:r)"),
                                {"r": rcepts})
            deleted["download_tasks"] = r.rowcount
        r = session.execute(text("DELETE FROM stock_prices WHERE stock_code = ANY(:s)"),
                            {"s": stocks})
        deleted["stock_prices"] = r.rowcount
        r = session.execute(text("DELETE FROM filings WHERE corp_code = ANY(:c)"), {"c": codes})
        deleted["filings"] = r.rowcount
        r = session.execute(text("DELETE FROM corporations WHERE corp_code = ANY(:c)"), {"c": codes})
        deleted["corporations"] = r.rowcount
        session.commit()
        print("\n[DB 삭제 완료]")
        for t, n in deleted.items():
            print(f"  {t:34s} {n:>8,}")

        # ── 다운로드 원문 파일/폴더 삭제 ──
        removed_dirs = 0
        for d in sorted(corp_dirs):
            if d.exists() and any(d.name.startswith(code) for code in codes):
                shutil.rmtree(d)
                removed_dirs += 1
        # 혹시 corp_dir 밖(예 폴더구조 예외)에 남은 개별 파일 정리.
        removed_files = 0
        for fp in file_paths:
            p = Path(fp)
            if p.exists():
                p.unlink()
                removed_files += 1
        print(f"\n[원문 파일 삭제 완료] 기업폴더 {removed_dirs}개 · 잔여 개별파일 {removed_files}개")


if __name__ == "__main__":
    main()
