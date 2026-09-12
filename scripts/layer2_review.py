#!/usr/bin/env python
"""계층2 재적재 + 원문대조 검토 캠페인 CLI (사용자 결정 2026-09-08).

설계: `docs/plans/layer2_reload_review_campaign_design_2026-09-08.md`
진행 트래킹: `docs/plans/layer2_reload_review_campaign_2026-09-08.md`

## 무엇을 하는가
현행 파서로 보고서를 **다시 파싱해 `report_lines` 에 적재**하고, 적재된 결과를
**보고서 원문과 눈으로 대조할 수 있는 CSV** 로 뽑아 사용자에게 넘긴다. 사용자가
`pass` 하면 다음 1건, `fail` 하면 **루프를 세우고** 원인 규명으로 넘어간다.

## 사용법
    python scripts/layer2_review.py init --top 50      # 시총 상위 50사 큐 생성
    python scripts/layer2_review.py next               # 1건 재적재 + 검산 + CSV
    python scripts/layer2_review.py pass               # 통과 → CSV 삭제 + 자동으로 다음 1건
    python scripts/layer2_review.py fail --note "..."  # 불일치 → 루프 정지 + 트리아지
    python scripts/layer2_review.py redo               # 파서 수정 후 같은 건 재실행
    python scripts/layer2_review.py skip --note "..."  # 검토 제외
    python scripts/layer2_review.py finish-corp        # 회사 종료 → std_v3 재빌드
    python scripts/layer2_review.py status             # 진척

## 결정된 규칙 (설계 문서 §"확정된 결정")
- 정정본은 **덮어쓰지 않는다.** 계층2 는 R3 대로 모든 버전을 rcept 단위로 전사하고,
  정정본도 원본과 동등한 **별개 검토 대상 1건**이다.
- 회사 순서 = **시가총액 큰 순**, 회사 안에서는 **최신 → 과거**(같은 기간 안에서는
  최초등록본 → 정정본).
- FAIL 이면 **멈춘다.** 원인 규명 후 파서를 고치고 `redo`.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text, update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from collector.db import engine, get_session
from collector.models import Layer2ReviewQueue
from fin2.audit import layer2_selfcheck as sc
from fin2.extract import review_csv
from fin2.extract.report_lines import (extract_report_lines, store_report_lines,
                                       store_report_tables)

# 회사 안 검토 순서의 기간 정렬 — 달력 순서(Q1 → H1 → Q3 → FY)를 역으로 쓴다.
_PERIOD_RANK = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4}

# ────────────────────────────────────────────────────────────────────────────
# init — 대상 큐 생성
# ────────────────────────────────────────────────────────────────────────────
# 시가총액 = **최신 종가 × 발행주식총수**.
#
# ★주식수를 `stock_prices.shares_out` 이 아니라 `report_shares_outstanding` 에서 가져온다.
#   전자는 일부 종목이 **1000배 부풀려져** 있다(2026-09-09 실측: 네오팜 16,027,989,000 vs
#   DART 원문 16,027,989 = 정확히 ×1000. 조선내화·일승·한일철강도 같은 증상. 삼성전자·
#   SK하이닉스 등 대다수는 정상이라 **비균일 오염**이다). 그대로 쓰면 소형주가 시총 3위로
#   올라와 캠페인 순서가 통째로 틀어진다.
#   후자는 이 프로젝트가 DART 원문("주식의 총수 등")에서 직접 파싱한 값이고
#   (`fin2/extract/shares_transcribe.py`), 활성 유니버스 2,531사 중 2,528사를 덮는다.
#   ※`stock_prices.shares_out` 의 ×1000 오염 자체는 이 캠페인 범위 밖 — 별건으로 기록.
#
# 종가는 market_cap 유무와 무관하게 **가장 최근 거래일**을 쓴다.
_UNIVERSE_SQL = text(
    """
    WITH last_close AS (
        SELECT DISTINCT ON (stock_code) stock_code, close_price, trade_date
        FROM stock_prices
        WHERE close_price IS NOT NULL
        ORDER BY stock_code, trade_date DESC
    ),
    last_shares AS (
        SELECT DISTINCT ON (corp_code) corp_code, shares_out
        FROM report_shares_outstanding
        ORDER BY corp_code, as_of_date DESC NULLS LAST, rcept_no DESC
    )
    SELECT c.corp_code, c.corp_name, c.market,
           lc.close_price::bigint * ls.shares_out AS mcap
    FROM corporations c
    LEFT JOIN last_close  lc ON lc.stock_code = c.stock_code
    LEFT JOIN last_shares ls ON ls.corp_code  = c.corp_code
    WHERE c.is_active
      AND c.stock_code IS NOT NULL
      AND c.stock_code NOT LIKE '9%'          -- R7 국내상장 외국기업 제외
      AND c.coverage_class = 'periodic'
    ORDER BY mcap DESC NULLS LAST, c.corp_code
    """
)

# ★is_final 로 거르지 않는다 — R3/`collector/filing_select.py`. 정정본도 대상이다.
# ★fiscal_year_min — 시대 4단계 분할(docs/plans/layer2_review_staged_screening_design_
#   2026-09-11.md §1) 지원. NULL 이면 전체 기간(기존 동작 무변경).
_FILINGS_SQL = text(
    """
    SELECT f.rcept_no, f.fiscal_year, f.fiscal_period, f.report_type, f.filed_at,
           f.report_nm, f.is_amendment, f.is_attachment_amendment
    FROM filings f
    WHERE f.corp_code = :c
      AND f.report_type IN ('annual', 'half', 'quarter')
      AND (CAST(:fy_min AS smallint) IS NULL OR f.fiscal_year >= :fy_min)
    """
)


def cmd_init(args) -> None:
    """시총순 × 회사내 최신→과거로 큐를 채운다.

    ★멱등 — 이미 있는 rcept 는 순서 정보(corp_rank/seq_in_corp)만 갱신하고
      **사람 판단(status/note/reviewed_at)은 건드리지 않는다** (ReconCandidate 관례).
    """
    Layer2ReviewQueue.__table__.create(bind=engine, checkfirst=True)
    added = updated = 0
    with get_session() as session:
        # ★순위는 **전체 유니버스**에서 매긴 뒤 필터한다 — `--corp` 로 한 회사만 넣을 때도
        #   그 회사의 진짜 시총 순위가 유지돼야 진행 순서(corp_rank)가 일관된다.
        #   (처음엔 필터 후 enumerate 해서 `--corp` 로 넣은 회사가 전부 1위로 찍혔다.)
        universe = session.execute(_UNIVERSE_SQL).fetchall()
        ranked = list(enumerate(universe, start=1))
        if args.corp:
            wanted = set(args.corp.split(","))
            ranked = [(i, c) for i, c in ranked if c.corp_code in wanted]
        elif args.top:
            ranked = ranked[: args.top]
        corps = [c for _, c in ranked]

        for rank, corp in ranked:
            filings = session.execute(
                _FILINGS_SQL, {"c": corp.corp_code, "fy_min": args.fiscal_year_min}).fetchall()
            if not filings:
                continue
            ordered = sorted(
                filings,
                key=lambda f: (-(f.fiscal_year or 0),
                               -_PERIOD_RANK.get(f.fiscal_period or "", 0),
                               f.filed_at or datetime.min.date(),
                               f.rcept_no),
            )
            rows = [{
                "rcept_no": f.rcept_no, "corp_code": corp.corp_code,
                "corp_name": corp.corp_name, "market": corp.market,
                "corp_rank": rank, "market_cap": corp.mcap, "seq_in_corp": seq,
                "fiscal_year": f.fiscal_year, "fiscal_period": f.fiscal_period,
                "report_type": f.report_type, "filed_at": f.filed_at,
                "report_nm": f.report_nm, "is_amendment": bool(f.is_amendment),
                "is_attachment_amendment": bool(f.is_attachment_amendment),
                "status": "pending",
            } for seq, f in enumerate(ordered, start=1)]

            stmt = pg_insert(Layer2ReviewQueue).values(rows)
            # 사람이 남긴 컬럼(status/note/reviewed_at)과 기계 산출(checks/csv_path 등)은
            # 갱신 대상에서 뺀다 — init 재실행이 진행 상황을 되감으면 안 된다.
            stmt = stmt.on_conflict_do_update(
                index_elements=[Layer2ReviewQueue.rcept_no],
                set_={k: stmt.excluded[k] for k in (
                    "corp_name", "market", "corp_rank", "market_cap", "seq_in_corp",
                    "fiscal_year", "fiscal_period", "report_type", "filed_at",
                    "report_nm", "is_amendment", "is_attachment_amendment")},
            )
            before = session.execute(
                text("SELECT count(*) FROM layer2_review_queue WHERE corp_code=:c"),
                {"c": corp.corp_code}).scalar_one()
            session.execute(stmt)
            after = session.execute(
                text("SELECT count(*) FROM layer2_review_queue WHERE corp_code=:c"),
                {"c": corp.corp_code}).scalar_one()
            added += after - before
            updated += len(rows) - (after - before)
        session.commit()
    logger.success(f"[init] 기업 {len(corps)}사 — 신규 {added:,}건, 갱신 {updated:,}건")


# ────────────────────────────────────────────────────────────────────────────
# 대상 선택
# ────────────────────────────────────────────────────────────────────────────
# ★2026-09-11(사용자 결정, 시대 게이트 도입) — docs/plans/layer2_review_staged_
#   screening_design_2026-09-11.md §1의 4단계를 **전역 우선순위**로 쓴다: 회사
#   진행순서(corp_rank)보다 시대(era_rank)가 먼저다 — "모든 회사의 2015+ 를 전부
#   끝낸 뒤에야 2011~2014 로, 그 다음 2007~2010, 그 다음 1999~2006" 로 넘어간다.
#   (같은 날 앞선 결정 — "삼성전자는 끝까지 계속" — 을 뒤집음. 회사 하나를
#   끝까지 보는 옛 방식 대신 기간 중요도 우선으로 확정.)
#   구현은 ORDER BY 맨 앞에 CASE 식 하나만 추가하면 된다 — "그 시대에 pending 이
#   하나라도 남아있으면 그 시대에서만 고른다"는 로 별도 상태 없이 이 정렬만으로
#   자동 성립(그 시대가 다 떨어지면 다음 시대 행이 자연히 최소값이 된다).
_ERA_RANK_SQL = """
    CASE
        WHEN fiscal_year >= 2015 THEN 1
        WHEN fiscal_year >= 2011 THEN 2
        WHEN fiscal_year >= 2007 THEN 3
        WHEN fiscal_year IS NOT NULL THEN 4
        ELSE 5
    END
