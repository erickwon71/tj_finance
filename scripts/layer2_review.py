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
import os
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
from fin2.audit import orphan_tables
from fin2.audit import row_coverage
from fin2.extract import review_csv
from fin2.extract.report_lines import (extract_report_lines, store_report_lines,
                                       store_report_tables)

# 회사 안 검토 순서의 기간 정렬 — 달력 순서(Q1 → H1 → Q3 → FY)를 역으로 쓴다.
_PERIOD_RANK = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4}

# ★재발방지(2026-09-20): autocompact 로 대화 맥락(지시)이 사라져도 이 커맨드 출력
# 자체가 규칙을 다시 상기시키도록, 매 건 제시 때마다 전체비교 메모리를 직접 읽어 출력한다.
# 이 세션에서 신한지주 23건이 BS↔SCE 내부대조만으로 pass 됐다가 전부 redo 로 되돌아갔다
# (참고: docs/qa/layer2_review_campaign_issues_2026-09-20.md).
_FULL_COMPARISON_MEMORY = Path(
    "~/.claude/projects/-Users-taejin-Project-tj-finance/memory/"
    "feedback-layer2-review-full-comparison-required.md"
).expanduser()


def _full_comparison_reminder() -> str:
    fallback = (
        "  ⚠️  ★전체비교 필수★ DART 원문(별도+연결 BS/IS/CF/SCE 전 항목)을 웹뷰로 직접 열어\n"
        "     CSV 와 라인별로 대조한 뒤에만 pass 할 것. 자본총계↔SCE종가 같은 내부대조나\n"
        "     부분 항목만 보고 pass 하는 것은 금지 (메모리 파일을 찾을 수 없어 요약만 표시)."
    )
    try:
        text_ = _FULL_COMPARISON_MEMORY.read_text(encoding="utf-8")
    except OSError:
        return fallback
    body = text_.split("---", 2)[-1].strip()
    if not body:
        return fallback
    lines = ["  ⚠️  ★전체비교 필수 (매 pass 전 확인) — " + str(_FULL_COMPARISON_MEMORY.name) + " ★"]
    lines += ["  " + ln for ln in body.splitlines()]
    return "\n".join(lines)


# ★★2026-09-20 강화(2차) — 리마인더 출력만으로는 "봤지만 그냥 넘어가는 것"을 막지 못한다
# (신한지주 23건 사고가 리마인더 부재가 아니라 습관적 생략이었다). `pass` 를 **기계적
# 게이트**로 바꾼다: 그 건에 실제로 적재된 모든 scope(별도/연결 × BS/IS/CF/SCE)를
# `--verified-scopes` 로 하나하나 열거하지 않으면 pass 자체를 거부한다. 이게 실제로
# DART 원문을 열어봤다는 것을 증명하진 못하지만(스크립트가 브라우저 사용을 감지할 방법은
# 없다), 최소한 "그 건에 뭐가 있는지도 모른 채 pass" 는 구조적으로 불가능해지고,
# 무엇을 확인했다고 주장했는지가 `layer2_review_queue.verified_scopes` 에 감사기록으로
# 남는다.
def _scope_codes(counts: dict | None) -> list[str]:
    """n_lines_by_scope(예: {"separate":{"BS":21,...},"consolidated":{...}}) →
    실제 행이 있는 scope 코드 리스트(예: ["sep-bs","sep-is","sep-cf","sep-sce",
    "con-bs","con-is","con-cf","con-sce"]). 순서 고정(별도 먼저, 각 안에서 BS/IS/CF/SCE)."""
    counts = counts or {}
    out = []
    for basis, prefix in (("separate", "sep"), ("consolidated", "con")):
        for stmt in ("BS", "IS", "CF", "SCE"):
            if (counts.get(basis) or {}).get(stmt, 0) > 0:
                out.append(f"{prefix}-{stmt.lower()}")
    return out


_ALL_SCOPE_CODES = tuple(f"{p}-{s}" for p in ("sep", "con")
                         for s in ("bs", "is", "cf", "sce"))


