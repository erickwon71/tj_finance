"""
Phase C 재구축 오케스트레이터 — Track 1(비정정·2015+·4섹션·추측 0) → std_v2 version=2
==============================================================================
재구축 계획 = docs/plans/vast-nibbling-blum.md · 실행계획 = docs/plans/loop-vivid-bubble.md

rebuild_target_track1(79,010 보고서 / 2,452 기업)을 corp 오름차순으로 하나씩 돌며,
각 기업을 **원자 커밋**(DB=체크포인트)으로 version=2 로 병행 재구축한다. 소비계층(앱)이
읽는 version=1 은 건드리지 않는다(Phase D 검증 통과 후 swap, 이후 v1 DROP).

기업 단위 파이프라인(사용자 확정 방식, 2026-07-18):
  1) 클린슬레이트: corp 의 fact_v2 에서 **Track A 2015+ 비정정만 보존**하고 나머지 전부 DELETE
     (pre-2015 · 정정본 · 구 추측 Track B 제거 — "덮어쓰기 잔존" 원천 차단).
  2) Track B 대상 rcept 재파싱(신 fin2/extract/text.py, 추측 0) → fact_v2 재삽입.
     ⟹ corp 의 fact_v2 = Track A 2015+(충실) ∪ Track B 대상(strict) = v2 스코프 그 자체.
  3) statement_source(corp) DELETE → reconcile_corp(정리된 fact_v2 만 봄, 스코핑 불필요).
  4) standardize(v2) → comparative(v2) → ★shares 재백필(v2) → quarterly(v2) → calendar(v2).
  5) v2 를 fiscal_year>=2015 로 한정(Track 1 스코프) → 잔여 <2015 파생행 정리.
  6) rebuild_target_track1.status='done'.

애매분은 build.py 가 std_v2.value_lineage(보류큐)에 기록한다. 파싱 루프는 사람을 기다리지
않는다(패턴루프는 scripts/phase_c_review_digest.py 로 배치 검토 — loop-vivid-bubble.md D4).

usage:
  python scripts/phase_c_rebuild.py --corps 0:10     # 파일럿 10사(foreground)
  python scripts/phase_c_rebuild.py --shard 0/8      # 8분할 중 0번
  python scripts/phase_c_rebuild.py                  # 전량(연속 잡이 호출)
  옵션: --limit N  --recheck(done 도 재처리)  --fy-min 2015
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session, engine

FY_MIN_DEFAULT = 2015


def select_corps(session, args) -> list[str]:
    """rebuild_target_track1 대상 corp 오름차순. --corps 슬라이스 / --shard a/n 분할."""
    corps = [r[0] for r in session.execute(text(
        "SELECT DISTINCT corp_code FROM rebuild_target_track1 ORDER BY corp_code")).fetchall()]
    if args.corps:
        if ":" in args.corps:
            lo, _, hi = args.corps.partition(":")
            corps = corps[(int(lo) if lo else None):(int(hi) if hi else None)]
        else:
            corps = corps[int(args.corps):int(args.corps) + 1]
    if args.shard:
        a, n = (int(x) for x in args.shard.split("/"))
        corps = [c for i, c in enumerate(corps) if i % n == a]
    if args.limit:
        corps = corps[:args.limit]
    return corps


def _clean_slate(session, corp: str, fy_min: int) -> int:
    """corp fact_v2 에서 **Track A(xbrl_acode) fy>=fy_min 비정정만 보존**하고 나머지 DELETE.
    반환=삭제 행수. (Track B 대상은 여기서 지워졌다가 _reextract 에서 strict 재삽입.)"""
    res = session.execute(text("""
        DELETE FROM fact_v2 fv
        WHERE fv.corp_code = :c
          AND fv.rcept_no NOT IN (
            SELECT f.rcept_no FROM filings f
            WHERE f.corp_code = :c AND f.fiscal_year >= :ymin
              AND f.report_nm NOT LIKE '%정정%'
              AND EXISTS (SELECT 1 FROM fact_v2 fa
                          WHERE fa.rcept_no = f.rcept_no AND fa.source_format = 'xbrl_acode')
          )
    """), {"c": corp, "ymin": fy_min})
    return res.rowcount or 0


def _remap_track_a_facts(session, corp: str) -> int:
    """보존된 Track A(xbrl_acode) fact 의 canonical_account 를 **현 concept_map 으로 재적용**.
    clean_slate 는 Track A 2015+ 를 재추출 없이 보존하므로, concept_map(Track A 매핑) 변경은
    재추출 없이는 반영되지 않는다. Track A canonical 은 acode 의 순수 함수(map_acode)이므로
    XML 재파싱 없이 acode 별 bulk UPDATE 로 재적용한다. 반환=갱신 행수."""
    from fin2.taxonomy.concept_map import map_acode
    acodes = [r[0] for r in session.execute(text(
        "SELECT DISTINCT acode FROM fact_v2 WHERE corp_code=:c "
        "AND source_format='xbrl_acode' AND acode IS NOT NULL"), {"c": corp}).fetchall()]
    n = 0
    for ac in acodes:
        canon = map_acode(ac)
        res = session.execute(text(
            "UPDATE fact_v2 SET canonical_account=:cn WHERE corp_code=:c "
            "AND source_format='xbrl_acode' AND acode=:ac "
            "AND canonical_account IS DISTINCT FROM :cn"),
            {"cn": canon, "c": corp, "ac": ac})
        n += res.rowcount or 0
    return n


def _reextract_targets(session, corp: str) -> tuple[int, int, dict[str, str]]:
    """corp 의 Track B 대상 rcept(rebuild_target_track1) 을 strict 재파싱 → fact_v2 재삽입.
    반환=(대상 파일수, fact 수, {rcept: outcome}). outcome ∈ done|held_no_facts|missing_file.
    A→B 폴백(대상은 Track B 이나 방어적으로 xbrl 우선 시도)."""
    from fin2.extract import xbrl, text as text_extract
    from fin2.extract.xbrl import store_facts

    targets = session.execute(text("""
        SELECT rcept_no, file_path, fiscal_year, fiscal_period
        FROM rebuild_target_track1 WHERE corp_code = :c
        ORDER BY fiscal_year DESC, fiscal_period
    """), {"c": corp}).fetchall()

    n_files = n_facts = 0
    outcome: dict[str, str] = {}
    for t in targets:
        if not t.file_path or not Path(t.file_path).exists():
            logger.warning(f"  [{t.fiscal_year}{t.fiscal_period}] r{t.rcept_no} 파일 소실 — 스킵")
            outcome[t.rcept_no] = "missing_file"
            n_files += 1
            continue
        common = dict(rcept_no=t.rcept_no, corp_code=corp,
                      report_fiscal_year=t.fiscal_year, report_fiscal_period=t.fiscal_period)
        try:
            facts = xbrl.extract_facts(t.file_path, **common)
            if not facts:
                facts = text_extract.extract_facts(t.file_path, **common)
        except (FileNotFoundError, OSError) as e:
            logger.warning(f"  [{t.fiscal_year}{t.fiscal_period}] r{t.rcept_no} 파일 오류 — 스킵: {e}")
            outcome[t.rcept_no] = "missing_file"
            n_files += 1
            continue
        n_files += 1
        if facts:
            n_facts += store_facts(session, facts)
            outcome[t.rcept_no] = "done"
        else:
            # 본문 섹션 없음 / 단위 미선언 / 값 전부 보류 → fact 0. 보류큐(패턴루프) 대상.
            # status varchar(12) 제약상 짧게; 상세 사유는 digest 가 원문 검사로 재분류.
            outcome[t.rcept_no] = "held"
    return n_files, n_facts, outcome


def _file_path(session, rcept: str | None) -> str | None:
    if not rcept:
        return None
    return session.execute(text(
        "SELECT file_path FROM download_tasks WHERE rcept_no=:r AND file_type='xml' "
        "AND file_path IS NOT NULL LIMIT 1"), {"r": rcept}).scalar()


def _revenue_by_basis(session, rcept: str) -> dict[str, int]:
    rows = session.execute(text("""
        SELECT basis, MAX(amount_won) FROM fact_v2
        WHERE rcept_no=:r AND canonical_account='is.revenue'
          AND col_index=0 AND NOT is_dimensional AND basis IN ('consolidated','separate')
        GROUP BY basis
    """), {"r": rcept}).fetchall()
    return {b: v for b, v in rows if v}


def _apply_notes(session, corp: str, version: int, fy_min: int) -> int:
    """★Task6: note 추출층(D&A/R&D)을 fact_v2 에 적재 → 이후 standardize 가 접어넣음.
    depreciation 결측 (fy,fp,basis) 에만 cf_da(주석우선·본문폴백)·expense_nature(비용성격주석)를
    돌려 중복합산 방지. rd_note 는 사업보고서(FY)에서 연구개발비 총액. 재사용:
    fin2.extract.{cf_da,expense_nature,rd_note} 의 per-file 추출기. 같은 세션(원자)."""
    from fin2.extract.cf_da import recover_cf_da
    from fin2.extract.expense_nature import extract_expense_nature_facts
    from fin2.extract.rd_note import extract_rd_facts
    from fin2.extract.xbrl import store_facts

    rows = session.execute(text("""
        SELECT s.fiscal_year, s.fiscal_period, s.statement_type AS basis,
               s.is_rcept, s.cf_rcept, s.depreciation
        FROM std_financials_v2 s
        WHERE s.corp_code=:c AND s.version=:v AND s.fiscal_year>=:y
          AND NOT COALESCE(s.is_discrete,false) AND NOT COALESCE(s.is_stub,false)
    """), {"c": corp, "v": version, "y": fy_min}).fetchall()

    stored = 0
    for r in rows:
        # D&A 결측 행만 note 복원(있으면 본문 값 보존 = 중복합산 방지).
        if r.depreciation is None:
            if r.cf_rcept:  # cf_da: 주석/본문 D&A, revenue 가드 필요
                fp = _file_path(session, r.cf_rcept)
                rev = _revenue_by_basis(session, r.cf_rcept)
                if fp and Path(fp).exists() and rev.get(r.basis):
                    facts, _ = recover_cf_da(
                        fp, rcept_no=r.cf_rcept, corp_code=corp,
                        report_fiscal_year=r.fiscal_year, report_fiscal_period=r.fiscal_period,
                        basis=r.basis, revenue_by_basis=rev)
                    if facts:
                        stored += store_facts(session, facts)
            if r.is_rcept:  # expense_nature: 비용의 성격별 분류 주석
                fp = _file_path(session, r.is_rcept)
                if fp and Path(fp).exists():
                    facts = extract_expense_nature_facts(
                        fp, rcept_no=r.is_rcept, corp_code=corp,
                        report_fiscal_year=r.fiscal_year, report_fiscal_period=r.fiscal_period,
                        basis=r.basis)
                    if facts:
                        stored += store_facts(session, facts)
        # rd_note: 사업보고서(FY, 연결) '사업의 내용' 연구개발비 총액
        if r.fiscal_period == "FY" and r.basis == "consolidated" and r.is_rcept:
            fp = _file_path(session, r.is_rcept)
            if fp and Path(fp).exists():
                facts = extract_rd_facts(
                    fp, rcept_no=r.is_rcept, corp_code=corp,
                    report_fiscal_year=r.fiscal_year, report_fiscal_period="FY",
                    basis="consolidated")
                if facts:
                    stored += store_facts(session, facts)
    return stored


def backfill_shares_corp(session, corp: str, version: int) -> int:
    """★D3: FY std_v2(version) 의 shares_out 결측을 사업보고서 본문에서 직접 파싱해 채운다.
    재구축 시 shares_out 은 NULL 로 시작 → 이 단계가 없으면 valuation_daily(PER/PBR/시총) 전멸.
    quarterly 이전에 실행해야 이산분기가 shares_out(stock)을 승계한다."""
    from fin2.extract.shares import extract_issued_common_shares

    rows = session.execute(text("""
        SELECT DISTINCT ON (s.fiscal_year) s.fiscal_year, d.file_path
        FROM std_financials_v2 s
        JOIN filings f ON f.corp_code = s.corp_code AND f.fiscal_year = s.fiscal_year
                      AND f.report_type = 'annual' AND f.is_final = true
        JOIN download_tasks d ON d.rcept_no = f.rcept_no AND d.file_type = 'xml'
                             AND d.file_path IS NOT NULL
        WHERE s.corp_code = :c AND s.version = :v AND s.fiscal_period = 'FY'
          AND NOT COALESCE(s.is_discrete, false) AND NOT COALESCE(s.is_stub, false)
          AND (s.shares_out IS NULL OR s.shares_out = 0)
        ORDER BY s.fiscal_year, f.filed_at DESC
    """), {"c": corp, "v": version}).fetchall()

    n = 0
    for fy, path in rows:
        if not path or not Path(path).exists():
            continue
        try:
            shares = extract_issued_common_shares(path)
        except Exception:  # noqa: BLE001 — 개별 보고서 파싱 실패는 결측 처리(전체 롤백 방지)
            continue
        if shares and shares > 0:
            session.execute(text("""
                UPDATE std_financials_v2 SET shares_out = :n
                WHERE corp_code = :c AND fiscal_year = :y AND fiscal_period = 'FY'
                  AND version = :v AND (shares_out IS NULL OR shares_out = 0)
            """), {"n": shares, "c": corp, "y": fy, "v": version})
            n += 1
    return n


def _bound_fy(session, corp: str, version: int, fy_min: int) -> None:
    """Track 1 스코프(fy>=fy_min) 밖 v2 파생행 정리(comparative 가 fy-1 로 만든 <2015 행 등)."""
    session.execute(text(
        "DELETE FROM std_financials_v2 WHERE corp_code=:c AND version=:v AND fiscal_year < :y"),
        {"c": corp, "v": version, "y": fy_min})
    session.execute(text(
        "DELETE FROM std_financials_calendar WHERE corp_code=:c AND version=:v AND calendar_year < :y"),
        {"c": corp, "v": version, "y": fy_min})


def rebuild_corp(corp: str, fy_min: int, version: int = 2) -> dict:
    """한 기업 재구축 1패스(원자 커밋). 반환=카운트 dict."""
    from fin2.reconcile import reconcile_corp
    from fin2.standardize.build import standardize_corp, standardize_comparative_corp
    from fin2.standardize.quarterly import derive_quarters_corp
    from fin2.standardize.calendar import calendarize_corp

    out = {"purged": 0, "e_files": 0, "e_facts": 0, "remap": 0, "r": 0, "s": 0, "notes": 0,
           "comp": 0, "shares": 0, "q": 0, "c": 0}
    with get_session() as s:
        out["purged"] = _clean_slate(s, corp, fy_min)
        # ★ 소비계층(v2) 잔여행 제거 — UPSERT 만으로는 재생성 안 되는 키(구 comparative 등)가
        # 남아 "덮이지 않은 잔존 오염"이 된다(사용자 지적). corp 의 v2 를 비우고 새로 쌓는다.
        s.execute(text("DELETE FROM std_financials_v2 WHERE corp_code=:c AND version=:v"),
                  {"c": corp, "v": version})
        s.execute(text("DELETE FROM std_financials_calendar WHERE corp_code=:c AND version=:v"),
                  {"c": corp, "v": version})
        out["e_files"], out["e_facts"], outcome = _reextract_targets(s, corp)
        # 보존된 Track A 의 canonical 을 현 concept_map 으로 재적용(재추출 없이 매핑 변경 반영).
        out["remap"] = _remap_track_a_facts(s, corp)
        # statement_source 재생성(파생층) — 정리된 fact_v2 만 반영되게 corp 것 삭제 후 reconcile.
        s.execute(text("DELETE FROM statement_source WHERE corp_code = :c"), {"c": corp})
        out["r"] = reconcile_corp(s, corp)
        out["s"] = standardize_corp(s, corp, version=version)
        # ★Task6: note 추출층(D&A/R&D) → fact_v2 적재 후 재표준화로 접어넣음(EBITDA/da_total/rd).
        out["notes"] = _apply_notes(s, corp, version, fy_min)
        if out["notes"]:
            standardize_corp(s, corp, version=version)
        out["comp"] = standardize_comparative_corp(s, corp, version=version)
        out["shares"] = backfill_shares_corp(s, corp, version)  # ★D3, quarterly 이전
        out["q"] = derive_quarters_corp(s, corp, version=version)
        out["c"] = calendarize_corp(s, corp, version=version)
        _bound_fy(s, corp, version, fy_min)
        # 대상별 outcome 기록(done / held_no_facts / missing_file) — 패턴루프 다이제스트 입력.
        now = datetime.utcnow()
        for rcept, st in outcome.items():
            s.execute(text(
                "UPDATE rebuild_target_track1 SET status=:s, processed_at=:t WHERE rcept_no=:r"),
                {"s": st, "t": now, "r": rcept})
        out["held"] = sum(1 for v in outcome.values() if v != "done")
        s.commit()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corps", help="corp 인덱스 슬라이스 LO:HI")
    ap.add_argument("--shard", help="a/n 분할(i %% n == a)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--fy-min", dest="fy_min", type=int, default=FY_MIN_DEFAULT)
    ap.add_argument("--recheck", action="store_true", help="status='done' 기업도 재처리")
    ap.add_argument("--managed", action="store_true",
                    help="launchd 연속잡 모드: 대상 전량 처리 완료 시 잡 자기해제(unload+plist 삭제)")
    args = ap.parse_args()

    with get_session() as s:
        corps = select_corps(s, args)
        # 처리 완료 = 이 기업 대상이 전부 종결 상태(done/held/missing_file). 'pending'·NULL·'error'
        # 는 미완 → 재시도(error 는 일시 오류일 수 있으므로 다음 실행에서 다시 처리).
        done = set() if args.recheck else {r[0] for r in s.execute(text(
            "SELECT corp_code FROM rebuild_target_track1 GROUP BY corp_code HAVING "
            "count(*) FILTER (WHERE status NOT IN ('done','held','missing_file')) = 0")).fetchall()}
    todo = [c for c in corps if c not in done]
    logger.info(f"[phase-c] 대상 {len(corps)}사 중 미완 {len(todo)}사 (skip {len(corps) - len(todo)})")

    agg = {"pass": 0, "err": 0}
    for i, corp in enumerate(todo, 1):
        try:
            o = rebuild_corp(corp, args.fy_min)
            agg["pass"] += 1
            logger.info(
                f"[{i}/{len(todo)}] {corp} — purge {o['purged']} / 재파싱 {o['e_files']}파일 "
                f"{o['e_facts']}fact(held {o['held']}) / remapA {o['remap']} / stmt_src {o['r']} / std_v2 {o['s']}"
                f"(+comp {o['comp']}) / note {o['notes']} / shares {o['shares']} / "
                f"분기 {o['q']} / 달력 {o['c']}")
        except Exception as e:  # noqa: BLE001 — 기업 예외 격리(루프 계속)
            agg["err"] += 1
            msg = f"{type(e).__name__}: {e}"[:300]
            logger.error(f"[{i}/{len(todo)}] {corp} — [ERR] {msg}")
            try:
                with get_session() as s:
                    s.execute(text(
                        "UPDATE rebuild_target_track1 SET status='error' WHERE corp_code=:c"),
                        {"c": corp})
                    s.commit()
            except Exception:  # noqa: BLE001
                pass

    logger.success(f"[phase-c] 완료 — PASS {agg['pass']} / ERR {agg['err']}")

    if args.managed:
        _self_disable_if_done()


def _self_disable_if_done() -> None:
    """launchd 연속잡: 남은 pending 이 0 이면 잡 unload + plist 삭제(gapfill 선례)."""
    import os
    import subprocess
    with get_session() as s:
        pending = s.execute(text(
            "SELECT count(*) FROM rebuild_target_track1 WHERE status='pending' OR status IS NULL"
        )).scalar() or 0
    if pending:
        logger.info(f"[phase-c] 아직 pending {pending:,}건 — 잡 유지(다음 실행에서 계속).")
        return
    label = "com.tjfinance.phasec"
    plist = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
    logger.success(f"[phase-c] pending 0 — 잡 자기해제({label}) 후 plist 삭제.")
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], check=False)
    subprocess.run(["launchctl", "unload", str(plist)], check=False)
    plist.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
