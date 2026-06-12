"""
CF 주석 D&A 고신뢰 추출 — 직접법/주석전용 보고서의 누락 감가상각 복원.

배경: parity null_flip 의 최대 손실은 D&A/CF 파생(depreciation/da_total/ebitda).
원인=직접법 현금흐름표 등 **재무제표 본문에 D&A 가 없고 주석에만** 있는 보고서를
fin2 가 추출 못 함. 레거시 note_extractor(검증됨)를 fin2/extract/notes.py 로 재사용한다.

★ 고신뢰만 적용(사용자 결정): note_extractor 의 basis 판정(섹션제목 "연결")은 연결
보고서에서 자주 오귀속 → **separate basis 만** 복원한다(기본 귀속이 신뢰가능, 검증에서
da_total 레거시 정확일치 확인). 추가 가드:
  - 단일실체: 연결 매출 없음 또는 |연결-별도|/별도 < 10%(연결≈별도 → 주석 귀속 안전)
  - 엄격 단위검증: 보정 후 da_total/별도매출 ∈ [0.3%, 60%]
  - 중복합산 방지: 대상은 std_v2 separate.depreciation IS NULL(=face D&A 없음)뿐

미복원분(연결 키·커버리지 밖 ~61%)은 known-gap 으로 남긴다(별도 문서).

단계: 1)note.* fact_v2 upsert  2)영향기업 standardize2 재실행(reconcile 불변).
중단·재개 안전(upsert idempotent). 실행:
  python scripts/fin2_extract_note_da.py [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.extract.notes import extract_note_da_facts
from fin2.extract.xbrl import store_facts
from fin2.standardize.build import standardize_corp

# 고신뢰 수용 범위(보정 후 da_total/별도매출). 모듈 기본보다 엄격.
_ACCEPT_LO, _ACCEPT_HI = 0.003, 0.6
_SINGLE_ENTITY_TOL = 0.10  # |연결-별도|/별도 < 10% → 단일실체로 간주

# 대상: std_v2 separate 인데 depreciation NULL(=주석전용/직접법 추정). CF source 보유.
_TARGET_SQL = """
    SELECT s.corp_code, s.fiscal_year, s.fiscal_period,
           ss.source_rcept_no AS cf_rcept, dt.file_path
    FROM std_financials_v2 s
    JOIN statement_source ss
      ON ss.corp_code=s.corp_code AND ss.fiscal_year=s.fiscal_year
     AND ss.fiscal_period=s.fiscal_period AND ss.basis='separate' AND ss.statement='CF'
    JOIN download_tasks dt ON dt.rcept_no = ss.source_rcept_no
    WHERE s.statement_type='separate' AND s.version=1 AND s.depreciation IS NULL
      AND dt.file_path IS NOT NULL
    ORDER BY s.corp_code, s.fiscal_year, s.fiscal_period
"""


def _revenue_by_basis(session, rcept: str) -> dict[str, int]:
    rows = session.execute(text("""
        SELECT basis, MAX(amount_won) FROM fact_v2
        WHERE rcept_no=:r AND canonical_account='is.revenue'
          AND col_index=0 AND NOT is_dimensional AND basis IN ('consolidated','separate')
        GROUP BY basis
    """), {"r": rcept}).fetchall()
    return {b: v for b, v in rows if v}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with get_session() as session:
        targets = session.execute(text(_TARGET_SQL)).fetchall()
    if args.limit:
        targets = targets[: args.limit]
    logger.info(f"[note-da] separate D&A-NULL 대상 {len(targets):,}건 검사")

    affected: dict[str, None] = {}
    stored = accepted = skip_unit = skip_dual = skip_noyield = skip_nofile = 0
    samples = []

    with get_session() as session:
        for i, t in enumerate(targets, 1):
            if not t.file_path or not Path(t.file_path).exists():
                skip_nofile += 1
                continue
            rev = _revenue_by_basis(session, t.cf_rcept)
            sep_rev = rev.get("separate")
            con_rev = rev.get("consolidated")
            if not sep_rev or sep_rev <= 0:
                skip_unit += 1
                continue
            # 단일실체 가드: 연결 매출이 있고 별도와 10% 넘게 다르면 귀속 위험 → 스킵
            if con_rev and abs(con_rev - sep_rev) / sep_rev >= _SINGLE_ENTITY_TOL:
                skip_dual += 1
                continue

            facts = extract_note_da_facts(
                t.file_path, rcept_no=t.cf_rcept, corp_code=t.corp_code,
                report_fiscal_year=t.fiscal_year, report_fiscal_period=t.fiscal_period,
                revenue_by_basis=rev,
            )
            sep_facts = [f for f in facts if f.basis == "separate"]
            if not sep_facts:
                skip_noyield += 1
                continue

            da_total = next((f.amount_won for f in sep_facts
                             if f.canonical_account == "note.da_total"), None)
            if da_total is None:
                da_total = sum(f.amount_won for f in sep_facts
                               if f.canonical_account in
                               ("note.depreciation", "note.amortization", "note.rou_depreciation"))
            ratio = abs(da_total) / sep_rev if da_total else 0
            if not (_ACCEPT_LO <= ratio <= _ACCEPT_HI):
                skip_unit += 1
                continue

            accepted += 1
            affected[t.corp_code] = None
            if len(samples) < 12:
                samples.append((t.corp_code, t.fiscal_year, t.fiscal_period, da_total, f"{ratio*100:.1f}%"))
            if not args.dry_run:
                stored += store_facts(session, sep_facts)
            if i % 500 == 0:
                if not args.dry_run:
                    session.commit()
                logger.info(f"[note-da] {i:,}/{len(targets):,} 수용 {accepted:,} "
                            f"(불가단위 {skip_unit} 이중basis {skip_dual} 무수율 {skip_noyield})")
        if not args.dry_run:
            session.commit()

    logger.info(f"[note-da] 검사 {len(targets):,} → 수용 {accepted:,} / "
                f"단위탈락 {skip_unit} / 이중basis {skip_dual} / 무수율 {skip_noyield} / 파일없음 {skip_nofile}")
    logger.info("샘플 (corp,fy,fp,da_total,da/rev):")
    for s in samples:
        logger.info(f"   {s}")

    if args.dry_run:
        logger.info(f"[note-da] --dry-run — 쓰기 없이 종료 (수용예정 {accepted:,}, 영향기업 {len(affected):,})")
        return

    logger.success(f"[note-da] E 완료 — note fact {stored:,} upsert, 영향기업 {len(affected):,}")

    # R 불변(note 는 source 선택 영향 없음) → S 만 재실행
    corps = list(affected)
    n_std = n_fail = 0
    for i, corp in enumerate(corps, 1):
        try:
            with get_session() as session:
                n_std += standardize_corp(session, corp)
                session.commit()
        except Exception as e:
            n_fail += 1
            logger.warning(f"[note-da] S 실패 corp={corp}: {e}")
        if i % 200 == 0:
            logger.info(f"[note-da] S {i:,}/{len(corps):,} (std_v2 {n_std:,})")
    logger.success(f"[note-da] 완료 — 영향기업 {len(corps):,}, std_v2 {n_std:,} 재계산, 실패 {n_fail}")


if __name__ == "__main__":
    main()