def _check_verified_scopes(item, given: str | None) -> tuple[bool, str]:
    """(ok, message). given 은 `pass --verified-scopes` 로 받은 콤마구분 문자열."""
    loaded = set(_scope_codes(item["n_lines_by_scope"]))
    got = {s.strip().lower() for s in (given or "").split(",") if s.strip()}

    unknown = got - set(_ALL_SCOPE_CODES)
    if unknown:
        return False, ("  ⛔ PASS 거부 — 알 수 없는 scope 코드: "
                       f"{','.join(sorted(unknown))}\n"
                       f"     쓸 수 있는 값: {','.join(_ALL_SCOPE_CODES)}")

    if not loaded:
        return False, (
            "  ⛔ PASS 거부 — 이 건은 적재된 재무제표가 하나도 없습니다.\n"
            "     원문에 표가 있는데 0행이면 파서 결함이니 `fail`, 원문 자체가 비어 있으면\n"
            "     `skip` 으로 기록하세요(빈 건을 조용히 통과시키지 않는다).")

    # ★원문엔 있는데 적재가 없는 scope 는 **결함 신고**지 입력 오류가 아니다(2026-09-20 2차).
    # 같은 날 초판은 이걸 "이 건엔 없는 scope" 로 거부해서, DART 원문을 제대로 열어보고
    # "연결 손익계산서도 확인했다"고 정직하게 적어낸 검토자에게 그 주장을 **지우라고**
    # 요구했다. 표가 통째로 유실되는 결함(R141 KB금융 연결IS 전체 유실 · R148 SCE 당기
    # 롤포워드 유실)이 정확히 이 모양이라, 캠페인이 찾아야 할 바로 그 신호를 입력 오류로
    # 처리한 셈이었다. 체크리스트를 감사 대상(DB)에서 뽑는 구조의 한계는 남지만, 최소한
    # 검토자가 "원문 기준으로 더 있었다"고 말할 수 있는 길은 막지 않는다.
    source_only = got - loaded
    if source_only:
        return False, (
            "  ⛔ PASS 거부 — 원문에서 확인했다는 scope 가 적재돼 있지 않습니다: "
            f"{','.join(sorted(source_only))}\n"
            "     이건 입력 오류가 아니라 **결함 신고**로 취급합니다(R141/R148 처럼 표가\n"
            "     통째로 유실된 모양). PASS 가 아니라 FAIL 로 기록하세요:\n"
            f'       python scripts/layer2_review.py fail --rcept {item["rcept_no"]} '
            f'--note "원문엔 {",".join(sorted(source_only))} 있으나 적재 0행"\n'
            "     원문에도 없는 것을 잘못 적었다면 그 값만 빼고 다시 실행하세요.")

    missing = loaded - got
    if missing:
        return False, (
            "  ⛔ PASS 거부 — 아직 열거되지 않은(=대조 안 끝난) scope 가 있습니다: "
            f"{','.join(sorted(missing))}\n"
            "     적재된 scope 는 전부 원문과 대조한 뒤 열거해야 합니다.")
    return True, ""


def _check_orphan_ack(item, accepted: str | None) -> tuple[bool, str]:
    """원문 본문표 미귀속 적출(`orphan_tables`)은 **사유를 적어야** 통과시킨다.

    ★`--verified-scopes` 는 적재된 scope 만 열거시키므로 "원문에 있는데 안 실린 표"를
      원리적으로 못 본다. 그 구멍을 메우는 유일한 신호라 그냥 경고로 두면 의미가 없다.
      반대로 무조건 차단하면 정당한 제외(은행 신탁계정 등)에서 캠페인이 멈춘다 —
      그래서 **사유를 남기면 통과**시키고 그 사유를 note 에 기록한다. 실측 발화율은
      160건 중 1건(0.6%)이라 통상 흐름을 막지 않는다.
    ★이 검산이 없는 옛 항목(이 기능 이전에 reloaded 된 건)은 그냥 통과시킨다 —
      없는 근거로 차단하지 않는다.
    """
    found = next((c for c in (item["checks"] or [])
                  if c.get("code") == orphan_tables.CODE), None)
    if found is None or found.get("verdict") != sc.FAIL:
        return True, ""
    if (accepted or "").strip():
        return True, ""
    return False, (
        "  ⛔ PASS 거부 — 원문 본문 섹션에 **어느 재무제표에도 안 붙은 금액표**가 있습니다.\n"
        f"     {found.get('message', '')}\n"
        "     표가 통째로 유실되는 결함(R141 연결IS 전체 유실 · R148 SCE 당기 유실)이\n"
        "     정확히 이 모양이므로, 원문에서 그 표가 무엇인지 직접 확인하세요.\n"
        "     · 적재됐어야 할 표다 → FAIL 로 기록:\n"
        f'         python scripts/layer2_review.py fail --rcept {item["rcept_no"]} '
        '--note "원문 본문표 미귀속 — 유실"\n'
        "     · 재무제표가 아니라 정당한 제외다 → 사유를 적고 통과:\n"
        f'         python scripts/layer2_review.py pass --rcept {item["rcept_no"]} '
        '--verified-scopes ... --accept-orphan-tables "신탁계정 — 은행 자체 재무제표 아님"')

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

