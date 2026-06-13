"""
Fiscal-change relabeling (PRD 01a) — filings 레이어
====================================================
결산월 변경 기업의 filings 라벨을 '그 시점 결산월' 기준으로 재계산한다
(period_end_date/period_end_month/fye_month_at_time/is_stub + fiscal_year/period + is_final 재그룹).
collector.filing_collector.relabel_corp_filings 를 호출.

Stage 1(이 스크립트)은 **filings 레이어만** 손댄다. 다운스트림(fact_v2/std_v2) cascade 는
Stage 3 에서 별도 수행(스키마 is_stub 반영 후).

사용:
    # 단일 기업 dry-run(변경 미적용, 결과 미리보기 + 무회귀 diff)
    python3 scripts/relabel_fiscal_change.py --corp 00104856 --dry-run
    # 적용
    python3 scripts/relabel_fiscal_change.py --corp 00104856
    # 결산월 변경 기업 전체(160사) dry-run 영향 집계
    python3 scripts/relabel_fiscal_change.py --changed-only --dry-run --summary-only
"""
import argparse
import os
import sys

# 저장소 루트를 import 경로에 추가 — `python scripts/...` 직접 실행 시에도 collector/run 임포트 가능
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from collector.db import SessionLocal
from collector.filing_collector import relabel_corp_filings


def cascade_corp(session, corp: str, reextract: bool = True) -> dict:
    """
    한 기업 전체 cascade(PRD 01a Stage 3): 라벨 재계산 → (재추출) → R → S 재구축.
    - relabel: filings 라벨/is_stub/is_final.
    - reextract: fact_v2 의 report_fiscal_year/period 를 새 라벨로 갱신(+섀도였던 annual 적재).
      store_facts 가 ON CONFLICT 로 전 컬럼 갱신 → 라벨 refresh. (파일 읽기 = heavy)
    - statement_source/std_v2 는 corp 단위로 purge 후 재구축(구 라벨 잔재 제거).
    호출자가 commit. 반환=요약.
    """
    from fin2.reconcile import reconcile_corp
    from fin2.standardize.build import (
        standardize_comparative_corp, standardize_corp, standardize_kgaap_gap_corp,
    )

    st = relabel_corp_filings(session, corp)
    if reextract:
        from run import _extract2_corp
        _extract2_corp(session, corp, verbose=False)  # fact_v2 라벨 refresh + 섀도 annual 적재(heavy)
    else:
        # 라벨만 갱신(파일 미읽기): 기존 fact_v2 의 report_fiscal_year/period 를 새 filings 라벨로.
        # 섀도였던 미추출 annual 은 적재 안 됨(추후 재추출 필요).
        session.execute(text("""
            UPDATE fact_v2 f
            SET report_fiscal_year = fl.fiscal_year, report_fiscal_period = fl.fiscal_period
            FROM filings fl
            WHERE fl.rcept_no = f.rcept_no AND f.corp_code = :c
        """), {"c": corp})
    session.execute(text("DELETE FROM statement_source WHERE corp_code=:c"), {"c": corp})
    reconcile_corp(session, corp)
    session.execute(text("DELETE FROM std_financials_v2 WHERE corp_code=:c"), {"c": corp})
    n_own = standardize_corp(session, corp)
    standardize_comparative_corp(session, corp)
    standardize_kgaap_gap_corp(session, corp)
    st["std_own"] = n_own
    return st


def _snapshot(session, corp: str) -> dict:
    rows = session.execute(text("""
        SELECT rcept_no, fiscal_year, fiscal_period, is_final
        FROM filings WHERE corp_code=:c
    """), {"c": corp}).fetchall()
    return {r.rcept_no: (r.fiscal_year, r.fiscal_period, r.is_final) for r in rows}


def _changed_corps(session) -> list[str]:
    rows = session.execute(text("""
        WITH ann AS (
          SELECT corp_code, substring(report_nm from '\\(\\d{4}\\.(\\d{2})\\)') AS mm
          FROM filings WHERE report_type='annual' AND report_nm ~ '\\(\\d{4}\\.\\d{2}\\)'
        )
        SELECT corp_code FROM ann WHERE mm IS NOT NULL
        GROUP BY corp_code HAVING count(DISTINCT mm) > 1
        ORDER BY corp_code
    """)).fetchall()
    return [r.corp_code for r in rows]


