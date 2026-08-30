"""신규 공시 수집·DB화 (헤드리스) — 수집 페이지와 동일 흐름의 CLI 판.

실행일 기준 최근 N일 정기공시 탐지 → sync_filings(force) → 다운로드 → 파싱(extract/reconcile)
→ 계층3 표준화(std_financials_v3). 수동 실행하거나 cron/launchd 로 매일 예약할 수 있다.

★2026-08-30(Phase 2, std_v3_daily_wiring_plan_2026-08-30.md D1-b) — 표준화 소비계층을
std_v2 → std_v3 로 전환했다. `process_corp`가 도는 std_v2의 standardize/quarterly/
calendar stage는 더 이상 돌지 않는다(④-6 `_sync_std_v3`가 std_financials_v3를 대신
채움). 이산분기·달력정규화는 v3에 대응 개념이 없어 이 시점 이후의 신규 기간에 한해
중단됐다 — §8 재구현 트랙 전까지의 공백(현재 뷰·스크리너 미사용이라 즉각 영향 없음,
정보 손실도 아님 — v3는 report_lines 에서 언제든 재생성 가능).
★2026-08-30(valuation_daily_blockers_da_netdebt_design_2026-08-30.md §5 순서1) —
`_sync_cf_da`가 독자적으로 std_v2를 재계산하던 잔여 경로도 제거했다. std_v2 쓰기는
이제 전무하다(fact_v2/extended_financials 소관 upsert만 남음).

④ 파싱·표준화는 **기업당 워커 프로세스 + 타임아웃**으로 처리한다: 대용량/병리 보고서
(예: 30MB iXBRL)에서 100% CPU 로 정체하는 기업을 `--timeout` 초 초과 시 강제 종료·스킵하고
다음 기업으로 넘어간다(C레벨 lxml 멈춤도 프로세스 kill 로 확실히 중단). 워커는 재사용하고
멈춘 경우에만 재생성하므로 정상 기업엔 오버헤드가 거의 없다.

실행:
  .venv/bin/python scripts/collect_new.py [--days 7] [--timeout 300]
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
    None 받으면 종료. (spawn 으로 모듈 재임포트되므로 함수는 모듈 레벨이어야 함)

    ★2026-08-30(Phase 2, std_v3_daily_wiring_plan_2026-08-30.md D1-b) — `stages`를
    `("extract", "reconcile")`만 남기고 `standardize`·`quarterly`·`calendar`(std_v2
    계열)는 뺐다. ④-6(`_sync_std_v3`)이 report_lines 로부터 std_financials_v3 를
    별도로 채우므로 std_v2 표준화는 데일리에 더 이상 필요 없다.
    ★ 잃는 것 — 이산분기(`is_discrete`)·달력정규화(`std_financials_calendar`)는
    std_v2 전용 개념이라 v3엔 대응 컬럼/테이블이 없다. 이 시점(이 커밋) 이후의
    **신규** 기간에 대해 두 산출물이 멈춘다. 현재 뷰·스크리너 미사용이라 즉각적
    영향은 없고(사용자 확인, D1-b), 정보 손실도 아니다 — v3는 report_lines 에서
    언제든 재생성 가능. §8 소비자 재구현 트랙에서 v3 기반으로 새로 만든 뒤 이
    공백(이 커밋 이후~재구현 완료 시점)을 소급 생성해야 한다.
    """
    from collector.db import get_session
    from run import process_corp

    while True:
        corp = in_q.get()
        if corp is None:
            return
        try:
            with get_session() as session:
                out = process_corp(session, corp, stages=("extract", "reconcile"))
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

    # ★2026-08-30(Phase 2) — "s"/"q"/"c"(std_v2 표준화/이산분기/달력) 카운터는 `_worker`가
    # 그 stages를 더 이상 돌지 않아 항상 0으로 고정되므로 뺐다(process_corp은 여전히 그
    # 키를 반환하지만 값은 0). 대신 extract 단계가 실제로 한 일을 보여주는 "e_facts"만 집계.
    agg = {"e_facts": 0, "errors": 0, "timeout": 0}
    ok_corps: list[str] = []
    skipped: list[str] = []
    total = len(affected)
    for i, corp in enumerate(affected, 1):
        in_q.put(corp)
        try:
            status, c, payload = out_q.get(timeout=timeout)
            if status == "ok":
                agg["e_facts"] += payload["e_facts"]
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
                        f"(fact {agg['e_facts']:,}, 스킵 {agg['timeout']}, 오류 {agg['errors']})")

    in_q.put(None)
    worker.join(timeout=10)
    if worker.is_alive():
        worker.terminate()
    if skipped:
        logger.warning(f"[collect]   ⏱ 타임아웃 스킵 {len(skipped)}개: {', '.join(skipped)}")
    agg["ok_corps"] = ok_corps
    return agg