# 정기보고서로 등록돼 있지만 **재무제표가 있을 수 없는 서류**를 걸러낸다
# (2026-09-20, docs/qa/layer2_blocked_filings_investigation_2026-09-20.md §①).
#
# `사업보고서제출기한연장신고서`(ACODE 11061) 류는 `report_nm` 이 '사업보고서…' 로
# 시작해 `report_type='annual'` 로 분류되지만, 본문이 6KB 남짓에 `<TABLE>` 이 하나도
# 없다(실측: 케이티앤지 `20200320001044`). 큐에 넣어봐야 전부 "추출 0행"으로 blocked
# 되므로 검토자 시간만 버린다. 실측 202건(193 사업 + 8 반기 + 1 분기)이 그랬다.
#
# ★전부 `is_final=False` 라 정본 선정에는 애초에 안 잡힌다 — 데이터 오염 문제가
#   아니라 **큐 위생** 문제다.
# ★`[첨부추가]`·`[기재정정]` 접두는 **절대 거르면 안 된다** — 실데이터가 있는 정상
#   보고서다(전수 확인: `[첨부추가]사업보고서` 만 수천 건, 대부분 lines>0).
#   그래서 접두가 아니라 **'제출기한연장신고서' 라는 서류 종류 자체**로 거른다
#   (`[기재정정]사업보고서제출기한연장신고서` 같은 조합도 이 한 조건으로 같이 걸린다).
# ★전수 확인 결과 `report_type` 이 정기보고서인 `report_nm` 뼈대는 4종뿐이고
#   (사업/반기/분기보고서 + 이 연장신고서), 다른 비-보고서 오염은 없었다.
_NON_REPORT_NM = "%제출기한연장신고서%"

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
      AND (f.report_nm IS NULL OR f.report_nm NOT LIKE :non_report_nm)
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
                _FILINGS_SQL, {"c": corp.corp_code, "fy_min": args.fiscal_year_min,
                               "non_report_nm": _NON_REPORT_NM}).fetchall()
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


_OWNER_ENV = "L2_REVIEW_OWNER"


def _owner() -> str:
    """이 실행의 소유자 식별자 — 기본값은 **워크트리 경로**.

    ★왜 워크트리 경로인가(2026-09-21) — CLI 프로세스는 명령 1회마다 죽으므로 PID 는
      키가 못 된다. 반면 세션마다 워크트리가 다르고(캠페인 = 메인 체크아웃 또는 자기
      워크트리, 결함조사 = `.claude/worktrees/camp_err_review`) 경로는 실행 사이에
      안정적이며 사람이 읽고 바로 이해한다.

    같은 워크트리를 둘로 나눠 써야 하면 `L2_REVIEW_OWNER` 로 덮는다.

    설계: docs/plans/layer2_review_session_ownership_design_2026-09-21.md
    """
    override = os.environ.get(_OWNER_ENV, "").strip()
    return override or str(Path(__file__).resolve().parents[1])


def _owner_label(owner: str | None) -> str:
    """표시용 짧은 이름(경로 마지막 조각). 없으면 '미지정'."""
    return Path(owner).name if owner else "미지정"


