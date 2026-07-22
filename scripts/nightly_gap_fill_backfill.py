"""전문서비스 갭 채우기 Phase 2·3·4 전수 백필 오케스트레이터 — 매일 00:01 launchd 자동실행.

deploy/launchd/com.tjfinance.gapfill.plist 로 등록. 각 Phase 는 독립적으로 완료 여부를
판정해 이미 끝난 Phase 는 건너뛰고(사실상 즉시 no-op), **셋 다 완료되면 launchctl unload +
plist 삭제로 자기 등록을 해제**한다(더 이상 실행되지 않음). 일회성 백필 잡이라 항구적으로
남겨두지 않는 것이 설계 의도.

Phase 2 (주주환원 API 6종, PRD 13) — DART 서버 쿼터 제한(하루 40,000콜, 계정 전체 공유).
  scripts/collect_periodic_apis.py 를 API 6종 각각 순차 subprocess 호출(--years 2015-<올해>,
  --skip-existing). 이미 완료됐거나 그날 쿼터가 소진된 API 는 즉시(또는 수초 내) 종료되므로
  매일 전부 호출해도 안전 — 진짜 서버 쿼터 소진 시 status='020' 5연속 감지로 각 API 호출이
  금방 끝난다(collect_periodic_apis.py 자체 circuit breaker, key-bugs-fixed #6·#7 패턴).
  완료판정 = periodic_api_progress 커버리지가 (활성기업×연도×API) 전수와 일치하는지 SQL 확인.

Phase 3 (부문·수출입 매출, PRD 14) — 로컬 파일 파싱, DART 쿼터 무관. collector.biz_metrics 로
  기업별 최신 사업보고서를 파싱하되, **매출표 자체가 없는 기업(금융지주 등)은 biz_metrics 에
  흔적이 안 남아** "이미 확인함"을 DB 만으로 구분할 수 없다 — app.data._localstore 로컬 JSON
  (~/.tj_finance/gap_fill_phase3_state.json)에 시도이력을 별도 기록해 완료를 판정한다.

Phase 4 (비용성격 D&A, PRD 15) — 로컬 파일 파싱+재표준화, DART 쿼터 무관.
  collector.expense_nature_sync.sync_expense_nature 로 depreciation IS NULL AND da_total IS
  NULL 잔여만 타겟(SQL 로 정확히 완료판정 가능, 별도 상태파일 불요).

로그: logs/gap_fill.out.log / logs/gap_fill.err.log (launchd StandardOut/ErrorPath, plist 참조).
수동 실행: python scripts/nightly_gap_fill_backfill.py
"""
from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.dart_periodic import API_NAMES
from collector.db import get_session

_ROOT = Path(__file__).resolve().parents[1]
_PYTHON = str(_ROOT / ".venv" / "bin" / "python")
_START_YEAR = 2015
_PLIST_LABEL = "com.tjfinance.gapfill"
_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{_PLIST_LABEL}.plist"

_P3_STATE_FILE = "gap_fill_phase3_state.json"
_P4_STATE_FILE = "gap_fill_phase4_state.json"


def _current_year() -> int:
    return date.today().year


# ── Phase 2 — 주주환원 API 6종 ───────────────────────────────────────────
def _phase2_remaining(session) -> int:
    """전수(활성기업×연도×API) 대비 아직 확인 안 된(periodic_api_progress 미기록) 조합 수."""
    y0, y1 = _START_YEAR, _current_year()
    n_corps = session.execute(text(
        "SELECT count(*) FROM corporations WHERE is_active AND stock_code IS NOT NULL")).scalar()
    n_years = y1 - y0 + 1
    total = n_corps * n_years * len(API_NAMES)
    done = session.execute(text("""
        SELECT count(*) FROM periodic_api_progress p
        JOIN corporations c ON c.corp_code = p.corp_code
        WHERE c.is_active AND c.stock_code IS NOT NULL
          AND p.fiscal_year BETWEEN :y0 AND :y1
          AND p.api_name = ANY(:apis)
    """), {"y0": y0, "y1": y1, "apis": list(API_NAMES)}).scalar()
    return max(0, total - done)


