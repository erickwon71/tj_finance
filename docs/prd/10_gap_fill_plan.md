# PRD 10 — 전문 서비스 갭 채우기 마스터 계획 (데이터 항목 확충 + 전수 인벤토리 감사 + 자유조합 차트 강화)

> 작성 2026-07-12. 총괄: `00_pm_master_plan.md`. 마스터 계획 원본: `~/.claude/plans/cosmic-stirring-snail.md`.
> Phase별 상세 PRD: `11_phase0_inventory_audit.md` ~ `16_phase5_chart_builder.md`.
> 진행 체크리스트(+Phase별 권장 모델): `10_16_checklist.md`.

## 0. 왜 이 PRD 인가

프로젝트 원목표(정기 공시 재무데이터+주석 정보 → DB → 시각화)는 v1.0으로 완성됐으나,
CompanyGuide/버틀러 등 전문 서비스와 비교하면 **데이터 항목**에 갭이 있다. 이 PRD 는
그 갭을 체계적으로 채우는 마스터 계획이다.

### 사용자 확정 사항 (2026-07-12)
- **소스 범위: DART 공시 내로 한정** — 컨센서스/기관·외국인 수급/신용등급 등 외부·유료 소스 제외.
- **우선순위(4개 전부)**: ① 주주환원(배당·자사주) ② 부문·지역별 실적 ③ 주석 상세(비용성격 등)
  ④ 회사 일반현황(직원·보수·출자).
- **누락 감사 깊이: 전수 인벤토리 감사** — 보고서 내 숫자 표 전체를 항목 단위로
  '수집됨/미수집/수집불가' 매트릭스화.
- 자유조합 차트에서 수집된 모든 항목을 쉽게 조합해 볼 수 있어야 함.

## 1. 현황 — 3대 갭 유형 (2026-07-12 탐색 확정)

1. **DB에 이미 있는데 안 보이는 것**: `fin2/taxonomy/concept_map.py`가 매핑하는 ~30개 캐노니컬 계정이
   fact_v2 에 파싱돼 있으나 std_financials_v2 wide 컬럼이 없어 앱에서 접근 불가.
   - BS: goodwill, paid_in_capital, capital_surplus, treasury_stock, noncontrolling_interest,
     lease_liability, pension_liability, investment_property, deferred_tax_asset/liability,
     investments_in_subsidiaries, short/long_term_investment 등
   - IS: finance_income, finance_cost, other_income/expense, eps_basic, eps_diluted,
     noncontrolling_ni, oci, total_comprehensive_income
   - CF: borrowings_proceeds/repaid, bond_repaid, interest_paid/received, tax_paid,
     treasury_stock_purchase, dividends_received, fx_effect_on_cash, beginning/ending_cash,
     lease_repaid, acquisition_of_subsidiaries 등
2. **미수집 — DART 구조화 API 존재(쉬움)**: alotMatter(배당에 관한 사항),
   tesstkAcqsDspsSttus(자기주식 취득·처분 현황), empSttus(직원 현황),
   otrCprInvstmntSttus(타법인 출자현황), hmvAuditAllSttus/indvdlByPay(임원보수 전체/개인별).
   모두 corp_code+bsns_year+reprt_code 컨벤션(기존 exctvSttus/hyslrSttus 와 동일).
3. **미수집 — 본문/주석 표 파싱 필요**: 매출실적 표(부문×수출/내수), 비용의 성격별 분류 주석,
   차입금 만기구조 주석(→보류), IFRS8 영업부문 주석(→보류).
4. **자유조합 차트 한계**: 46개 큐레이트 지표만 선택 가능(플랫 목록), 원시 컬럼·PER/PBR 시계열·
   biz_metrics·수주잔고 등 접근 불가, 파생연산 3종(비율/차분/주당)뿐, 다기업 비교 불가.

## 2. 핵심 아키텍처 결정

### 결정 1 — 미승격 캐노니컬 ~30종: std_v2 wide 컬럼 추가 대신 **`extended_financials` long 뷰**

std_v2 컬럼 추가는 건당 6개 접점(models/migration/rules/build/분기/달력 전파+뷰 재생성)이라 과중.
대신 `fact_v2 × statement_source` 조인 뷰 하나로 전부 해결 — statement_source 가 이미 rcept 승자를
선택했으므로 dedup 공짜, 향후 concept_map 추가 계정도 자동 노출.

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
  AND f.col_index = 0            -- 당기 컬럼만
  AND NOT f.is_dimensional       -- SCE/차원 fact 제외
  AND f.canonical_account IS NOT NULL AND f.amount_won IS NOT NULL
  AND CASE left(f.canonical_account,3) WHEN 'bs.' THEN 'BS'
      WHEN 'is.' THEN 'IS' WHEN 'cf.' THEN 'CF' END = ss.statement