def _pick(session, rcept_no: str | None, *, statuses: tuple[str, ...],
          min_severity: int | None = None):
    """진행 순서 `(era_rank, corp_rank, screen_severity, seq_in_corp)` 로 다음 대상 1건.
    `rcept_no` 지정 시 그것만.

    ★era_rank(시대 게이트)가 최우선 — 2015+ 전체 회사를 다 끝내야 2011~2014 로
      넘어간다(위 상수 참고). 그 안에서는 시총순(corp_rank), 그 안에서는 사전
      스크리닝(`layer2_screen.py`) 심각도 큰 순, 마지막에 회사 내 순번(seq_in_corp).
      screen_severity 가 NULL(미스크리닝)이면 0과 동급으로 취급.

    ★`min_severity` — 브라우저 에이전트 자동화 캠페인의 단계(B) 지원
      (`docs/plans/layer2_review_browser_agent_automation_design_2026-09-18.md`,
      사용자 지시 2026-09-18). 사전 스크리닝에서 뭔가 걸린 건(`screen_severity>0`,
      2015+ 기준 27,136건)부터 먼저 끝내고, 그 다음에 `screen_severity=0`인
      나머지(79,312건)까지 이어서 전체를 돈다 — 파서 수정 건이 나올 가능성이
      높은 쪽부터 처리해 배치 수정 주기를 앞당기려는 것. `None`(기본값)이면
      기존 동작 그대로(필터 없음, era 2011-14/2007-10/pre-2007 캠페인도 이 함수를
      그대로 쓰므로 무변경).

    ★어느 경로든 **RowMapping(dict 처럼 쓰는 것)** 으로 통일한다 — 한때 rcept 지정 경로만
      ORM 객체를 돌려줘 호출부에서 `item["..."]` 가 TypeError 로 터졌다.
    """
    if rcept_no:
        return session.execute(
            text("SELECT * FROM layer2_review_queue WHERE rcept_no = :r"),
            {"r": rcept_no}).mappings().first()
    sev_filter = "AND COALESCE(screen_severity, 0) >= :min_sev" if min_severity is not None else ""
    return session.execute(
        text(f"""SELECT * FROM layer2_review_queue
                WHERE status = ANY(:st) {sev_filter}
                ORDER BY {_ERA_RANK_SQL},
                         corp_rank NULLS LAST,
                         COALESCE(screen_severity, 0) DESC,
                         seq_in_corp, rcept_no
                LIMIT 1"""),
        {"st": list(statuses), "min_sev": min_severity}).mappings().first()


def _current(session, *, owner: str | None = None):
    """**이 세션이** 재적재해 검토를 기다리는 건(= `pass`/`fail` 의 기본 대상).

    ★`owner` 로 한정하는 이유(2026-09-21) — 예전엔 `status='reloaded'` 중 **전역에서
      가장 최근**을 집었다. 큐를 만지는 세션이 둘(캠페인 진행 + 결함조사·백필)이라,
      조사 세션이 어떤 건을 재적재한 직후 캠페인 세션이 `pass` 를 부르면 **자기가 본
      적 없는 건에 통과 판정이 찍혔다.** `pass` 는 R139 보호가 걸리는 되돌리기 어려운
      관문이라 이 사고의 대가가 크다(그 뒤 `store_report_lines()` 가 그 rcept 를
      거부한다).

      ★`--verified-scopes` 게이트도 이걸 못 막는다 — 그 게이트는 "적재된 scope 를 다
      명시했는가"만 보므로, 검토한 건의 scope 집합이 우연히 엉뚱한 건과 같으면 그대로
      통과한다.

    ★`owner IS NULL`(이 컬럼 도입 전에 만들어진 건)은 **일부러 제외**한다 — 포함시키면
      막으려던 위험이 그대로 남는다. 전환기에 남은 건은 `--rcept` 로 한 번 지목해
      처리한다(설계문서 §5).
    """
    return session.execute(
        text("""SELECT * FROM layer2_review_queue
                WHERE status = 'reloaded' AND owner = :o
                ORDER BY reloaded_at DESC NULLS LAST LIMIT 1"""),
        {"o": owner or _owner()}).mappings().first()


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


