#!/usr/bin/env python3
"""
DART 재무데이터 수집·파싱 시스템 — CLI 진입점

── 수집 ───────────────────────────────────────────────────────────────────
  python run.py init                    # DB 초기화 (최초 1회)
  python run.py sync-corps              # 기업 목록 동기화
  python run.py sync-filings            # 공시 목록 동기화 (전체 기업)
  python run.py sync-filings --corp 00126380   # 특정 기업만
  python run.py download                # XML/PDF 다운로드 (전체)
  python run.py download --limit 100    # 최대 100건만
  python run.py download --corp 00126380
  python run.py download --corps 0:10   # 기업 목록 0~9번째 (10개)
  python run.py list-corps              # 번호 붙은 기업 목록 출력
  python run.py list-corps --page 2
  python run.py status                  # 다운로드 현황
  python run.py failed                  # 실패 목록
  python run.py reset-failed            # 실패 건 재시도 등록
  python run.py all                     # sync-corps → sync-filings → download 순서

── 파싱 ───────────────────────────────────────────────────────────────────
  python run.py parse                   # 전체 파싱 (completed XML, parse_status=NULL)
  python run.py parse --corp 00102858   # 특정 기업만
  python run.py parse --limit 500       # 최대 500건만
  python run.py parse-status            # 파싱 현황 (완료/실패/미처리)
  python run.py parse-reset             # 파싱 실패 건 재시도 등록
  python run.py parse-reset --track-b  # Track B 전체 재파싱 (새 파서로 Track A 재분류)
  python run.py parse-reset --all      # 파싱 완료 전체 재파싱
  python run.py unknown-accounts        # 미매핑 계정과목 목록 (account_maps 확장 우선순위)
  python run.py unknown-accounts --limit 100

── 분석 (Phase 3) ──────────────────────────────────────────────────────────
  python run.py aggregate               # financial_facts → standard_financials 집계
  python run.py aggregate --corp 00126380  # 특정 기업
  python run.py aggregate --since 2020  # 2020년 이후만
  python run.py analyze --corp 00126380  # Bloomberg 스타일 재무분석 리포트
  python run.py analyze --corp 00126380 --sep  # 별도재무제표
  python run.py sync-prices               # pykrx + DART 주가/시총 일괄 수집
  python run.py sync-prices --since 2022  # 2022년 이후 FY 결산일 기준

── 유지보수 ────────────────────────────────────────────────────────────────
  python run.py deactivate              # 선박투자/리츠 등 제외 대상 비활성화
  python run.py cleanup                 # 비활성 기업 pending 작업 정리
  python run.py reset-html              # 레거시 HTML → PDF 재다운로드 등록
"""
import argparse
import sys
from pathlib import Path

from loguru import logger

# ── 로거 설정 ─────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger.remove()  # 기본 핸들러 제거
logger.add(
    sys.stderr,
    format="<green>{time:MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
    level="INFO",
    colorize=True,
)
logger.add(
    LOG_DIR / "dart_{time:YYYYMMDD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
    level="DEBUG",
    rotation="00:00",     # 자정에 로그 파일 교체
    retention="30 days",  # 30일치 보관
    encoding="utf-8",
)


def cmd_init(args):
    """DB 초기화"""
    from collector.db import init_db
    init_db()
    logger.success("DB 초기화 완료")


def cmd_sync_corps(args):
    """기업 목록 동기화"""
    from collector.corp_collector import sync_corporations
    result = sync_corporations()
    logger.success(f"완료: {result}")


def cmd_deactivate(args):
    """DB의 제외 대상 기업 비활성화 (선박투자/리츠 등)"""
    from collector.corp_collector import deactivate_excluded_corps
    result = deactivate_excluded_corps()
    logger.success(f"완료: {result}")


def cmd_sync_filings(args):
    """공시 목록 동기화"""
    from collector.filing_collector import sync_filings
    corp_codes = [args.corp] if args.corp else None
    result = sync_filings(corp_codes=corp_codes, force=getattr(args, "force", False))
    logger.success(f"완료: {result}")


def _get_active_corp_codes() -> list[str]:
    """
    다운로드 대상이 있는 활성 기업 목록을 corp_code 순으로 반환.
    (pending/failed 건이 1개 이상 있는 기업만 포함)
    """
    from sqlalchemy import text
    from collector.db import get_session

    with get_session() as session:
        rows = session.execute(text("""
            SELECT DISTINCT c.corp_code
            FROM corporations c
            JOIN filings f ON f.corp_code = c.corp_code
            JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
            WHERE c.is_active = TRUE
              AND f.is_final = TRUE
              AND dt.status IN ('pending', 'failed')
            ORDER BY c.corp_code
        """)).fetchall()
    return [r[0] for r in rows]


def _parse_corps_slice(corps_arg: str, all_codes: list[str]) -> list[str]:
    """
    '--corps 0:10' 형식을 파싱해 corp_code 리스트로 변환.
    단일 인덱스 '5' 도 지원 (해당 기업 1개).
    """
    if ":" in corps_arg:
        parts = corps_arg.split(":", 1)
        start = int(parts[0]) if parts[0] else 0
        end   = int(parts[1]) if parts[1] else len(all_codes)
    else:
        idx   = int(corps_arg)
        start, end = idx, idx + 1

    sliced = all_codes[start:end]
    if not sliced:
        raise ValueError(
            f"--corps {corps_arg} 범위가 전체 기업 수({len(all_codes)}개)를 벗어났습니다."
        )
    return sliced


def cmd_download(args):
    """PDF 다운로드"""
    from collector.downloader import run_downloads

    corp_codes: list[str] | None = None

    if getattr(args, "corp", None):
        corp_codes = [args.corp]
    elif getattr(args, "corps", None):
        all_codes  = _get_active_corp_codes()
        corp_codes = _parse_corps_slice(args.corps, all_codes)
        logger.info(
            f"--corps {args.corps} → {len(corp_codes)}개 기업 "
            f"(전체 {len(all_codes)}개 중 인덱스 선택)"
        )
        # 선택된 기업 목록 미리 출력
        for i, code in enumerate(corp_codes):
            from collector.db import get_session
            from sqlalchemy import text
            with get_session() as session:
                row = session.execute(
                    text("SELECT corp_name FROM corporations WHERE corp_code = :c"),
                    {"c": code},
                ).fetchone()
            name = row[0] if row else "?"
            start_idx = (
                int(args.corps.split(":")[0]) if ":" in args.corps else int(args.corps)
            )
            logger.info(f"  [{start_idx + i:>4}] {code}  {name}")

    result = run_downloads(
        limit=getattr(args, "limit", None),
        only_corp_codes=corp_codes,
    )
    logger.success(f"완료: {result}")