def run_phase2() -> int:
    """API 6종을 순차 subprocess 호출(이미 완료/쿼터소진분은 즉시 종료). 반환=완료 후 잔여 조합 수."""
    years = f"{_START_YEAR}-{_current_year()}"
    for api in API_NAMES:
        cmd = [_PYTHON, str(_ROOT / "scripts" / "collect_periodic_apis.py"),
               "--api", api, "--years", years, "--skip-existing"]
        logger.info(f"[gapfill] Phase2 실행: {' '.join(cmd[1:])}")
        try:
            subprocess.run(cmd, cwd=str(_ROOT), check=False)
        except Exception as exc:  # noqa: BLE001 — 개별 API 실패는 격리(비치명), 다음 API 계속
            logger.warning(f"[gapfill] Phase2 {api} subprocess 실행 실패(계속): {exc}")
    with get_session() as s:
        remaining = _phase2_remaining(s)
    logger.info(f"[gapfill] Phase2 잔여 조합: {remaining:,}")
    return remaining


# ── Phase 3 — 부문·수출입 매출 ───────────────────────────────────────────
def _phase3_target_corps(session) -> list[str]:
    """완료 다운로드된 사업보고서(annual)가 있는 활성 상장기업 전체(파싱 대상 모집단)."""
    rows = session.execute(text("""
        SELECT DISTINCT c.corp_code FROM corporations c
        JOIN filings f ON f.corp_code = c.corp_code AND f.report_type='annual' AND f.is_final
        JOIN download_tasks dt ON dt.rcept_no = f.rcept_no AND dt.status='completed'
            AND dt.file_type='xml' AND dt.file_path IS NOT NULL
        WHERE c.is_active AND c.stock_code IS NOT NULL
    """)).fetchall()
    return [r[0] for r in rows]


def run_phase3() -> int:
    """미시도 기업만 골라 biz_metrics(생산+매출) 최신 사업보고서 파싱. 반환=잔여 미시도 기업 수."""
    from app.data import _localstore as _ls
    from collector.biz_metrics import sync_biz_metrics_corp

    with get_session() as s:
        targets = _phase3_target_corps(s)
    state = _ls.load(_P3_STATE_FILE)
    attempted: set[str] = set(state.get("attempted_corps", []))
    todo = [c for c in targets if c not in attempted]
    logger.info(f"[gapfill] Phase3 대상 {len(targets)}사 · 미시도 {len(todo)}사")

    for i, corp in enumerate(todo, 1):
        try:
            with get_session() as s:
                sync_biz_metrics_corp(s, corp, latest_only=True)
                s.commit()
        except Exception as exc:  # noqa: BLE001 — 개별 기업 실패는 격리(비치명), 다음 기업 계속
            logger.warning(f"[gapfill] Phase3 {corp} 실패(계속): {exc}")
        attempted.add(corp)
        if i % 100 == 0 or i == len(todo):
            _ls.save(_P3_STATE_FILE, {"attempted_corps": sorted(attempted)})
            logger.info(f"[gapfill] Phase3 진행 {i}/{len(todo)}")

    remaining = len(set(targets) - attempted)
    logger.info(f"[gapfill] Phase3 잔여 미시도 기업: {remaining}")
    return remaining


# ── Phase 4 — 비용성격 D&A ───────────────────────────────────────────────
# year_min: 2024(DART Track A D&A 절벽 대응) → **2015 로 확대**(외부평가 P2, EBITDA 커버리지 확대).
# 비용성격별 분류 주석은 2024 이전 보고서에도 있어, da_total NULL 인 과거연도(2015~2023)의 EBITDA
# 커버리지(연결 FY ~22-35%)를 끌어올린다. 멱등·단위가드(da/매출 범위) → 오염 없음. 밤당 상한으로 페이싱.
_PHASE4_YEAR_MIN = 2015
# NULL D&A 대상 기업 목록(연결 FY, 2015+). attempt-tracking 판정용 모집단.
_PHASE4_CORPS_SQL = """
    SELECT DISTINCT corp_code FROM std_financials_v2
    WHERE statement_type='consolidated' AND version=1 AND fiscal_period='FY'
      AND fiscal_year>=:ymin AND NOT COALESCE(is_stub,false) AND NOT COALESCE(is_discrete,false)
      AND depreciation IS NULL AND da_total IS NULL
    ORDER BY corp_code
"""


