"""I3 · 참조무결성/정합성 SQL 어서션 — 야간 상시 검사.

DB 전반의 '있어서는 안 되는' 상태를 SQL 어서션으로 점검한다. ERROR 위반이 1건이라도 있으면
종료코드 1(게이트/알림). WARN 은 참고 지표(정상 예외 존재)라 종료코드에 영향 없음.

달력 유령/미래 분기 검사는 `diag_calendar_orphans` 의 orphan 술어를 재사용한다.

C11(완전성 매트릭스): `check_completeness()` — 상장일 컬럼이 없어 "상장 이후 전체 이력"
재검증은 못하지만(6/25 전수검증이 그건 이미 증명함), 결산월 기준 이미 기한이 지난 최신
분기가 DB에 없는 기업을 매일 잡아 신규 공백(지연공시·정정드리프트)을 조기 발견한다.

usage:
  python scripts/dq_assertions.py            # 전 어서션 실행·요약
  python scripts/dq_assertions.py --sample   # 위반 표본행도 출력

★2026-09-01(fact_v2/std_v2 GC 트랙, `std_financials_v2` DROP) — std_financials_v2 를
쓰던 어서션 전부를 v3로 이식했다(dq_nightly.py 가 매일 20:30 launchd 로 이 스크립트를
돌리는 실사용 코드라 미이식 시 그날 밤 깨졌을 것). v3는 PK가 (corp_code,fiscal_year,
fiscal_period,statement_type) 뿐이라 `version=1`/`is_stub`/`is_discrete` 조건은 전부
삭제(그런 중복행 자체가 없음). `check_completeness()`는 CHECKS 루프의 try/except
SKIP 보호가 없어(직접 호출) 실제 크래시 위험이 있었던 지점 — 이것도 이식함.
`std_financials_calendar`(→`std_v2_controlling_ni_exceeds_net` 이름의 유래가 된 std_v2
와는 별개 테이블)는 GC 범위 밖이라 그대로 둠.

★2026-09-02(fact_v2 GC §4-4 DROP 후속, docs/plans/factv2_stdv2_gc_backfill_backlog_
2026-09-01.md 백로그 항목1+4) — `fact_v2` DROP으로 상시 SKIP 되던 WARN 2건 중
`std_v2_controlling_ni_exceeds_net`은 `extended_facts_v3`로 재소싱해 복구,
`fact_v2_q1_duration_col0_eq_col1`은 구조적으로 재현 불가로 확인해 폐기(사유는 해당
항목 주석). `extended_financials_n_facts_outlier`는 `std_v3_conflicts_unresolved`로 교체.
`calendar_orphan_cq`(→`diag_calendar_orphans.py::_ORPHAN_PRED`)는 여전히 `std_financials_v2`를
직접 읽어 SKIP 상태 그대로 — 이산분기/달력 계열은 별도 트랙(백로그 항목5).

★2026-09-02(calendar_v3_migration_scoping_2026-09-02.md §3(c)) — 위 백로그 항목5(이산분기/
달력) 트랙 완료 후, `calendar_orphan_cq`를 `std_financials_v3` 기반(source_lineage 대조)
으로 재작성해 SKIP 복구(`diag_calendar_orphans.py` 참고, 판정식 자체가 바뀜 — "이산분기
존재 여부"가 아니라 "그 CQ 를 만든 as-filed 행이 지금도 그 슬롯을 뒷받침하는가").
"""
from __future__ import annotations

import argparse
import calendar
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from diag_calendar_orphans import _ORPHAN_PRED   # scripts/ 는 실행 시 sys.path[0]