def cmd_list_corps(args):
    """번호 붙은 활성 기업 목록 출력 (--corps 인덱스 확인용)"""
    from sqlalchemy import text
    from collector.db import get_session

    page     = getattr(args, "page", 1) or 1
    per_page = 100
    offset   = (page - 1) * per_page

    with get_session() as session:
        rows = session.execute(text("""
            SELECT c.corp_code, c.corp_name, c.market,
                   COUNT(dt.rcept_no) AS pending_cnt
            FROM corporations c
            JOIN filings f ON f.corp_code = c.corp_code
            JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
            WHERE c.is_active = TRUE
              AND f.is_final = TRUE
              AND dt.status IN ('pending', 'failed')
            GROUP BY c.corp_code, c.corp_name, c.market
            ORDER BY c.corp_code
        """)).fetchall()

    total = len(rows)
    page_rows = rows[offset : offset + per_page]

    logger.info(f"활성 기업 (다운로드 대기 있는 기업) — 총 {total}개  [페이지 {page}]")
    logger.info(f"{'idx':>5}  {'corp_code':10}  {'market':8}  {'대기건수':>6}  corp_name")
    logger.info("-" * 65)
    for i, r in enumerate(page_rows):
        global_idx = offset + i
        logger.info(f"{global_idx:>5}  {r[0]:10}  {r[2] or '':8}  {r[3]:>6}건  {r[1]}")

    if total > offset + per_page:
        next_page = page + 1
        logger.info(f"\n  다음 페이지: python run.py list-corps --page {next_page}")


def cmd_status(args):
    """현황 조회"""
    from collector.runner import print_status
    print_status()


def cmd_failed(args):
    """실패 목록 조회"""
    from collector.runner import print_failed_downloads
    print_failed_downloads()


def cmd_reset_failed(args):
    """실패 건 재시도 등록"""
    from collector.runner import reset_failed_downloads
    reset_failed_downloads()


def cmd_cleanup(args):
    """비활성 기업의 pending 다운로드 작업 정리"""
    from collector.runner import cleanup_inactive_tasks
    cleanup_inactive_tasks()


def cmd_reset_html(args):
    """
    기존 레거시 HTML(표지만 있는 파일)을 pending으로 되돌려 PDF 재시도 등록.
    - DB: completed → pending, 파일 정보 초기화
    - 파일: 실제 .html 파일 삭제
    """
    from sqlalchemy import text
    from collector.db import get_session
    from pathlib import Path

    with get_session() as session:
        rows = session.execute(text("""
            SELECT rcept_no, file_path
            FROM download_tasks
            WHERE file_type = 'html'
              AND status = 'completed'
        """)).fetchall()

    if not rows:
        logger.info("재처리 대상 HTML 파일 없음")
        return

    logger.info(f"레거시 HTML {len(rows)}건을 pending으로 재등록합니다...")

    deleted_files  = 0
    missing_files  = 0

    for rcept_no, file_path in rows:
        # 파일 삭제
        if file_path:
            p = Path(file_path)
            if p.exists():
                p.unlink()
                deleted_files += 1
            else:
                missing_files += 1

    # DB 일괄 업데이트
    with get_session() as session:
        session.execute(text("""
            UPDATE download_tasks
            SET status       = 'pending',
                file_path    = NULL,
                file_type    = NULL,
                file_size    = NULL,
                completed_at = NULL,
                last_error   = 'HTML 재처리: PDF 재시도',
                attempts     = 0
            WHERE file_type = 'html'
              AND status = 'completed'
        """))

    logger.success(
        f"완료 — 파일 삭제: {deleted_files}건 / 파일 없음: {missing_files}건 / "
        f"DB pending 전환: {len(rows)}건"
    )
    logger.info("이제 'python run.py download' 로 PDF 재다운로드를 실행하세요.")


def cmd_all(args):
    """전체 파이프라인 순서 실행"""
    logger.info("=== 전체 파이프라인 시작 ===")
    cmd_sync_corps(args)
    cmd_sync_filings(args)
    cmd_download(args)
    logger.success("=== 전체 파이프라인 완료 ===")


# ══════════════════════════════════════════════════════════════════════
# Phase 2: 파싱 명령어
# ══════════════════════════════════════════════════════════════════════

def _parse_single(task_tuple) -> tuple:
    """
    단일 XML 파일 파싱 워커 (ThreadPoolExecutor에서 호출).

    Returns:
        (parse_status, fact_count, parser_track, unknown_accs_dict)
        unknown_accs_dict: {norm_name: {fs_type, corp_code, count}}
    """
    from sqlalchemy import text
    from pathlib import Path
    from collector.db import get_session
    from parser.xml.dart_xml_parser import parse_dart_xml
    from parser.common.amount_normalizer import normalize_account_name

    rcept_no, file_path, corp_code, fiscal_year, fiscal_period, report_type = task_tuple

    # 파일 존재 확인
    if not file_path or not Path(file_path).exists():
        with get_session() as s:
            s.execute(
                text("UPDATE download_tasks SET parse_status='skip',"
                     " parse_error='파일 없음' WHERE rcept_no=:r"),
                {"r": rcept_no},
            )
        return ("skip", 0, None, {})

    # parsing 상태 마킹
    with get_session() as s:
        s.execute(
            text("UPDATE download_tasks SET parse_status='parsing' WHERE rcept_no=:r"),
            {"r": rcept_no},
        )

    try:
        result = parse_dart_xml(
            file_path=Path(file_path),
            rcept_no=rcept_no,
            corp_code=corp_code,
            fiscal_year=fiscal_year or 2000,
            fiscal_period=fiscal_period or "FY",
            report_type=report_type or "annual",
        )

        fact_count = _save_parsed_facts(result)

        # unknown 계정 집계:
        # 1. result.unknown_accounts_seen: Track B에서 저장 건너뛴 unknown 계정 (새 방식)
        # 2. result.facts에 남은 unknown.*: 이전 코드 호환성 (Track A Note 등)
        unknown_accs: dict[str, dict] = {}
        # 신규: ParseResult.unknown_accounts_seen (Track B 미매핑 추적)
        for norm, info in result.unknown_accounts_seen.items():
            entry = unknown_accs.setdefault(norm, {
                "fs_type":   info["fs_type"],
                "corp_code": corp_code,
                "count":     0,
            })
            entry["count"] += info["count"]
        # 레거시: result.facts에 남은 unknown.* (Track A Fallback 등)
        for fact in result.facts:
            if fact.account_code.startswith("unknown."):
                norm = normalize_account_name(fact.account_name_raw)[:300]
                entry = unknown_accs.setdefault(norm, {
                    "fs_type":   fact.fs_type[:6],
                    "corp_code": corp_code,
                    "count":     0,
                })
                entry["count"] += 1

        # 최종 상태 갱신
        with get_session() as s:
            s.execute(text("""
                UPDATE download_tasks
                SET parse_status = :status,
                    parsed_facts = :facts,
                    parser_track = :track,
                    parsed_at    = NOW(),
                    parse_error  = NULL
                WHERE rcept_no = :r
            """), {
                "status": result.parse_status,
                "facts":  fact_count,
                "track":  result.parser_track,
                "r":      rcept_no,
            })

        return (result.parse_status, fact_count, result.parser_track, unknown_accs)

    except Exception as exc:
        err_msg = str(exc)[:1000]
        try:
            with get_session() as s:
                s.execute(text("""
                    UPDATE download_tasks
                    SET parse_status='failed', parse_error=:err
                    WHERE rcept_no=:r
                """), {"err": err_msg, "r": rcept_no})
        except Exception:
            pass
        return ("failed", 0, None, {"__exception__": {"fs_type": "??", "corp_code": corp_code,
                                                       "count": 0, "_err": err_msg}})


