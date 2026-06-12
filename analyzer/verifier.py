"""
계층형 재무 정합성 검증 엔진 (C3)

Layer 1 — 항등식 (전 기업·전 기간):
  BS: 자산 = 부채 + 자본
  IS: 매출 - 매출원가 = 매출총이익  (항목이 있을 때만)
      매출총이익 - 판관비 = 영업이익  (항목이 있을 때만)
      법인세차감전 - 법인세 = 당기순이익 (항목이 있을 때만)

Layer 3 — 기간 연속성 (FY 기준):
  전기 기말 총자본 ≈ 당기 기초 총자본 (CF 기간 처음 항목으로 근사)
  (현금 연속성은 data 부족 케이스 많아 tolerance 높게)

결과는 verification_results 테이블에 upsert.
단위: 원(DB) → 비교 표시는 억원.
tolerance 기본 0.5%.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from collector.db import get_session
from collector.models import VerificationResult

UNIT = 100_000_000  # 억원
DEFAULT_TOL = 0.5   # 0.5%


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _pct_diff(a: Optional[int], b: Optional[int]) -> Optional[float]:
    """abs(a-b)/abs(b)*100. None if either is None or b==0."""
    if a is None or b is None or b == 0:
        return None
    return abs(a - b) / abs(b) * 100


def _pass(diff: Optional[float], tol: float) -> Optional[bool]:
    if diff is None:
        return None
    return diff <= tol


def _upsert_result(rec: dict) -> None:
    with get_session() as s:
        stmt = pg_insert(VerificationResult.__table__).values([rec])
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                "corp_code", "fiscal_year", "fiscal_period",
                "statement_type", "check_name",
            ],
            set_={
                "rcept_no":     stmt.excluded.rcept_no,
                "layer":        stmt.excluded.layer,
                "passed":       stmt.excluded.passed,
                "lhs_label":    stmt.excluded.lhs_label,
                "rhs_label":    stmt.excluded.rhs_label,
                "lhs_value":    stmt.excluded.lhs_value,
                "rhs_value":    stmt.excluded.rhs_value,
                "diff_pct":     stmt.excluded.diff_pct,
                "tolerance_pct":stmt.excluded.tolerance_pct,
                "source_ref":   stmt.excluded.source_ref,
                "checked_at":   stmt.excluded.checked_at,
            }
        )
        s.execute(stmt)


def _base_rec(corp_code, fy, fp, stmt_type, rcept_no, check_name, layer) -> dict:
    return {
        "corp_code":       corp_code,
        "fiscal_year":     fy,
        "fiscal_period":   fp,
        "statement_type":  stmt_type,
        "rcept_no":        rcept_no,
        "check_name":      check_name,
        "layer":           layer,
        "passed":          None,
        "lhs_label":       None,
        "rhs_label":       None,
        "lhs_value":       None,
        "rhs_value":       None,
        "diff_pct":        None,
        "tolerance_pct":   DEFAULT_TOL,
        "source_ref":      None,
        "checked_at":      datetime.utcnow(),
    }


# ── SF 값 조회 ────────────────────────────────────────────────────────────────

def _fetch_sf(corp_code: str, fy: int, fp: str, stmt_type: str) -> dict:
    with get_session() as s:
        row = s.execute(text("""
            SELECT
                revenue, cogs, gross_profit, sga,
                operating_income, ebt, tax_expense, net_income,
                total_assets, total_liabilities, total_equity,
                controlling_equity,
                rcept_no
            FROM standard_financials
            WHERE corp_code = :c AND fiscal_year = :fy
              AND fiscal_period = :fp AND statement_type = :st
              AND version = 1
            LIMIT 1
        """), {"c": corp_code, "fy": fy, "fp": fp, "st": stmt_type}).fetchone()
    if row is None:
        return {}
    keys = ["revenue", "cogs", "gross_profit", "sga",
            "operating_income", "ebt", "tax_expense", "net_income",
            "total_assets", "total_liabilities", "total_equity",
            "controlling_equity", "rcept_no"]
    return dict(zip(keys, row))


def _fetch_source_ref(rcept_no: str, account_code: str, stmt_type: str) -> Optional[str]:
    """해당 fact의 source_ref 조회 (fail 항목 원본 위치 안내용)."""
    suffix = "_C" if stmt_type == "consolidated" else "_S"
    with get_session() as s:
        row = s.execute(text("""
            SELECT source_ref FROM financial_facts
            WHERE rcept_no = :rn AND account_code = :ac
              AND fs_type = ANY(ARRAY[:bs, :is_, :cf])
              AND col_index = 0 AND NOT is_superseded
              AND source_ref IS NOT NULL
            LIMIT 1
        """), {
            "rn": rcept_no, "ac": account_code,
            "bs": f"BS{suffix}", "is_": f"IS{suffix}", "cf": f"CF{suffix}",
        }).fetchone()
    return row[0] if row else None


# ── Layer 1 항등식 검사 ───────────────────────────────────────────────────────

def verify_identities(
    corp_code: str,
    fy: int,
    fp: str,
    stmt_type: str,
    tol: float = DEFAULT_TOL,
) -> list[dict]:
    """BS/IS 항등식을 검사해 결과 레코드 목록 반환."""
    sf = _fetch_sf(corp_code, fy, fp, stmt_type)
    if not sf:
        return []

    rcept = sf.get("rcept_no")
    results = []

    def _check(check_name: str, lhs_label: str, lhs: Optional[int],
                rhs_label: str, rhs: Optional[int],
                ac_for_ref: str = "") -> dict:
        rec = _base_rec(corp_code, fy, fp, stmt_type, rcept, check_name, layer=1)
        rec["lhs_label"] = lhs_label
        rec["rhs_label"] = rhs_label
        rec["lhs_value"] = lhs
        rec["rhs_value"] = rhs
        d = _pct_diff(lhs, rhs)
        rec["diff_pct"]  = d
        rec["passed"]    = _pass(d, tol)
        if rec["passed"] is False and rcept and ac_for_ref:
            rec["source_ref"] = _fetch_source_ref(rcept, ac_for_ref, stmt_type)
        return rec

    ta = sf.get("total_assets")
    tl = sf.get("total_liabilities")
    te = sf.get("total_equity")

    # BS: 자산 = 부채 + 자본
    if ta is not None and tl is not None and te is not None:
        results.append(_check(
            "bs_identity",
            "total_assets", ta,
            "liab+equity", (tl + te) if (tl is not None and te is not None) else None,
            "bs.total_assets",
        ))

    # IS: 매출총이익 = 매출 - 원가 (존재 항목만)
    rev  = sf.get("revenue")
    cogs = sf.get("cogs")
    gp   = sf.get("gross_profit")
    if rev is not None and cogs is not None and gp is not None:
        results.append(_check(
            "is_gross_profit",
            "gross_profit", gp,
            "rev-cogs", rev - cogs,
            "is.gross_profit",
        ))

    # IS: 영업이익 = 매출총이익 - 판관비 (존재 항목만)
    sga = sf.get("sga")
    oi  = sf.get("operating_income")
    if gp is not None and sga is not None and oi is not None:
        results.append(_check(
            "is_operating_income",
            "operating_income", oi,
            "gp-sga", gp - sga,
            "is.operating_income",
        ))

    # IS: 당기순이익 = EBT - 법인세 (존재 항목만)
    ebt = sf.get("ebt")
    tax = sf.get("tax_expense")
    ni  = sf.get("net_income")
    if ebt is not None and tax is not None and ni is not None:
        results.append(_check(
            "is_net_income",
            "net_income", ni,
            "ebt-tax", ebt - tax,
            "is.net_income",
        ))

    return results


# ── Layer 3 연속성 검사 ───────────────────────────────────────────────────────

# 연속성 = 자릿수/부호 이상 탐지용 밴드.
# 전기·당기 기말 총자본은 이익·배당·OCI로 정상 변동하므로 strict 동일 검사는 불가.
# 1년 사이 10배 이상 변동 또는 부호 반전은 거의 항상 파싱/단위 오류 → FAIL.
CONTINUITY_MAX_RATIO = 10.0           # 10배 = 900% 변동까지 허용
CONTINUITY_TOL_PCT   = (CONTINUITY_MAX_RATIO - 1) * 100  # 900%


def verify_continuity(
    corp_code: str,
    fy: int,
    stmt_type: str,
) -> list[dict]:
    """
    전기↔당기 FY 기말 총자본의 'gross anomaly'(자릿수 점프/부호 반전) 검사.

    엄밀한 rollforward(기초+순이익-배당±OCI)는 OCI·증자·자사주로 오차가 커
    오탐이 많으므로, 단위/파싱 오류만 잡는 느슨한 밴드(±10배, 부호 일치)로 검증한다.
    정상 사업 성장(±수십%)은 PASS, 1,000x 단위 오파싱·부호 반전은 FAIL.
    """
    with get_session() as s:
        cur = s.execute(text("""
            SELECT sf_cur.total_equity, sf_prev.total_equity, sf_cur.rcept_no
            FROM standard_financials sf_cur
            LEFT JOIN standard_financials sf_prev ON (
                sf_prev.corp_code = sf_cur.corp_code
                AND sf_prev.fiscal_year = sf_cur.fiscal_year - 1
                AND sf_prev.fiscal_period = 'FY'
                AND sf_prev.statement_type = sf_cur.statement_type
                AND sf_prev.version = 1
            )
            WHERE sf_cur.corp_code = :c AND sf_cur.fiscal_year = :fy
              AND sf_cur.fiscal_period = 'FY'
              AND sf_cur.statement_type = :st AND sf_cur.version = 1
        """), {"c": corp_code, "fy": fy, "st": stmt_type}).fetchone()

    if not cur:
        return []

    cur_equity, prev_equity, rcept = cur
    if cur_equity is None or prev_equity is None or prev_equity == 0:
        return []

    rec = _base_rec(corp_code, fy, "FY", stmt_type, rcept, "equity_continuity", layer=3)
    rec["lhs_label"] = f"prev_FY({fy-1})_equity"
    rec["rhs_label"] = f"cur_FY({fy})_equity"
    rec["lhs_value"] = prev_equity
    rec["rhs_value"] = cur_equity
    rec["diff_pct"]  = _pct_diff(prev_equity, cur_equity)
    rec["tolerance_pct"] = CONTINUITY_TOL_PCT

    sign_flip = (cur_equity > 0) != (prev_equity > 0)
    ratio = abs(cur_equity) / abs(prev_equity)
    gross_anomaly = sign_flip or ratio >= CONTINUITY_MAX_RATIO or ratio <= 1 / CONTINUITY_MAX_RATIO
    rec["passed"] = not gross_anomaly
    return [rec]


# ── 단일 기업 검증 진입점 ──────────────────────────────────────────────────────

def verify_corp(
    corp_code: str,
    since_year: int = 2015,
    stmt_type: str = "consolidated",
    tol: float = DEFAULT_TOL,
    save: bool = True,
) -> list[dict]:
    """
    해당 기업의 모든 기간을 검증하고, save=True면 DB에 upsert한다.
    반환: 결과 레코드 목록.
    """
    with get_session() as s:
        periods = s.execute(text("""
            SELECT DISTINCT fiscal_year, fiscal_period
            FROM standard_financials
            WHERE corp_code = :c AND statement_type = :st
              AND fiscal_year >= :since AND version = 1
            ORDER BY fiscal_year DESC, fiscal_period
        """), {"c": corp_code, "st": stmt_type, "since": since_year}).fetchall()

    all_results: list[dict] = []
    for fy, fp in periods:
        all_results.extend(verify_identities(corp_code, fy, fp, stmt_type, tol))
        if fp == "FY":
            all_results.extend(verify_continuity(corp_code, fy, stmt_type))

    if save:
        for rec in all_results:
            _upsert_result(rec)

    # data_quality 갱신: any FAIL → DQ 상승 (3>2>기존)
    # ⚠ P5 컷오버 후 standard_financials 는 view(쓰기 불가). fin2 build.py 가 이미
    #    data_quality 를 산출하므로 레거시 DQ writeback 은 스킵한다.
    from collector.db import relation_is_view
    if save and all_results and not relation_is_view("standard_financials"):
        with get_session() as s:
            for fy, fp in periods:
                period_recs = [r for r in all_results
                               if r["fiscal_year"] == fy and r["fiscal_period"] == fp]
                has_fail = any(r["passed"] is False for r in period_recs)
                has_warn = any(r["passed"] is None and r["diff_pct"] is not None
                               for r in period_recs)
                dq = 3 if has_fail else (2 if has_warn else 1)
                s.execute(text("""
                    UPDATE standard_financials
                    SET data_quality = GREATEST(data_quality, :dq)
                    WHERE corp_code = :c AND fiscal_year = :fy
                      AND fiscal_period = :fp AND statement_type = :st
                      AND version = 1
                """), {"dq": dq, "c": corp_code, "fy": fy, "fp": fp, "st": stmt_type})

    return all_results


def verify_all(
    since_year: int = 2015,
    stmt_type: str = "consolidated",
    tol: float = DEFAULT_TOL,
    log_dir: str = "logs/coverage",
) -> dict:
    """모든 활성 기업을 배치 검증. fail 기업별 로그 생성."""
    import re
    from pathlib import Path

    with get_session() as s:
        corps = s.execute(text("""
            SELECT c.corp_code, c.corp_name, COALESCE(c.market,'?')
            FROM corporations c
            WHERE c.is_active = TRUE
            ORDER BY c.corp_code
        """)).fetchall()

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    stats = {"total": len(corps), "fail": 0, "pass": 0, "skip": 0}

    for corp_code, corp_name, market in corps:
        results = verify_corp(corp_code, since_year, stmt_type, tol, save=True)
        if not results:
            stats["skip"] += 1
            continue

        fails = [r for r in results if r["passed"] is False]
        if fails:
            stats["fail"] += 1
            safe = re.sub(r'[\\/:*?"<>|]', '_', corp_name)
            fail_log = log_path / f"{corp_code}_{safe}.verify_fail.log"
            lines = [
                f"# {corp_code}  {corp_name}  [{market}]",
                f"# 검증 실패 {len(fails)}건 / 전체 {len(results)}건",
                f"# 생성: {datetime.utcnow().isoformat()}",
                "",
                f"  {'check_name':<24}  {'FY':>4}  {'FP':<3}  "
                f"{'LHS(억)':>12}  {'RHS(억)':>12}  {'diff%':>7}  source_ref",
                "  " + "─" * 85,
            ]
            for r in sorted(fails, key=lambda x: (x["fiscal_year"], x["check_name"])):
                lhs_awk = f"{r['lhs_value']/UNIT:,.1f}" if r["lhs_value"] else "—"
                rhs_awk = f"{r['rhs_value']/UNIT:,.1f}" if r["rhs_value"] else "—"
                diff_s  = f"{r['diff_pct']:.2f}%" if r["diff_pct"] else "—"
                src     = r.get("source_ref") or "—"
                lines.append(
                    f"  {r['check_name']:<24}  {r['fiscal_year']:>4}  "
                    f"{r['fiscal_period']:<3}  {lhs_awk:>12}  {rhs_awk:>12}  "
                    f"{diff_s:>7}  {src}"
                )
            fail_log.write_text("\n".join(lines), encoding="utf-8")
        else:
            stats["pass"] += 1

    return stats