def _show_corp(session, corp: str):
    print(f"\n── {corp} annual 라벨 ──")
    rows = session.execute(text("""
        SELECT report_nm, fiscal_year, fiscal_period, period_end_date,
               fye_month_at_time, is_stub, is_final
        FROM filings WHERE corp_code=:c AND report_type='annual'
        ORDER BY period_end_date NULLS FIRST, rcept_no
    """), {"c": corp}).fetchall()
    for r in rows:
        print(f"  {r.report_nm[:34]:34s} fy={r.fiscal_year} {r.fiscal_period:3s} "
              f"end={r.period_end_date} fye={r.fye_month_at_time} stub={r.is_stub} final={r.is_final}")
    print(f"── {corp} 전환연도(stub 보유 fiscal_year) 전체 기간 ──")
    rows = session.execute(text("""
        SELECT fiscal_year, fiscal_period, is_stub, count(*) n, bool_or(is_final) anyfinal
        FROM filings
        WHERE corp_code=:c AND fiscal_year IN (
            SELECT DISTINCT fiscal_year FROM filings WHERE corp_code=:c AND is_stub
        )
        GROUP BY 1,2,3 ORDER BY 1,2,3
    """), {"c": corp}).fetchall()
    for r in rows:
        print(f"  fy={r.fiscal_year} {r.fiscal_period:3s} stub={r.is_stub} n={r.n} final={r.anyfinal}")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--corp", metavar="CODE")
    g.add_argument("--changed-only", action="store_true", help="결산월 변경 기업 전체")
    ap.add_argument("--dry-run", action="store_true", help="변경 미적용(rollback), 미리보기만")
    ap.add_argument("--summary-only", action="store_true", help="기업별 상세 생략, 집계만")
    ap.add_argument("--cascade", action="store_true",
                    help="라벨 적용 + 재추출 + R/S 재구축(기업단위 commit, heavy)")
    ap.add_argument("--no-reextract", action="store_true",
                    help="cascade 시 재추출 생략(라벨만 갱신, 섀도 annual 미적재 — 빠름)")
    ap.add_argument("--resume-file", default=None,
                    help="cascade 진행상황 기록 파일(완료 corp 스킵, 중단·재개 안전)")
    args = ap.parse_args()

    session = SessionLocal()
    try:
        corps = [args.corp] if args.corp else _changed_corps(session)
        print(f"대상 기업: {len(corps)}")

        # ── cascade 모드: 기업단위 relabel→(reextract)→R→S, 기업단위 commit(재개안전) ──
        if args.cascade:
            import os
            done_set: set[str] = set()
            if args.resume_file and os.path.exists(args.resume_file):
                done_set = set(open(args.resume_file).read().split())
            todo = [c for c in corps if c not in done_set]
            print(f"cascade 대상 {len(todo)} (완료 스킵 {len(corps)-len(todo)}), "
                  f"reextract={not args.no_reextract}")
            done = fail = 0
            for i, corp in enumerate(todo, 1):
                try:
                    st = cascade_corp(session, corp, reextract=not args.no_reextract)
                    session.commit()
                    done += 1
                    if args.resume_file:
                        with open(args.resume_file, "a") as fh:
                            fh.write(corp + "\n")
                    if not args.summary_only:
                        print(f"[{i}/{len(todo)}] {corp}: filings {st['filings']}, "
                              f"stub {st['stubs']}, std_own {st.get('std_own','?')}")
                except Exception as e:
                    session.rollback()
                    fail += 1
                    print(f"[{i}/{len(todo)}] {corp}: 실패 — {e}")
            print(f"\ncascade 완료: 성공 {done}, 실패 {fail} / {len(todo)}")
            return

        total_changed = 0
        total_stub = 0
        for corp in corps:
            before = _snapshot(session, corp)
            st = relabel_corp_filings(session, corp)
            after = _snapshot(session, corp)
            diffs = [(r, before[r], after[r]) for r in before if before[r] != after[r]]
            total_changed += len(diffs)
            total_stub += st["stubs"]
            if not args.summary_only:
                print(f"\n=== {corp}: filings {st['filings']}, stub연도 {st['stubs']}, "
                      f"라벨변경 {len(diffs)}건 ===")
                for r, b, a in diffs[:40]:
                    print(f"  {r}: (fy={b[0]},{b[1]},final={b[2]}) → (fy={a[0]},{a[1]},final={a[2]})")
                if len(diffs) > 40:
                    print(f"  ... 외 {len(diffs)-40}건")
                if args.corp:
                    _show_corp(session, corp)

        print(f"\n총: 대상 {len(corps)}사, 라벨변경 {total_changed}건, stub연도 {total_stub}개")

        if args.dry_run:
            session.rollback()
            print("[dry-run] rollback — 변경 미적용.")
        else:
            session.commit()
            print("[적용 완료] commit.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