def cmd_parse(args):
    """
    다운로드된 XML 파일을 파싱해 financial_facts 저장.

    대상: download_tasks.status='completed' AND file_type='xml'
          AND (parse_status IS NULL OR parse_status='pending')

    옵션:
      --workers N          : N개 서브프로세스로 병렬 실행 (기본 1 = 단일)
      --worker-id W        : 내부용 — 워커 W번이 처리할 파티션 선택
      --total-workers N    : 내부용 — 전체 워커 수 (해시 파티션 분모)
    """
    import subprocess, sys
    from sqlalchemy import text
    from collector.db import get_session

    corp_code_filter = getattr(args, "corp", None)
    limit            = getattr(args, "limit", None)
    workers          = getattr(args, "workers", 1)

    # ── 워커 모드: 실제 파싱 실행 ────────────────────────────────────
    worker_id     = getattr(args, "worker_id", None)
    total_workers = getattr(args, "total_workers", 1)

    if worker_id is not None:
        # 이 프로세스는 파티션 worker_id % total_workers 담당
        _run_parse_worker(
            worker_id=worker_id,
            total_workers=total_workers,
            corp_code_filter=corp_code_filter,
            limit=limit,
        )
        return

    # ── 관리자 모드: workers=1이면 직접 실행, >1이면 서브프로세스 스폰 ──
    if workers <= 1:
        _run_parse_worker(
            worker_id=0,
            total_workers=1,
            corp_code_filter=corp_code_filter,
            limit=limit,
        )
        return

    # N개 서브프로세스 병렬 스폰 (각 프로세스는 독립 Python 인터프리터 → GIL 없음)
    logger.info(f"병렬 파싱 시작: workers={workers}")

    base_cmd = [sys.executable, __file__,
                "parse",
                f"--worker-id", "0",            # placeholder
                f"--total-workers", str(workers)]
    if corp_code_filter:
        base_cmd += ["--corp", corp_code_filter]
    if limit:
        # limit을 workers에 균등 분배
        per = max(1, limit // workers)
        base_cmd += ["--limit", str(per)]

    procs = []
    for wid in range(workers):
        cmd = base_cmd[:]
        cmd[cmd.index("0")] = str(wid)   # --worker-id W
        p = subprocess.Popen(cmd)
        procs.append(p)
        logger.info(f"  워커 {wid} PID={p.pid} 시작")

    # 모든 서브프로세스 완료 대기
    for p in procs:
        p.wait()

    # 완료 후 최종 상태 출력
    logger.success(f"병렬 파싱 완료 (workers={workers})")
    _print_parse_status()


def _print_parse_status():
    """parse-status 요약 1줄 출력 (내부 헬퍼)"""
    from sqlalchemy import text
    from collector.db import get_session
    with get_session() as s:
        row = s.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE parse_status='success')  AS success,
                COUNT(*) FILTER (WHERE parse_status='partial')  AS partial,
                COUNT(*) FILTER (WHERE parse_status='failed')   AS failed,
                COALESCE(SUM(parsed_facts),0)                   AS total_facts
            FROM download_tasks
            WHERE file_type='xml'
        """)).fetchone()
    if row:
        logger.info(f"  XML 파싱 누계 — 성공:{row.success}  부분:{row.partial}  "
                    f"실패:{row.failed}  총facts:{row.total_facts:,}")


def _run_parse_worker(worker_id: int, total_workers: int,
                      corp_code_filter, limit):
    """
    실제 XML 파싱 루프.
    worker_id / total_workers 해시 파티션으로 중복 없이 파일을 분배.
    """
    from sqlalchemy import text
    from collector.db import get_session

    # ── 파싱 대상 조회 ────────────────────────────────────────────────
    partition_clause = (
        f" AND ABS(HASHTEXT(dt.rcept_no)) % {total_workers} = {worker_id}\n"
        if total_workers > 1 else ""
    )
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    sql = f"""
        SELECT dt.rcept_no, dt.file_path,
               f.corp_code, f.fiscal_year, f.fiscal_period, f.report_type
        FROM download_tasks dt
        JOIN filings f ON f.rcept_no = dt.rcept_no
        WHERE dt.status = 'completed'
          AND dt.file_type = 'xml'
          AND (dt.parse_status IS NULL OR dt.parse_status = 'pending')
          AND f.is_final = TRUE
          AND dt.file_path IS NOT NULL
        {partition_clause}
        ORDER BY f.fiscal_year DESC, dt.rcept_no
        {limit_clause}
    """
    params: dict = {}
    if corp_code_filter:
        sql = sql.replace("AND dt.file_path IS NOT NULL",
                          "AND dt.file_path IS NOT NULL\n  AND f.corp_code = :corp_code")
        params["corp_code"] = corp_code_filter

    with get_session() as session:
        tasks = [tuple(row) for row in session.execute(text(sql), params).fetchall()]

    if not tasks:
        logger.info(f"[W{worker_id}] 파싱 대상 없음")
        return

    total = len(tasks)
    pfx = f"[W{worker_id}]" if total_workers > 1 else ""
    logger.info(f"{pfx} 파싱 대상: {total:,}건")

    success_cnt = partial_cnt = failed_cnt = skip_cnt = 0
    total_facts = 0
    unknown_acc: dict[str, dict] = {}

    for idx, task in enumerate(tasks, 1):
        rcept_no, file_path, corp_code, fiscal_year, fiscal_period, report_type = task
        status, fact_count, _, unknowns = _parse_single(task)

        # 카운터 업데이트
        if status == "success":
            success_cnt += 1
        elif status == "partial":
            partial_cnt += 1
        elif status == "skip":
            skip_cnt += 1
        else:
            failed_cnt += 1
        total_facts += fact_count or 0

        # unknown 계정 누적
        for norm, info in unknowns.items():
            if norm.startswith("__exception__"):
                continue
            entry = unknown_acc.setdefault(norm, {
                "fs_type": info["fs_type"], "corp_code": info["corp_code"], "count": 0
            })
            entry["count"] += info["count"]

        # 로그: 100건마다, 마지막에, 또는 실패 시
        if idx % 100 == 0 or idx == total:
            pct = idx / total * 100
            logger.info(
                f"{pfx} {idx:,}/{total:,} ({pct:.1f}%)  "
                f"성공:{success_cnt}  부분:{partial_cnt}  실패:{failed_cnt}  "
                f"facts:{total_facts:,}"
            )
        elif status == "failed":
            logger.error(f"{pfx} 실패 [{rcept_no}]")

    # UnknownAccount upsert
    if unknown_acc:
        _upsert_unknown_accounts(unknown_acc)
        logger.info(f"{pfx} 미매핑 계정 {len(unknown_acc)}종 기록")

    logger.success(
        f"{pfx} 완료 — 성공:{success_cnt}  부분:{partial_cnt}  "
        f"실패:{failed_cnt}  스킵:{skip_cnt}  facts:{total_facts:,}"
    )


def _save_parsed_facts(result) -> int:
    """
    ParseResult → financial_facts 테이블 저장.

    - 재파싱 idempotency: 동일 rcept_no 기존 데이터 삭제 후 재삽입
    - 배치 내 중복 처리: 같은 (fs_type, account_code, col_index)가 여러 번
      매핑될 경우 extraction_confidence 높은 것 1건만 유지
      (합계/소계 행은 일반 행보다 우선)

    저장된 행 수를 반환한다.
    """
    from datetime import datetime
    from sqlalchemy import text
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from collector.db import get_session
    from collector.models import FinancialFact

    now = datetime.utcnow()

    if not result.facts:
        # facts가 없어도 이전 파싱 데이터를 삭제해야 idempotency 보장
        # (재파싱 시 old facts가 잔류하면 quality 저하)
        with get_session() as session:
            session.execute(
                text("DELETE FROM financial_facts WHERE rcept_no = :r"),
                {"r": result.rcept_no},
            )
        return 0

    # ── 배치 내 중복 제거 ────────────────────────────────────────────
    # 키: (fs_type, account_code, col_index)
    # 우선순위: is_subtotal=True > confidence 높음 > row_order 작음
    dedup: dict[tuple, dict] = {}
    for f in result.facts:
        key = (f.fs_type, f.account_code[:120], f.col_index)
        rec = {
            "corp_code":             result.corp_code,
            "rcept_no":              result.rcept_no,
            "fs_type":               f.fs_type,
            "statement_type":        f.statement_type,
            "period_type":           f.period_type,
            "account_code":          f.account_code[:120],
            "account_name_raw":      f.account_name_raw[:300],
            "period_end":            f.period_end,
            "fiscal_year":           f.fiscal_year,
            "fiscal_period":         f.fiscal_period,
            "amount":                f.amount,
            "unit_multiplier":       f.unit_multiplier,
            "col_index":             f.col_index,
            "row_order":             f.row_order,
            "is_subtotal":           f.is_subtotal,
            "is_ifrs":               result.is_ifrs,
            "source_format":         f.source_format,
            "extraction_confidence": f.extraction_confidence,
            "parser_track":          f.parser_track,
            "is_superseded":         False,
            "parsed_at":             now,
        }
        if key not in dedup:
            dedup[key] = rec
        else:
            prev = dedup[key]
            # 우선순위:
            # 1. 합계(is_subtotal=True) 행 우선
            # 2. NULL 금액보다 실제 금액 우선 (이전 NULL → 새 값으로 교체)
            # 3. confidence 높은 것 우선
            # 4. 동점이면 먼저 나온 것(선착순)
            new_has_amount = f.amount is not None
            prev_has_amount = prev["amount"] is not None
            if (f.is_subtotal and not prev["is_subtotal"]) or \
               (f.is_subtotal == prev["is_subtotal"] and
                    new_has_amount and not prev_has_amount) or \
               (f.is_subtotal == prev["is_subtotal"] and
                    new_has_amount == prev_has_amount and
                    f.extraction_confidence > prev["extraction_confidence"]):
                dedup[key] = rec

    records = list(dedup.values())

    with get_session() as session:
        # 기존 데이터 삭제 (재파싱 idempotency)
        session.execute(
            text("DELETE FROM financial_facts WHERE rcept_no = :r"),
            {"r": result.rcept_no},
        )
        if records:
            # ON CONFLICT DO NOTHING: 혹시 남은 중복도 안전하게 처리
            stmt = pg_insert(FinancialFact.__table__).values(records)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["corp_code", "rcept_no", "fs_type", "account_code", "col_index"]
            )
            session.execute(stmt)

    return len(records)


def _upsert_unknown_accounts(accumulator: dict) -> None:
    """
    account_maps에서 매핑 실패한 계정과목을 unknown_accounts 테이블에 기록.
    이미 존재하면 occurrence_count 누적, last_seen_at 갱신.
    VALUES 절을 한 번에 묶어 배치 upsert로 처리 (성능 최적화).
    """
    from sqlalchemy import text
    from collector.db import get_session

    if not accumulator:
        return

    # 배치 upsert: VALUES (:n0,:f0,:c0,:s0), (:n1,:f1,:c1,:s1), ...
    # 한 번에 최대 500건씩 처리 (PostgreSQL max params 제한 고려)
    items = list(accumulator.items())
    CHUNK = 500

    with get_session() as session:
        for start in range(0, len(items), CHUNK):
            chunk = items[start:start + CHUNK]
            vals_parts = []
            params: dict = {}
            for i, (norm_name, info) in enumerate(chunk):
                vals_parts.append(f"(:n{i}, :f{i}, :c{i}, :s{i}, NOW(), NOW())")
                params[f"n{i}"] = norm_name
                params[f"f{i}"] = info["fs_type"]
                params[f"c{i}"] = info["count"]
                params[f"s{i}"] = info["corp_code"]

            sql = f"""
                INSERT INTO unknown_accounts
                    (account_name_normalized, fs_type, occurrence_count,
                     corp_sample, first_seen_at, last_seen_at)
                VALUES {', '.join(vals_parts)}
                ON CONFLICT (account_name_normalized) DO UPDATE
                    SET occurrence_count = unknown_accounts.occurrence_count
                                        + EXCLUDED.occurrence_count,
                        last_seen_at     = NOW()
            """
            session.execute(text(sql), params)


def cmd_parse_status(args):
    """파싱 현황 조회 (파일 타입별 성공/실패/미처리)"""
    from sqlalchemy import text
    from collector.db import get_session

    with get_session() as session:
        rows = session.execute(text("""
            SELECT
                COALESCE(dt.file_type, '-')                                       AS file_type,
                COUNT(*)                                                           AS downloaded,
                COUNT(*) FILTER (WHERE dt.parse_status = 'success')              AS success,
                COUNT(*) FILTER (WHERE dt.parse_status = 'partial')              AS partial,
                COUNT(*) FILTER (WHERE dt.parse_status = 'failed')               AS failed,
                COUNT(*) FILTER (WHERE dt.parse_status = 'skip')                 AS skip,
                COUNT(*) FILTER (WHERE dt.parse_status IS NULL)                  AS not_parsed,
                COALESCE(SUM(dt.parsed_facts)
                    FILTER (WHERE dt.parse_status IN ('success','partial')), 0)   AS total_facts
            FROM download_tasks dt
            WHERE dt.status = 'completed'
            GROUP BY dt.file_type
            ORDER BY dt.file_type
        """)).fetchall()

        total = session.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE parse_status = 'success')                 AS success,
                COUNT(*) FILTER (WHERE parse_status = 'partial')                 AS partial,
                COUNT(*) FILTER (WHERE parse_status = 'failed')                  AS failed,
                COUNT(*) FILTER (WHERE parse_status IS NULL)                     AS not_parsed,
                COALESCE(SUM(parsed_facts)
                    FILTER (WHERE parse_status IN ('success','partial')), 0)      AS total_facts
            FROM download_tasks
            WHERE status = 'completed'
        """)).fetchone()

    bar = "=" * 75
    header = f"  {'파일유형':<8} {'다운완료':>8} {'성공':>8} {'부분':>6} {'실패':>6} {'스킵':>6} {'미파싱':>8} {'총facts':>13}"
    logger.info(bar)
    logger.info("  파싱 현황")
    logger.info(bar)
    logger.info(header)
    logger.info("-" * 75)
    for r in rows:
        logger.info(
            f"  {r[0]:<8} {r[1]:>8,} {r[2]:>8,} {r[3]:>6,} {r[4]:>6,} "
            f"{r[5]:>6,} {r[6]:>8,} {r[7]:>13,}"
        )
    if total:
        logger.info("-" * 75)
        logger.info(
            f"  {'합계':<8} {'':>8} {total[0]:>8,} {total[1]:>6,} {total[2]:>6,} "
            f"{'':>6} {total[3]:>8,} {total[4]:>13,}"
        )
    logger.info(bar)