def _run_standardize_batches(affected: list[str], timeout: int, batch_size: int = 50) -> dict:
    """④ 추출·정합화(extract/reconcile) → D&A → 계층2(xml) → 주식수전사를 배치 단위
    (기본 50개사)로 묶어 배치마다 즉시 완결시킨다(P1-2,
    docs/plans/handoff_next_session_2026-08-19.md §5).

    ★2026-08-30(Phase 2, std_v3_daily_wiring_plan_2026-08-30.md D1-b) — std_v2
    표준화 stage 는 `_worker`(`process_corp`)에서 뺐다(④-6 `_sync_std_v3`가 std_v3를
    대신 채움). 함수명·docstring의 "std_v2 표준화"는 그 이전 관례명일 뿐 지금은
    extract/reconcile만 돈다.

    ★★ 그런데도 std_v2 쓰기가 완전히 멈추진 않는다 — `_sync_cf_da`(아래)가 부르는
    `cf_da_sync.sync_cf_da`/`expense_nature_sync.sync_expense_nature`는 **자신의
    SELECT 대상을 std_financials_v2 에서 직접 골라**(`depreciation IS NULL`인 기존
    행), 그 corp에 대해 **독자적으로** `standardize_corp`(v2)→`derive_quarters_corp`
    →`calendarize_corp`를 다시 돌린다(`process_corp`의 stages 축소와 무관한 별도
    경로). 브랜드뉴 기간(오늘 처음 생긴 fy/period)은 애초에 std_v2 행이 없어 대상이
    안 되지만, **Phase 2 이전에 이미 만들어진 std_v2 행 중 depreciation NULL인 것은
    이후에도 계속 재표준화(recompute)된다** — 그 corp이 다른 이유로 오늘 `ok_corps`
    에 다시 들어올 때마다. `std_v2_retirement_port_to_v3_2026-08-22.md`의 R17이
    이미 같은 문제를 지적했다("이 단계를 걷어내면 extended_financials가 stale") —
    그 문서의 결정대로 지금은 **손대지 않고 남겨둔다**(§8 소비자 이식과 함께 처리).
    "std_v2 쓰기 제거"는 이 Phase 2 범위에서 **완전하지 않다** — 신규 쓰기는 없지만
    기존 행 재계산은 남는다.

    Why(배치 자체의 이유): previously these downstream steps ran once, after the *entire*
    affected list finished. If the process was killed mid-run, corps that already
    committed were left with layer2 permanently missing — `needs_standardize_corps()`
    treats std_v3 presence as "done"(D0), so a rerun never reselects them (actually
    observed 2026-08-18 with the old std_v2 셀렉터: 374 corps stuck at report_lines=0).
    Batching bounds the loss to one batch instead of the whole run, and each batch is
    fully durable once logged.

    batch_size=50 ≈ 37min/batch at the measured 44.4s/corp(당시 std_v2 표준화 포함 기준 —
    Phase 2로 그 stage를 뺐으니 실제로는 더 빠르다). Ordinary daily runs (tens of corps)
    fit in a single batch, so this is a no-op in practice for the common case.
    """
    agg = {"e_facts": 0, "errors": 0, "timeout": 0, "ok_corps": []}
    if not affected:
        return agg
    total_batches = -(-len(affected) // batch_size)
    for i in range(0, len(affected), batch_size):
        batch = affected[i:i + batch_size]
        r = _standardize_with_timeout(batch, timeout)
        for k in ("e_facts", "errors", "timeout"):
            agg[k] += r.get(k, 0)
        ok = r.get("ok_corps") or []
        agg["ok_corps"].extend(ok)
        _sync_cf_da(ok)
        _sync_layer2_lines(ok)
        _sync_shares_transcribe(ok)
        logger.info(f"[collect]   배치 {i // batch_size + 1}/{total_batches} 완결 — "
                    f"{len(ok)}개사 layer2+주식수 반영")
    return agg


def run_dq_gate(corps: list[str], fy_min: int = 2015) -> dict:
    """I2 · 수집시 DQ 게이트 — 수집된 기업에 Gate B(보고서==DB) 재감사 + 항등식(DQ) 집계.

    기존 검증 자산 재사용: `gateb_audit.audit_corp`(Phase A 면표 + Phase B 라인, 내부 커밋) +
    `verify_corp_sequential.rollup_corp`(→ corp_verify_status upsert). 표준화가 std_v3 에 이미 반영한
    항등식 위반은 data_quality>=3 로 집계(★2026-08-30 v2→v3 전환, D1). fail_a(확정 불일치)·
    line value_diff·DQ3 를 반환한다.
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
            fy_min=fy_min, fy_max=2100, recheck=True, no_commit=False, line_audit=True,
            # gateb_audit.audit_corp() 는 args.source 를 첫 줄부터 참조한다(scripts/gateb_audit.py:119).
            # 이 필드가 없어 --download-only 를 벗기는 순간 AttributeError 로 즉사하는 배선
            # 누락이었다(docs/plans/gateb_view_source_version_join_fix_design_2026-08-17.md §1-C
            # ⑤). ★2026-08-30 "v2"→"v3" 전환(std_v3_daily_wiring_plan_2026-08-30.md D1):
            # 예전엔 이 파이프라인이 std_financials_v3 를 안 만들었다 — 별도 수동 배치
            # (`scripts/build_std_v3.py`)만 채웠고, source="v3" 로 두면 방금 수집한 신규
            # 기간이 std_v3 에 아직 없어 감사 대상 0건인 채로 "이상없음"을 반환하는
            # 위양성 그린(false-green) 게이트가 됐다. 이제 위 ④-6(`_sync_std_v3`)가 이
            # 함수 호출 **전에** 같은 실행 안에서 std_v3 를 채우므로 그 함정이 없다 —
            # 남은 방어선은 ④-6 자체가 실패한 corp 을 `_verify_and_log`가 `agg["std_v3_failed"]`
            # 로 넘겨받아 감사 결과와 무관하게 명시적 실패로 승격시키는 것(아래 dq3 쿼리도
            # 이제 std_financials_v3 를 직접 읽는다).
            source="v3")
        gb_agg = {"status": Counter(), "gate": Counter(),
                  "fld_pass": 0, "fld_fail": 0, "fail_rows": [], "errors": 0}
        try:
            with get_session() as s:
                gateb_audit.audit_corp(s, corp, gb_args, gb_agg)
            with get_session() as s:
                vals = vcs.rollup_corp(s, corp, names.get(corp, "?"), stage="audited")
                dq3 = s.execute(text(
                    "SELECT count(*) FROM std_financials_v3 WHERE corp_code=:c "
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


def _resolve_window(days_arg: str, mode: str) -> tuple[int, str]:
    """조회 창 결정. `--days auto` 면 마지막 성공 실행 이후를 자동으로 다시 훑는다.

    `--days 3` 고정이 2026-07 의 21일 공백을 만든 직접 원인이다. 3일 넘는 장애가 나면
    그 사이 공시가 **영구 누락**되고 아무도 모른다. 워터마크(pipeline_runs)를 두면
    며칠 멈춰 있었어도 다음 실행이 그 구간을 자동으로 회수한다.

    반환: (days, 설명)
    """
    if days_arg != "auto":
        return int(days_arg), f"고정 {days_arg}일"

    from sqlalchemy import text
    from collector.db import get_session

    try:
        with get_session() as s:
            last = s.execute(text(
                "SELECT max(window_end) FROM pipeline_runs "
                "WHERE mode = :m AND status = 'success'"), {"m": mode}).scalar()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] 워터마크 조회 실패({exc}) — 기본 7일로 진행")
        return 7, "워터마크 실패 → 기본 7일"

    if last is None:
        return 7, "이전 성공 이력 없음 → 기본 7일"

    # 3일 겹침 = DART 반영 지연 대비(수집은 rcept_no 단위 멱등이라 중복 무해).
    # 90일 상한 = 장기 중단 시 DART 쿼터 폭주 방지. 그보다 긴 공백은 수동 백필.
    days = (date.today() - last).days + 3
    if days > 90:
        logger.warning(f"[collect] 마지막 성공 {last} — 공백 {days}일이 상한(90) 초과. "
                       f"90일만 훑는다. 나머지는 수동 백필 필요")
        return 90, f"공백 {days}일 → 90일로 절단"
    return max(days, 3), f"마지막 성공 {last} 기준 자동 {days}일"


def _start_run(mode: str, days: int) -> int | None:
    """pipeline_runs 에 실행 시작을 기록하고 id 반환."""
    from sqlalchemy import text
    from collector.db import get_session
    try:
        with get_session() as s:
            rid = s.execute(text("""
                INSERT INTO pipeline_runs (mode, status, window_bgn, window_end)
                VALUES (:m, 'running', :bgn, :end) RETURNING id
            """), {"m": mode, "bgn": date.today() - timedelta(days=days),
                   "end": date.today()}).scalar()
            s.commit()
            return rid
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] 실행 이력 기록 실패(비치명적): {exc}")
        return None


def _finish_run(run_id: int | None, status: str, summary: dict) -> None:
    """실행 종료 기록. status='success' 여야 다음 실행의 워터마크가 전진한다."""
    if run_id is None:
        return
    import json

    from sqlalchemy import text
    from collector.db import get_session
    try:
        with get_session() as s:
            s.execute(text("""
                UPDATE pipeline_runs SET finished_at = now(), status = :st, summary = :sm
                WHERE id = :id
            """), {"id": run_id, "st": status, "sm": json.dumps(summary, default=str)})
            s.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] 실행 이력 갱신 실패(비치명적): {exc}")


def _audit_completeness(days: int) -> dict:
    """⑦ 수집 완전성 감사 — DART 목록 대비 미탐지·미다운로드가 0인지.

    이것이 있었다면 2026-07-17 의 다운로드 13건 전건 실패가 당일 드러났다.
    추가로 `status='completed'` 인데 파일이 실재하지 않는 건을 찾아 `pending` 으로 되돌린다
    (큐 조건이 pending|failed 뿐이라 한 번 completed 가 되면 파일이 사라져도 재수집되지 않는다).
    """
    from sqlalchemy import text
    from collector.db import get_session

    summary = {"missing_filing": 0, "not_downloaded": 0, "vanished_files": 0}

    # ① DART 대조
    try:
        import subprocess
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[0] / "qa" / "audit_download_gap.py"),
             "--days", str(days)],
            capture_output=True, text=True, timeout=600)
        for line in proc.stdout.splitlines():
            if line.startswith("① filings 테이블에 없음"):
                summary["missing_filing"] = int(line.split(":")[1].strip().split("건")[0].replace(",", ""))
            elif line.startswith("② filings 에는 있으나"):
                summary["not_downloaded"] = int(line.split(":")[1].strip().split("건")[0].replace(",", ""))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[audit] DART 대조 실패(비치명적): {type(exc).__name__}: {exc}")

    # ② 당일 다운로드분 파일 실재 확인(§5.4 최후 안전망)
    try:
        with get_session() as s:
            # ⓪-4 로 아카이브된 기업은 제외한다. 원문이 raw_report 밖으로 **의도적으로**
            # 옮겨진 것이라 '유실'이 아니다. 빼지 않으면 completed → pending 으로 되돌려
            # 원장이 영구히 어긋난다(어제 받고 오늘 폐지 확정된 기업에서 실제로 발생).
            rows = s.execute(text("""
                SELECT dt.rcept_no, dt.file_path FROM download_tasks dt
                WHERE dt.status = 'completed' AND dt.file_path IS NOT NULL
                  AND dt.completed_at >= current_date - 1
                  AND NOT EXISTS (
                      SELECT 1 FROM filings f
                      JOIN corporations c ON c.corp_code = f.corp_code
                      WHERE f.rcept_no = dt.rcept_no AND c.archive_path IS NOT NULL)
            """)).fetchall()
            gone = [r[0] for r in rows if not Path(r[1]).exists()]
            if gone:
                s.execute(text("""
                    UPDATE download_tasks SET status = 'pending'
                    WHERE rcept_no = ANY(:r)
                """), {"r": gone})
                s.commit()
                summary["vanished_files"] = len(gone)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[audit] 파일 실재 확인 실패(비치명적): {type(exc).__name__}: {exc}")

    bad = summary["missing_filing"] + summary["not_downloaded"] + summary["vanished_files"]
    msg = (f"[audit] 완전성 — 미탐지 {summary['missing_filing']} · "
           f"미다운로드 {summary['not_downloaded']} · 유실복구 {summary['vanished_files']}")
    if bad:
        logger.error(msg + "  ⚠ 수집 누락 발견!")
        try:
            from scripts.notify import notify_failure
            notify_failure("수집 완전성 경고", msg)
        except Exception:  # noqa: BLE001
            pass
    else:
        logger.success(msg)
    return summary


def _sync_delisting() -> dict:
    """⓪-3 상장폐지 판정 — 상태(DB)만 갱신한다. **원문 파일은 여기서 건드리지 않는다.**

    여기서 하는 것: delisting_status(candidate/confirmed/reinstated) + delisted_at 기록.
    파일 조치는 판정과 분리해 다음 단계(⓪-4)에서 한다 — 판정이 틀렸을 때 상태만 되돌리면
    되는 구간을 남겨두기 위해서다.

    판정에는 G0(소스 신뢰)·G1(연속 부재)·G2(교차 신호)·G3(일일 상한)·G4(알림) 가 걸려 있고,
    폐지 명부처럼 폐지일·사유가 명시된 **양성 증거**는 G1 을 건너뛴다(collector/delisting.py).

    비치명적 — 실패해도 수집은 계속한다.
    """
    try:
        from collector import krx_client as kc
        from collector.corp_collector import _get_krx_universe
        from collector.delisting import evaluate

        universe, market_status = _get_krx_universe()
        _, results = kc.fetch_all()
        listed = kc.listed_codes(list(results.values())) or set(universe or {})
        registry = kc.fetch_delisted()

        r = evaluate(listed, market_status, krx_mode=universe is not None,
                     apply=True, delisted_registry=registry)
        if r["skipped"]:
            logger.warning(f"[collect] ⓪-3 상장폐지 판정 스킵 — {r['reason']}")
            return {"delisting": "skipped"}

        c = r["counts"]
        logger.info(f"[collect] ⓪-3 상장폐지 — 후보 {c['candidate']} · 확정 {c['confirmed']} · "
                    f"복귀 {c['reinstated']} · 보류 {c['hold']}")
        return {"delisting_confirmed": c["confirmed"], "delisting_candidate": c["candidate"]}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] ⓪-3 상장폐지 판정 실패(비치명적): {type(exc).__name__}: {exc}")
        return {"delisting": "error"}


def _sync_delisting_archive() -> dict:
    """⓪-4 상장폐지 확정분 원문 조치 — NAS 아카이브 이관 + SD 백업 폴더 삭제.

    사용자 결정(2026-08-01): 원래 수동이던 §6.4/§6.4b 를 데일리 자동으로 돌린다.
    · NAS: raw_report/{시장}/{기업}/ → archive/delisted/{연도}/{기업}/ **이동**(영구 보존, D1)
    · SD : 같은 폴더 **삭제** — NAS 아카이브 실물+파일 수를 대조한 뒤에만

    ★ 순서가 중요하다: 반드시 ⑥ 미러보다 **먼저** 돌아야 한다. 원문이 raw_report 밖으로
      나간 뒤에 미러가 돌아야 방금 지운 SD 폴더를 미러가 다시 채우지 않는다.

    오탐 복원: `scripts/delisting_manage.py --restore <corp_code> --apply`
      (아카이브에서 원위치 + 상태 해제. SD 는 다음 미러가 다시 채운다.)

    ★ `--standardize-only`(재개) 경로에는 **일부러 배선하지 않는다.** 재개는 이미 받아둔
      원문을 다시 파싱하는 모드라 파일을 옮기면 그 실행 자신의 입력이 사라진다.
      (파서 편입 런북의 "두 call site" 규칙에 대한 명시적 예외 — 암묵적 누락이 아니다.)

    비치명적 — 실패해도 수집은 계속한다. 상한 초과·정합 불일치는 메일로 알린다.
    """
    try:
        from collector.delisting_archive import run_daily
        r = run_daily(apply=True)
        if r["archived"] or r["backup_purged"] or r["archive_capped"]:
            logger.info(f"[collect] ⓪-4 원문 이관 — 아카이브 {r['archived']}개 · "
                        f"SD 정리 {r['backup_purged']}개({r['backup_purged_mb']:.0f}MB)"
                        f"{' · ⚠상한초과로 중단' if r['archive_capped'] else ''}")
        return r
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] ⓪-4 원문 이관 실패(비치명적): {type(exc).__name__}: {exc}")
        return {"delisting_archive": "error"}


def _run_mirror_and_audit(days: int) -> dict:
    """⑥ NAS→SD 덧붙이기 미러 + ⑦ 수집 완전성 감사. 둘 다 비치명적(수집을 되돌리지 않는다)."""
    out: dict = {}
    try:
        from scripts.sync_storage_mirror import check_freshness, run_mirror
        r = run_mirror()
        out["mirror"] = r.get("status")
        out["mirror_files"] = r.get("files_sent")
        check_freshness()      # `--delete` 를 뺀 대가 — 백업이 조용히 낡는 것 감시
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] ⑥ 미러 실패(비치명적): {type(exc).__name__}: {exc}")
        out["mirror"] = "error"
    try:
        out.update(_audit_completeness(days))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] ⑦ 완전성 감사 실패(비치명적): {type(exc).__name__}: {exc}")
    return out


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
    fact_v2/extended_financials 의 EBITDA/da_total 갭을 메운다. 비치명(수집 계속). expense_nature
    는 cf_da 다음에 돌아 **여전히 depreciation NULL** 인 잔여만 타겟(이중 계상 방지).

    ★2026-08-30(valuation_daily_blockers_da_netdebt_design_2026-08-30.md §5 순서1) — std_v2
    재전파 호출은 두 sync 함수에서 제거됐다(std_v2 소비자 없음). fact_v2 upsert 만 한다."""
    if not corps:
        return
    try:
        from collector.cf_da_sync import sync_cf_da
        res = sync_cf_da(corps=corps, year_min=2024)
        if res["corps"]:
            logger.info(f"[collect] ④-2 D&A 복원(CF) — 기업 {res['corps']} · note fact {res['facts']:,}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] ④-2 D&A 복원(CF) 실패(비치명적): {exc}")
    try:
        from collector.expense_nature_sync import sync_expense_nature
        res2 = sync_expense_nature(corps=corps, year_min=2024)
        if res2["corps"]:
            logger.info(f"[collect] ④-2 D&A 복원(비용성격 주석) — 기업 {res2['corps']} · "
                        f"note fact {res2['facts']:,}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] ④-2 D&A 복원(비용성격) 실패(비치명적): {exc}")


def _sync_layer2_lines(corps: list[str]) -> None:
    """④-3 계층2 증분 적재 — 신규 보고서를 **본문(report_lines) + 주석(note_lines)** 으로 전사.

    이게 없으면 백필을 끝내도 신규 공시분이 영영 적재되지 않는다(주석 2026-07-28 배선,
    **본문 2026-07-31 배선** — 그전까지 본문은 배치 전용이라 데일리 경로에 없었다).
    계층3 이 두 테이블을 다 읽으므로 데일리로 따라가야 한다.
    비치명(수집 계속). 벌크 백필과 달리 인덱스는 그대로 두고 증분 INSERT 만 한다.

    ★이 함수는 **두 call site** 에서 불린다(메인 ④-3 · `--standardize-only` 재개) —
      `docs/runbook_new_parser_pipeline_integration.md` 체크리스트 ①. 하나만 배선하면
      재개 경로에서 조용히 빠진다."""
    if not corps:
        return
    try:
        from collector.note_lines_sync import sync_layer2_lines
        res = sync_layer2_lines(corps=corps)
        if res["filings"]:
            logger.info(f"[collect] ④-3 계층2 전사 — 기업 {res['corps']} · "
                        f"보고서 {res['filings']:,} · 주석 {res['rows']:,}행 · "
                        f"본문 {res['body_rows']:,}행 (실패 {res['errors']})")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] ④-3 계층2 전사 실패(비치명적): {exc}")