# 각 어서션: name / sev(ERROR|WARN) / desc / count SQL / sample SQL(선택)
CHECKS: list[dict] = [
    {
        "name": "future_period_std",
        "sev": "ERROR",
        "desc": "미래 period_end 인데 미격리(DQ<3) — 아직 끝나지 않은 기간이 소비계층에 노출",
        "count": "SELECT count(*) FROM std_financials_v3 "
                 "WHERE period_end > CURRENT_DATE AND COALESCE(data_quality,1) < 3",
        "sample": "SELECT corp_code, fiscal_year, fiscal_period, statement_type, period_end "
                  "FROM std_financials_v3 WHERE period_end > CURRENT_DATE "
                  "AND COALESCE(data_quality,1) < 3 ORDER BY period_end DESC LIMIT 10",
    },
    {
        # 밸류에이션 최신성(A4a): valuation_daily matview 는 nightly_valuation_refresh(19:30) 로 갱신된다.
        # 최신 거래일이 6일 이상 지났으면 refresh/주가동기화 파이프라인 정체 신호(외부평가 2026-07-15 = 3주 정체).
        # ★ 단일 종목이 앞서가면 max(trade_date) 가 착시를 준다(테스트 1종목이 07-14, 전수는 06-26 정체).
        #   → **전수 커버(≥100 종목)된 최신 거래일**로 판정해 착시를 차단. 임계 6일 = 주말·연휴 여유.
        #   ERROR → dq_nightly 가 알림(notify_failure).
        "name": "valuation_daily_stale",
        "sev": "ERROR",
        "desc": "valuation_daily 전수커버 최신 거래일이 6일 이상 지연 (refresh/주가동기화 정체 신호)",
        "count": "SELECT CASE WHEN COALESCE((SELECT max(trade_date) FROM "
                 "(SELECT trade_date FROM valuation_daily GROUP BY trade_date HAVING count(*) >= 100) t), "
                 "DATE '1900-01-01') < CURRENT_DATE - INTERVAL '6 days' THEN 1 ELSE 0 END",
        "sample": "SELECT max(trade_date) AS broad_latest, CURRENT_DATE - max(trade_date) AS days_behind "
                  "FROM (SELECT trade_date FROM valuation_daily GROUP BY trade_date HAVING count(*) >= 100) t",
    },
    {
        "name": "calendar_orphan_cq",
        "sev": "ERROR",
        "desc": "달력분기(CQ) 유령행 — 대응 이산분기 없음",
        "count": f"SELECT count(*) FROM std_financials_calendar cf WHERE {_ORPHAN_PRED}",
        "sample": f"SELECT cf.corp_code, cf.calendar_year, cf.calendar_period, cf.statement_type "
                  f"FROM std_financials_calendar cf WHERE {_ORPHAN_PRED} "
                  f"ORDER BY cf.calendar_year DESC LIMIT 10",
    },
    {
        "name": "calendar_future_period",
        "sev": "ERROR",
        "desc": "달력행에 미래 period_end(끝나지 않은 분기)",
        "count": "SELECT count(*) FROM std_financials_calendar "
                 "WHERE version=1 AND period_end > CURRENT_DATE",
        "sample": "SELECT corp_code, calendar_year, calendar_period, statement_type, period_end "
                  "FROM std_financials_calendar WHERE version=1 AND period_end > CURRENT_DATE LIMIT 10",
    },
    {
        "name": "calendar_cy_without_4cq",
        "sev": "ERROR",
        "desc": "달력연도(CY)인데 그 해 CQ1~CQ4 가 다 있지 않음",
        "count": """
            SELECT count(*) FROM std_financials_calendar cy WHERE cy.calendar_period='CY'
              AND cy.version=1 AND (
                SELECT count(*) FROM std_financials_calendar cq
                WHERE cq.corp_code=cy.corp_code AND cq.statement_type=cy.statement_type
                  AND cq.version=1 AND cq.calendar_year=cy.calendar_year
                  AND cq.calendar_period IN ('CQ1','CQ2','CQ3','CQ4')) < 4""",
        "sample": """
            SELECT cy.corp_code, cy.calendar_year, cy.statement_type FROM std_financials_calendar cy
            WHERE cy.calendar_period='CY' AND cy.version=1 AND (
                SELECT count(*) FROM std_financials_calendar cq
                WHERE cq.corp_code=cy.corp_code AND cq.statement_type=cy.statement_type
                  AND cq.version=1 AND cq.calendar_year=cy.calendar_year
                  AND cq.calendar_period IN ('CQ1','CQ2','CQ3','CQ4')) < 4 LIMIT 10""",
    },
    {
        # P0-3(외부평가 2026-07-15): shares_out 10^6 과다저장 → 시총·PER/PBR 천문학적 왜곡.
        # 물리적 불가(> 10^11 = 삼성전자 발행주식수 ~60억주의 10배 초과). 단위변환 버그 재발 감지.
        "name": "shares_out_impossible",
        "sev": "ERROR",
        "desc": "발행주식수 > 10^11 (물리적 불가 — shares_out 단위변환 버그 신호)",
        "count": "SELECT count(*) FROM std_financials_v3 "
                 "WHERE shares_out IS NOT NULL AND shares_out > 100000000000",
        "sample": "SELECT corp_code, fiscal_year, fiscal_period, statement_type, shares_out "
                  "FROM std_financials_v3 WHERE shares_out > 100000000000 "
                  "ORDER BY shares_out DESC LIMIT 10",
    },
    {
        # P0-3: 위 shares_out 버그가 stock_prices.market_cap 으로 전파된 결과. 국내증시 총액 ~3,000조.
        # 단일종목 시총 > 5,000조(5e18원)는 불가값 → 시총 정렬·스크리너·피어 오염.
        "name": "market_cap_impossible",
        "sev": "ERROR",
        "desc": "시가총액 > 5,000조원 (물리적 불가 — shares_out/단위 버그가 market_cap 으로 전파)",
        "count": "SELECT count(DISTINCT stock_code) FROM stock_prices "
                 "WHERE market_cap IS NOT NULL AND market_cap > 5e18",
        "sample": "SELECT stock_code, max(market_cap) AS max_mc, max(shares_out) AS max_shares "
                  "FROM stock_prices WHERE market_cap > 5e18 GROUP BY stock_code "
                  "ORDER BY max_mc DESC LIMIT 10",
    },
    {
        "name": "nonpositive_total_assets",
        "sev": "ERROR",
        "desc": "자산총계 <= 0 인데 미격리(DQ<3) — 소비계층에 노출되는 불가값",
        "count": "SELECT count(*) FROM std_financials_v3 "
                 "WHERE total_assets IS NOT NULL AND total_assets <= 0 AND COALESCE(data_quality,1) < 3",
        "sample": "SELECT corp_code, fiscal_year, fiscal_period, statement_type, total_assets "
                  "FROM std_financials_v3 "
                  "WHERE total_assets IS NOT NULL AND total_assets <= 0 "
                  "AND COALESCE(data_quality,1) < 3 LIMIT 10",
    },
    {
        # ★ 2026-07-17 — 단위 오염 발견(docs/qa/plan_note_body_separation_2026-07-17.md).
        # 본문 재무제표 값이 ×10^3~10^6 부풀려진 채 소비계층에 도달했다
        # (예: DB손해보험 2023 H1 별도 retained_earnings 8.5경원 = 정답 8.56조 × 10^6).
        # 원인은 **최소 두 가지**(초기 진단 '주석표 누수' 는 일부만 맞았다 — 원문 대조로 정정):
        #   (a) 추출기의 단위 추측 — 표에 단위가 없으면 앞 형제에서 주워오거나 기본값 가정.
        #       DB손해보험이 이 경우. 섹션 기반 재설계 + '명시 선언만' 규칙으로 해소.
        #   (b) **원문 자체의 단위 오기** — 회사가 (단위:백만원)이라 써놓고 원 단위 값을 기재.
        #       3S 20230209000202(×10^6) · 네오크레마 20231226000346(천원 오기, ×10^3).
        #       garbage-in 이라 재파싱으로 안 고쳐진다 → 이 어서션으로 탐지 후 사용자 확인.
        #
        # 왜 기존 게이트가 전부 놓쳤나: DQ 는 항등식(자산=부채+자본)을 보는데 **양변이 균일하게
        # ×10^6 되면 항등식은 그대로 성립** → DQ=1(정상) 판정. shares_out/market_cap 에는 크기
        # 어서션이 있었으나 **재무제표 본체 금액엔 없었다.** 이 어서션이 그 구멍을 막는다.
        #
        # 임계 보정(실측, 2026-07-17): 국내 상장사 정상 최대 = 삼성전자 2025 연결 FY
        # (매출 334조·자산 567조·자본 436조·이익잉여금 402조), 자산 최대 = KB금융 830조.
        # 오염 최소 = SKC 2004 자산 1,340조 / 코리아써키트 2019 매출 402조. 경계 검증 결과
        # 임계 바로 위 행들이 전부 명백한 오염(중소사 매출 402~416조 등)이라 **오탐 0**.
        # ⚠ 한계: 코리아써키트 매출 339조(오염) < 삼성전자 334조(정상)로 **구간이 겹쳐** 절대
        # 임계로는 중간대역 오염을 못 잡는다. 이 어서션은 극단값 하한선이지 완전 검출이 아니다
        # (완전 분리는 provenance 기록 + 재추출 = 계획서 Phase 2~5).
        #
        # is_discrete 포함: 파생분기(Q2=H1−Q1, Q4=FY−Q3)에 오염이 몰려 있고(196행) 앱 분기
        # 차트가 이를 실제로 소비한다. 기존 nonpositive_total_assets 는 discrete 를 제외하나,
        # 여기선 노출 실태를 그대로 드러내는 것이 목적이라 포함한다.
        "name": "statement_magnitude_impossible",
        "sev": "ERROR",
        "desc": "재무제표 본체 금액이 물리적 불가 크기 (자산>1,000조·자본/이익잉여금>500조·매출>400조) "
                "인데 미격리(DQ<3) — 단위 ×10³~10⁶ 오염이 소비계층 노출",
        "count": "SELECT count(*) FROM std_financials_v3 "
                 "WHERE COALESCE(data_quality,1) < 3 "
                 "AND (abs(total_assets) > 1e15 OR abs(total_equity) > 5e14 "
                 "     OR abs(retained_earnings) > 5e14 OR abs(revenue) > 4e14)",
        "sample": "SELECT corp_code, fiscal_year, fiscal_period, statement_type, "
                  "round(total_assets/1e12) AS assets_jo, round(total_equity/1e12) AS equity_jo, "
                  "round(retained_earnings/1e12) AS re_jo, round(revenue/1e12) AS revenue_jo "
                  "FROM std_financials_v3 "
                  "WHERE COALESCE(data_quality,1) < 3 "
                  "AND (abs(total_assets) > 1e15 OR abs(total_equity) > 5e14 "
                  "     OR abs(retained_earnings) > 5e14 OR abs(revenue) > 4e14) "
                  "ORDER BY GREATEST(COALESCE(abs(total_assets),0), COALESCE(abs(total_equity),0), "
                  "COALESCE(abs(retained_earnings),0), COALESCE(abs(revenue),0)) DESC LIMIT 10",
    },
    {
        # ★ 2026-07-17 — 위 절대임계가 못 잡는 **중간대역** 오염 검출(같은 조사 산물).
        # 원리: 오염은 한 기간만 튀고 인접 기간엔 원복하는 **스파이크**로 나타난다(제주은행 2003
        # 매출 1,697억 → 1,187,562,825억 → 1,311억). 정상 성장은 인접연도 대비 100배가 될 수
        # 없다(삼성전자 334조 vs 이웃 301조 = 1.1배). 자기 자신과 비교하므로 대기업 오탐이 없다.
        # 검출력 실측: FY 기준 절대임계 13행 vs 급변검출 26행(자산) / 6행 vs 32행(매출) — 2~5배.
        # 전후 연도가 모두 있어야 판정 가능(첫·마지막 연도는 미검출) → 절대임계와 상호보완.
        "name": "statement_magnitude_spike",
        "sev": "WARN",
        "desc": "FY 값이 인접 전·후 연도 대비 100배 이상 급등 후 원복 (단위/주석표 오염 스파이크)",
        "count": """
            WITH fy AS (
              SELECT corp_code, statement_type, fiscal_year,
                     revenue::numeric AS revenue, total_assets::numeric AS total_assets
              FROM std_financials_v3
              WHERE fiscal_period='FY'
            ), nb AS (
              SELECT f.*,
                LAG(total_assets)  OVER w AS pa, LEAD(total_assets) OVER w AS na,
                LAG(revenue)       OVER w AS pr, LEAD(revenue)      OVER w AS nr
              FROM fy f
              WINDOW w AS (PARTITION BY corp_code, statement_type ORDER BY fiscal_year)
            )
            SELECT count(*) FROM nb
            WHERE (pa > 0 AND na > 0 AND total_assets/pa > 100 AND total_assets/na > 100)
               OR (pr > 0 AND nr > 0 AND revenue/pr > 100 AND revenue/nr > 100)
        """,
        "sample": """
            WITH fy AS (
              SELECT corp_code, statement_type, fiscal_year,
                     revenue::numeric AS revenue, total_assets::numeric AS total_assets
              FROM std_financials_v3
              WHERE fiscal_period='FY'
            ), nb AS (
              SELECT f.*,
                LAG(total_assets)  OVER w AS pa, LEAD(total_assets) OVER w AS na,
                LAG(revenue)       OVER w AS pr, LEAD(revenue)      OVER w AS nr
              FROM fy f
              WINDOW w AS (PARTITION BY corp_code, statement_type ORDER BY fiscal_year)
            )
            SELECT corp_code, fiscal_year, statement_type,
                   round(pr/1e8) AS prev_rev_eok, round(revenue/1e8) AS cur_rev_eok,
                   round(nr/1e8) AS next_rev_eok
            FROM nb
            WHERE (pa > 0 AND na > 0 AND total_assets/pa > 100 AND total_assets/na > 100)
               OR (pr > 0 AND nr > 0 AND revenue/pr > 100 AND revenue/nr > 100)
            ORDER BY GREATEST(COALESCE(total_assets,0), COALESCE(revenue,0)) DESC LIMIT 10
        """,
    },
    {
        "name": "operating_income_eq_net_income",
        "sev": "WARN",
        "desc": "영업이익 == 순이익 (원단위 정확일치 = Track B 순이익 라인 오매핑 신호)",
        "count": "SELECT count(*) FROM std_financials_v3 "
                 "WHERE fiscal_period IN ('FY','Q1') "
                 "AND operating_income IS NOT NULL AND operating_income = net_income",
        "sample": "SELECT corp_code, fiscal_year, fiscal_period, statement_type, operating_income "
                  "FROM std_financials_v3 WHERE fiscal_period IN ('FY','Q1') "
                  "AND operating_income IS NOT NULL AND operating_income = net_income LIMIT 10",
    },
    {
        "name": "bs_identity_gt5pct",
        "sev": "WARN",
        "desc": "자산 ≠ 부채+자본 (5% 초과, =DQ3 항등식 위반)",
        "count": "SELECT count(*) FROM std_financials_v3 "
                 "WHERE COALESCE(data_quality,1) >= 3",
    },
    {
        # C2(2026-07-05): con<sep 전수는 14,525(대부분 구형 아티팩트) → 노이즈. 유의미 이상만:
        # 최근FY·양수·sep≤1000조·연결<별도×0.5. baseline ~21 = 신탁회계 정당(한국토지신탁 등) +
        # 별도 ×1000 단위오탐 버그. WARN(정당 예외 존재). 상세 docs/dq_con_lt_sep_triage_2026-07-05.
        "name": "consolidated_lt_separate_assets_material",
        "sev": "WARN",
        "desc": "연결 자산총계 < 별도×0.5 (최근FY 유의미 이상 — 별도 ×1000 오탐 or 신탁 정당, C2)",
        "count": """
            SELECT count(*) FROM standard_financials con
            JOIN standard_financials sep ON sep.corp_code=con.corp_code
              AND sep.fiscal_year=con.fiscal_year AND sep.fiscal_period=con.fiscal_period
              AND sep.statement_type='separate'
            WHERE con.statement_type='consolidated' AND con.fiscal_period='FY'
              AND con.fiscal_year >= 2015 AND con.total_assets > 0 AND sep.total_assets > 0
              AND sep.total_assets <= 1e15 AND con.total_assets < sep.total_assets * 0.5""",
        "sample": """
            SELECT con.corp_code, con.fiscal_year, con.total_assets AS con_assets,
                   sep.total_assets AS sep_assets
            FROM standard_financials con
            JOIN standard_financials sep ON sep.corp_code=con.corp_code
              AND sep.fiscal_year=con.fiscal_year AND sep.fiscal_period=con.fiscal_period
              AND sep.statement_type='separate'
            WHERE con.statement_type='consolidated' AND con.fiscal_period='FY'
              AND con.fiscal_year >= 2015 AND con.total_assets > 0 AND sep.total_assets > 0
              AND sep.total_assets <= 1e15 AND con.total_assets < sep.total_assets * 0.5
            ORDER BY con.total_assets::float / sep.total_assets LIMIT 10""",
    },
    # ── C3(2026-07-05): 신규 데이터셋 무결성(수주/자본이벤트/사업지표) ─────────────
    {
        "name": "order_backlog_negative",
        "sev": "WARN",
        "desc": "수주잔고 < 0 (불가값 — 본문표 파싱 오류 신호, B1/B4)",
        "count": "SELECT count(*) FROM order_backlog WHERE backlog_amt < 0",
        "sample": "SELECT corp_code, fiscal_year, category, backlog_amt FROM order_backlog "
                  "WHERE backlog_amt < 0 ORDER BY backlog_amt LIMIT 10",
    },
    # ★"extended_financials_n_facts_outlier" 어서션 폐기(2026-09-01, 계층2 GC 트랙 —
    # docs/plans/extended_financials_v3_label_based_design_2026-09-01.md §3-4/§4-①).
    # extended_financials 뷰가 fact_v2(acode, 원시 다중매치 가능) 경유에서 extended_facts_v3
    # (라벨 기반, combine.py::_resolve() 가 이미 충돌을 해소한 단일값) 경유로 바뀌면서
    # n_facts 는 뷰 정의에서 상시 1로 고정됨 — 이 어서션이 감시하던 신호(같은 canonical 에
    # 무관 라인 다수 합산) 자체가 새 경로에선 발생할 수 없는 값이 되어 영구 0건(=무의미)이
    # 된다.
    #
    # ★대체 어서션 구현(2026-09-02, 백로그 항목4) — 설계문서 §4-①이 제안한 대로
    # `std_financials_v3.conflicts`(canonical별 combine.py::_resolve() 가 값 충돌로 보류한
    # 후보 목록) 기반. 옛 신호(같은 canonical 에 무관 라인 다수 합산)와 동일하진 않지만 —
    # "이 기간·이 canonical 은 후보가 갈려 자동 확정을 못 했다"는, 결측/오선택 원인후보로서
    # 더 정확한 신호다(코어 DIRECT_MAP 필드뿐 아니라 EXTENDED_CATALOG 확장 캐노니컬도 같은
    # dict 를 씀 — combine.py:1830 `_resolve()`). 실측(2026-09-02): 35,305행에 실제 충돌
    # 존재(전체 303,903행 중 11.6%), 최빈 canonical=bs.intangibles/is.cogs/is.sga/
    # is.noncontrolling_ni. WARN(참고 신호, 신규 휴리스틱이라 정착 전까지 게이트 승격 보류).
    {
        "name": "std_v3_conflicts_unresolved",
        "sev": "WARN",
        "desc": "조립 중 값 충돌로 보류된 canonical 존재 (결측/오선택 원인후보, extended_financials_n_facts_outlier 대체)",
        "count": "SELECT count(*) FROM std_financials_v3 "
                 "WHERE jsonb_typeof(conflicts)='object' AND conflicts <> '{}'::jsonb",
        "sample": "SELECT corp_code, fiscal_year, fiscal_period, statement_type, conflicts "
                  "FROM std_financials_v3 "
                  "WHERE jsonb_typeof(conflicts)='object' AND conflicts <> '{}'::jsonb "
                  "ORDER BY (SELECT count(*) FROM jsonb_object_keys(conflicts)) DESC LIMIT 10",
    },
    {
        "name": "capital_events_unknown_type",
        "sev": "WARN",
        "desc": "자본이벤트 event_type 미지값 (수집기 매핑 누락 신호, B2)",
        "count": "SELECT count(*) FROM capital_events WHERE event_type NOT IN "
                 "('paid_increase','free_increase','mixed_increase','reduction','cb_issue',"
                 "'bw_issue','eb_issue','treasury_acquire','treasury_dispose')",
        "sample": "SELECT corp_code, rcept_no, event_type FROM capital_events WHERE event_type NOT IN "
                  "('paid_increase','free_increase','mixed_increase','reduction','cb_issue',"
                  "'bw_issue','eb_issue','treasury_acquire','treasury_dispose') LIMIT 10",
    },
    {
        "name": "biz_metrics_util_impossible",
        "sev": "WARN",
        "desc": "가동률 > 500% (초과가동 교대·잔업 넘는 파싱 오류 — 계산근거/설비수량 오분류, B4)",
        "count": "SELECT count(*) FROM biz_metrics WHERE metric='utilization' AND value > 500",
        "sample": "SELECT corp_code, fiscal_year, segment, item, value FROM biz_metrics "
                  "WHERE metric='utilization' AND value > 500 ORDER BY value DESC LIMIT 10",
    },
    {
        # controlling_ni 총포괄 오염 재발 감지: 지배주주 귀속 '순이익'과 '총포괄손익'이 텍스트에서
        # 동일 축약 라벨로 나와 둘 다 is.controlling_ni 로 매핑 → max-abs 가 총포괄분(OCI 포함,
        # 더 큼)을 오선택하던 버그(build._collect 가 항등식으로 교정). 소급수정=fin2_fix_controlling_ni.py.
        #
        # ★ 판별식 정제(2026-07-15, docs/qa/triage_controlling_ni_residual_2026-07-14.md):
        # 단순 프록시 |controlling|>|net|*1.02 는 '정당한 비지배 음수'(controlling 손실>net 이 정상,
        # 양의 NCI 가 상쇄) 9,164 행을 오탐한다. 실제 신호는 회계 항등식 잔차이므로,
        # noncontrolling_ni 로 controlling+nci=net 이 성립하는(=정상) 행은 제외하고,
        # 항등식이 재구성되지 않는 행만 센다(진짜 총포괄 오염). std_v3 코어 컬럼엔 nci가 없어
        # is.noncontrolling_ni 후보를 조회한다.
        # ★2026-09-02(fact_v2 GC 트랙 §4-4 DROP 후속, 백로그 항목1 구현) — `fact_v2` 대신
        # `extended_facts_v3`(§4-2 재설계, combine.py::_resolve() 가 이미 충돌 해소를 끝낸
        # 단일값)에서 is.noncontrolling_ni 를 조회하도록 재소싱. 셀 단위 col_index/is_dimensional
        # 필터가 불필요해져(PK가 corp/fy/period/statement_type 뿐) 쿼리가 오히려 단순해짐 — 판정식
        # 자체(|controlling|>|net|*1.02 AND 항등식 잔차>임계)는 변경 없음. 재실측(2026-09-02):
        # 357건/223개사(과거 fact_v2 기준 ~6,950 과는 직접비교 불가 — 제외소스가 원시후보군에서
        # 단일 확정값으로 바뀌어 모집단이 다름). 표본 확인 결과 상위권 다수가 이 어서션이 원래
        # 잡던 '총포괄오염'이 아니라 controlling_ni 가 net_income 대비 정확히 ×10³~10⁶ 인
        # 단위오염(별도 버그류, statement_magnitude_impossible/unit_contamination 계열과 겹침) —
        # 이 어서션의 판정식 자체가 그 두 신호를 원래도 구분 못 했을 가능성이 있음, 별도 확인 과제.
        "name": "std_v2_controlling_ni_exceeds_net",
        "sev": "WARN",
        "desc": "controlling_ni 총포괄 오염 (항등식 controlling+nci=net 재구성 실패 — 정당 비지배음수는 제외)",
        "count": "SELECT count(*) FROM std_financials_v3 s WHERE "
                 "s.net_income IS NOT NULL AND s.controlling_ni IS NOT NULL AND s.net_income<>0 "
                 "AND ABS(s.controlling_ni) > ABS(s.net_income)*1.02 "
                 "AND ABS(s.net_income - s.controlling_ni) > ABS(s.net_income)*0.02 + 1000000 "
                 "AND NOT EXISTS (SELECT 1 FROM extended_facts_v3 e "
                 "  WHERE e.corp_code=s.corp_code AND e.fiscal_year=s.fiscal_year "
                 "  AND e.fiscal_period=s.fiscal_period AND e.statement_type=s.statement_type "
                 "  AND e.canonical_account='is.noncontrolling_ni' AND e.amount_won IS NOT NULL "
                 "  AND ABS(e.amount_won - (s.net_income - s.controlling_ni)) "
                 "      <= ABS(s.net_income)*0.02 + 1000000)",
        "sample": "SELECT s.corp_code, s.fiscal_year, s.fiscal_period, s.statement_type, "
                  "s.net_income, s.controlling_ni "
                  "FROM std_financials_v3 s WHERE "
                  "s.net_income IS NOT NULL AND s.controlling_ni IS NOT NULL AND s.net_income<>0 "
                  "AND ABS(s.controlling_ni) > ABS(s.net_income)*1.02 "
                  "AND ABS(s.net_income - s.controlling_ni) > ABS(s.net_income)*0.02 + 1000000 "
                  "AND NOT EXISTS (SELECT 1 FROM extended_facts_v3 e "
                  "  WHERE e.corp_code=s.corp_code AND e.fiscal_year=s.fiscal_year "
                  "  AND e.fiscal_period=s.fiscal_period AND e.statement_type=s.statement_type "
                  "  AND e.canonical_account='is.noncontrolling_ni' AND e.amount_won IS NOT NULL "
                  "  AND ABS(e.amount_won - (s.net_income - s.controlling_ni)) "
                  "      <= ABS(s.net_income)*0.02 + 1000000) "
                  "ORDER BY ABS(s.controlling_ni)-ABS(s.net_income) DESC LIMIT 10",
    },
    # ★"fact_v2_q1_duration_col0_eq_col1" 어서션 폐기(2026-09-02, 계층2 GC 트랙 §4-4 DROP
    # 후속, 백로그 항목1). DEF-4 재발 감지: Q1 분기보고서 IS/CF 표에서 당분기(col0)와
    # 전기(col1) 3개월 값이 완전 동일하면 전기컬럼 추출 오류 신호였다(fin2/extract/text.py
    # interim_flow 미적용 등). `fact_v2` DROP으로 상시 SKIP 됐던 것을, report_lines 기반
    # 재구현을 시도했으나 **구조적으로 불가능함을 확인**해 폐기로 결론 — `report_lines.py:1199`
    # `_is_loadable()`가 BS/IS/CF는 당기(col_index=0)만 적재한다(2026-07-30 결정, 전기 col1은
    # 그 자체가 DB에 없음). 즉 "같은 문서 안의 col0 vs col1 직접비교"라는 이 어서션의 판정
    # 방식 자체를 재현할 저장 데이터가 없다 — 재도입하려면 ①2026-07-30 정책을 뒤집어 col1도
    # 적재하거나(대형 재설계, 별도 트랙) ②추출 단계에서 즉시 비교해 별도 플래그 컬럼으로
    # 남기는(파이프라인 변경, SQL 어서션의 범위를 벗어남) 방법뿐. 대체 신호로 이미 살아있는
    # `calendar_adjacent_year_cq1_identical`(아래, std_financials_calendar 기반 — 같은 기업
    # 인접연도 CQ1 비교)을 이 DEF-4 재발 감지의 공식 대체로 삼는다 — 탐지 범위는 다르다(원문
    # 동일문서 col0/col1 비교가 아니라 소비계층의 연도간 비교)는 한계는 남아 있음.
    {
        # DEF-4 재발 감지(소비계층): 같은 기업·기준에서 인접연도 CQ1 매출·영업이익이 완전
        # 동일값이면 상류 전기컬럼 중복 추출의 결과일 수 있음. 잔여 소수(휴면·구 K-GAAP 우연)는
        # 정상 예외라 WARN. 진단 스크립트=scripts/diag_calendar_cq1_dup.py.
        "name": "calendar_adjacent_year_cq1_identical",
        "sev": "WARN",
        "desc": "인접연도 CQ1 매출+영업이익 완전동일 (상류 전기컬럼 중복 추출 신호, DEF-4)",
        "count": "SELECT count(*) FROM std_financials_calendar a JOIN std_financials_calendar b "
                 "ON a.corp_code=b.corp_code AND a.statement_type=b.statement_type "
                 "AND b.calendar_year=a.calendar_year+1 "
                 "WHERE a.calendar_period='CQ1' AND b.calendar_period='CQ1' "
                 "AND a.revenue IS NOT NULL AND a.revenue<>0 "
                 "AND a.revenue=b.revenue "
                 "AND a.operating_income IS NOT DISTINCT FROM b.operating_income",
        "sample": "SELECT a.corp_code, a.statement_type, a.calendar_year, b.calendar_year, a.revenue "
                  "FROM std_financials_calendar a JOIN std_financials_calendar b "
                  "ON a.corp_code=b.corp_code AND a.statement_type=b.statement_type "
                  "AND b.calendar_year=a.calendar_year+1 "
                  "WHERE a.calendar_period='CQ1' AND b.calendar_period='CQ1' "
                  "AND a.revenue IS NOT NULL AND a.revenue<>0 "
                  "AND a.revenue=b.revenue "
                  "AND a.operating_income IS NOT DISTINCT FROM b.operating_income LIMIT 10",
    },
    # ── 계층2 (2026-07-31 F1·F4) ────────────────────────────────────────────
    # 둘 다 **최근 filing 으로 범위를 좁혀** 돈다. note_lines 전량 스캔(75.9 GB heap)은
    # 야간 어서션에 부적합하고, 회귀 감시에는 '새로 적재된 것이 깨끗한가'면 충분하다.
    {
        "name": "unit_contamination",
        "sev": "ERROR",
        "sev_note": "재적재(2026-07-31) 후 0 확인 → ERROR 승격",
        "desc": "비금액 열(이자율·지분율·주식수·외화)인데 value_won 이 채워진 행 — 단위 오적용",
        # ★판정 규칙은 **로더와 같아야** 한다(fin2/extract/units.py). 초판은 2026-07-30 측정용
        #   정의(맨 % + 선언 접두 포함)를 그대로 써서, 재적재 후에도 2,401 행을 위반으로 셌다.
        #   전부 원문 대조로 **의도해서 제외한** 거짓양성 3종이었다:
        #     · '(단위: 천원, 천USD)>실행금액' — 'USD' 는 **표의 선언**이지 그 열의 성격이 아니다
        #     · '전기말>10% 상승시'            — 환위험 시나리오 열. 값은 천원 금액이다
        #     · '…>지분100%를 취득'            — 문장 속 '%'
        #   그래서 여기서도 ① '단위' 가 든 단(segment)을 걷어내고 ② '%' 는 단위로 쓰인 때만 본다.
        "count": """
            WITH x AS (
              SELECT n.value_won,
                     regexp_replace(n.col_label, '(^|>)[^>]*단위[^>]*', '', 'g') AS lbl
              FROM note_lines n
              WHERE n.rcept_no IN (SELECT rcept_no FROM filings ORDER BY rcept_no DESC LIMIT 200)
                AND n.value_won IS NOT NULL AND n.col_label IS NOT NULL)
            SELECT count(*) FROM x
            WHERE lbl ~ '(\(\s*%\s*\)|%\s*(>|$)|율|률|비율|주당|수량|주수|배수|USD|EUR|JPY'
                        '|외화|주식수|소유주식|보유주식|발행주식|의결권|일수|적수|천주|백만주'
                        '|인원|건수|톤)'
        """,
        "sample": """
            WITH x AS (
              SELECT n.rcept_no, n.col_label, n.label_raw, n.value_won,
                     regexp_replace(n.col_label, '(^|>)[^>]*단위[^>]*', '', 'g') AS lbl
              FROM note_lines n
              WHERE n.rcept_no IN (SELECT rcept_no FROM filings ORDER BY rcept_no DESC LIMIT 200)
                AND n.value_won IS NOT NULL AND n.col_label IS NOT NULL)
            SELECT rcept_no, col_label, label_raw, value_won FROM x
            WHERE lbl ~ '(\(\s*%\s*\)|%\s*(>|$)|율|률|비율|주당|USD|주식수)'
            ORDER BY abs(value_won) DESC LIMIT 10
        """,
    },
    {
        "name": "daily_body_load",
        "sev": "WARN",
        "desc": "최근 30일 다운로드 완료 보고서인데 report_lines 가 0행 — 데일리 본문 배선 사고"
                "(2026-07-31 F4 이전에는 상시 위반이었다). 백필 미실행분도 여기 잡힌다",
        "count": """
            SELECT count(*) FROM download_tasks d JOIN filings f USING (rcept_no)
            WHERE d.status='completed' AND d.file_type='xml' AND d.file_path IS NOT NULL
              AND d.created_at > CURRENT_DATE - 30 AND f.fiscal_year >= 2015
              AND NOT EXISTS (SELECT 1 FROM report_lines r WHERE r.rcept_no = f.rcept_no)
        """,
        "sample": """
            SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period
            FROM download_tasks d JOIN filings f USING (rcept_no)
            WHERE d.status='completed' AND d.file_type='xml' AND d.file_path IS NOT NULL
              AND d.created_at > CURRENT_DATE - 30 AND f.fiscal_year >= 2015
              AND NOT EXISTS (SELECT 1 FROM report_lines r WHERE r.rcept_no = f.rcept_no)
            LIMIT 10
        """,
    },
]


