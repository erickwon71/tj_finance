"""신규 공시 수집·DB화 (헤드리스) — 수집 페이지와 동일 흐름의 CLI 판.

실행일 기준 최근 N일 정기공시 탐지 → sync_filings(force) → 다운로드 → 파싱·표준화·분기·달력.
수동 실행하거나 cron/launchd 로 매일 예약할 수 있다.

④ 파싱·표준화는 **기업당 워커 프로세스 + 타임아웃**으로 처리한다: 대용량/병리 보고서
(예: 30MB iXBRL)에서 100% CPU 로 정체하는 기업을 `--timeout` 초 초과 시 강제 종료·스킵하고
다음 기업으로 넘어간다(C레벨 lxml 멈춤도 프로세스 kill 로 확실히 중단). 워커는 재사용하고
멈춘 경우에만 재생성하므로 정상 기업엔 오버헤드가 거의 없다.

실행:
  .venv/bin/python scripts/collect_new.py [--days 7] [--timeout 120]
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
    ap.add_argument("--days", type=str, default="7",
                    help="최근 N일 정기공시 확인. 'auto' = 마지막 성공 실행 이후를 자동 회수"
                         "(3일 겹침·90일 상한). 고정값은 장애 시 그 기간을 영구 누락시킨다")
    ap.add_argument("--download-only", action="store_true",
                    help="⓪~③+미러+감사만 — 파싱·표준화·계층2/3 적재는 전부 생략. "
                         "계층3 재설계 중 데일리 운영용(계획 §5.1)")
    ap.add_argument("--timeout", type=int, default=120, help="기업당 파싱·표준화 타임아웃(초)")
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
        agg = _standardize_with_timeout(affected, args.timeout) if affected else {}
        logger.success(f"[collect] 재개 완료 — std_v2 {agg.get('s', 0):,} · 이산분기 {agg.get('q', 0):,} · "
                       f"달력 {agg.get('c', 0):,} · 타임아웃스킵 {agg.get('timeout', 0)} · 오류 {agg.get('errors', 0)}")
        _sync_cf_da(affected)
        _sync_layer2_lines(affected)
        _verify_and_log(agg, args)
        _sync_biz_metrics(affected)
        _sync_order_backlog(affected)
        _sync_periodic_apis(affected)
        _refresh_valuation_daily()
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
    agg = _standardize_with_timeout(affected, args.timeout) if affected else {}

    logger.success(f"[collect] 완료 — 신규 {len(corps)}개 기업 · fact {agg.get('e_facts', 0):,} · "
                   f"std_v2 {agg.get('s', 0):,} · 이산분기 {agg.get('q', 0):,} · 달력 {agg.get('c', 0):,} · "
                   f"타임아웃스킵 {agg.get('timeout', 0)} · 오류 {agg.get('errors', 0)}")

    # ④-2 D&A note 복원(B5) — 신규 기업의 연결 CF D&A 갭을 채워 EBITDA 재퇴행 방지.
    _sync_cf_da(affected)

    # ④-3 계층2 전사 — 신규 보고서 → report_lines(본문) + note_lines(주석).
    _sync_layer2_lines(affected)

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

    # ⑦ 미러 + 완전성 감사 (full 모드도 동일하게 수행)
    audit = _run_mirror_and_audit(days)
    _finish_run(run_id, "success", {"corps": len(corps), **archive_stats, **audit})


if __name__ == "__main__":
    main()