def cmd_parse_reset(args):
    """파싱 실패(failed) 또는 Track B 전체를 NULL로 재등록 → parse 재시도 대상에 포함

    옵션:
      --partial   : parse_status='partial' 파일만 재시도 (부분 파싱 재처리)
      --track-b   : Track B 파싱 완료 파일 전체 재시도 (새 파서 코드로 재분류)
      --all       : 파싱된 모든 파일 재시도 (success/partial/failed 포함)
    기본값 (옵션 없음): parse_status='failed' 인 파일만 재시도
    """
    from sqlalchemy import text
    from collector.db import get_session

    track_b = getattr(args, "track_b", False)
    reset_all = getattr(args, "all", False)
    partial_only = getattr(args, "partial", False)

    with get_session() as session:
        if partial_only:
            result = session.execute(text("""
                UPDATE download_tasks
                SET parse_status = NULL,
                    parse_error  = NULL
                WHERE parse_status = 'partial'
            """))
            label = "부분 파싱(partial) 재시도"
        elif reset_all:
            result = session.execute(text("""
                UPDATE download_tasks
                SET parse_status = NULL,
                    parse_error  = NULL,
                    parser_track = NULL
                WHERE parse_status IN ('success', 'partial', 'failed')
            """))
            label = "전체 재파싱"
        elif track_b:
            result = session.execute(text("""
                UPDATE download_tasks
                SET parse_status = NULL,
                    parse_error  = NULL,
                    parser_track = NULL
                WHERE parse_status IN ('success', 'partial', 'failed')
                  AND parser_track = 'B'
            """))
            label = "Track B 재파싱 (새 파서 코드로 재분류)"
        else:
            result = session.execute(text("""
                UPDATE download_tasks
                SET parse_status = NULL,
                    parse_error  = NULL
                WHERE parse_status = 'failed'
            """))
            label = "파싱 실패 재시도"
        count = result.rowcount

    logger.success(f"{label} 등록: {count}건  → parse_status=NULL")
    if count:
        logger.info("  이제 'python run.py parse' 로 재파싱을 실행하세요.")