# 한 밤에 처리할 최대 기업 수(야간 잡 실행시간 유계). 기업당 추출+재표준화 ≈ 4초라
# 500사 ≈ 30~40분. 남은 기업은 다음 밤에 이어감(기업단위 commit 이라 자동 재개).
_PHASE4_MAX_CORPS_PER_NIGHT = 500


def run_phase4() -> int:
    """비용성격 D&A 복원 — **미시도 기업만** 밤당 상한으로 처리(Phase3 와 동일 attempt-tracking).

    D&A 를 어느 서식에도 공시하지 않는 기업은 복원 후에도 NULL 로 남는다. 시도 여부를 상태파일에
    기록하지 않으면 그런 영구-NULL 기업이 매일 재시도되어 잔여가 0 에 도달하지 못하고 잡이 자기
    해제되지 않는다. 그래서 성공·실패 무관하게 **1회 시도한 기업은 기록해 재시도에서 제외**한다
    (신규 보고서 분은 collect_new 파이프라인이 별도 커버). 반환=잔여 미시도 기업 수."""
    from app.data import _localstore as _ls
    from collector.expense_nature_sync import sync_expense_nature

    with get_session() as s:
        targets = [r[0] for r in s.execute(text(_PHASE4_CORPS_SQL), {"ymin": _PHASE4_YEAR_MIN})]
    state = _ls.load(_P4_STATE_FILE)
    attempted: set[str] = set(state.get("attempted_corps", []))
    todo = [c for c in targets if c not in attempted]
    logger.info(f"[gapfill] Phase4 대상 {len(targets)}사(NULL D&A) · 미시도 {len(todo)}사 · "
                f"이번 밤 최대 {_PHASE4_MAX_CORPS_PER_NIGHT}사")
    if not todo:
        return 0

    batch = todo[:_PHASE4_MAX_CORPS_PER_NIGHT]
    res = sync_expense_nature(corps=batch, year_min=_PHASE4_YEAR_MIN)
    logger.info(f"[gapfill] Phase4 실행 결과: {res}")

    # 성공·실패 무관 시도 기록(영구-NULL 재시도 방지) → 상태 저장.
    attempted.update(batch)
    _ls.save(_P4_STATE_FILE, {"attempted_corps": sorted(attempted)})

    remaining = len([c for c in targets if c not in attempted])
    logger.info(f"[gapfill] Phase4 잔여 미시도 기업: {remaining}")
    return remaining


# ── 자기 등록 해제 ────────────────────────────────────────────────────────
def _unregister_self() -> None:
    logger.success("[gapfill] Phase 2·3·4 전부 완료 — launchd 자동 등록을 해제합니다")
    try:
        subprocess.run(["launchctl", "unload", "-w", str(_PLIST_PATH)], check=False)
        logger.info(f"[gapfill] launchctl unload 완료: {_PLIST_PATH}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[gapfill] launchctl unload 실패(수동 확인 필요): {exc}")
    try:
        if _PLIST_PATH.exists():
            _PLIST_PATH.unlink()
            logger.info(f"[gapfill] plist 삭제 완료: {_PLIST_PATH}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[gapfill] plist 삭제 실패(수동 확인 필요): {exc}")


def main() -> None:
    logger.info(f"[gapfill] ==== 시작 {date.today()} ====")

    p2 = run_phase2()
    p3 = run_phase3()
    p4 = run_phase4()

    logger.info(f"[gapfill] ==== 요약 — Phase2 잔여 {p2:,} · Phase3 잔여 {p3} · Phase4 잔여 {p4} ====")

    if p2 == 0 and p3 == 0 and p4 == 0:
        _unregister_self()
    else:
        logger.info("[gapfill] 아직 미완료 항목 있음 — 내일 00:01 다시 실행됩니다")


if __name__ == "__main__":
    main()
