"""영업이익(is.operating_income) 오매핑 소급수정 + 영향기업 재표준화 (C5 크로스소스로 발견).

배경: parser/common/account_mapper.py 에 가드 추가(2026-07-06) — '계속영업이익(손실)'·
'중단영업이익(손실)'(세후 계속/중단영업 손익 소계)·'영업외손익' 계열(영업외수익-비용 순액)이
alias '영업이익(손실)'/'영업손익' 과의 부분포함·근접유사도로 Stage 3 퍼지에 잘못 흡수되어
is.operating_income 으로 매핑되던 버그. DART API 크로스소스 검증(scripts/verify_cross_source.py)
으로 발견 — 65건 불일치 중 29건이 operating_income, 그중 다수가 부호까지 뒤집힘(금호타이어
2022 등). 가드는 **신규 추출**만 막으므로, 이미 fact_v2 에 적재된 기존 오매핑 행은 이 스크립트로
소급 수정한다(재파싱 불필요 — canonical_account 만 NULL 로 되돌리고 영향기업만 재표준화).

★ 동시성: 재표준화(standardize_corp)는 다른 재표준화 작업과 동시 실행 금지(단독 실행).

실행:
  python scripts/fix_operating_income_mismap.py --dry-run   # 영향만 출력
  python scripts/fix_operating_income_mismap.py             # 소급수정 + 재표준화
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from parser.common.account_mapper import get_mapper
from fin2.standardize.build import standardize_corp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-restandardize", action="store_true")
    args = ap.parse_args()

    mapper = get_mapper()

    with get_session() as session:
        # 현재 is.operating_income 으로 매핑된 col0(비차원) distinct acode.
        # ⚠ Track A(XBRL)는 canonical_account 를 account_mapper 가 아니라 별도
        # concept_map.map_acode() 로 부여한다(fin2/extract/xbrl.py) — account_mapper.map() 은
        # Track B(텍스트, source_format='xml_text')만의 관할이다. 그래서 source_format='xml_text'
        # 로 한정(+방어적으로 XBRL 접두 acode 도 제외)해야, dart_*/ifrs-full_* 처럼 애초에
        # account_mapper 가 알지 못하는(=재판정 시 통째로 unknown 이 되는) 정상 Track A 개념이
        # "오매핑이었다"로 오판되어 잘못 NULL 처리되는 사고를 막는다.
        rows = session.execute(text("""
            SELECT acode, count(*) AS n, count(DISTINCT corp_code) AS corps
            FROM fact_v2
            WHERE canonical_account = 'is.operating_income' AND col_index = 0
              AND NOT COALESCE(is_dimensional, false) AND source_format = 'xml_text'
              AND acode NOT LIKE 'ifrs-full\_%' ESCAPE '\' AND acode NOT LIKE 'dart\_%' ESCAPE '\'
            GROUP BY acode
        """)).fetchall()

    # 고친 매퍼로 재판정 — 결과가 더 이상 is.operating_income 이 아니면 오매핑이었던 것.
    plan = []  # (acode, n, corps)
    for acode, n, corps in rows:
        new_code = mapper.map(acode, fs_section="is").account_code
        if new_code != "is.operating_income":
            plan.append((acode, n, corps))

    if not plan:
        logger.info("[opinc-fix] 수정 대상 없음(이미 최신).")
        return

    plan.sort(key=lambda t: -t[1])
    total_rows = sum(p[1] for p in plan)
    logger.info(f"[opinc-fix] 오매핑 acode {len(plan)}종 · {total_rows:,} 행")
    for acode, n, corps in plan[:30]:
        logger.info(f"   {acode[:40]:40s} 행={n:6,d} 기업={corps}")
    if len(plan) > 30:
        logger.info(f"   ... 외 {len(plan) - 30}종")

    if args.dry_run:
        logger.info("[opinc-fix] --dry-run — 쓰기 없음.")
        return

    # 소급수정: canonical_account 를 NULL 로 되돌림(미매핑 관행, raw acode 는 그대로 보존).
    affected: set[str] = set()
    with get_session() as session:
        for acode, n, corps in plan:
            cc = session.execute(text("""
                UPDATE fact_v2 SET canonical_account = NULL
                WHERE acode = :acode AND canonical_account = 'is.operating_income'
                  AND col_index = 0 AND NOT COALESCE(is_dimensional, false)
                  AND source_format = 'xml_text'
                RETURNING corp_code
            """), {"acode": acode}).fetchall()
            affected.update(r[0] for r in cc)
        session.commit()
    logger.success(f"[opinc-fix] 소급수정 완료 — {total_rows:,}행, 영향기업 {len(affected):,}")

    if args.no_restandardize:
        logger.info("[opinc-fix] --no-restandardize — 재표준화 생략(별도 실행 필요).")
        return

    corps = sorted(affected)
    n_std = n_fail = 0
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as session:
                n_std += standardize_corp(session, corp)
                session.commit()
        except Exception as e:  # noqa: BLE001 — 기업 단위 예외 격리
            n_fail += 1
            logger.warning(f"[opinc-fix] 재표준화 실패 corp={corp}: {e}")
        if i % 200 == 0:
            logger.info(f"[opinc-fix] 재표준화 {i:,}/{len(corps):,} (std_v2 {n_std:,})")
    logger.success(f"[opinc-fix] 완료 — 영향기업 {len(corps):,}, std_v2 {n_std:,} 재계산, 실패 {n_fail}")


if __name__ == "__main__":
    main()