def cmd_unknown_accounts(args):
    """
    미매핑 계정과목 목록 출력.
    occurrence_count 높은 순으로 정렬 → account_maps 확장 우선순위 기준.
    """
    from sqlalchemy import text
    from collector.db import get_session

    limit = getattr(args, "limit", None) or 50

    with get_session() as session:
        rows = session.execute(text("""
            SELECT account_name_normalized, fs_type, occurrence_count,
                   corp_sample,
                   TO_CHAR(first_seen_at, 'YYYY-MM-DD') AS first_seen
            FROM unknown_accounts
            WHERE suggested_code IS NULL
            ORDER BY occurrence_count DESC
            LIMIT :lim
        """), {"lim": limit}).fetchall()

        total = session.execute(text(
            "SELECT COUNT(*) FROM unknown_accounts WHERE suggested_code IS NULL"
        )).scalar() or 0

    if not rows:
        logger.info("미매핑 계정과목 없음 — account_maps가 완전합니다 ✓")
        return

    logger.info(f"미매핑 계정과목  TOP {len(rows)} / 전체 {total}종")
    logger.info(f"  {'계정과목명(정규화)':<42} {'FS':>7} {'발생':>7} {'기업샘플':>10}  최초발견")
    logger.info("-" * 80)
    for r in rows:
        name = r[0][:40]
        logger.info(
            f"  {name:<42} {(r[1] or '')[:6]:>7} {r[2]:>7,} "
            f"{(r[3] or ''):>10}  {r[4] or ''}"
        )

    logger.info("")
    logger.info("alias 추가 방법:")
    logger.info("  account_maps/bs_accounts.py (또는 is_/cf_/note_) 에 해당 코드의")
    logger.info("  aliases 리스트에 계정과목명 추가 → python run.py parse-reset → parse 재실행")


def cmd_aggregate(args):
    """
    financial_facts → standard_financials 집계.

    사용:
      python run.py aggregate                          # 전체 기업 2015년 이후
      python run.py aggregate --corp 00126380          # 특정 기업
      python run.py aggregate --since 2020             # 2020년 이후만
      python run.py aggregate --dry-run --corp 00126380  # DB 저장 없이 변경 미리보기
    """
    from analyzer.aggregator import aggregate_corp, aggregate_all

    corp_code = getattr(args, "corp", None)
    since     = getattr(args, "since", 2015) or 2015
    dry_run   = getattr(args, "dry_run", False)

    if dry_run:
        logger.info("=== DRY-RUN 모드 — DB에 저장하지 않습니다 ===")

    if corp_code:
        n = aggregate_corp(corp_code, dry_run=dry_run)
        if dry_run:
            logger.success(f"[DRY-RUN] {corp_code} — {n}건 계산 완료 (저장 안 함)")
        else:
            logger.success(f"집계 완료: {corp_code} — {n}건 표준화")
    else:
        aggregate_all(since_fiscal_year=since)