def _sync_xbrl_instance_lines(corps: list[str]) -> None:
    """④-4 계층2 증분 적재 — DART 표준 XBRL instance zip(`file_type='xbrl_zip'`) 경로.

    `_sync_layer2_lines`(④-3, `file_type='xml'`)와 대상이 다른 별도 파이프라인이다 —
    `document.xml`(014, "파일없음")로 XML 본문을 못 받은 필링을 다운로더가 XBRL instance
    zip 으로 폴백 수집했을 때만 대상이 생긴다(`collector/downloader.py::
    _try_xbrl_instance_fallback`, Phase 2). 본문(BS/IS/CF/SCE)만 만든다 — 주석 없음
    (`fin2/extract/report_lines_xbrl.py` 모듈 docstring).

    ★이 함수도 **두 call site** 에서 불려야 한다(메인 ④-4 · `--standardize-only` 재개) —
      `docs/runbook_new_parser_pipeline_integration.md` 체크리스트 ①, `_sync_layer2_lines`
      와 동일 원칙. 비치명(수집 계속)."""
    if not corps:
        return
    try:
        from collector.xbrl_instance_lines_sync import sync_xbrl_instance_lines
        res = sync_xbrl_instance_lines(corps=corps)
        if res["filings"]:
            logger.info(f"[collect] ④-4 XBRL 원문 계층2 전사 — 기업 {res['corps']} · "
                        f"보고서 {res['filings']:,} · 본문 {res['rows']:,}행 · "
                        f"표 {res['table_rows']:,} (실패 {res['errors']})")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] ④-4 XBRL 원문 계층2 전사 실패(비치명적): {exc}")