# ── C11 · 완전성(completeness) 매트릭스 ──────────────────────────────────────
# corporations 에 상장일이 없어 "상장 이후 전체 이력"을 재구성할 순 없다(6/25 전수검증이
# 그건 이미 1회 증명함 — verify_corp_sequential.py). 대신 **향후 신규 공백**(신규상장 누락·
# 지연공시·정정드리프트)을 잡는 최신성(staleness) 검사: 기업별 결산월 기준으로 "이미 법정
# 제출기한이 지난 가장 최근 분기"가 실제로 std_financials_v2 에 존재하는지 확인한다.
_DEADLINE_DAYS_BY_QUARTER = {1: 45, 2: 45, 3: 45, 4: 90}   # Q1/반기/Q3=45일, 사업보고서=90일
_GRACE_DAYS = 15                                            # 정정·DART 처리 지연 여유(오탐 방지)


def _add_months(y: int, m: int, n: int) -> tuple[int, int]:
    total = y * 12 + (m - 1) + n
    return total // 12, total % 12 + 1


def _fiscal_quarter_ends(fiscal_month: int, fy_label_year: int) -> list[tuple[int, date]]:
    """결산월 fiscal_month, 회계연도 라벨 fy_label_year 의 4분기 말일 [(quarter_no, date), ...]."""
    fy_start_m = fiscal_month % 12 + 1
    fy_start_y = fy_label_year if fiscal_month == 12 else fy_label_year - 1
    out = []
    for k in (1, 2, 3, 4):
        y2, m2 = _add_months(fy_start_y, fy_start_m, 3 * k - 1)
        last_day = calendar.monthrange(y2, m2)[1]
        out.append((k, date(y2, m2, last_day)))
    return out


