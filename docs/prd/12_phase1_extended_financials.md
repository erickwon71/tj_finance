# PRD 12 — Phase 1: extended_financials 뷰 + 차트빌더 노출

> 마스터 계획: `10_gap_fill_plan.md`. 체크리스트: `10_16_checklist.md`. 권장 모델: **Sonnet**
> (SQL 뷰 + 카탈로그 노출, 패턴이 명확한 구현).

## 0. 왜 이 PRD 인가

fact_v2 에는 이미 goodwill·자기주식·이자지급·EPS 등 ~30개 캐노니컬 계정이 파싱돼 있지만
std_financials_v2 wide 테이블에 컬럼이 없어 앱에서 볼 방법이 없다. std_v2 컬럼을 추가하는 정공법은
건당 6개 접점(models/migration/rules/build/분기·달력 전파/뷰 재생성)이 필요해 30종 전체엔 과중하다.
대신 **읽기 전용 long 뷰 하나**로 저비용에 전부 노출한다(마스터 PRD 결정 1).

## 1. 목표

- `extended_financials` SQL 뷰 생성 — fact_v2 × statement_source 조인, dedup 은 statement_source
  의 기존 rcept 선택 로직에 편승.
- 자유조합 차트빌더에서 이 뷰의 계정들을 선택 가능하게 만든다(카테고리 그룹 피커 포함).

## 2. 범위

- 뷰는 **연간(FY) only**, 연결/별도(basis) 모두. 비차원(non-dimensional) 당기(col_index=0) 값만.
- 대상 계정: `concept_map.py` 의 canonical vocabulary 중 std_v2 컬럼에 없는 전체 집합(Phase 0 Pass 1
  이 정량 리스트 제공 — 그 결과를 참고해 `app/registry/extended.py` 카탈로그 확정).
- 차트빌더: 기존 46종 큐레이트 지표 선택은 그대로, **병행** 카테고리로 extended 항목 추가.

## 3. 비범위

- 분기 그레인 노출(H1/Q3 누적 as-filed 이산화는 재구현 필요 — 결정 5 보류).
- 스크리너 필터 연동(향후 검토).
- std_v2 wide 컬럼 자체를 늘리는 것(의도적으로 피함).

## 4. 데이터 플로우

### 4.1 DB — extended_financials 뷰

`collector/db.py::_run_migrations` 에 `schema_migrations` 거버넌스를 따르는 신규 마이그레이션
(`2026_07_extended_financials_view`, 멱등 `CREATE OR REPLACE VIEW`) 추가:

```sql
CREATE OR REPLACE VIEW extended_financials AS
SELECT f.corp_code, ss.fiscal_year, ss.fiscal_period, ss.basis,
       f.canonical_account, SUM(f.amount_won) AS amount_won,
       COUNT(*) AS n_facts, ss.source_rcept_no
FROM statement_source ss
JOIN fact_v2 f ON f.rcept_no = ss.source_rcept_no
  AND f.corp_code = ss.corp_code
  AND f.report_fiscal_year = ss.fiscal_year
  AND f.report_fiscal_period = ss.fiscal_period
  AND f.basis = ss.basis
WHERE NOT ss.is_stub
  AND f.col_index = 0
  AND NOT f.is_dimensional
  AND f.canonical_account IS NOT NULL AND f.amount_won IS NOT NULL
  AND CASE left(f.canonical_account,3) WHEN 'bs.' THEN 'BS'
      WHEN 'is.' THEN 'IS' WHEN 'cf.' THEN 'CF' END = ss.statement
GROUP BY 1,2,3,4,5,8;
```

**핵심 설계 노트**:
- `SUM(amount_won)` 은 의도적 — leaf-additive 캐노니컬(예: `bs.lease_liability` = 유동+비유동
  두 acode 합)이 있으므로 그룹 합산이 맞는 값을 만든다. `n_facts` 로 이상(예: 예상외로 많은 라인
  합산) 을 감지 가능하게 남겨둔다.
- `CASE ... = ss.statement` 조건은 canonical prefix(bs./is./cf.) 로 올바른 statement_source 행과
  매칭시키기 위함 — BS 계정이 IS 소스 rcept 와 잘못 조인되는 것 방지.
- `eps_basic`/`eps_diluted` 는 원/주 단위 — 억원 단위가 아니므로 카탈로그에서 반드시 별도 UnitType
  으로 표시(억원 스케일로 나누면 안 됨).

### 4.2 앱 — 카탈로그·소스·빌더 노출

- **`app/registry/extended.py`**(신규): `EXTENDED_CATALOG: dict[str, ExtSpec]` — 약 30개 항목,
  각각 `canonical_account`(예: `"bs.goodwill"`), `name_ko`, `unit`(UnitType), `statement`.
  한글 라벨은 수기 작성(concept_map.py 주석의 한글명을 1차 소스로 사용).
- **`app/data/extended.py`**(신규): `load_extended_series(corp_code, basis) -> DataFrame` —
  extended_financials 뷰 단일 쿼리.
- **`app/compute/sources.py`**(신규): `fetch_ext_frame(corp_code, specs, grain, basis) -> DataFrame`
  — `resolver.build_metric_frame` 과 **동일 tidy 스키마**(period_label/period_end/metric_id/name/
  unit/value) 로 반환해 기존 `chart_panel.render_metric_chart`/CSV/프리셋 로직을 무변경 재사용.
  grain != "annual" 이면 빈 프레임 + 안내 캡션(분기 미지원).
- **`app/cache.py`**: `extended_series(corp_code, basis)` 캐시 함수 추가(TTL_HEAVY 등급).
- **`app/views/chart_builder_page.py`**: 기존 플랫 `st.multiselect` 를 카테고리 그룹 피커로 개편
  (기존 4개 Category + 신규 "extended" 카테고리). 이 개편은 Phase 5 의 다른 UI 작업과 겹치지 않도록
  Phase 1 에서는 **그룹핑 + extended 카테고리 추가**까지만, yoy/ttm 등 신규 연산은 Phase 5 로 분리.
- **`scripts/dq_assertions.py`**: `n_facts` 이상 감지 어서션 추가(예: 특정 캐노니컬에 대해
  n_facts > 4 인 행 비율이 임계치 초과 시 WARN — 실제 회계상 다분류 라인이 있을 수 있어 ERROR 아님).

## 5. 검증

- **삼성전자 FY2023** 등 알려진 대기업 goodwill/자기주식/이자지급을 DART 원문(사업보고서 재무상태표/
  현금흐름표)과 대조 — 뷰 값이 정확히 일치하는지 확인.
- `bs.lease_liability`(2개 leaf acode 합산 케이스)의 SUM 이 유동+비유동 리스부채 합과 일치하는지
  별도 검증.
- 차트빌더에서 extended 카테고리 선택 → 차트 렌더 → CSV export 까지 수동 확인(AppTest 무예외).
- `fin2/tests` 에 statement-prefix CASE 매칭 단위 테스트 추가(BS/IS/CF 각 1개 캐노니컬로 매칭 검증).

## 6. 사용자 실행

- 없음 — 뷰는 `CREATE VIEW` 즉시 반영(백필 불필요, 기존 fact_v2/statement_source 데이터 그대로 소비).

## 7. 완료 기준

- 뷰 존재 + 마이그레이션 멱등(재실행 시 스킵) 확인.
- `EXTENDED_CATALOG` 에 Phase 0 Pass 1 이 식별한 미승격 캐노니컬 전량 등재.
- 차트빌더에서 extended 카테고리 선택 → 정상 차트 렌더, 기존 46종 지표 기능 무회귀.