def cmd_analyze(args):
    """
    기업 재무분석 출력 (Bloomberg Terminal 스타일).

    사용:
      python run.py analyze --corp 00126380              # 연결 FY 5개년
      python run.py analyze --corp 00126380 --sep        # 별도재무제표
      python run.py analyze --corp 00126380 --period Q   # 최근 8분기 (YTD)
      python run.py analyze --corp 00126380 --period H   # 최근 4반기
    """
    from analyzer.display.table_view import print_analysis

    corp_code = getattr(args, "corp", None)
    if not corp_code:
        logger.error("--corp CORP_CODE 를 지정하세요.")
        return

    sep        = getattr(args, "sep", False)
    period_arg = getattr(args, "period", "FY") or "FY"
    stmt_type  = "separate" if sep else "consolidated"

    # --period 매핑
    period_mode_map = {
        "FY": ("FY",   5),   # 연간 5개년
        "Q":  ("ALL",  8),   # 최근 8분기(혼합)
        "H":  ("HALF", 4),   # 최근 4반기
    }
    fp, n = period_mode_map.get(period_arg.upper(), ("FY", 5))

    print_analysis(corp_code=corp_code, statement_type=stmt_type, fiscal_period=fp, years=n)


def cmd_sync_prices(args):
    """
    주가 / 시가총액 일괄 수집.

    standard_financials의 FY 결산일 기준으로 pykrx(주가) + DART(상장주식수)를
    조합해 stock_prices 테이블에 캐시 저장.

    사용:
      python run.py sync-prices               # 2020년 이후 전체
      python run.py sync-prices --since 2022  # 2022년 이후
      python run.py sync-prices --corp 00126380
    """
    from analyzer.price_fetcher import sync_prices

    corp_code = getattr(args, "corp", None)
    since     = getattr(args, "since", 2015)  # aggregate 기본값과 통일

    corp_codes = [corp_code] if corp_code else None
    sync_prices(corp_codes=corp_codes, since_year=since)


def cmd_dcf(args):
    """
    DCF 모델 — 내재가치 / 안전마진 계산.

    사용:
      python run.py dcf --corp 00126380
      python run.py dcf --corp 00126380 --growth 8% --wacc 10% --terminal 3%
      python run.py dcf --corp 00126380 --sep
    """
    from analyzer.dcf_engine import run_dcf, print_dcf

    corp_code = getattr(args, "corp", None)
    if not corp_code:
        logger.error("--corp CORP_CODE 를 지정하세요.")
        return

    sep       = getattr(args, "sep", False)
    stmt_type = "separate" if sep else "consolidated"

    def _parse_pct(s):
        if s is None: return None
        s = s.strip().rstrip("%")
        return float(s) / 100.0

    user_growth = _parse_pct(getattr(args, "dcf_growth", None))
    user_wacc   = _parse_pct(getattr(args, "dcf_wacc", None))
    terminal    = float(getattr(args, "dcf_terminal", None) or "2.5") / 100.0

    result = run_dcf(corp_code, user_growth=user_growth, user_wacc=user_wacc,
                     terminal_growth=terminal, statement_type=stmt_type)
    if result:
        print_dcf(result)


def cmd_dividend(args):
    """
    배당 히스토리 분석.

    사용:
      python run.py dividend --corp 00126380
      python run.py dividend --corp 00126380 --years 10
    """
    from analyzer.dividend_engine import analyze_dividend, print_dividend

    corp_code = getattr(args, "corp", None)
    if not corp_code:
        logger.error("--corp CORP_CODE 를 지정하세요.")
        return

    sep       = getattr(args, "sep", False)
    stmt_type = "separate" if sep else "consolidated"
    years     = getattr(args, "div_years", 10) or 10

    summary = analyze_dividend(corp_code, years=years, statement_type=stmt_type)
    if summary:
        print_dividend(summary)


def cmd_screen(args):
    """
    재무 조건으로 기업 스크리닝.

    사용:
      python run.py screen --roe ">15%" --per "<12"
      python run.py screen --piotroski ">=7" --market KOSPI --sort roe
      python run.py screen --revenue-growth ">10%" --debt-ratio "<1" --limit 20
      python run.py screen --roic ">12%" --ev-ebitda "<10" --min-cap 1

    조건 형식:
      ">15%"   ← % 포함 시 비율값(0.15로 변환)
      "<12"    ← % 없으면 그대로 사용
      ">=7"    ← Piotroski 등 정수형

    필터 옵션: --roe --roa --roic --op-margin --net-margin
               --per --pbr --ev-ebitda --pcr --psr
               --revenue-growth --op-growth
               --debt-ratio --current-ratio
               --piotroski --fcf-quality
    """
    from analyzer.screener import screen, print_screen_results

    # 필터 수집
    filter_keys = [
        ("roe", "roe"), ("roa", "roa"), ("roic", "roic"),
        ("op_margin", "op_margin"), ("net_margin", "net_margin"),
        ("ebitda_margin", "ebitda_margin"),
        ("per", "per"), ("pbr", "pbr"), ("ev_ebitda", "ev_ebitda"),
        ("pcr", "pcr"), ("psr", "psr"),
        ("revenue_growth", "revenue_growth"), ("op_growth", "op_growth"),
        ("debt_ratio", "debt_ratio"), ("current_ratio", "current_ratio"),
        ("piotroski", "piotroski"), ("fcf_quality", "fcf_quality"),
    ]
    filters = {}
    for attr_name, filter_key in filter_keys:
        val = getattr(args, attr_name, None)
        if val:
            filters[filter_key] = val

    market  = getattr(args, "market",   None)
    sort_by = getattr(args, "sort",     "roe")
    limit   = getattr(args, "limit",    30) or 30
    year    = getattr(args, "year",     None)
    min_cap = getattr(args, "min_cap",  None)
    asc     = getattr(args, "asc",      False)

    results = screen(
        filters=filters,
        market=market,
        sort_by=sort_by,
        sort_asc=asc,
        limit=limit,
        fiscal_year=year,
        min_market_cap=min_cap,
    )
    print_screen_results(results, filters=filters, sort_by=sort_by, market=market)