def _sync_std_v3(corps: list[str]) -> dict:
    """④-6 계층3 std_v3 신규 배선 — `report_lines`(+`note_lines`)로부터 `std_financials_v3`
    를 corp 단위로 재빌드한다(`fin2.layer3.build.build_corp`, 기간·basis 단위
    delete-then-insert, 멱등 — 재실행해도 무손상, std_v3_daily_wiring_plan_2026-08-30.md §1-2).

    ★ 반드시 `_sync_xbrl_instance_lines`(④-4) **직후** · `_verify_and_log`(⑤) **직전**에서만
    호출한다. `build_corp`가 `report_lines`를 읽으므로 계층2의 xml 경로(④-3)와 xbrl_zip
    경로(④-4)가 둘 다 끝난 뒤여야 한다 — ④-4보다 먼저 돌면 xbrl_zip-only 기업이 누락된다
    (같은 문서 §1-4/§1-5).

    ★이 함수는 **두 call site**에서 불려야 한다(메인 ④-6 · `--standardize-only` 재개) —
    `docs/runbook_new_parser_pipeline_integration.md` 체크리스트 ①.

    corp 단위 try/except로 격리(하나 실패해도 나머지 corp은 계속) + 함수 전체를 다시
    비치명적으로 감쌈(런북 A2). 실패 corp은 "failed"에 담아 반환한다 — `_verify_and_log`가
    이 목록을 명시적 실패로 승격시켜, std_v3 빌드가 실패한 corp이 "감사 대상 0건"으로
    조용히 통과하는 false-green을 막는다(D1).
    """
    out = {"corps": 0, "rows": 0, "failed": []}
    if not corps:
        return out
    try:
        from collector.db import get_session
        from fin2.layer3.build import build_corp

        for corp in corps:
            try:
                with get_session() as session:
                    out["rows"] += build_corp(session, corp, year_min=2015)
                out["corps"] += 1
            except Exception as exc:  # noqa: BLE001
                out["failed"].append(corp)
                logger.warning(f"[collect]   ④-6 std_v3 {corp} 실패: {type(exc).__name__}: {exc}")
        if out["corps"] or out["failed"]:
            fail_note = f" (실패 {len(out['failed'])})" if out["failed"] else ""
            logger.info(f"[collect] ④-6 계층3 std_v3 — 기업 {out['corps']} · 행 {out['rows']:,}{fail_note}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] ④-6 계층3 std_v3 전체 실패(비치명적): {type(exc).__name__}: {exc}")
    return out


