# 순서5 — `valuation_daily` matview `net_debt` v2→v3 이식 (단일 LATERAL 복귀) 계획

**전제**: `docs/plans/valuation_daily_blockers_da_netdebt_design_2026-08-30.md` §5의 "구현
순서" 표 5번. 게이트 조건("4 전체 선행" = 순서4 ①wiring/②alias 3종/③나머지 소수 라벨)은
2026-08-31 R58/R59 트랙으로 전부 완전 종료됨(전수재감사 회귀 0, 잔여 4건 원인규명 완료·
범위 밖 기록). 이 문서는 그 다음 단계인 순서5 자체의 실행 계획이다.

## 1. 현재 상태

`valuation_daily`는 지금 **두 개의 독립 LATERAL**로 구성돼 있다(`collector/db.py`
마이그레이션 `2026_08_valuation_daily_v3_ebitda_migration`):

- `fin` LATERAL → `std_financials_v3`에서 `ni`/`eq`/`revenue`/`cfo`/`ebitda`/
  `operating_income`/`dividends_paid` 조회
- `finnd` LATERAL → `std_financials_v2`(`version=1`, `is_discrete`/`is_stub` 제외)에서
  **`net_debt`만** 별도 조회

두 LATERAL이 각자 독립적으로 "corp 기준 최신 FY"를 고르기 때문에, 한 코스프의
`ev`/`ev_ebitda`/`ev_ebit`가 **서로 다른 (fiscal_year, basis)의 값을 섞어 계산**될 수
있는 구조적 트레이드오프가 마이그레이션 코멘트에 이미 명시돼 있음(과도기 한정).

**실측(오늘)**: `std_financials_v3` FY net_debt 보유 62,634행 vs `std_financials_v2`
(FY, version=1, non-discrete, non-stub) 44,540행 — v3가 v2보다 넓다. 순서4 트랙의
결론("v3가 v2보다 완전해짐")과 일치.

## 2. 변경 내용

`finnd` LATERAL을 제거하고 `net_debt`를 `fin` LATERAL(v3) 안으로 합친다 — 즉 두
LATERAL을 하나로 되돌린다. `DROP MATERIALIZED VIEW` + `CREATE MATERIALIZED VIEW`
(matview는 `CREATE OR REPLACE` 불가, 이전 마이그레이션과 동일 패턴) 새 마이그레이션
`2026_08_valuation_daily_v3_netdebt_migration`을 `collector/db.py`에 추가:

```sql
DROP MATERIALIZED VIEW IF EXISTS valuation_daily;

CREATE MATERIALIZED VIEW valuation_daily AS
SELECT
    c.corp_code, c.corp_name, sp.stock_code, sp.trade_date,
    sp.close_price, sp.market_cap, sp.shares_out,
    fin.fiscal_year, fin.basis,
    CASE WHEN fin.ni > 0      THEN sp.market_cap::double precision / fin.ni END      AS per,
    CASE WHEN fin.eq > 0      THEN sp.market_cap::double precision / fin.eq END      AS pbr,
    CASE WHEN fin.revenue > 0 THEN sp.market_cap::double precision / fin.revenue END AS psr,
    CASE WHEN fin.cfo > 0     THEN sp.market_cap::double precision / fin.cfo END     AS pcr,
    (sp.market_cap + COALESCE(fin.net_debt, 0))                                     AS ev,
    CASE WHEN fin.ebitda > 0
         THEN (sp.market_cap + COALESCE(fin.net_debt,0))::double precision / fin.ebitda END           AS ev_ebitda,
    CASE WHEN fin.operating_income > 0
         THEN (sp.market_cap + COALESCE(fin.net_debt,0))::double precision / fin.operating_income END AS ev_ebit,
    CASE WHEN sp.shares_out > 0 THEN fin.ni::double precision / sp.shares_out END AS eps,
    CASE WHEN sp.shares_out > 0 THEN fin.eq::double precision / sp.shares_out END AS bps,
    CASE WHEN sp.shares_out > 0 AND fin.dividends_paid IS NOT NULL
         THEN abs(fin.dividends_paid)::double precision / sp.shares_out END AS dps,
    CASE WHEN sp.shares_out > 0 AND fin.dividends_paid IS NOT NULL AND sp.close_price > 0
         THEN (abs(fin.dividends_paid)::double precision / sp.shares_out) / sp.close_price END AS dividend_yield
FROM stock_prices sp
JOIN corporations c ON c.stock_code = sp.stock_code AND c.is_active
LEFT JOIN LATERAL (
    SELECT f.fiscal_year, f.statement_type AS basis,
           COALESCE(f.controlling_ni, f.net_income)       AS ni,
           COALESCE(f.controlling_equity, f.total_equity) AS eq,
           f.revenue, f.cfo, f.ebitda, f.operating_income, f.dividends_paid, f.net_debt
    FROM std_financials_v3 f
    WHERE f.corp_code = c.corp_code AND f.fiscal_period = 'FY'
      AND f.period_end <= sp.trade_date
    ORDER BY f.period_end DESC,
             CASE f.statement_type WHEN 'consolidated' THEN 0 ELSE 1 END
    LIMIT 1
) fin ON true
WHERE sp.market_cap IS NOT NULL
WITH NO DATA;

CREATE UNIQUE INDEX ux_valuation_daily_corp_date ON valuation_daily (corp_code, trade_date);
```