def cmd_validate(args):
    """
    standard_financials vs financial_facts 원본 대조.

    사용:
      python run.py validate --corp 00126380
    """
    from collector.db import get_session
    from sqlalchemy import text
    from rich.console import Console
    from rich.table import Table
    from rich import box

    corp_code = getattr(args, "corp", None)
    if not corp_code:
        logger.error("--corp CORP_CODE 를 지정하세요.")
        return

    sep       = getattr(args, "sep", False)
    stmt_type = "separate" if sep else "consolidated"

    with get_session() as session:
        corp = session.execute(text(
            "SELECT corp_name FROM corporations WHERE corp_code = :c"
        ), {"c": corp_code}).fetchone()
        corp_name = corp[0] if corp else corp_code

        sf_rows = session.execute(text("""
            SELECT fiscal_year, fiscal_period, data_quality, rcept_no,
                   revenue, operating_income, net_income, total_assets,
                   total_liabilities, total_equity, cfo, cfi, cff
            FROM standard_financials
            WHERE corp_code = :cc AND statement_type = :st
              AND fiscal_period = 'FY' AND version = 1
            ORDER BY fiscal_year DESC LIMIT 5
        """), {"cc": corp_code, "st": stmt_type}).fetchall()

    if not sf_rows:
        logger.error(f"standard_financials 데이터 없음: {corp_code}")
        return

    console = Console(width=160)
    console.print(f"\n[bold cyan]{corp_name}[/bold cyan] — 원본 대조 (standard_financials vs financial_facts)")

    fields = [
        ("revenue",           "매출액"),
        ("operating_income",  "영업이익"),
        ("net_income",        "당기순이익"),
        ("total_assets",      "총자산"),
        ("total_liabilities", "총부채"),
        ("total_equity",      "총자본"),
        ("cfo",               "영업CF"),
        ("cfi",               "투자CF"),
        ("cff",               "재무CF"),
    ]

    for sf_row in sf_rows:
        fy     = sf_row[0]
        fp     = sf_row[1]
        dq     = sf_row[2]
        rcept  = sf_row[3]
        sf_vals = dict(zip(
            ["revenue", "operating_income", "net_income",
             "total_assets", "total_liabilities", "total_equity",
             "cfo", "cfi", "cff"],
            sf_row[4:]
        ))

        dq_label = {1: "[green]정상[/green]", 2: "[yellow]경고[/yellow]", 3: "[red]오류[/red]"}.get(dq, "—")
        tbl = Table(
            title=f"{fy} {fp}  DQ={dq_label}  rcept={rcept or '—'}",
            box=box.SIMPLE, show_header=True, header_style="bold",
        )
        tbl.add_column("항목",   width=12)
        tbl.add_column("집계값 (억)", justify="right", width=14)
        tbl.add_column("원본값 (억)", justify="right", width=14)
        tbl.add_column("차이(%)", justify="right", width=10)
        tbl.add_column("상태", width=6)

        # BS 항등식 체크
        ta = sf_vals.get("total_assets")
        tl = sf_vals.get("total_liabilities")
        te = sf_vals.get("total_equity")
        if ta and tl is not None and te is not None:
            expected = tl + te
            diff = abs(ta - expected) / abs(ta) * 100 if ta else 0
            status = "[green]OK[/green]" if diff < 1 else "[red]FAIL[/red]"
            tbl.add_row(
                "BS 항등식",
                f"{ta/1e8:,.0f}",
                f"{expected/1e8:,.0f}",
                f"{diff:.2f}%",
                status,
            )

        # 각 항목의 원본 facts 합계와 비교
        if rcept:
            _BS_CODES = {"revenue": "is.revenue", "operating_income": "is.operating_income",
                         "net_income": "is.net_income", "total_assets": "bs.total_assets",
                         "total_liabilities": "bs.total_liabilities", "total_equity": "bs.total_equity",
                         "cfo": "cf.operating", "cfi": "cf.investing", "cff": "cf.financing"}
            suffix = "_C" if stmt_type == "consolidated" else "_S"

            with get_session() as session:
                for col, label in fields:
                    sf_v = sf_vals.get(col)
                    acode = _BS_CODES.get(col)
                    if not acode:
                        continue

                    fact_row = session.execute(text("""
                        SELECT amount FROM financial_facts
                        WHERE rcept_no = :rn AND account_code = :ac
                          AND fiscal_year = :fy AND fiscal_period = :fp
                          AND fs_type = ANY(:fst)
                          AND NOT is_superseded
                        ORDER BY col_index ASC, is_subtotal DESC,
                                 extraction_confidence DESC
                        LIMIT 1
                    """), {
                        "rn": rcept, "ac": acode, "fy": fy, "fp": fp,
                        "fst": [f"BS{suffix}", f"IS{suffix}", f"CF{suffix}"],
                    }).fetchone()

                    fact_v = int(fact_row[0]) if fact_row and fact_row[0] is not None else None

                    sf_str   = f"{sf_v/1e8:,.0f}" if sf_v is not None else "—"
                    fact_str = f"{fact_v/1e8:,.0f}" if fact_v is not None else "—"

                    if sf_v is not None and fact_v is not None and fact_v != 0:
                        diff_pct = abs(sf_v - fact_v) / abs(fact_v) * 100
                        diff_str = f"{diff_pct:.2f}%"
                        status = "[green]OK[/green]" if diff_pct < 1 else "[yellow]!![/yellow]"
                    elif sf_v is None and fact_v is None:
                        diff_str = "—"
                        status = "[dim]N/A[/dim]"
                    else:
                        diff_str = "—"
                        status = "[yellow]??[/yellow]"

                    tbl.add_row(label, sf_str, fact_str, diff_str, status)

        console.print(tbl)


def cmd_compare(args):
    """
    여러 기업의 핵심 재무지표를 나란히 비교.

    사용:
      python run.py compare --compare-corps 00126380,00164779,00164742
      python run.py compare --compare-corps 00126380,00164779 --sep
    """
    from analyzer.comparator import compare, print_compare_results

    corps_str = getattr(args, "compare_corps", None)
    if not corps_str:
        logger.error("--corps CORP1,CORP2,... 를 지정하세요.")
        return

    corp_codes = [c.strip() for c in corps_str.split(",") if c.strip()]
    if len(corp_codes) < 2:
        logger.error("비교할 기업을 2개 이상 지정하세요.")
        return

    sep       = getattr(args, "sep", False)
    stmt_type = "separate" if sep else "consolidated"

    results = compare(corp_codes, statement_type=stmt_type)
    print_compare_results(results)