def _sync_shares_transcribe(corps: list[str]) -> None:
    """④-5 계층2 cross-cutting 전사 — 신규 정기보고서 '주식의 총수 등' 절 →
    `report_shares_outstanding`(std_v3_dq_shares_period_backfill_plan_2026-08-09.md §3.3, Phase 2).

    이게 없으면 소급 백필을 끝내도 신규 공시분의 발행주식수가 영영 적재되지 않는다 —
    `_sync_layer2_lines`(④-3)와 동일한 이유. 계층3(`build_corp`)가 이 테이블을 조인해
    std_v3.shares_out 을 채운다(원문 직접 read 없음).

    ★이 함수는 **두 call site** 에서 불린다(메인 ④-5 · `--standardize-only` 재개) —
      `docs/runbook_new_parser_pipeline_integration.md` 체크리스트 ①. 하나만 배선하면
      재개 경로에서 조용히 빠진다. 비치명(수집 계속)."""
    if not corps:
        return
    try:
        from fin2.extract.shares_transcribe import sync_shares_transcribe
        res = sync_shares_transcribe(corps=corps)
        if res["filings"]:
            logger.info(f"[collect] ④-5 발행주식수 전사 — 기업 {res['corps']} · "
                        f"보고서 {res['filings']:,} · 적재 {res['rows']:,} (실패 {res['errors']})")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] ④-5 발행주식수 전사 실패(비치명적): {exc}")