def _latest_due_period_end(fiscal_month: int, today: date) -> date:
    """오늘 기준, 이미 법정기한(+여유)이 지난 가장 최근 분기말일."""
    candidates: list[date] = []
    for fy_label_year in (today.year - 1, today.year, today.year + 1):
        for k, period_end in _fiscal_quarter_ends(fiscal_month, fy_label_year):
            deadline = period_end + timedelta(days=_DEADLINE_DAYS_BY_QUARTER[k] + _GRACE_DAYS)
            if deadline <= today:
                candidates.append(period_end)
    return max(candidates)


def check_completeness(session) -> tuple[int, list[tuple]]:
    """활성 정기보고 대상 기업 중, 이미 기한이 지난 최신 분기가 DB에 없는 기업 수·표본."""
    today = date.today()
    corps = session.execute(text(
        "SELECT corp_code, corp_name, fiscal_month, dart_modify_date FROM corporations "
        "WHERE is_active AND coverage_class = 'periodic'"
    )).fetchall()

    # is_stub 은 제외하지 않는다 — 결산월 변경 전환기간(예: 9월→12월)도 실제 제출·처리된 유효
    # 데이터라 "커버리지 있음"으로 인정해야 함(제외하면 아시아종묘류 오탐 발생, 2026-07-04 확인).
    # 2026-09-01: std_financials_v2→v3. v3엔 is_stub/is_discrete 컬럼 자체가 없다(PK가
    # (corp,fy,fp,basis) 뿐이라 그런 중복행이 없음) — 조건 삭제.
    latest = dict(session.execute(text(
        "SELECT corp_code, max(period_end) FROM std_financials_v3 "
        "GROUP BY corp_code"
    )).fetchall())

    stale: list[tuple] = []
    for corp_code, corp_name, fiscal_month, dart_modify_date in corps:
        expected = _latest_due_period_end(fiscal_month or 12, today)
        # 상장일 컬럼이 없어 대신 DART 레코드 최종변경일(신규상장 시 최근으로 찍힘)을 프록시로
        # 사용 — 그 시점이 기대 분기말보다 나중이면 "그 시점엔 존재하지 않았을 기업"이라 스킵
        # (신규상장 오탐 방지, 2026-07-04 확인 — 저스텍/스트라드비젼 등 6월~7월 신규상장 5사).
        if dart_modify_date:
            try:
                dmd = date(int(dart_modify_date[:4]), int(dart_modify_date[4:6]), int(dart_modify_date[6:8]))
                if dmd > expected:
                    continue
            except (ValueError, TypeError):
                pass
        have = latest.get(corp_code)
        if have is None or have < expected:
            stale.append((corp_code, corp_name, str(have), str(expected)))
    return len(stale), stale


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true", help="위반 표본행도 출력")
    args = ap.parse_args()

    n_error_viol = 0
    n_warn_viol = 0
    print("===== DQ 어서션 =====")
    with get_session() as s:
        for chk in CHECKS:
            try:
                cnt = s.execute(text(chk["count"])).scalar() or 0
            except Exception as exc:  # noqa: BLE001
                # 레거시 테이블이 드롭되면(예 extended_financials, P5 컷오버) 어서션 하나
                # 때문에 **나머지 전부가 안 돈다**. 건너뛰고 계속한다(2026-07-31 실측 사고).
                s.rollback()
                print(f"  ⏭ [SKIP ] {chk['name']:<32} — {type(exc).__name__}: "
                      f"{str(exc).splitlines()[0][:80]}")
                continue
            mark = "✅" if cnt == 0 else ("❌" if chk["sev"] == "ERROR" else "⚠")
            print(f"  {mark} [{chk['sev']:<5}] {chk['name']:<32} 위반 {cnt:,} — {chk['desc']}")
            if cnt:
                if chk["sev"] == "ERROR":
                    n_error_viol += 1
                else:
                    n_warn_viol += 1
                if args.sample and chk.get("sample"):
                    for r in s.execute(text(chk["sample"])).fetchall():
                        print(f"        {tuple(r)}")

        n_stale, stale_sample = check_completeness(s)
        mark = "✅" if n_stale == 0 else "⚠"
        print(f"  {mark} [WARN ] {'completeness_staleness':<32} 위반 {n_stale:,} — "
              f"기한(+{_GRACE_DAYS}일 여유) 지난 최신분기 미존재 기업(C11)")
        if n_stale:
            n_warn_viol += 1
            if args.sample:
                for row in stale_sample[:10]:
                    print(f"        {row}")

    print(f"\nERROR 위반 어서션 {n_error_viol} · WARN 위반 어서션 {n_warn_viol}")
    print("✅ 무결성 OK" if n_error_viol == 0 else f"❌ ERROR 어서션 {n_error_viol}건 위반")
    sys.exit(1 if n_error_viol else 0)


if __name__ == "__main__":
    main()
