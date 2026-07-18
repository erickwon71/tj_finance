"""
Phase C 무결성 어서션 — 재구축(version=2) 오염/잔존 전수 점검 (Phase D 게이트 겸용)
================================================================================
"덮이지 않은 잔존 오염"(stale/orphan) 을 code 가 아니라 **DB 상태**로 직접 검증한다.
각 체크는 위반 행 수를 세고 0 이 아니면 FAIL. 재구축 스크립트와 독립(외부 검증).

usage:
  python scripts/phase_c_integrity_check.py            # version=2 전수
  python scripts/phase_c_integrity_check.py --version 1 # v1 도 stale 계열만 참고 점검
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from collector.db import get_session
from fin2.taxonomy.concept_map import map_acode

FY_MIN = 2015


def _scalar(s, sql, **p):
    return s.execute(text(sql), p).scalar() or 0


def run_checks(version: int) -> list[tuple]:
    """반환 [(name, count, ok, note)]. count=위반 행수, ok=(count==0)."""
    out = []
    with get_session() as s:
        v = {"v": version}

        # 1) STALE: 한 기업의 v2 행이 그 기업 최신 기록보다 30분+ 오래됨 = 재구축에 안 덮인 잔존.
        #    (재구축은 기업 단위 원자 커밋 = 한 패스로 전 행 동일 시각 → 오래된 행은 orphan.)
        n = _scalar(s, """
            SELECT count(*) FROM std_financials_v2 s
            JOIN (SELECT corp_code, max(calculated_at) mx FROM std_financials_v2
                  WHERE version=:v GROUP BY corp_code) m ON m.corp_code=s.corp_code
            WHERE s.version=:v AND s.calculated_at < m.mx - interval '30 minutes'
        """, **v)
        out.append(("stale_rows(미갱신 잔존)", n, n == 0,
                    "기업 최신기록보다 30분+ 오래된 v2 행"))

        # 2) DUP: uq_std_v2 키 중복(스키마 제약 있으나 방어적 확인).
        n = _scalar(s, """
            SELECT COALESCE(sum(c-1),0) FROM (
              SELECT count(*) c FROM std_financials_v2 WHERE version=:v
              GROUP BY corp_code,fiscal_year,fiscal_period,statement_type,version,is_stub,is_discrete
              HAVING count(*)>1) x
        """, **v)
        out.append(("dup_keys(중복키)", n, n == 0, "uq 키 중복 초과행"))

        # 3) ORPHAN CORP: v2 에 있으나 재구축 대상목록에 없는 기업.
        n = _scalar(s, """
            SELECT count(DISTINCT corp_code) FROM std_financials_v2
            WHERE version=:v AND corp_code NOT IN (SELECT corp_code FROM rebuild_target_track1)
        """, **v)
        out.append(("orphan_corp(대상외 기업)", n, n == 0, "rebuild_target 에 없는 v2 기업"))

        # 4) FY 범위: Track1=2015+ 밖 행(bound_fy 누락).
        n = _scalar(s, "SELECT count(*) FROM std_financials_v2 WHERE version=:v AND fiscal_year<:y",
                    v=version, y=FY_MIN)
        out.append((f"fy<{FY_MIN}(범위밖)", n, n == 0, "Track1 스코프 밖 v2 행"))
        n = _scalar(s, "SELECT count(*) FROM std_financials_calendar WHERE version=:v AND calendar_year<:y",
                    v=version, y=FY_MIN)
        out.append((f"calendar fy<{FY_MIN}", n, n == 0, "범위밖 달력행"))

        # 5) PROVENANCE 불변식: operating_income 있으나 K-IFRS 마크 없음(혼입 감지).
        n = _scalar(s, """
            SELECT count(*) FROM std_financials_v2 WHERE version=:v
            AND operating_income IS NOT NULL AND NOT (applied_rules @> '["opinc_kifrs"]')
        """, **v)
        out.append(("opinc 비-K-IFRS(혼입)", n, n == 0, "op 있으나 opinc_kifrs 마크 없음"))

        # 6) K-IFRS 순수성(fact_v2): is.operating_income 에 IFRS acode 유입(v2 기업 한정).
        n = _scalar(s, """
            SELECT count(*) FROM fact_v2
            WHERE canonical_account='is.operating_income'
              AND acode='ifrs-full_ProfitLossFromOperatingActivities'
              AND corp_code IN (SELECT DISTINCT corp_code FROM std_financials_v2 WHERE version=:v)
        """, **v)
        out.append(("opinc IFRS acode 유입", n, n == 0, "is.operating_income 에 ifrs 개념(재구축 기업)"))

        # 7) Track A canonical 신선도: 보존된 xbrl_acode fact 의 canonical 이 현 concept_map 과
        #    불일치(재-map 누락 = 구 매핑 잔존). v2 기업 한정, Python 으로 대조.
        rows = s.execute(text("""
            SELECT DISTINCT acode, canonical_account FROM fact_v2
            WHERE source_format='xbrl_acode' AND acode IS NOT NULL
              AND corp_code IN (SELECT DISTINCT corp_code FROM std_financials_v2 WHERE version=:v)
        """), v).fetchall()
        stale_map = sum(1 for ac, canon in rows
                        if (map_acode(ac) or None) != (canon or None))
        out.append(("trackA canonical 구매핑", stale_map, stale_map == 0,
                    f"acode→canonical 이 현 concept_map 과 불일치한 (acode) 종류 수 / 전체 {len(rows)}"))

        # 8) 클린슬레이트 잔여: v2 기업의 fact_v2 중 (Track A 2015+ 비정정) 도 아니고
        #    (재파싱 대상 rcept) 도 아닌 행 = 지워졌어야 할 잔존.
        n = _scalar(s, """
            SELECT count(*) FROM fact_v2 fv
            WHERE fv.corp_code IN (SELECT DISTINCT corp_code FROM std_financials_v2 WHERE version=:v)
              AND fv.rcept_no NOT IN (SELECT rcept_no FROM rebuild_target_track1)
              AND fv.rcept_no NOT IN (
                SELECT f.rcept_no FROM filings f
                WHERE f.fiscal_year>=:y AND f.report_nm NOT LIKE '%정정%'
                  AND EXISTS (SELECT 1 FROM fact_v2 fa WHERE fa.rcept_no=f.rcept_no
                              AND fa.source_format='xbrl_acode'))
        """, v=version, y=FY_MIN)
        out.append(("clean_slate 잔여 fact", n, n == 0, "지워졌어야 할 pre-2015·정정본·비대상 fact"))

    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", type=int, default=2)
    args = ap.parse_args()

    print(f"── Phase C 무결성 점검 (version={args.version}) ──")
    results = run_checks(args.version)
    n_fail = 0
    for name, cnt, ok, note in results:
        mark = "✓ PASS" if ok else "✗ FAIL"
        if not ok:
            n_fail += 1
        print(f"  {mark}  {name:28} = {cnt:>8,}   ({note})")
    print(f"\n{'✅ 전체 통과' if n_fail == 0 else f'❌ {n_fail}개 FAIL'} / {len(results)}개 체크")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
