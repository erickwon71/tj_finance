"""신규 공시 수집·DB화 (헤드리스) — 수집 페이지와 동일 흐름의 CLI 판.

실행일 기준 최근 N일 정기공시 탐지 → sync_filings(force) → 다운로드 → 파싱·표준화·분기·달력.
수동 실행하거나 cron/launchd 로 매일 예약할 수 있다.

④ 파싱·표준화는 **기업당 워커 프로세스 + 타임아웃**으로 처리한다: 대용량/병리 보고서
(예: 30MB iXBRL)에서 100% CPU 로 정체하는 기업을 `--timeout` 초 초과 시 강제 종료·스킵하고
다음 기업으로 넘어간다(C레벨 lxml 멈춤도 프로세스 kill 로 확실히 중단). 워커는 재사용하고
멈춘 경우에만 재생성하므로 정상 기업엔 오버헤드가 거의 없다.

실행:
  .venv_tj_finance/bin/python scripts/collect_new.py [--days 7] [--timeout 120]
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import queue as pyqueue
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger


def _worker(in_q, out_q) -> None:
    """워커 프로세스: in_q 에서 corp 받아 process_corp 실행·커밋, 결과를 out_q 로.
    None 받으면 종료. (spawn 으로 모듈 재임포트되므로 함수는 모듈 레벨이어야 함)"""
    from collector.db import get_session
    from run import process_corp

    while True:
        corp = in_q.get()
        if corp is None:
            return
        try:
            with get_session() as session:
                out = process_corp(session, corp)
                session.commit()
            out_q.put(("ok", corp, out))
        except Exception as exc:  # noqa: BLE001
            out_q.put(("err", corp, str(exc)))


def _standardize_with_timeout(affected: list[str], timeout: int) -> dict:
    """기업당 워커+타임아웃으로 파싱·표준화. 타임아웃 초과 기업은 워커 kill 후 스킵."""
    ctx = mp.get_context("spawn")
    in_q, out_q = ctx.Queue(), ctx.Queue()
    worker = ctx.Process(target=_worker, args=(in_q, out_q), daemon=True)
    worker.start()

    agg = {"e_facts": 0, "s": 0, "q": 0, "c": 0, "errors": 0, "timeout": 0}
    ok_corps: list[str] = []
    skipped: list[str] = []
    total = len(affected)
    for i, corp in enumerate(affected, 1):
        in_q.put(corp)
        try:
            status, c, payload = out_q.get(timeout=timeout)
            if status == "ok":
                for k in ("e_facts", "s", "q", "c"):
                    agg[k] += payload[k]
                ok_corps.append(c)
            else:
                agg["errors"] += 1
                logger.warning(f"[collect]   {c} 실패: {payload}")
        except pyqueue.Empty:
            # timeout 초과 = 정체 기업 → 워커 강제종료 후 재생성(미커밋 트랜잭션은 롤백)
            agg["timeout"] += 1
            skipped.append(corp)
            logger.warning(f"[collect]   ⏱ {corp} {timeout}초 초과 → 강제 스킵·워커 재시작")
            worker.terminate()
            worker.join()
            in_q, out_q = ctx.Queue(), ctx.Queue()
            worker = ctx.Process(target=_worker, args=(in_q, out_q), daemon=True)
            worker.start()
        if i % 20 == 0 or i == total:
            logger.info(f"[collect]   진행 {i}/{total} "
                        f"(std_v2 {agg['s']:,}, 스킵 {agg['timeout']}, 오류 {agg['errors']})")

    in_q.put(None)
    worker.join(timeout=10)
    if worker.is_alive():
        worker.terminate()
    if skipped:
        logger.warning(f"[collect]   ⏱ 타임아웃 스킵 {len(skipped)}개: {', '.join(skipped)}")
    agg["ok_corps"] = ok_corps
    return agg


def run_dq_gate(corps: list[str], fy_min: int = 2015) -> dict:
    """I2 · 수집시 DQ 게이트 — 수집된 기업에 Gate B(보고서==DB) 재감사 + 항등식(DQ) 집계.

    기존 검증 자산 재사용: `gateb_audit.audit_corp`(Phase A 면표 + Phase B 라인, 내부 커밋) +
    `verify_corp_sequential.rollup_corp`(→ corp_verify_status upsert). 표준화가 std_v2 에 이미 반영한
    항등식 위반은 data_quality>=3 로 집계. fail_a(확정 불일치)·line value_diff·DQ3 를 반환한다.
    """
    from collections import Counter
    from types import SimpleNamespace

    from sqlalchemy import text

    from collector.db import get_session
    import gateb_audit                         # scripts/ 는 실행 시 sys.path[0]
    import verify_corp_sequential as vcs

    vcs.ensure_tables()
    names: dict[str, str] = {}
    with get_session() as s:
        for cc, nm in s.execute(text(
                "SELECT corp_code, corp_name FROM corporations WHERE corp_code = ANY(:cs)"),
                {"cs": corps}).fetchall():
            names[cc] = nm

    summ = {"corps": 0, "gb_fail_a": 0, "line_value_diff": 0, "dq3": 0, "fail_corps": []}
    for corp in corps:
        gb_args = SimpleNamespace(
            corp=corp, corp_file=None, corps=None, sample=None, seed=42,
            fy_min=fy_min, fy_max=2100, recheck=True, no_commit=False, line_audit=True)
        gb_agg = {"status": Counter(), "gate": Counter(),
                  "fld_pass": 0, "fld_fail": 0, "fail_rows": [], "errors": 0}
        try:
            with get_session() as s:
                gateb_audit.audit_corp(s, corp, gb_args, gb_agg)
            with get_session() as s:
                vals = vcs.rollup_corp(s, corp, names.get(corp, "?"), stage="audited")
                dq3 = s.execute(text(
                    "SELECT count(*) FROM std_financials_v2 WHERE corp_code=:c AND version=1 "
                    "AND COALESCE(data_quality,1) >= 3"), {"c": corp}).scalar() or 0
                s.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[verify]   {corp} 검사 실패: {type(exc).__name__}: {exc}")
            continue
        vd = vals.get("line_value_diff", 0) or 0
        summ["corps"] += 1
        summ["gb_fail_a"] += vals["gb_fail_a"]
        summ["line_value_diff"] += vd
        summ["dq3"] += dq3
        if vals["gb_fail_a"] or vd or dq3:
            summ["fail_corps"].append((corp, vals["gb_fail_a"], vd, dq3))
    return summ


def _sync_regulatory(lookback_days: int = 5) -> None:
    """시장조치(관리종목/상장폐지/매매정지 등) 감지 — 정기보고와 무관하게 매일 상시 실행.
    비치명적 실패(네트워크 등)는 본 수집을 막지 않는다. lookback_days 여유로 결측 방지."""
    try:
        from collector.dart_extra import sync_regulatory_events
        end_de = date.today().strftime("%Y%m%d")
        bgn_de = (date.today() - timedelta(days=lookback_days)).strftime("%Y%m%d")
        n = sync_regulatory_events(bgn_de, end_de)
        if n:
            logger.info(f"[collect] ⓪-1 시장조치 이벤트 신규 {n}건(관리종목/상장폐지/매매정지 등)")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] ⓪-1 시장조치 이벤트 동기화 실패(비치명적): {exc}")


def _sync_capital(lookback_days: int = 5) -> None:
    """B2 — 자본이벤트(증자/감자/CB·BW·EB/자기주식) 감지. 정기보고와 무관하게 매일 상시.
    비치명적 실패(네트워크 등)는 본 수집을 막지 않는다."""
    try:
        from collector.dart_capital import sync_capital_events
        end_de = date.today().strftime("%Y%m%d")
        bgn_de = (date.today() - timedelta(days=lookback_days)).strftime("%Y%m%d")
        n = sync_capital_events(bgn_de, end_de)
        if n:
            logger.info(f"[collect] ⓪-2 자본이벤트 신규 {n}건(증자/감자/CB·BW·EB/자기주식)")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] ⓪-2 자본이벤트 동기화 실패(비치명적): {exc}")


def _sync_cf_da(corps: list[str]) -> None:
    """④-2 D&A note 복원(B5+Phase4) — 신규 표준화 기업의 연결 CF D&A 갭(2024+ Track A 전환으로
    누락)을 ① CF 주석/본문(cf_da) → ② 비용의 성격별 분류 주석(expense_nature) 하이브리드로 채워
    EBITDA/da_total 재퇴행 방지. S→Q→C 재전파. 비치명(수집 계속). expense_nature 는 cf_da 다음에
    돌아 **여전히 depreciation NULL** 인 잔여만 타겟(이중 계상 방지)."""
    if not corps:
        return
    try:
        from collector.cf_da_sync import sync_cf_da
        res = sync_cf_da(corps=corps, year_min=2024)
        if res["corps"]:
            logger.info(f"[collect] ④-2 D&A 복원(CF) — 기업 {res['corps']} · note fact {res['facts']:,} · "
                        f"std_v2 {res['std_recalc']:,} 재전파(실패 {res['fail']})")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] ④-2 D&A 복원(CF) 실패(비치명적): {exc}")
    try:
        from collector.expense_nature_sync import sync_expense_nature
        res2 = sync_expense_nature(corps=corps, year_min=2024)
        if res2["corps"]:
            logger.info(f"[collect] ④-2 D&A 복원(비용성격 주석) — 기업 {res2['corps']} · "
                        f"note fact {res2['facts']:,} · std_v2 {res2['std_recalc']:,} 재전파(실패 {res2['fail']})")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] ④-2 D&A 복원(비용성격) 실패(비치명적): {exc}")


def _sync_biz_metrics(corps: list[str]) -> None:
    """B4+Phase3 — 새로 수집된 기업의 사업보고서 본문 생산능력/생산실적/가동률 **및 부문·수출/내수
    매출실적**(metric='sales', channel) → biz_metrics. 매출 파서가 parse_biz_metrics 에 통합돼
    같은 sync 진입점에서 함께 방출된다(PRD 14). 사업의 내용 절은 annual 에만 있어 이번에 표준화된
    기업의 최신 사업보고서만 대상. 비치명적 실패는 본 수집을 막지 않는다(rcept 단위 멱등)."""
    if not corps:
        return
    try:
        from collector.biz_metrics import sync_biz_metrics
        agg = sync_biz_metrics(corps, latest_only=True)
        if agg.get("metric_rows"):
            logger.info(f"[collect] ⑤-1 사업지표(생산·가동률+부문/수출입 매출) 기업 {agg['corps']} · "
                        f"표 {agg['tables']} · 지표행 {agg['metric_rows']:,}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] ⑤-1 사업지표 수집 실패(비치명적): {exc}")


def _sync_order_backlog(corps: list[str]) -> None:
    """B1(→B4) — 새로 수집된 기업의 사업보고서 본문 수주상황 → order_backlog.
    사업의 내용 절은 annual 에만 있어 이번에 표준화된 기업의 최신 사업보고서만 대상.
    비치명적 실패는 본 수집을 막지 않는다(rcept 단위 멱등). v1 은 계약잔액/수주잔고
    컬럼이 명시된 표만 채택 — 진행률%만 있는 표는 낮은신뢰도라 자연 스킵."""
    if not corps:
        return
    try:
        from collector.order_backlog import sync_order_backlog
        agg = sync_order_backlog(corps, latest_only=True)
        if agg.get("rows"):
            logger.info(f"[collect] ⑤-2 수주상황 기업 {agg['corps']} · 행 {agg['rows']:,}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] ⑤-2 수주상황 수집 실패(비치명적): {exc}")


def _sync_periodic_apis(corps: list[str]) -> None:
    """⑤-3(Phase 2, PRD 13) — 신규 표준화 기업의 최신 사업연도만 배당/자기주식/직원현황/
    타법인출자/임원보수(요약+개인별) 6개 API 동기화. 전수 백필(scripts/collect_periodic_apis.py)과
    별개, 매일 소규모 증분. corp+fy+api 그레인 멱등이라 재실행 안전. 비치명적 — 개별 실패는
    건너뛰고 계속(일일 쿼터 소진 시에만 이번 배치를 조기 종료, 본 수집엔 영향 없음)."""
    if not corps:
        return
    from datetime import date

    from collector.dart_client import DartClient, DartApiError
    from collector.dart_periodic import API_NAMES, sync_periodic
    from collector.rate_limiter import DailyQuotaReached

    fy = date.today().year - 1
    client = DartClient()
    rows = 0
    quota_stopped = False
    try:
        for corp in corps:
            for api in API_NAMES:
                try:
                    rows += sync_periodic(client, api, corp, fy)
                except DailyQuotaReached as exc:
                    logger.warning(f"[collect] ⑤-3 일일 쿼터 소진으로 중단(비치명적): {exc}")
                    quota_stopped = True
                    break
                except DartApiError:
                    continue  # '020' 등 — 일일 증분 규모라 스킵하고 계속(전수 백필은 별도 오케스트레이터)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"[collect] ⑤-3 {corp} {api} 실패(비치명적): {exc}")
                    continue
            if quota_stopped:
                break
    finally:
        client.close()
    if rows:
        logger.info(f"[collect] ⑤-3 배당/자기주식/직원/출자/임원보수(FY{fy}) 기업 {len(corps)} · 행 {rows:,}")


def _refresh_valuation_daily() -> None:
    """A4a — 수집 후 valuation_daily matview 갱신(CONCURRENTLY, 읽기 비차단). 비치명적 실패."""
    try:
        from scripts.refresh_valuation_daily import refresh
        refresh(concurrent=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] valuation_daily 갱신 실패(비치명적): {exc}")


def _verify_and_log(agg: dict, args) -> None:
    """수집 후 DQ 게이트 실행·로깅. fail_a/value_diff(확정 불일치) 발견 시 loud error."""
    ok = agg.get("ok_corps") or []
    if getattr(args, "no_verify", False) or not ok:
        return
    logger.info(f"[verify] DQ 게이트 — {len(ok)}개 기업 Gate B(보고서==DB)+항등식 재검(fy≥{args.verify_fy_min})")
    summ = run_dq_gate(ok, args.verify_fy_min)
    msg = (f"[verify] 완료 — 검사 {summ['corps']} · fail_a {summ['gb_fail_a']} · "
           f"line_value_diff {summ['line_value_diff']} · DQ3(항등식위반) {summ['dq3']}")
    if summ["gb_fail_a"] or summ["line_value_diff"]:
        logger.error(msg + "  ⚠ 보고서≠DB 확정 불일치 발견!")
        for corp, fa, vd, dq in summ["fail_corps"]:
            logger.error(f"[verify]   {corp}: fail_a={fa} value_diff={vd} dq3={dq}")
    elif summ["dq3"]:
        logger.warning(msg + "  (DQ3=항등식 경고, 비차단 — corp_verify_status 기록됨)")
    else:
        logger.success(msg)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="실행일로부터 최근 N일 정기공시 확인")
    ap.add_argument("--timeout", type=int, default=120, help="기업당 파싱·표준화 타임아웃(초)")
    ap.add_argument("--standardize-only", action="store_true",
                    help="①②③ 건너뛰고 ④(파싱·표준화)만 — 다운로드는 됐는데 표준화 남은 전체 기업 대상. 중단 후 재개용")
    ap.add_argument("--refresh-universe", action="store_true",
                    help="⓪ 수집 전 상장 유니버스 갱신(KRX 기준 신규 상장 반영·상장폐지 비활성화)")
    ap.add_argument("--corps", type=str, default=None,
                    help="쉼표구분 corp_code — 이 기업들만 ④ 처리(--standardize-only 와 함께). "
                         "예: 타임아웃 스킵분 재시도")
    ap.add_argument("--no-verify", action="store_true",
                    help="⑤ 수집 후 DQ 게이트(Gate B 재감사+항등식) 생략")
    ap.add_argument("--verify-fy-min", type=int, default=2015,
                    help="DQ 게이트 Gate B 재감사 최소 회계연도(기본 2015)")
    args = ap.parse_args()

    # ⓪-1 시장조치 감지 — 모드와 무관하게 매일 상시(정기보고 유무와 독립적인 이벤트).
    _sync_regulatory()
    # ⓪-2 자본이벤트 감지 — 마찬가지로 매일 상시.
    _sync_capital()

    from app.data import collect

    # ── 재개 모드: ④만 (이미 다운로드된 표준화 미완 전 기업, 또는 --corps 지정분) ──
    if args.standardize_only:
        if args.corps:
            affected = [c.strip() for c in args.corps.split(",") if c.strip()]
            logger.info(f"[collect] (재개) ④ 파싱·표준화 — 지정 {len(affected)}개 기업 "
                        f"(타임아웃 {args.timeout}초/기업)")
        else:
            affected = collect.needs_standardize_corps()
            logger.info(f"[collect] (재개) ④ 파싱·표준화 대상 {len(affected)}개 기업 "
                        f"(타임아웃 {args.timeout}초/기업)")
        agg = _standardize_with_timeout(affected, args.timeout) if affected else {}
        logger.success(f"[collect] 재개 완료 — std_v2 {agg.get('s', 0):,} · 이산분기 {agg.get('q', 0):,} · "
                       f"달력 {agg.get('c', 0):,} · 타임아웃스킵 {agg.get('timeout', 0)} · 오류 {agg.get('errors', 0)}")
        _sync_cf_da(affected)
        _verify_and_log(agg, args)
        _sync_biz_metrics(affected)
        _sync_order_backlog(affected)
        _sync_periodic_apis(affected)
        _refresh_valuation_daily()
        return

    from collector.downloader import run_downloads
    from collector.filing_collector import sync_filings

    # ⓪ 상장 유니버스 갱신(옵션) — 신규 상장 반영 + 상장폐지·제외 비활성화.
    #    네트워크(KRX/DART) 조회라 실패해도 수집은 계속(비치명적).
    if args.refresh_universe:
        try:
            u = collect.refresh_universe()
            new_names = ", ".join(c.get("corp_name", "") for c in (u.get("new_corps") or [])[:20])
            deact_names = ", ".join(c.get("corp_name", "") for c in (u.get("deactivated_corps") or [])[:20])
            logger.info(f"[collect] ⓪ 유니버스 갱신 — 대상 {u.get('final_count', 0):,}개 · "
                        f"신규 {u.get('new_count', 0)} · 제외 {u.get('deactivated', 0)}")
            if new_names:
                logger.info(f"[collect]    신규: {new_names}")
            if deact_names:
                logger.info(f"[collect]    제외: {deact_names}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[collect] ⓪ 유니버스 갱신 실패(수집은 계속): {exc}")

    # ① 탐지
    disc = collect.discover_recent_corps(args.days)
    corps = disc["corps"]
    logger.info(f"[collect] ① 최근 {args.days}일({disc['window']}) 정기공시 "
                f"{disc['total_filings']}건 → 활성 보통주 {len(corps)}개 기업")
    if not corps:
        logger.success("[collect] 신규 공시 없음 — 종료")
        return

    # ② 공시목록 동기화(force: 기존 기업의 신규 공시 재확인)
    r1 = sync_filings(corp_codes=corps, force=True)
    logger.info(f"[collect] ② 동기화 {r1.get('processed', 0)}개 기업 (API {r1.get('api_calls', 0)}콜)")

    # ③ 다운로드
    r2 = run_downloads(only_corp_codes=corps)
    logger.info(f"[collect] ③ 다운로드 완료 {r2.get('completed', 0)} / 실패 {r2.get('failed', 0)} / "
                f"스킵 {r2.get('skipped', 0)} (큐 {r2.get('total_queued', 0)})")

    # ④ 파싱·표준화·분기·달력 (신규 기업만, 기업당 타임아웃)
    affected = collect.needs_standardize_corps(only=corps)
    logger.info(f"[collect] ④ 파싱·표준화 대상 {len(affected)}개 기업 (타임아웃 {args.timeout}초/기업)")
    agg = _standardize_with_timeout(affected, args.timeout) if affected else {}

    logger.success(f"[collect] 완료 — 신규 {len(corps)}개 기업 · fact {agg.get('e_facts', 0):,} · "
                   f"std_v2 {agg.get('s', 0):,} · 이산분기 {agg.get('q', 0):,} · 달력 {agg.get('c', 0):,} · "
                   f"타임아웃스킵 {agg.get('timeout', 0)} · 오류 {agg.get('errors', 0)}")

    # ④-2 D&A note 복원(B5) — 신규 기업의 연결 CF D&A 갭을 채워 EBITDA 재퇴행 방지.
    _sync_cf_da(affected)

    # ⑤ 수집 후 DQ 게이트 — 새로 표준화된 기업만 Gate B(보고서==DB)+항등식 재검, corp_verify_status 적재.
    _verify_and_log(agg, args)

    # ⑤-1 사업지표(생산능력/생산실적/가동률) — 신규 기업의 사업보고서 본문표 → biz_metrics(B4).
    _sync_biz_metrics(affected)

    # ⑤-2 수주상황 — 신규 기업의 사업보고서 본문표 → order_backlog(B1→B4).
    _sync_order_backlog(affected)

    # ⑤-3 배당/자기주식/직원현황/타법인출자/임원보수 — 신규 기업의 최신 사업연도만(Phase 2, PRD 13).
    _sync_periodic_apis(affected)

    # ⑥ valuation_daily matview 갱신(A4a) — 오늘 반영분(신규 재무·주가)까지 밸류에이션 뷰에 즉시 노출.
    _refresh_valuation_daily()


if __name__ == "__main__":
    main()
