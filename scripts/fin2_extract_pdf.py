"""Track C — PDF-only 보고서 재무제표 추출 + (선택)fact_v2 적재.

대상 = download_tasks 의 pdf(completed) 중 **같은 rcept 의 xml 추출이 없는** 보고서
(Track A/B 0행). filings 의 fiscal_year/fiscal_period 로 라벨링해 ExtractedFact(source_format='pdf')
를 만들고 --store 시 store_facts 로 upsert. 기본은 dry-run(추출 통계 + 회계 항등식 검증).

usage:
  # 표본 추출 통계(항등식 검증)
  python scripts/fin2_extract_pdf.py --limit 40
  # 단일 corp
  python scripts/fin2_extract_pdf.py --corp 00126566
  # 적재(per-rcept purge 후 store, resume)
  python scripts/fin2_extract_pdf.py --store --resume-file /tmp/pdf_done.txt
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.extract.pdf import extract_pdf_facts
from fin2.extract.xbrl import store_facts

_SEL = """
SELECT p.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period, f.report_nm, p.file_path
FROM download_tasks p JOIN filings f ON f.rcept_no = p.rcept_no
WHERE p.file_type='pdf' AND p.status='completed' AND p.file_path IS NOT NULL
  AND f.fiscal_year IS NOT NULL AND f.fiscal_period IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM download_tasks x WHERE x.rcept_no=p.rcept_no
                  AND x.file_type='xml' AND x.status='completed')
  AND NOT EXISTS (SELECT 1 FROM fact_v2 v WHERE v.rcept_no=p.rcept_no
                  AND v.source_format <> 'pdf')
  -- ★ 진짜 갭만: 해당 (corp,fy,fp) 에 기존 std_v2 가 없을 때만 적재 → XML 파생 std 와 경쟁/회귀 방지.
  AND NOT EXISTS (SELECT 1 FROM std_financials_v2 v2 WHERE v2.corp_code=f.corp_code
                  AND v2.fiscal_year=f.fiscal_year AND v2.fiscal_period=f.fiscal_period
                  AND v2.version=1 AND NOT COALESCE(v2.is_stub,false))
"""


def identity_ok(facts) -> bool | None:
    """연결 우선, BS 회계 항등식(자산≈부채+자본, 0.5% 이내) 검증. 데이터 부족 None."""
    for basis in ("consolidated", "separate"):
        d = {}
        for f in facts:
            if f.basis == basis and f.canonical_account in (
                    "bs.total_assets", "bs.total_liabilities", "bs.total_equity"):
                d[f.canonical_account] = f.amount_won
        if len(d) == 3 and d["bs.total_assets"]:
            diff = abs(d["bs.total_assets"] - d["bs.total_liabilities"] - d["bs.total_equity"])
            return diff <= abs(d["bs.total_assets"]) * 0.005
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corp")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--store", action="store_true")
    ap.add_argument("--resume-file")
    ap.add_argument("--shard", help="병렬 샤딩 I/N (rcept 정렬 후 i::N)")
    args = ap.parse_args()

    done = set()
    if args.resume_file and Path(args.resume_file).exists():
        done = {ln.strip() for ln in Path(args.resume_file).read_text().splitlines() if ln.strip()}

    with get_session() as s:
        q = _SEL + (" AND f.corp_code=:c" if args.corp else "")
        q += " ORDER BY p.rcept_no"
        rows = s.execute(text(q), {"c": args.corp} if args.corp else {}).fetchall()
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        rows = rows[i::n]
    rows = [r for r in rows if r.rcept_no not in done]
    if not args.store and args.limit:
        rows = rows[:args.limit]
    logger.info(f"[pdf] 대상 {len(rows)} rcept (store={args.store})")

    agg = {"facts": 0, "ok": 0, "bad": 0, "none": 0, "empty": 0, "err": 0, "n": 0,
           "stored": 0, "skip_bad": 0}
    for r in rows:
        agg["n"] += 1
        try:
            facts = extract_pdf_facts(
                r.file_path, corp_code=r.corp_code, rcept_no=r.rcept_no,
                report_fiscal_year=r.fiscal_year, report_fiscal_period=r.fiscal_period)
        except Exception as e:
            agg["err"] += 1
            logger.warning(f"[pdf] {r.rcept_no} 실패: {type(e).__name__}: {e}")
            continue
        if not facts:
            agg["empty"] += 1
            continue
        agg["facts"] += len(facts)
        ident = identity_ok(facts)
        agg["ok" if ident else ("none" if ident is None else "bad")] += 1
        if args.store:
            # ★ 품질 게이트: BS 회계 항등식이 깨진 rcept(구 K-GAAP 다단컬럼 오추출)은 적재 스킵
            # → 'DB=보고서' 원칙상 잘못된 값으로 메인뷰 오염 방지. OK/n/a(BS triple 불완전)만 적재.
            if ident is False:
                agg["skip_bad"] += 1
                if args.resume_file:
                    with open(args.resume_file, "a") as fh:
                        fh.write(r.rcept_no + "\n")
                continue
            try:
                with get_session() as s:
                    s.execute(text("DELETE FROM fact_v2 WHERE rcept_no=:r AND source_format='pdf'"),
                              {"r": r.rcept_no})
                    store_facts(s, facts)
                    s.commit()
                agg["stored"] += 1
                if args.resume_file:
                    with open(args.resume_file, "a") as fh:
                        fh.write(r.rcept_no + "\n")
            except Exception as e:
                agg["err"] += 1
                logger.error(f"[pdf] store {r.rcept_no} 실패: {e}")
        else:
            flag = {True: "OK", False: "IDENTITY_FAIL", None: "n/a"}[ident]
            logger.info(f"  {r.rcept_no} {r.corp_code} {r.fiscal_year}{r.fiscal_period} "
                        f"facts={len(facts)} identity={flag} {str(r.report_nm)[:24]}")
        if agg["n"] % 50 == 0:
            logger.info(f"  ..{agg['n']}/{len(rows)} facts={agg['facts']} "
                        f"ok={agg['ok']} bad={agg['bad']} empty={agg['empty']}")

    logger.success(f"[pdf] 완료 — rcept {agg['n']}, facts {agg['facts']:,}, "
                   f"항등식 OK {agg['ok']} / FAIL {agg['bad']} / n/a {agg['none']} / "
                   f"빈추출 {agg['empty']} / 오류 {agg['err']} | "
                   f"적재 {agg['stored']} / 품질스킵 {agg['skip_bad']}")
    if not args.store:
        logger.info("적재하려면 --store (per-rcept purge 후 store_facts). 이후 reconcile/standardize 필요.")


if __name__ == "__main__":
    main()