# ── CLI 파서 ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="DART PDF 수집 시스템",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "command",
        choices=[
            # 수집
            "init", "sync-corps", "sync-filings",
            "download", "list-corps",
            "status", "failed", "reset-failed", "all",
            # 파싱 (Phase 2)
            "parse", "parse-status", "parse-reset", "unknown-accounts",
            # 분석 (Phase 3)
            "aggregate", "analyze", "sync-prices",
            # 스크리닝 (Phase 4)
            "screen", "compare",
            # DCF / 배당 (Phase 5)
            "dcf", "dividend",
            # 검증 (Phase 5A)
            "validate",
            # 유지보수
            "deactivate", "cleanup", "reset-html",
        ],
        help="실행할 명령",
    )
    parser.add_argument(
        "--corp",
        metavar="CORP_CODE",
        help="특정 기업 DART 고유코드 (8자리). sync-filings, download에서 사용.",
    )
    parser.add_argument(
        "--corps",
        metavar="START:END",
        help=(
            "download: list-corps 인덱스 범위로 기업 선택. "
            "예) --corps 0:10 (0~9번째), --corps 20:30, --corps 5 (5번째 1개). "
            "--corp 과 동시 사용 불가."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="download: 최대 처리 건 수",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="sync-filings: last_filing_sync 무시하고 전체 재수집",
    )
    parser.add_argument(
        "--page",
        type=int,
        default=1,
        metavar="N",
        help="list-corps: 페이지 번호 (100개씩, 기본값 1)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        metavar="N",
        help="parse: 병렬 서브프로세스 수 (기본값 1, 권장 4~6)",
    )
    parser.add_argument(
        "--worker-id",
        type=int,
        default=None,
        dest="worker_id",
        metavar="W",
        help=argparse.SUPPRESS,   # 내부용 (parse 서브프로세스가 자동 사용)
    )
    parser.add_argument(
        "--total-workers",
        type=int,
        default=1,
        dest="total_workers",
        metavar="N",
        help=argparse.SUPPRESS,   # 내부용
    )
    parser.add_argument(
        "--since",
        type=int,
        default=2015,
        metavar="YEAR",
        help="aggregate: 집계 시작 연도 (기본값 2015)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="aggregate: DB 저장 없이 변경 내용만 출력 (Side Effect 방어용)",
    )
    parser.add_argument(
        "--sep",
        action="store_true",
        help="analyze: 별도재무제표 출력 (기본: 연결)",
    )
    parser.add_argument(
        "--period",
        default="FY",
        choices=["FY", "Q", "H"],
        help="analyze: 기간 모드 — FY=연간 5개년(기본) / Q=최근 8분기 / H=최근 4반기",
    )
    # ── dcf / dividend 옵션 ─────────────────────────────────────────
    parser.add_argument("--growth",   metavar="PCT", dest="dcf_growth",
                        help="dcf: FCF 성장률 수동 입력 (예: 8% 또는 8)")
    parser.add_argument("--wacc",     metavar="PCT", dest="dcf_wacc",
                        help="dcf: WACC 수동 입력 (예: 10%)")
    parser.add_argument("--terminal", metavar="PCT", dest="dcf_terminal", default="2.5",
                        help="dcf: 영구성장률 (기본 2.5%%)")
    parser.add_argument("--div-years", type=int, metavar="N", dest="div_years", default=10,
                        help="dividend: 조회 연수 (기본 10)")
    # ── screen 옵션 ─────────────────────────────────────────────────
    parser.add_argument("--roe",            metavar="COND", help="ROE 조건 (예: \">15%\")")
    parser.add_argument("--roa",            metavar="COND", help="ROA 조건")
    parser.add_argument("--roic",           metavar="COND", help="ROIC 조건")
    parser.add_argument("--op-margin",      metavar="COND", dest="op_margin",    help="영업이익률 조건")
    parser.add_argument("--net-margin",     metavar="COND", dest="net_margin",   help="순이익률 조건")
    parser.add_argument("--ebitda-margin",  metavar="COND", dest="ebitda_margin",help="EBITDA 마진 조건")
    parser.add_argument("--per",            metavar="COND", help="PER 조건 (예: \"<12\")")
    parser.add_argument("--pbr",            metavar="COND", help="PBR 조건")
    parser.add_argument("--ev-ebitda",      metavar="COND", dest="ev_ebitda",    help="EV/EBITDA 조건")
    parser.add_argument("--pcr",            metavar="COND", help="PCR 조건")
    parser.add_argument("--psr",            metavar="COND", help="PSR 조건")
    parser.add_argument("--revenue-growth", metavar="COND", dest="revenue_growth",help="매출 성장률 조건")
    parser.add_argument("--op-growth",      metavar="COND", dest="op_growth",    help="영업이익 성장률 조건")
    parser.add_argument("--debt-ratio",     metavar="COND", dest="debt_ratio",   help="부채비율 조건")
    parser.add_argument("--current-ratio",  metavar="COND", dest="current_ratio",help="유동비율 조건")
    parser.add_argument("--piotroski",      metavar="COND", help="Piotroski F-Score 조건 (예: \">=7\")")
    parser.add_argument("--fcf-quality",    metavar="COND", dest="fcf_quality",  help="FCF품질(CFO/순이익) 조건")
    parser.add_argument("--market",         choices=["KOSPI", "KOSDAQ"],          help="시장 필터")
    parser.add_argument("--sort",           metavar="FIELD", default="roe",       help="정렬 기준 (기본: roe)")
    parser.add_argument("--asc",            action="store_true",                   help="오름차순 정렬 (기본: 내림차순)")
    parser.add_argument("--year",           type=int, metavar="YEAR",             help="기준 연도 (기본: 최신)")
    parser.add_argument("--min-cap",        type=float, dest="min_cap", metavar="조",
                        help="최소 시가총액 (조원, 예: 1)")
    # ── compare 옵션 ────────────────────────────────────────────────
    parser.add_argument("--compare-corps",  metavar="CORP1,CORP2,...",
                        dest="compare_corps",
                        help="compare: 비교할 기업 DART 코드 콤마 구분")
    parser.add_argument(
        "--partial",
        action="store_true",
        dest="partial",
        help="parse-reset: 부분 파싱(partial) 파일만 재시도 대상으로 등록",
    )
    parser.add_argument(
        "--track-b",
        action="store_true",
        dest="track_b",
        help="parse-reset: Track B 파싱 파일 전체를 재시도 대상으로 등록 (새 파서 코드로 재분류)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all",
        help="parse-reset: 성공/부분/실패 포함 전체 파일을 재시도 대상으로 등록",
    )

    args = parser.parse_args()

    # --corp / --corps 동시 사용 방지
    if getattr(args, "corp", None) and getattr(args, "corps", None):
        parser.error("--corp 과 --corps 는 동시에 사용할 수 없습니다.")

    dispatch = {
        # 수집
        "init":             cmd_init,
        "sync-corps":       cmd_sync_corps,
        "sync-filings":     cmd_sync_filings,
        "download":         cmd_download,
        "list-corps":       cmd_list_corps,
        "status":           cmd_status,
        "failed":           cmd_failed,
        "reset-failed":     cmd_reset_failed,
        "all":              cmd_all,
        # 파싱 (Phase 2)
        "parse":            cmd_parse,
        "parse-status":     cmd_parse_status,
        "parse-reset":      cmd_parse_reset,
        "unknown-accounts": cmd_unknown_accounts,
        # 분석 (Phase 3)
        "aggregate":        cmd_aggregate,
        "analyze":          cmd_analyze,
        "sync-prices":      cmd_sync_prices,
        # 스크리닝 (Phase 4)
        "screen":           cmd_screen,
        "compare":          cmd_compare,
        # DCF / 배당 (Phase 5)
        "dcf":              cmd_dcf,
        "dividend":         cmd_dividend,
        # 검증 (Phase 5A)
        "validate":         cmd_validate,
        # 유지보수
        "deactivate":       cmd_deactivate,
        "cleanup":          cmd_cleanup,
        "reset-html":       cmd_reset_html,
    }

    try:
        dispatch[args.command](args)
    except KeyboardInterrupt:
        logger.warning("사용자 중단 (Ctrl+C). 진행 상태는 DB에 저장되어 있습니다.")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"오류 발생: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