def _reload_one(session, item, *, overwrite_reviewed: bool = False) -> tuple[str, str | None, list]:
    """재파싱 + 적재. 반환 (source_kind, 실패사유 or None, 추출된 lines).

    ★lines 를 돌려주는 이유(2026-09-20) — `row_coverage` 감사가 "원문 행이 전부
      실렸나"를 보려면 **방금 추출한 결과**가 필요하다. DB 를 다시 읽으면
      `store_report_lines()` 의 col_index=0 필터(BS/IS/CF)가 걸린 뒤라 멀쩡한 행도
      결측으로 오인된다. 여기서 이미 손에 있는 것을 그대로 넘겨 재파싱도 아낀다.

    ★`store_report_lines` 와 `store_report_tables` 를 **반드시 같이** 부른다 —
      `run.py::cmd_extract_lines` 는 후자를 부르지 않아 검토 CSV 에 찍을 단위 선언
      원문(`report_tables.unit_decl_raw`)이 갱신되지 않는다(설계 문서 §2).
    ★`store_report_lines` 의 manual 보호가드(report_lines.py:1373)는 그대로 둔다 —
      사람이 타이핑해 넣은 값을 이 캠페인이 조용히 덮어쓰면 안 된다. ValueError 는
      `blocked` 로 흡수한다.
    """
    kind, path = _resolve_source(session, item["rcept_no"])
    if kind == "none":
        return kind, "원문 파일 없음(다운로드 미완/소실)", []
    if kind != "xml":
        # PDF/HTML 복구 경로는 DART 웹 스크래핑이 필요하고 값조작 결함 이력이 있다
        # (docs/qa/report_lines_row_count_outlier_scan_2026-09-08.md Pattern A).
        # 이 캠페인의 1차 대상(시총 상위 = 2015+ XML)에는 사실상 안 나온다.
        return kind, (f"{kind} 소스는 이 CLI 가 자동 재적재하지 않는다 — "
                      f"collector/pdf_lines_sync.py::sync_pdf_recovery 로 별도 처리"), []
    try:
        lines = extract_report_lines(
            path, rcept_no=item["rcept_no"], corp_code=item["corp_code"],
            report_fiscal_year=item["fiscal_year"],
            report_fiscal_period=item["fiscal_period"], include_notes=False)
    except (FileNotFoundError, OSError) as exc:
        return kind, f"원문 읽기 실패: {type(exc).__name__}: {exc}", []
    if not lines:
        return kind, "추출 0행(보류) — 섹션/표 미검출", []
    try:
        store_report_lines(session, item["rcept_no"], lines, overwrite_reviewed=overwrite_reviewed)
        store_report_tables(session, item["rcept_no"], lines)
    except ValueError as exc:      # manual/원문대조 보호가드
        session.rollback()
        return kind, str(exc), []
    return kind, None, lines


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