GROUP BY 1,2,3,4,5,8;
```

- SUM 은 의도적(leaf-additive 캐노니컬: lease_liability=유동+비유동 등). `n_facts` 로 이상 감지.
- v1은 **연간(FY)만 앱 노출** — H1/Q3 는 누적 as-filed 라 이산화 재구현 회피(한계 명시).
- 일반 뷰(비 matview) — 기업 단위 조회는 인덱스 경로라 충분. 스크리너 소비 시점에 materialize 재검토.

### 결정 2 — 주주환원: 신규 API 수집 + 앱측 파생 + 신규 탭

- `collector/dart_periodic.py` 신규 1모듈에 6개 정기보고서 API 공통루프(dart_extra.py 패턴).
  각 API별 파싱 테이블 + raw JSONB 보존.
- 파생지표(배당성향·총주주환원율=(배당+자사주순취득)/지배NI 또는 FCF)는 **앱측**(pandas) 계산 —
  DB 뷰 추가 없이 `app/data/shareholder_return.py` 단일 쿼리 조인.
- company_page 에 **신규 "💸 주주환원" 탭**(radio 목록이라 추가 저렴). 자사주 금액 폴백:
  treasury_activity → extended_financials 의 cf.treasury_stock_purchase.

### 결정 3 — 부문·수출/내수 매출: biz_section 인프라 재사용, biz_metrics 에 `channel` 컬럼 추가

- 소스는 II.사업의 내용 '매출실적/판매실적' 표 (IFRS8 주석 아님 — 주석은 이질성 높아 보류).
- `biz_section.py` 의 `_SALES_KW` 가드가 현재 매출표를 **버리고** 있음 → 캡처로 전환.
- 신규 테이블 대신 `biz_metrics.channel VARCHAR(12)`(수출/내수/합계) 가산 마이그레이션 +
  `metric='sales'` — 기존 sync/로더/멱등성 전부 재사용. 수출비중 = 파생 비율.

### 결정 4 — 비용의 성격별 분류 주석: 포함 (Phase 4)

급여/원재료 확보 + **D&A→EBITDA 커버리지 상승**(현재 연결 42% 천장 돌파) 이중 효과.
검증된 note.* 채널 재사용: rules.py `_DA_TOTAL_CANON` 이 이미 note.da_total 소비,
cf_da_sync.py 가 영속화 패턴(주석파서→합성 fact→재표준화→분기→달력) 확립.

### 결정 5 — 보류 (ROI 불리, Phase 0 인벤토리 결과 보고 재검토)

차입금 만기구조 주석 · IFRS8 영업부문 주석 · extended 분기 그레인 · 주주환원 스크리너 통합.
(차입금 총액·리스부채·차입/상환 CF는 결정 1로 이미 노출됨.)

### 결정 6 — 자유조합 차트: 레지스트리 병행 확장 카탈로그 + 얇은 소스 디스패치

기존 `METRIC_REGISTRY`/`resolver` 불변. 병행 카탈로그 + kind별 fetcher:
- `app/registry/extended.py`: kind별 스펙 — "extended"(~30개 수기 한글라벨), "biz", "dividend",
  "employee", "valuation"(PER/PBR/PSR/EV-EBITDA/배당수익률 시계열).
- `app/compute/sources.py::fetch_ext_frame` → `build_metric_frame` 과 동일 tidy 스키마 출력
  (차트/표/CSV/프리셋 전부 무변경 재사용). 연간 그레인 가드(캡션 안내).
- UI: 플랫 multiselect → 카테고리 그룹 피커, 파생연산 yoy/ttm 추가, 다기업 비교 모드.

### 결정 7 — 전수 인벤토리 감사: 2-pass

- **Pass 1 (SQL, 수 분)**: fact_v2 미매핑 acode 상위 빈도, 미승격 캐노니컬별 행수·corp×fy 커버,
  기존 테이블별 연도 커버.
- **Pass 2 (표본 심층, 30~60분)**: `scripts/audit_table_inventory.py` — 층화표본 ~300사
  (시장×업종×규모) × {최신 사업보고서, 2020, 2016}. TABLE 요소 순회(expand_table_grid 재사용),
  수치셀 ≥30% = 숫자표, 직전 헤딩 키워드 분류(~40개 항목 유형), `ITEM_STATUS` 맵과 대조.
- **산출물**: `docs/data_inventory_matrix.md` — 항목|절|최적소스|상태|출현빈도 매트릭스.
  이후 각 Phase 완료 시 상태 갱신 (누락 감사 목표의 수용 기준 문서).
- 선택: 189K 파일 전수 제목-레벨 스캔(정규식, 파싱 없음) — 사용자 실행, 옵션.

## 3. Phase 개요 (각 Phase = 세션 1개 규모; 0·1·3·4 상호 독립)

| Phase | 내용 | DART 쿼터 | 상세 PRD |
|---|---|---|---|
| 0 | 전수 인벤토리 감사 (최우선 — 3~5단계 리스크 제거) | 0 | 11 |
| 1 | extended_financials 뷰 + 차트빌더 노출 | 0 | 12 |
| 2 | 주주환원 + 회사 일반현황 6 API 수집 | 백필 ~4~7일 야간 | 13 |
| 3 | 부문·수출/내수 매출 파서 | 0 (로컬 파일) | 14 |
| 4 | 비용의 성격별 주석 파서 + EBITDA 상승 | 0 (로컬 파일) | 15 |
| 5 | 차트빌더 고급 기능 (yoy/ttm·밸류에이션 시계열·다기업 비교) | 0 | 16 |

## 4. 검증 총칙 (기존 절차 준수)

- 각 파서: 프로토타입 → 표본 스윕(100~300사) → 버그 트리아지 → 테스트(fin2/tests) →
  전수 백필(**사용자 터미널**) → 커버리지 리포트.
- 장시간 잡은 전부 사용자 실행 (에이전트 백그라운드 금지 — 기존 운영교훈).
- 각 Phase 완료 시 `docs/data_inventory_matrix.md` 상태 갱신.
- DART 쿼터: Phase 2 백필만 소모(야간 스케줄), 나머지 Phase 전부 쿼터 0.

## 5. 비범위

- 애널리스트 컨센서스/목표주가, 기관·외국인 수급, 신용등급 (DART 밖 소스 — 사용자 확정 제외).
- 백테스트, 실시간 데이터.
- 차입금 만기구조·IFRS8 영업부문 주석 (보류 — Phase 0 결과 보고 재검토).