def _sync_biz_metrics(corps: list[str]) -> None:
    """B4+Phase3+B5 — 새로 수집된 기업의 사업보고서 '사업의 내용' 본문표 → biz_metrics.

    한 진입점(`parse_biz_metrics`)이 세 파서를 모두 방출한다:
      · B4  생산능력/생산실적/가동률            (biz_section)
      · P3  부문·수출/내수 매출실적(metric='sales', channel)  (sales_section)
      · B5  캡션 카탈로그 — 제품/원재료 현황·가격변동추이·생산설비·부문별 재무·점유율·
            매출처·투자계획·지식재산권 + 업종특수(보험/증권/건설/제약)  (biz_catalog)
    따라서 파서를 늘려도 이 배선은 바뀌지 않는다. 사업의 내용 절은 annual 에만 있어 이번에
    표준화된 기업의 최신 사업보고서만 대상. 비치명적 실패는 본 수집을 막지 않는다(rcept 단위 멱등)."""
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


def _run_curated_key_scan() -> None:
    """④ 후속 — Gate B curated 키 재생성기(§5-B, 2026-08-19 확정 범위 1차 구현,
    docs/plans/gateb_curated_key_regenerator_design_2026-08-18.md) 전수 패턴 스캔.

    R15~R33 다수가 (corp,fy,period[,basis]) 리터럴 override 로 구현돼 있어, 새 필링이
    같은 부류로 들어와도 자동으로 안 잡힌다(stale). 여기서 **corp 무관 전수** 재스캔해
    신규/재발 후보를 `curated_key_candidates` 에 적재하고(자동 코드 반영 없음, §5-A),
    1건 이상이면 macOS 알림(§6 결정사항 1).

    ★이 함수는 **두 call site** 에서 불려야 한다(메인 · `--standardize-only` 재개) —
      `docs/runbook_new_parser_pipeline_integration.md` 체크리스트 ①과 동일 원칙.
      `corps` 인자를 받지 않는다 — 스캔 모집단이 이번에 처리된 기업이 아니라 전체
      report_lines/face_audit 패턴이라(§5-A, 신규 corp 축까지 잡아야 lateral 후보를
      놓치지 않음), 매 호출 corp 무관하게 항상 전수로 돈다. 비치명(수집 계속)."""
    try:
        from fin2.audit.curated_key_scan import run_all_scans
        res = run_all_scans(notify=True)
        logger.info(f"[collect] ④+ curated 키 재생성기 — 신규후보 {res['total_new']}건 · "
                    f"소멸후보 {res['total_vanished']}건")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] ④+ curated 키 재생성기 실패(비치명적): {exc}")