"""


def _pick(session, rcept_no: str | None, *, statuses: tuple[str, ...]):
    """진행 순서 `(era_rank, corp_rank, screen_severity, seq_in_corp)` 로 다음 대상 1건.
    `rcept_no` 지정 시 그것만.

    ★era_rank(시대 게이트)가 최우선 — 2015+ 전체 회사를 다 끝내야 2011~2014 로
      넘어간다(위 상수 참고). 그 안에서는 시총순(corp_rank), 그 안에서는 사전
      스크리닝(`layer2_screen.py`) 심각도 큰 순, 마지막에 회사 내 순번(seq_in_corp).
      screen_severity 가 NULL(미스크리닝)이면 0과 동급으로 취급.

    ★어느 경로든 **RowMapping(dict 처럼 쓰는 것)** 으로 통일한다 — 한때 rcept 지정 경로만
      ORM 객체를 돌려줘 호출부에서 `item["..."]` 가 TypeError 로 터졌다.
    """
    if rcept_no:
        return session.execute(
            text("SELECT * FROM layer2_review_queue WHERE rcept_no = :r"),
            {"r": rcept_no}).mappings().first()
    return session.execute(
        text(f"""SELECT * FROM layer2_review_queue
                WHERE status = ANY(:st)
                ORDER BY {_ERA_RANK_SQL},
                         corp_rank NULLS LAST,
                         COALESCE(screen_severity, 0) DESC,
                         seq_in_corp, rcept_no
                LIMIT 1"""),
        {"st": list(statuses)}).mappings().first()


def _current(session):
    """가장 최근에 재적재돼 사람 검토를 기다리는 건(= `pass`/`fail` 의 기본 대상)."""
    return session.execute(
        text("""SELECT * FROM layer2_review_queue
                WHERE status = 'reloaded'
                ORDER BY reloaded_at DESC NULLS LAST LIMIT 1""")).mappings().first()


# ────────────────────────────────────────────────────────────────────────────
# 재적재
# ────────────────────────────────────────────────────────────────────────────
_SOURCE_SQL = text(
    """
    SELECT file_type, file_path
    FROM download_tasks
    WHERE rcept_no = :r AND status = 'completed' AND file_path IS NOT NULL
    ORDER BY CASE file_type WHEN 'xml' THEN 0 WHEN 'pdf' THEN 1 ELSE 2 END
    """
)


def _resolve_source(session, rcept_no: str) -> tuple[str, str | None]:
    """소스 라우팅 — (source_kind, file_path). 파일이 실제로 존재하는 것만 채택한다."""
    for row in session.execute(_SOURCE_SQL, {"r": rcept_no}).fetchall():
        if Path(row.file_path).exists():
            return (row.file_type or "unknown"), row.file_path
    return "none", None


def _reload_one(session, item) -> tuple[str, str | None]:
    """재파싱 + 적재. 반환 (source_kind, 실패사유 or None).

    ★`store_report_lines` 와 `store_report_tables` 를 **반드시 같이** 부른다 —
      `run.py::cmd_extract_lines` 는 후자를 부르지 않아 검토 CSV 에 찍을 단위 선언
      원문(`report_tables.unit_decl_raw`)이 갱신되지 않는다(설계 문서 §2).
    ★`store_report_lines` 의 manual 보호가드(report_lines.py:1373)는 그대로 둔다 —
      사람이 타이핑해 넣은 값을 이 캠페인이 조용히 덮어쓰면 안 된다. ValueError 는
      `blocked` 로 흡수한다.
    """
    kind, path = _resolve_source(session, item["rcept_no"])
    if kind == "none":
        return kind, "원문 파일 없음(다운로드 미완/소실)"
    if kind != "xml":
        # PDF/HTML 복구 경로는 DART 웹 스크래핑이 필요하고 값조작 결함 이력이 있다
        # (docs/qa/report_lines_row_count_outlier_scan_2026-09-08.md Pattern A).
        # 이 캠페인의 1차 대상(시총 상위 = 2015+ XML)에는 사실상 안 나온다.
        return kind, (f"{kind} 소스는 이 CLI 가 자동 재적재하지 않는다 — "
                      f"collector/pdf_lines_sync.py::sync_pdf_recovery 로 별도 처리")
    try:
        lines = extract_report_lines(
            path, rcept_no=item["rcept_no"], corp_code=item["corp_code"],
            report_fiscal_year=item["fiscal_year"],
            report_fiscal_period=item["fiscal_period"], include_notes=False)
    except (FileNotFoundError, OSError) as exc:
        return kind, f"원문 읽기 실패: {type(exc).__name__}: {exc}"
    if not lines:
        return kind, "추출 0행(보류) — 섹션/표 미검출"
    try:
        store_report_lines(session, item["rcept_no"], lines)
        store_report_tables(session, item["rcept_no"], lines)
    except ValueError as exc:      # manual 보호가드
        session.rollback()
        return kind, str(exc)
    return kind, None


def _mark(session, rcept_no: str, **fields) -> None:
    """★raw text SQL 이 아니라 ORM update 를 쓴다 — `n_lines_by_scope`/`checks` 가 JSONB 라
    psycopg2 가 dict/list 를 그대로는 못 넘긴다("can't adapt type 'dict'"). ORM 경로는
    컬럼 타입을 알고 있어 직렬화를 대신 해준다."""
    session.execute(
        sa_update(Layer2ReviewQueue)
        .where(Layer2ReviewQueue.rcept_no == rcept_no)
        .values(**fields))


def _delete_review_csv(csv_path: str | None) -> None:
    """PASS 확정된 건의 검토 CSV 는 로컬 작업 파일일 뿐이라 더 볼 일이 없다(DB 판정이
    영구 기록이고, `layer2_review/` 는 `.gitignore` 대상). 쌓아두면 2,500개사 규모에서
    디스크만 채운다. 파일이 이미 없어도(재실행·수동 정리 등) 조용히 넘어간다."""
    if not csv_path:
        return
    path = Path(csv_path)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        print(f"  ⚠ CSV 삭제 실패({path}): {exc}")
    else:
        print(f"  🗑 CSV 삭제: {path}")


def _run_target(session, item, *, root: Path | None = None) -> dict:
    """1건 재적재 → 검산 → CSV. 큐 상태까지 갱신하고 요약 dict 를 돌려준다."""
    now = datetime.now()
    kind, err = _reload_one(session, item)
    if err:
        _mark(session, item["rcept_no"], status="blocked", source_kind=kind,
              reloaded_at=now, note=err)
        session.commit()
        return {"blocked": True, "source_kind": kind, "reason": err}

    rows = sc.load_rows(session, item["rcept_no"])
    checks = sc.run_checks(session, item["rcept_no"], corp_code=item["corp_code"],
                           fiscal_period=item["fiscal_period"], rows=rows)
    path, counts = review_csv.generate(
        session, rcept_no=item["rcept_no"], corp_code=item["corp_code"],
        corp_name=item["corp_name"], market=item["market"],
        corp_rank=item["corp_rank"], report_type=item["report_type"],
        report_nm=item["report_nm"], fiscal_year=item["fiscal_year"],
        fiscal_period=item["fiscal_period"], filed_at=item["filed_at"],
        source_kind=kind, checks=checks, reloaded_at=now, root=root, db_rows=rows)

    n_lines = len(rows)
    _mark(session, item["rcept_no"], status="reloaded", source_kind=kind,
          reloaded_at=now, n_lines=n_lines, n_lines_by_scope=counts,
          check_status=sc.rollup(checks),
          checks=[c.as_dict() for c in checks], csv_path=str(path))
    session.commit()
    return {"blocked": False, "source_kind": kind, "n_lines": n_lines,
            "counts": counts, "checks": checks, "csv_path": path}


# ────────────────────────────────────────────────────────────────────────────
# 출력
# ────────────────────────────────────────────────────────────────────────────
def _print_target(item, result: dict) -> None:
    """사용자 접점. ★DART 링크와 CSV 경로를 **항상 같이** 보여준다
    (메모리 feedback-manual-review-show-dart-link-and-csv-path)."""
    amend = ""
    if item["is_amendment"]:
        amend = " [기재정정]"
    elif item["is_attachment_amendment"]:
        amend = " [첨부정정]"
    print()
    print(f"[시총 {item['corp_rank']}위 {item['corp_name']} {item['corp_code']}]  "
          f"회사 내 {item['seq_in_corp']}번째")
    print(f"  보고서  {item['fiscal_year']}{item['fiscal_period']} "
          f"{item['report_type']}{amend}  r{item['rcept_no']}  ({item['filed_at']})")
    print(f"  DART   {review_csv.DART_VIEWER.format(rcept=item['rcept_no'])}")

    if result["blocked"]:
        print(f"  ⛔ 재적재 불가 ({result['source_kind']}) — {result['reason']}")
        print("     status=blocked 로 기록했습니다. `next` 로 다음 건으로 넘어갑니다.")
        return

    print(f"  CSV    {result['csv_path']}")
    counts = result["counts"]
    parts = []
    for basis, ko in (("separate", "별도"), ("consolidated", "연결")):
        if counts.get(basis):
            parts.append(f"{ko} " + " / ".join(
                f"{s} {counts[basis].get(s, 0)}" for s in ("BS", "IS", "CF")))
    print(f"  적재    {'  ·  '.join(parts) or '0행'}  (총 {result['n_lines']:,}행)")

    fails = sc.suspects(result["checks"])
    if not fails:
        print("  검산    ✅ 이상 없음")
    else:
        print(f"  검산    ⚠ 의심 {len(fails)}건")
        for c in fails:
            print(f"           · [{c.grade}] {c.scope} {c.code} — {c.message}")
    print()
    print(f'  open "{result["csv_path"]}"')
    print()
    print("  → CSV 와 DART 원문을 대조한 뒤:")
    print("       python scripts/layer2_review.py pass")
    print('       python scripts/layer2_review.py fail --note "무엇이 어떻게 틀렸는지"')
    print()


def _print_triage(item) -> None:
    """FAIL 시 원인 규명 진입점 — 전부 기존 `--rcept` 지원 스크립트."""
    r = item["rcept_no"]
    print()
    print("  ── 원인 규명 진입점 ──")
    print(f"  python scripts/verify_report_lines.py --rcept {r}          # 원문 face ↔ DB 다중집합 대조")
    print(f"  python scripts/layer2_fidelity_roundtrip.py --rcept {r}    # DB 값이 원문에 실재하는가(날조 검사)")
    print(f"  python scripts/layer2_forward_cells.py --rcept {r}         # 원문 셀이 왜 떨어졌는가(드롭 사유)")
    print(f"  python scripts/audit_unit_declarations.py --rcept {r}      # 표별 단위 선언")
    print()
    print("  파서를 고친 뒤:  python scripts/layer2_review.py redo")
    print()


# ────────────────────────────────────────────────────────────────────────────
# 서브커맨드
# ────────────────────────────────────────────────────────────────────────────
def cmd_next(args) -> None:
    root = Path(args.root) if args.root else None
    with get_session() as session:
        # --rcept 는 특정 건 지목이라 '미판정 건 있음' 가드를 건너뛴다.
        pending = None if (args.rcept or args.force) else _current(session)
        if pending is not None:
            print("\n⚠ 아직 검토가 끝나지 않은 건이 있습니다 "
                  f"(r{pending['rcept_no']}, status=reloaded).")
            print("  pass / fail 로 판정하거나, --force 로 건너뛰고 다음 건을 받으세요.")
            _print_target(pending, {"blocked": False, "source_kind": pending["source_kind"],
                                    "n_lines": pending["n_lines"] or 0,
                                    "counts": pending["n_lines_by_scope"] or {},
                                    "checks": [sc.CheckResult(**c) for c in (pending["checks"] or [])],
                                    "csv_path": pending["csv_path"]})
            return
        # blocked 는 자동으로 건너뛴다 — 사람이 할 수 있는 게 없다.
        while True:
            item = _pick(session, args.rcept, statuses=("pending",))
            if item is None:
                print("\n✅ 대기 중인 대상이 없습니다. `init` 로 큐를 넓히거나 `status` 로 확인하세요.")
                return
            result = _run_target(session, item, root=root)
            _print_target(item, result)
            if not result["blocked"] or args.rcept:
                return


def cmd_pass(args) -> None:
    with get_session() as session:
        item = _pick(session, args.rcept, statuses=("reloaded",)) if args.rcept else _current(session)
        if item is None:
            print("판정할 대상이 없습니다 (status=reloaded 인 건 없음).")
            return
        _mark(session, item["rcept_no"], status="pass", reviewed_at=datetime.now(),
              note=args.note)
        session.commit()
        print(f"✅ PASS  r{item['rcept_no']}  {item['corp_name']} "
              f"{item['fiscal_year']}{item['fiscal_period']}")
        _delete_review_csv(item["csv_path"])
        remaining = session.execute(
            text("""SELECT count(*) FROM layer2_review_queue
                    WHERE corp_code = :c AND status IN ('pending','reloaded')"""),
            {"c": item["corp_code"]}).scalar_one()
        if remaining == 0:
            print(f"\n🎉 {item['corp_name']} 전 보고서 검토 완료.")
            print("   런북 B5 — 하류 반영이 남았습니다:")
            print("       python scripts/layer2_review.py finish-corp "
                  f"--corp {item['corp_code']}")
            return
    if not args.no_advance:
        cmd_next(argparse.Namespace(rcept=None, root=args.root, force=False))


def cmd_fail(args) -> None:
    with get_session() as session:
        item = _pick(session, args.rcept, statuses=("reloaded",)) if args.rcept else _current(session)
        if item is None:
            print("판정할 대상이 없습니다 (status=reloaded 인 건 없음).")
            return
        _mark(session, item["rcept_no"], status="fail", reviewed_at=datetime.now(),
              note=args.note)
        session.commit()
        print(f"\n❌ FAIL  r{item['rcept_no']}  {item['corp_name']} "
              f"{item['fiscal_year']}{item['fiscal_period']}")
        print(f"  사유: {args.note}")
        print("\n★ 루프를 정지합니다 (사용자 결정 2026-09-08: FAIL 이면 원인부터 규명).")
        _print_triage(item)


def cmd_redo(args) -> None:
    """파서를 고친 뒤 같은 대상만 재적재 → 재검산 → CSV 재생성."""
    root = Path(args.root) if args.root else None
    with get_session() as session:
        if args.rcept:
            item = session.execute(
                text("SELECT * FROM layer2_review_queue WHERE rcept_no = :r"),
                {"r": args.rcept}).mappings().first()
        else:
            item = session.execute(
                text("""SELECT * FROM layer2_review_queue
                        WHERE status IN ('fail','reloaded','blocked')
                        ORDER BY reviewed_at DESC NULLS LAST, reloaded_at DESC NULLS LAST
                        LIMIT 1""")).mappings().first()
        if item is None:
            print("재실행할 대상이 없습니다.")
            return
        result = _run_target(session, item, root=root)
        _print_target(item, result)


def cmd_skip(args) -> None:
    with get_session() as session:
        item = _pick(session, args.rcept, statuses=("pending", "reloaded", "blocked")) \
            if args.rcept else _current(session)
        if item is None:
            print("건너뛸 대상이 없습니다.")
            return
        _mark(session, item["rcept_no"], status="skipped", reviewed_at=datetime.now(),
              note=args.note)
        session.commit()
        print(f"⏭  SKIP  r{item['rcept_no']} — {args.note}")


def cmd_finish_corp(args) -> None:
    """회사 1곳 검토 종료 → std_v3 재빌드 + calendar_v3 재동기화.

    ★런북 `docs/runbook_new_parser_pipeline_integration.md` B5 — `report_lines` 를 바꾼 뒤
      같은 corp 로 `calendarize_corp_v3()` 를 다시 안 돌리면 예전 std_v3 행을 가리키던
      달력분기가 유령행으로 남는다(`dq_assertions.py::calendar_orphan_cq`, ERROR).
    """
    from fin2.standardize.calendar_v3 import calendarize_corp_v3
    # 유령행 판정식은 dq_assertions 가 쓰는 것을 **그대로 재사용**한다 — 여기서 다시 쓰면
    # 게이트와 다른 판정을 하게 되고, "여기선 0건인데 게이트는 ERROR" 가 된다.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from diag_calendar_orphans import _ORPHAN_PRED

    with get_session() as session:
        corp = args.corp
        if not corp:
            row = session.execute(
                text("""SELECT corp_code, corp_name FROM layer2_review_queue
                        GROUP BY corp_code, corp_name
                        HAVING count(*) FILTER (WHERE status IN ('pending','reloaded')) = 0
                           AND count(*) FILTER (WHERE status = 'pass') > 0
                        ORDER BY min(corp_rank) LIMIT 1""")).first()
            if row is None:
                print("검토가 끝난 회사가 없습니다 (--corp 로 직접 지정할 수 있습니다).")
                return
            corp = row.corp_code
        left = session.execute(
            text("""SELECT count(*) FROM layer2_review_queue
                    WHERE corp_code = :c AND status IN ('pending','reloaded')"""),
            {"c": corp}).scalar_one()
        if left and not args.force:
            print(f"⚠ {corp} 은 아직 {left}건이 미검토입니다. --force 로 강행할 수 있습니다.")
            return

    print(f"[finish-corp] {corp} — std_v3 재빌드")
    rc = subprocess.run(
        [sys.executable, "scripts/build_std_v3.py", "--corp", corp,
         "--year-min", str(args.year_min)],
        cwd=str(Path(__file__).resolve().parents[1])).returncode
    if rc != 0:
        print(f"❌ build_std_v3.py 실패 (rc={rc}) — calendarize 를 건너뜁니다.")
        sys.exit(rc)

    with get_session() as session:
        n = calendarize_corp_v3(session, corp)
        session.commit()
        print(f"[finish-corp] calendarize_corp_v3({corp}) → {n:,}행")
        orphans = session.execute(
            text(f"""SELECT count(*) FROM std_financials_calendar cf
                     WHERE cf.corp_code = :c AND {_ORPHAN_PRED}"""),
            {"c": corp}).scalar_one()
        print(f"[finish-corp] calendar_orphan_cq({corp}) = {orphans}건"
              + ("  ✅" if orphans == 0 else "  ⚠ 확인 필요"))


def cmd_status(args) -> None:
    with get_session() as session:
        print("\n── 전체 ──")
        for r in session.execute(text(
                """SELECT status, count(*) n FROM layer2_review_queue
                   GROUP BY 1 ORDER BY 2 DESC""")).fetchall():
            print(f"  {r.status:9s} {r.n:>8,}")
        print("\n── 회사별 (시총순, 상위 20) ──")
        rows = session.execute(text(
            """SELECT corp_rank, corp_code, corp_name,
                      count(*) AS total,
                      count(*) FILTER (WHERE status = 'pass')    AS n_pass,
                      count(*) FILTER (WHERE status = 'fail')    AS n_fail,
                      count(*) FILTER (WHERE status = 'blocked') AS n_blocked,
                      count(*) FILTER (WHERE status = 'skipped') AS n_skip
               FROM layer2_review_queue
               GROUP BY 1, 2, 3 ORDER BY corp_rank NULLS LAST LIMIT 20""")).fetchall()
        print(f"  {'순위':>4} {'회사':<16} {'통과':>6}/{'전체':<6} {'실패':>4} {'불가':>4} {'제외':>4}")
        for r in rows:
            print(f"  {r.corp_rank or 0:>4} {(r.corp_name or '')[:16]:<16} "
                  f"{r.n_pass:>6,}/{r.total:<6,} {r.n_fail:>4} {r.n_blocked:>4} {r.n_skip:>4}")
        cur = _current(session)
        if cur is not None:
            print(f"\n  검토 대기 중: r{cur['rcept_no']} {cur['corp_name']} "
                  f"{cur['fiscal_year']}{cur['fiscal_period']}")
            print(f"  CSV: {cur['csv_path']}")
        print()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="시총순으로 검토 큐 생성/갱신")
    p.add_argument("--top", type=int, default=50, help="시총 상위 N사 (기본 50, 0=전체)")
    p.add_argument("--corp", help="쉼표구분 corp_code — 지정 시 그 회사만")
    p.add_argument("--fiscal-year-min", type=int, default=None,
                   help="이 연도 이상 필링만 큐에 넣음(시대 구분 1단계=2015)")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("next", help="다음 1건 재적재 + 검산 + CSV 생성")
    p.add_argument("--rcept", help="특정 rcept 만")
    p.add_argument("--root", help="CSV 루트 디렉터리 (기본 layer2_review/)")
    p.add_argument("--force", action="store_true", help="미판정 건이 있어도 다음으로")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("pass", help="원문대조 통과 → 다음 1건")
    p.add_argument("--rcept")
    p.add_argument("--note")
    p.add_argument("--root")
    p.add_argument("--no-advance", action="store_true", help="다음 건을 자동으로 받지 않음")
    p.set_defaults(func=cmd_pass)

    p = sub.add_parser("fail", help="불일치 → 루프 정지 + 트리아지 진입점")
    p.add_argument("--rcept")
    p.add_argument("--note", required=True, help="무엇이 어떻게 틀렸는지")
    p.set_defaults(func=cmd_fail)

    p = sub.add_parser("redo", help="파서 수정 후 같은 건 재적재")
    p.add_argument("--rcept")
    p.add_argument("--root")
    p.set_defaults(func=cmd_redo)

    p = sub.add_parser("skip", help="검토 제외")
    p.add_argument("--rcept")
    p.add_argument("--note", required=True)
    p.set_defaults(func=cmd_skip)

    p = sub.add_parser("finish-corp", help="회사 종료 → std_v3 재빌드 + calendarize (런북 B5)")
    p.add_argument("--corp")
    p.add_argument("--year-min", type=int, default=1999)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_finish_corp)

    p = sub.add_parser("status", help="캠페인 진척")
    p.set_defaults(func=cmd_status)
    return ap


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.func(args)