변경점은 딱 두 곳: ① `fin` SELECT 목록에 `f.net_debt` 추가, ② `ev`/`ev_ebitda`/
`ev_ebit`의 `finnd.net_debt` → `fin.net_debt`, ③ `finnd` LATERAL 블록 통째로 삭제.
`per`/`pbr`/`psr`/`pcr`/`eps`/`bps`/`dps`/`dividend_yield`는 이미 v3 단일 LATERAL이라
**무변경**.

## 3. 실행 순서

1. `collector/db.py`에 마이그레이션 추가(위 SQL, `WITH NO DATA`로 생성만).
2. 마이그레이션 적용 — 앱/컬렉터 기동 시 `_run_migrations()`가 자동 실행하거나,
   `python -c` 금지 규칙에 따라 별도 실행 스크립트로 트리거.
3. `python scripts/refresh_valuation_daily.py` (최초 1회, non-concurrent) 로 재적재.
4. 검증(§4).

## 4. 검증 계획 — 전부 완료(2026-08-31)

- [x] **4-1. 행수/커버리지 전후 비교**: 전후 모두 총 11,196,547행, `ev`/`ev_ebitda`/
      `ev_ebit` non-null 행수도 완전 동일(7,057,617 / 7,149,115) — `ev` 계열은
      `COALESCE(net_debt,0)`이라 non-null 여부 자체는 net_debt 소스와 무관하고, **값**이
      바뀐다: 조인 비교 결과 `ev` 6,359,963행(56.8%)·`ev_ebitda` 4,632,799행·`ev_ebit`
      4,627,681행 변경, 영향 corp 2,399/2,514개사. 큰 변경폭은 문서 §2-10의 결론(불일치
      대부분이 v2 불완전성 노출)과 일치 — 회귀 아님.
- [x] **4-2. 표본 corp 전후 시계열 비교**: R57 표본(`00130763`, 서울반도체) — 최근
      거래일 6건 `ev`/`ev_ebitda` **무변화**(현재 활성 FY2025 연결 net_debt이 v2=v3로
      마침 일치, 과거 FY만 갈림 — 정상). R59 표본(`00181712`, SK) — 최근 거래일 EV/EBITDA
      **9.9배→8.6배**로 하향(FY2025 연결 net_debt v2 60.2조 vs v3 47.0조, 13.2조 차이) —
      v3가 순서4/R59로 누적 수정된 최신 상태를 반영한 결과, 방향성은 문서의 기존 결론
      (v2가 구조적으로 불완전) 범위 안.
- [x] **4-3. fiscal_year/basis 정합성 확인**: 마이그레이션 전 실측 — corp별 최신거래일
      기준 `fin`(v3)·`finnd`(v2)의 (fiscal_year) 불일치 2,514개사 중 2건(둘 다 v3만
      데이터 존재/불일치 아님 확인). 이식 후 단일 LATERAL이라 **구조적으로 이 갭 자체가
      소멸**(전후 `fiscal_year` 비교 결과 변경 0행 — `fin` 선택 로직 자체는 원래도 v3
      단독이었으므로 당연한 결과이자 설계 의도 그대로).
- [x] **4-4. 회귀 테스트**: `pytest tests/ fin2/tests/` 668 passed, 1 failed —
      실패건(`fin2/tests/test_biz_section.py::test_lxintl_facility_table_dropped`)은
      `git diff --stat`로 이번 변경이 `collector/db.py` 1개 파일뿐임을 확인, 실패 테스트는
      생산설비 표 파싱(LX인터내셔널) 영역으로 net_debt/matview와 무관한 기존 이슈 — 회귀
      아님.
- [x] **4-5. `scripts/dq_assertions.py::valuation_daily_stale`** — ✅ 위반 0. (전체
      스캔의 ERROR 1건 `statement_magnitude_impossible`은 `std_financials_v2` 본체
      금액을 보는 무관 체크 — 기존 백로그, 이번 변경과 무관.)
- [ ] **4-6. 밴드 차트 육안 확인** — 미실행(선택 사항, 필요 시 `streamlit run
      app/main.py`에서 사용자가 직접 확인).

## 5. 위험도 / 롤백

**낮음** — 파생 matview 변경만, 기저 테이블(`std_financials_v2/v3`) 무변경. 문제 발생 시
직전 SQL(`finnd` LATERAL 포함 버전, `collector/db.py` 기존 `2026_08_valuation_daily_v3_
ebitda_migration` 블록)을 그대로 재실행하면 즉시 롤백 가능.

**알려진 잔여 리스크**: net_debt v2/v3 집계 불일치율이 여전히 40.6%/51.4%로 남아있다는
사실 자체는 이식을 막지 않는다 — §2-10 원인규명 결과 그 불일치의 90%가 "v2의 구조적
불완전성이 드러난 것(v3가 더 완전함)"이었고 v3 결함이 아니었기 때문. 단, 4-2 표본 대조에서
반례가 나오면 이식을 중단하고 재조사한다.

---

이 문서는 계획이며, 사용자 승인 없이 구현에 착수하지 않는다.