def _refresh_valuation_daily() -> None:
    """A4a — 수집 후 valuation_daily matview 갱신(CONCURRENTLY, 읽기 비차단). 비치명적 실패."""
    try:
        from scripts.refresh_valuation_daily import refresh
        refresh(concurrent=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[collect] valuation_daily 갱신 실패(비치명적): {exc}")


def _verify_and_log(agg: dict, args) -> None:
    """수집 후 DQ 게이트 실행·로깅. fail_a/value_diff(확정 불일치) 발견 시 loud error.

    ★2026-08-30(D1, std_v3_daily_wiring_plan_2026-08-30.md) — `agg["std_v3_failed"]`
    (④-6 `_sync_std_v3`가 반환한 실패 corp 목록)을 감사 결과와 무관하게 명시적 실패로
    승격한다. ④-6이 런북 A2에 따라 비치명적으로 감싸여 있어, 실패해도 파이프라인은 계속
    가지만 그 corp은 std_v3에 새 행이 없다 — 그대로 두면 source="v3" 감사가 "대상 0건"
    으로 조용히 "이상없음"을 반환하는 false-green이 재발한다(위 gb_args 주석의 경고).
    """
    ok = agg.get("ok_corps") or []
    std_v3_failed = agg.get("std_v3_failed") or []
    if getattr(args, "no_verify", False) or not (ok or std_v3_failed):
        return
    logger.info(f"[verify] DQ 게이트 — {len(ok)}개 기업 Gate B(보고서==DB)+항등식 재검(fy≥{args.verify_fy_min})")
    summ = run_dq_gate(ok, args.verify_fy_min) if ok else {
        "corps": 0, "gb_fail_a": 0, "line_value_diff": 0, "dq3": 0, "fail_corps": []}
    msg = (f"[verify] 완료 — 검사 {summ['corps']} · fail_a {summ['gb_fail_a']} · "
           f"line_value_diff {summ['line_value_diff']} · DQ3(항등식위반) {summ['dq3']}"
           + (f" · std_v3 빌드실패 {len(std_v3_failed)}" if std_v3_failed else ""))
    if summ["gb_fail_a"] or summ["line_value_diff"] or std_v3_failed:
        logger.error(msg + "  ⚠ 보고서≠DB 확정 불일치 또는 std_v3 빌드 실패 발견!")
        for corp, fa, vd, dq in summ["fail_corps"]:
            logger.error(f"[verify]   {corp}: fail_a={fa} value_diff={vd} dq3={dq}")
        for corp in std_v3_failed:
            logger.error(f"[verify]   {corp}: std_v3 빌드 실패(false-green 방지 위해 명시 승격)")
    elif summ["dq3"]:
        logger.warning(msg + "  (DQ3=항등식 경고, 비차단 — corp_verify_status 기록됨)")
    else:
        logger.success(msg)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=str, default="7",
                    help="최근 N일 정기공시 확인. 'auto' = 마지막 성공 실행 이후를 자동 회수"
                         "(3일 겹침·90일 상한). 고정값은 장애 시 그 기간을 영구 누락시킨다")
    ap.add_argument("--download-only", action="store_true",
                    help="⓪~③+미러+감사만 — 파싱·표준화·계층2/3 적재는 전부 생략. "
                         "계층3 재설계 중 데일리 운영용(계획 §5.1)")
    ap.add_argument("--timeout", type=int, default=300, help="기업당 파싱·표준화 타임아웃(초)")
    ap.add_argument("--standardize-only", action="store_true",
                    help="①②③ 건너뛰고 ④(파싱·표준화)만 — 다운로드는 됐는데 표준화 남은 전체 기업 대상. 중단 후 재개용")
    # ⓪ 유니버스 갱신 + 상장폐지 판정은 **기본 ON**.
    #   예전엔 opt-in 이라 플래그를 안 주면 신규 상장이 영원히 안 들어오고 상장폐지 판정도
    #   통째로 건너뛰었다. 데일리에서 이건 옵션이 아니라 필수 단계다.
    #   `--refresh-universe` 는 기존 호출부(plist·스크립트) 호환을 위해 받기만 하고 무시한다.
    ap.add_argument("--refresh-universe", action="store_true",
                    help="(기본 동작 — 하위호환용으로 남겨둔 무시되는 플래그)")
    ap.add_argument("--no-refresh-universe", dest="refresh_universe_off",
                    action="store_true",
                    help="⓪ 유니버스 갱신·상장폐지 판정 생략(네트워크 차단 환경 등 예외용)")
    ap.add_argument("--corps", type=str, default=None,
                    help="쉼표구분 corp_code — 이 기업들만 ④ 처리(--standardize-only 와 함께). "
                         "예: 타임아웃 스킵분 재시도")
    ap.add_argument("--no-verify", action="store_true",
                    help="⑤ 수집 후 DQ 게이트(Gate B 재감사+항등식) 생략")
    ap.add_argument("--verify-fy-min", type=int, default=2015,
                    help="DQ 게이트 Gate B 재감사 최소 회계연도(기본 2015)")
    ap.add_argument("--skip-holidays", action="store_true",
                    help="KRX 휴장일(주말·공휴일)이면 아무것도 하지 않고 종료. 스케줄 실행(plist)용 — "
                         "손으로 돌릴 때는 주지 않으므로 휴일에도 그대로 작업할 수 있다")
    args = ap.parse_args()

    # ⓪-0 휴장일 스킵 — **저장소 계약보다 먼저**. 안 돌 날이면 볼륨조차 건드리지 않는다.
    #     정기보고서 접수·시세·상장폐지는 전부 영업일에만 생긴다.
    #     여기서 종료해도 누락은 없다: pipeline_runs 에 기록을 남기지 않으므로 워터마크가
    #     그대로 유지되고, 다음 영업일 `--days auto` 가 건너뛴 구간까지 함께 회수한다.
    if args.skip_holidays:
        from collector.market_calendar import skip_reason
        reason = skip_reason()
        if reason:
            logger.info(f"[collect] ⓪-0 {reason} — 실행 스킵(다음 영업일에 --days auto 가 회수)")
            return

    # ⓪ 저장소 계약 — 최우선. 실패면 아무것도 하지 않는다.
    #    2026-07-17 실행은 이 검사가 없어 다운로드 13/13 이 EPERM 으로 실패하는데도
    #    "비치명적"으로 넘기고 성공 로그를 남겼다.
    if not args.standardize_only:
        from collector.storage_guard import StorageContractError, assert_storage
        try:
            assert_storage(require_backup=False)
        except StorageContractError as exc:
            logger.error(f"[collect] ⓪ 저장소 계약 위반 — 수집 중단\n{exc}")
            try:
                from scripts.notify import notify_failure
                notify_failure("수집 중단 — 저장소 계약 위반", str(exc))
            except Exception:  # noqa: BLE001
                pass
            sys.exit(1)

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
        agg = _run_standardize_batches(affected, args.timeout)
        logger.success(f"[collect] 재개 완료 — fact {agg.get('e_facts', 0):,} · "
                       f"타임아웃스킵 {agg.get('timeout', 0)} · 오류 {agg.get('errors', 0)}")
        # ④-4 XBRL instance zip 경로 — own selector (P1-1), independent of the xml-only
        # `affected` list above since xbrl_zip-only corps never appear in it. Honor an
        # explicit --corps scope (targeted retry) the same way `affected` above does;
        # otherwise scan the full pending population.
        xbrl_affected = collect.needs_xbrl_instance_corps(only=affected if args.corps else None)
        _sync_xbrl_instance_lines(xbrl_affected)

        # ④-6 계층3 std_v3 — 메인 경로와 동일 원칙(아래 `_sync_std_v3` docstring 참고).
        # 재개 경로도 두 call site 규칙(런북 A3)에 따라 반드시 여기 배선한다.
        v3_corps = sorted(set(agg.get("ok_corps") or []) | set(xbrl_affected))
        v3_agg = _sync_std_v3(v3_corps)
        agg["std_v3_failed"] = v3_agg["failed"]

        _verify_and_log(agg, args)
        _sync_biz_metrics(affected)
        _sync_order_backlog(affected)
        _sync_periodic_apis(affected)
        _refresh_valuation_daily()
        _run_curated_key_scan()
        return

    from collector.downloader import run_downloads
    from collector.filing_collector import sync_filings

    # ⓪ 상장 유니버스 갱신 — 신규 상장 반영 + 상장폐지·제외 비활성화.
    #    네트워크(KRX/DART) 조회라 실패해도 수집은 계속(비치명적).
    if not args.refresh_universe_off:
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

        # ⓪-3 상장폐지 판정 — 유니버스 갱신 직후(같은 소스를 봐야 판단이 일관된다).
        _sync_delisting()

    # ⓪-4 확정분 원문 조치(NAS 아카이브 이관 + SD 폴더 삭제).
    #     유니버스 갱신 여부와 무관하게 돌린다 — 대상은 DB 에 이미 기록된 확정분이고,
    #     ⑥ 미러보다 먼저 끝나야 지운 SD 폴더가 되살아나지 않는다.
    archive_stats = _sync_delisting_archive()

    # ① 탐지 — DART 쿼터초과([020]) 등 API 실패 시 하드 크래시 대신 정상 종료(비치명).
    #    밸류에이션 refresh 는 별도 잡(nightly_valuation_refresh)이 담당하므로 여기서 죽어도 무방.
    mode = "download_only" if args.download_only else "full"
    days, window_desc = _resolve_window(args.days, mode)
    logger.info(f"[collect] 조회 창: {window_desc}")
    run_id = _start_run(mode, days)

    try:
        disc = collect.discover_recent_corps(days)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[collect] ① 탐지 실패(수집 중단): {type(exc).__name__}: {exc}")
        _finish_run(run_id, "failed", {"stage": "discover", "error": str(exc)})
        return
    corps = disc["corps"]
    logger.info(f"[collect] ① 최근 {days}일({disc['window']}) 정기공시 "
                f"{disc['total_filings']}건 → 활성 보통주 {len(corps)}개 기업")
    if not corps:
        logger.success("[collect] 신규 공시 없음 — 미러·감사만 수행")
        audit = _run_mirror_and_audit(days)
        _finish_run(run_id, "success", {"corps": 0, **archive_stats, **audit})
        return

    # ② 공시목록 동기화(force: 기존 기업의 신규 공시 재확인)
    r1 = sync_filings(corp_codes=corps, force=True)
    logger.info(f"[collect] ② 동기화 {r1.get('processed', 0)}개 기업 (API {r1.get('api_calls', 0)}콜)")

    # ③ 다운로드
    r2 = run_downloads(only_corp_codes=corps)
    logger.info(f"[collect] ③ 다운로드 완료 {r2.get('completed', 0)} / 실패 {r2.get('failed', 0)} / "
                f"스킵 {r2.get('skipped', 0)} (큐 {r2.get('total_queued', 0)})")

    # ══════════════════════════════════════════════════════════════════════
    #  확장 지점 (Phase 5) — 파싱·적재 재편입
    # ══════════════════════════════════════════════════════════════════════
    #  현재 데일리는 여기서 멈춘다. 아래는 **삭제한 게 아니라 조건 분기**이며,
    #  계층3 재설계가 끝나면 plist 에서 `--download-only` 를 빼는 것만으로 되살아난다.
    #
    #  되살릴 때 반드시 확인할 것 (docs/runbook_new_parser_pipeline_integration.md):
    #    ① **두 call site 모두** 배선 — 여기(메인)와 `--standardize-only` 재개 경로
    #    ② 소급 백필은 자동이 아니다 — download-only 기간에 받은 원문은 별도 재표준화
    #       (대상: `SELECT window_bgn, window_end FROM pipeline_runs WHERE mode='download_only'`)
    #    ③ 검증 — 회귀 테스트 + 원문 대조 + Gate B 무영향
    #
    #  ⚠ 상장폐지 확정 기업(delisting_status='confirmed')의 원문은 아카이브로 옮겨져
    #    raw_report 밖에 있다. 전량 재적재 시 **기존 DB 데이터를 보존하고 명시적으로
    #    스킵**해야 한다 — 조용히 빈 값으로 덮어쓰면 과거 시계열이 사라진다.
    # ══════════════════════════════════════════════════════════════════════
    if args.download_only:
        logger.info("[collect] --download-only — ④ 파싱·표준화 이하 전 단계 생략")
        audit = _run_mirror_and_audit(days)
        _finish_run(run_id, "success", {
            "corps": len(corps), "downloaded": r2.get("completed", 0),
            "failed": r2.get("failed", 0), **archive_stats, **audit})
        logger.success(f"[collect] 완료(download-only) — 기업 {len(corps)} · "
                       f"다운로드 {r2.get('completed', 0)} · 실패 {r2.get('failed', 0)}")
        return

    # ④ 파싱·표준화·분기·달력 (신규 기업만, 기업당 타임아웃)
    affected = collect.needs_standardize_corps(only=corps)
    logger.info(f"[collect] ④ 파싱·표준화 대상 {len(affected)}개 기업 (타임아웃 {args.timeout}초/기업)")

    # ④~④-5: 추출·정합화(extract/reconcile) → D&A → 계층2(xml) → 주식수전사, 배치 단위
    # (기본 50개사)로 즉시 완결(P1-2 — a mid-run kill used to leave a batch committed with
    # layer2 permanently missing). ★Phase 2로 std_v2 표준화 stage는 뺐다(D1-b) — std_v3는
    # 아래 ④-6이 채운다.
    agg = _run_standardize_batches(affected, args.timeout)

    logger.success(f"[collect] 완료 — 신규 {len(corps)}개 기업 · fact {agg.get('e_facts', 0):,} · "
                   f"타임아웃스킵 {agg.get('timeout', 0)} · 오류 {agg.get('errors', 0)}")

    # ④-4 계층2 전사(XBRL 원문 zip 경로) — own selector (P1-1): xbrl_zip-only corps never
    # appear in `affected` above (no xml file_type row), so they need their own pending list.
    xbrl_affected = collect.needs_xbrl_instance_corps(only=corps)
    _sync_xbrl_instance_lines(xbrl_affected)

    # ④-6 계층3 std_v3 — report_lines 갱신된 corp(xml ④-3 경로의 ok_corps + xbrl_zip ④-4
    # 경로의 xbrl_affected 합집합) 재빌드. ④-4 **직후** · ⑤ **직전**에 놓는다 — build_corp가
    # report_lines를 읽으므로 두 계층2 경로가 전부 끝난 뒤여야 xbrl_zip-only 기업이
    # 누락되지 않는다(std_v3_daily_wiring_plan_2026-08-30.md §1-4/§1-5).
    v3_corps = sorted(set(agg.get("ok_corps") or []) | set(xbrl_affected))
    v3_agg = _sync_std_v3(v3_corps)
    agg["std_v3_failed"] = v3_agg["failed"]

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

    # ④+ curated 키 재생성기 — 표준화 직후 전수 패턴 재스캔(§5-B, 위 함수 docstring 참고).
    _run_curated_key_scan()

    # ⑦ 미러 + 완전성 감사 (full 모드도 동일하게 수행)
    audit = _run_mirror_and_audit(days)
    _finish_run(run_id, "success", {"corps": len(corps), **archive_stats, **audit})


if __name__ == "__main__":
    main()