def _run_target(session, item, *, root: Path | None = None, overwrite_reviewed: bool = False) -> dict:
    """1건 재적재 → 검산 → CSV. 큐 상태까지 갱신하고 요약 dict 를 돌려준다."""
    now = datetime.now()
    kind, err, lines = _reload_one(session, item, overwrite_reviewed=overwrite_reviewed)
    if err:
        # ★blocked 경로도 소유자를 찍는다 — 빠뜨리면 그 건이 무소유로 남아
        #   `redo`(소유자 범위)로 이어서 다룰 수 없다.
        _mark(session, item["rcept_no"], status="blocked", source_kind=kind,
              reloaded_at=now, note=err, owner=_owner())
        session.commit()
        return {"blocked": True, "source_kind": kind, "reason": err}

    rows = sc.load_rows(session, item["rcept_no"])
    checks = sc.run_checks(session, item["rcept_no"], corp_code=item["corp_code"],
                           fiscal_period=item["fiscal_period"], rows=rows)
    # ★원문 쪽에서 보는 결측 신호(2026-09-20) — 다른 검산은 전부 **적재 결과**를 보므로
    # "원문에 있는데 안 실린 표"를 원리적으로 못 본다. 여기서만 원문 표 목록과 귀속
    # 결과를 맞댄다. 근거·실측은 fin2/audit/orphan_tables.py docstring.
    src_path = _resolve_source(session, item["rcept_no"])[1]
    checks.append(orphan_tables.check(src_path))
    # 행 단위 결측(표는 정상 귀속되고 안의 행만 사라지는 R149 류). 차단 등급이 아니다 —
    # 근거는 fin2/audit/row_coverage.py docstring 마지막 단락. ★결측행 목록은 검토
    # CSV 에도 '★원문만' 블록으로 실어 대조 방향을 양방향으로 만든다(같은 목록을 써야
    # 검산과 CSV 가 어긋나지 않으므로 `scan()` 으로 한 번만 훑는다).
    missing_rows, row_check = row_coverage.scan(src_path, lines)
    checks.append(row_check)
    path, counts = review_csv.generate(
        session, rcept_no=item["rcept_no"], corp_code=item["corp_code"],
        corp_name=item["corp_name"], market=item["market"],
        corp_rank=item["corp_rank"], report_type=item["report_type"],
        report_nm=item["report_nm"], fiscal_year=item["fiscal_year"],
        fiscal_period=item["fiscal_period"], filed_at=item["filed_at"],
        source_kind=kind, checks=checks, reloaded_at=now, root=root, db_rows=rows,
        source_only_rows=missing_rows)

    n_lines = len(rows)
    _mark(session, item["rcept_no"], status="reloaded", source_kind=kind,
          reloaded_at=now, n_lines=n_lines, n_lines_by_scope=counts,
          check_status=sc.rollup(checks),
          checks=[c.as_dict() for c in checks], csv_path=str(path),
          owner=_owner())
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
                f"{s} {counts[basis].get(s, 0)}" for s in ("BS", "IS", "CF", "SCE")))
    print(f"  적재    {'  ·  '.join(parts) or '0행'}  (총 {result['n_lines']:,}행)")

    fails = sc.suspects(result["checks"])
    if not fails:
        print("  검산    ✅ 이상 없음")
    else:
        print(f"  검산    ⚠ 의심 {len(fails)}건")
        for c in fails:
            print(f"           · [{c.grade}] {c.scope} {c.code} — {c.message}")
    print()
    print(_full_comparison_reminder())
    print()
    print(f'  open "{result["csv_path"]}"')
    print()
    scopes = ",".join(_scope_codes(counts))
    print("  → CSV 와 DART 원문을 대조한 뒤:")
    print(f'       python scripts/layer2_review.py pass --verified-scopes {scopes}')
    print('       python scripts/layer2_review.py fail --note "무엇이 어떻게 틀렸는지"')
    print("     ⛔ --verified-scopes 는 실제로 대조를 끝낸 scope 만 나열할 것 — 위 목록은")
    print("        '이 건에 적재된 scope 전부' 일 뿐, 대조 완료를 대신 증명해주지 않습니다.")
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
            print("\n⚠ 이 세션이 아직 판정하지 않은 건이 있습니다 "
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
            item = _pick(session, args.rcept, statuses=("pending",),
                        min_severity=args.min_severity)
            if item is None:
                print("\n✅ 대기 중인 대상이 없습니다. `init` 로 큐를 넓히거나 `status` 로 확인하세요.")
                return
            result = _run_target(session, item, root=root)
            _print_target(item, result)
            if not result["blocked"] or args.rcept:
                return


def _print_no_target() -> None:
    """`pass`/`fail` 대상이 없을 때 — 왜 없는지와 다음 수를 같이 알려준다.

    소유자 범위(2026-09-21)로 바뀐 뒤엔 "reloaded 건이 아예 없음"과 "남의 세션 것만
    있음"이 구분되므로, 후자에서 사용자가 막막해지지 않게 `--rcept` 를 안내한다.
    """
    print("판정할 대상이 없습니다 — 이 세션이 재적재한 reloaded 건이 없습니다.")
    print(f"  (소유자: {_owner_label(_owner())})")
    print("  다른 세션이 재적재한 건을 판정하려면 `--rcept <접수번호>` 로 지목하세요.")


def _warn_if_other_owner(item, *, explicit: bool) -> None:
    """`--rcept` 로 **남의 세션 것**을 지목했으면 경고한다(차단하지는 않는다).

    ★차단하지 않는 이유 — 이 워크트리가 백필 후 재검토를 대신 처리하는 정상 흐름이
      실제로 있다(R154 백필 77건). 막으면 그 흐름이 죽는다. 다만 상대 세션이 지금
      원문대조 중일 수 있으므로 반드시 눈에 띄게 알린다.
    """
    if not explicit:
        return
    other = item["owner"]
    if other and other != _owner():
        print(f"\n⚠ 이 건의 소유 세션은 {_owner_label(other)} 입니다 "
              f"(현재: {_owner_label(_owner())}).")
        print("  그 세션이 원문대조 중일 수 있습니다 — 확인하고 진행하세요.")


def cmd_pass(args) -> None:
    # ★autocompact 대비(2026-09-20) — 세션이 새로 시작해 `next` 없이 곧바로 `pass` 만
    # 부르면 전체비교 규칙을 한 번도 못 본 채 판정하게 된다(실측: R148 백필 때 `pass
    # --rcept` 8회가 전부 그 경로였다). 판정은 되돌리기 어려운 마지막 관문이므로
    # 여기서도 규칙 전문을 다시 찍는다.
    print()
    print(_full_comparison_reminder())
    print()
    with get_session() as session:
        item = _pick(session, args.rcept, statuses=("reloaded",)) if args.rcept else _current(session)
        if item is None:
            _print_no_target()
            return
        _warn_if_other_owner(item, explicit=bool(args.rcept))
        for ok, msg in (_check_verified_scopes(item, args.verified_scopes),
                        _check_orphan_ack(item, args.accept_orphan_tables)):
            if not ok:
                print()
                print(msg)
                print()
                return
        note = args.note
        if (args.accept_orphan_tables or "").strip():
            note = (f"{note} / " if note else "") + \
                f"원문 미귀속표 확인함: {args.accept_orphan_tables.strip()}"
        _mark(session, item["rcept_no"], status="pass", reviewed_at=datetime.now(),
              note=note, verified_scopes=args.verified_scopes)
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
        cmd_next(argparse.Namespace(rcept=None, root=args.root, force=False,
                                    min_severity=args.min_severity))


def cmd_fail(args) -> None:
    with get_session() as session:
        item = _pick(session, args.rcept, statuses=("reloaded",)) if args.rcept else _current(session)
        if item is None:
            _print_no_target()
            return
        _warn_if_other_owner(item, explicit=bool(args.rcept))
        _mark(session, item["rcept_no"], status="fail", reviewed_at=datetime.now(),
              note=args.note)
        session.commit()
        print(f"\n❌ FAIL  r{item['rcept_no']}  {item['corp_name']} "
              f"{item['fiscal_year']}{item['fiscal_period']}")
        print(f"  사유: {args.note}")
        print("\n★ 루프를 정지합니다 (사용자 결정 2026-09-08: FAIL 이면 원인부터 규명).")
        _print_triage(item)


def cmd_redo(args) -> None:
    """파서를 고친 뒤 같은 대상만 재적재 → 재검산 → CSV 재생성.

    ★--overwrite-reviewed(2026-09-22, R162 백필 요청 대응): `store_report_lines`의
      원문대조-pass 보호가드(R139)를 이 건 하나에 한해 명시적으로 해제한다. 파서가
      수정된 뒤(예: R162 SCE 부호복원) 이미 pass 된 건을 재검토자 스스로 재판정해
      덮어써야 하는 경우를 위한 것 — **--rcept 로 특정 건을 지정했을 때만** 허용한다
      (owner 범위 최신픽 경로에 실수로 걸리지 않도록). 재적재 후 반드시 원문 재대조 →
      다시 pass 할 것."""
    root = Path(args.root) if args.root else None
    with get_session() as session:
        if args.rcept:
            item = session.execute(
                text("SELECT * FROM layer2_review_queue WHERE rcept_no = :r"),
                {"r": args.rcept}).mappings().first()
        else:
            # ★소유자 범위(2026-09-21) — **이 함수가 실제로 사고를 낸 경로다.**
            #   `--rcept` 없이 부르면 전역에서 가장 최근 건을 집어, 백필 중에
            #   캠페인 세션이 보고 있던 항목을 가로챘다(2026-09-20). 그 뒤로 "백필에
            #   redo 를 쓰지 않는다"는 규약으로만 회피했는데, 규약은 autocompact 를
            #   못 견딘다 — 코드로 막는다.
            item = session.execute(
                text("""SELECT * FROM layer2_review_queue
                        WHERE status IN ('fail','reloaded','blocked')
                          AND owner = :o
                        ORDER BY reviewed_at DESC NULLS LAST, reloaded_at DESC NULLS LAST
                        LIMIT 1"""), {"o": _owner()}).mappings().first()
        if item is None:
            print("재실행할 대상이 없습니다.")
            return
        overwrite_reviewed = bool(args.overwrite_reviewed and args.rcept)
        result = _run_target(session, item, root=root, overwrite_reviewed=overwrite_reviewed)
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
        # ★브라우저 자동화 캠페인 단계(B) 진행 가시성(2026-09-18) —
        #   docs/plans/layer2_review_browser_agent_automation_design_2026-09-18.md.
        #   screen_severity>0(사전 스크리닝이 뭔가 걸어놓은 것)을 먼저 끝내고
        #   =0(스크리닝 무결점)은 나중이므로, 이 둘의 잔량을 따로 보여준다.
        print("\n── 사전 스크리닝 단계(B/A) — pending만 ──")
        for r in session.execute(text(
                """SELECT (COALESCE(screen_severity, 0) > 0) AS flagged, count(*) n
                   FROM layer2_review_queue WHERE status = 'pending'
                   GROUP BY 1 ORDER BY 1 DESC""")).fetchall():
            label = "severity>0 (단계 B)" if r.flagged else "severity=0 (단계 A)"
            print(f"  {label:<20} {r.n:>8,}")
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
        # ★autocompact 대비 — `status` 는 새 세션이 캠페인을 이어받을 때 가장 먼저 치는
        # 명령이다. 여기서 규칙을 먼저 보여줘야 대화 맥락이 날아간 채 재개해도 규칙이 산다.
        print()
        print(_full_comparison_reminder())
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
    p.add_argument("--min-severity", type=int, default=None,
                   help="이 값 이상 screen_severity 인 건만(브라우저 자동화 캠페인 "
                        "단계(B) — 미지정시 필터 없음, 기존 동작과 동일)")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("pass", help="원문대조 통과 → 다음 1건")
    p.add_argument("--rcept")
    p.add_argument("--note")
    p.add_argument("--verified-scopes", required=True,
                   help="이 건에 실제로 적재된 scope 전부를 콤마구분으로 명시(예: "
                        "sep-bs,sep-is,sep-cf,sep-sce,con-bs,con-is,con-cf,con-sce). "
                        "`next`/`redo` 출력의 pass 명령에 정확한 목록이 이미 채워져 나옴. "
                        "누락/불일치 시 PASS 자체가 거부됨(2026-09-20, DB감사기록 "
                        "layer2_review_queue.verified_scopes 로 남김).")
    p.add_argument("--accept-orphan-tables", metavar="사유",
                   help="원문 본문표 미귀속 적출을 '유실 아님'으로 판단한 사유(예: "
                        "'신탁계정 — 은행 자체 재무제표 아님'). 사유는 note 에 남는다. "
                        "재무제표가 아니라서 제외된 것이 확실할 때만 쓸 것 — 유실이면 fail.")
    p.add_argument("--root")
    p.add_argument("--no-advance", action="store_true", help="다음 건을 자동으로 받지 않음")
    p.add_argument("--min-severity", type=int, default=None,
                   help="자동 진행되는 다음 건에도 같은 필터 유지(next 참고)")
    p.set_defaults(func=cmd_pass)

    p = sub.add_parser("fail", help="불일치 → 루프 정지 + 트리아지 진입점")
    p.add_argument("--rcept")
    p.add_argument("--note", required=True, help="무엇이 어떻게 틀렸는지")
    p.set_defaults(func=cmd_fail)

    p = sub.add_parser("redo", help="파서 수정 후 같은 건 재적재")
    p.add_argument("--rcept")
    p.add_argument("--root")
    p.add_argument("--overwrite-reviewed", action="store_true",
                   help="원문대조-pass 보호(R139)를 이 건 한정 해제 — --rcept 필수, "
                        "파서 수정 후 재판정 백필 요청(예: R162) 대응용")
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
