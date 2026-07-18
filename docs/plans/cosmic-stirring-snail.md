# 전문 서비스 갭 채우기 — 데이터 항목 확충 + 전수 인벤토리 감사 + 자유조합 차트 강화

## Context

프로젝트 원목표(정기 공시 재무데이터+주석 정보 → DB → 시각화)는 v1.0으로 완성됐으나,
CompanyGuide/버틀러 등 전문 서비스와 비교하면 **데이터 항목**에 갭이 있다. 사용자 확정 사항:

- **소스 범위: DART 공시 내로 한정** (컨센서스/수급/신용등급 등 외부 유료소스 제외)
- **우선순위(4개 전부)**: ① 주주환원(배당·자사주) ② 부문·지역별 실적 ③ 주석 상세(비용성격 등) ④ 회사 일반현황(직원·보수·출자)
- **누락 감사: 전수 인벤토리 감사** — 보고서 내 숫자 표 전체를 항목 단위로 '수집됨/미수집/수집불가' 매트릭스화
- 자유조합 차트에서 수집된 모든 항목을 쉽게 조합해 볼 수 있어야 함

### 탐색으로 확인된 현황 (3대 갭 유형)
1. **DB에 이미 있는데 안 보이는 것**: `fin2/taxonomy/concept_map.py`가 매핑하는 ~30개 캐노니컬 계정
   (bs.goodwill/paid_in_capital/treasury_stock/lease_liability…, is.finance_income/finance_cost/eps_basic/
   eps_diluted/oci…, cf.borrowings_proceeds/repaid/interest_paid/tax_paid/treasury_stock_purchase…)이
   fact_v2에 파싱돼 있으나 std_financials_v2 wide 컬럼이 없어 앱에서 접근 불가.
2. **미수집 (DART 구조화 API 존재 → 쉬움)**: alotMatter(배당), tesstkAcqsDspsSttus(자기주식 취득·처분),
   empSttus(직원), otrCprInvstmntSttus(타법인출자), hmvAuditAllSttus/indvdlByPay(임원보수 전체/개인별).
3. **미수집 (본문/주석 표 파싱 필요)**: 매출실적 표(부문×수출/내수), 비용의 성격별 분류 주석,
   차입금 만기구조 주석(→보류), IFRS8 영업부문 주석(→보류).
4. **자유조합 차트 한계**: 46개 큐레이트 지표만 선택 가능(플랫 목록), 원시 컬럼·PER/PBR 시계열·
   biz_metrics·수주잔고 등 접근 불가, 파생연산 3종(비율/차분/주당)뿐, 다기업 비교 불가.

---

## 핵심 아키텍처 결정

### 결정 1 — 미승격 캐노니컬 ~30종: std_v2 wide 컬럼 추가 대신 **`extended_financials` long 뷰**
std_v2 컬럼 추가는 건당 6개 접점(models/migration/rules/build/분기/달력 전파+뷰 재생성)이라 과중.
대신 `fact_v2 × statement_source` 조인 뷰 하나로 전부 해결 — statement_source가 이미 rcept 승자를
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
- SUM은 의도적(leaf-additive 캐노니컬: lease_liability=유동+비유동 등). `n_facts`로 이상 감지.
- v1은 **연간(FY)만 앱 노출**(H1/Q3는 누적 as-filed — 이산화 재구현 회피, 한계 명시).
- 일반 뷰(비 matview) — 기업 단위 조회는 인덱스 경로라 충분. 스크리너 소비 시점에 materialize 재검토.

### 결정 2 — 주주환원: 신규 API 수집 + 앱측 파생 + 신규 탭
- `collector/dart_periodic.py` 신규 1모듈에 6개 정기보고서 API 공통루프(corp+bsns_year+reprt_code
  컨벤션 동일, dart_extra.py 패턴). 각 API별 파싱 테이블 + raw JSONB 보존.
- 파생지표(배당성향·총주주환원율=(배당+자사주순취득)/지배NI 또는 FCF)는 **앱측**(pandas) 계산 —
  DB 뷰 추가 없이 `app/data/shareholder_return.py` 단일 쿼리 조인.
- company_page에 **신규 "💸 주주환원" 탭**(radio 목록이라 추가 저렴). 자사주 금액 폴백:
  treasury_activity → extended_financials의 cf.treasury_stock_purchase.

### 결정 3 — 부문·수출/내수 매출: biz_section 인프라 재사용, biz_metrics에 `channel` 컬럼 추가
- 소스는 II.사업의 내용 '매출실적/판매실적' 표 (IFRS8 주석 아님 — 주석은 이질성 높아 보류).
- `biz_section.py`의 `_SALES_KW`(line 313) 가드가 현재 매출표를 **버리고** 있음 → 캡처로 전환.
- 신규 테이블 대신 `biz_metrics.channel VARCHAR(12)`(수출/내수/합계) 가산 마이그레이션 +
  `metric='sales'` — 기존 sync/로더/멱등성 전부 재사용. 수출비중 = 파생 비율.

### 결정 4 — 비용의 성격별 분류 주석: 포함 (Phase 4)
급여/원재료 확보 + **D&A→EBITDA 커버리지 상승**(현재 연결 42% 천장 돌파) 이중 효과.
검증된 note.* 채널 재사용: rules.py `_DA_TOTAL_CANON`이 이미 note.da_total 소비,
cf_da_sync.py가 영속화 패턴(주석파서→합성 fact→재표준화→분기→달력) 확립.

### 결정 5 — 보류 (ROI 불리, Phase 0 인벤토리 결과 보고 재검토)
차입금 만기구조 주석 · IFRS8 영업부문 주석 · extended 분기 그레인 · 주주환원 스크리너 통합.
(차입금 총액·리스부채·차입/상환 CF는 결정 1로 이미 노출됨.)

### 결정 6 — 자유조합 차트: 레지스트리 병행 확장 카탈로그 + 얇은 소스 디스패치
기존 `METRIC_REGISTRY`/`resolver` 불변. 병행 카탈로그 + kind별 fetcher:
- `app/registry/extended.py`: kind별 스펙 — "extended"(~30개 수기 한글라벨), "biz", "dividend",
  "employee", "valuation"(PER/PBR/PSR/EV-EBITDA/배당수익률 시계열).
- `app/compute/sources.py::fetch_ext_frame` → `build_metric_frame`과 동일 tidy 스키마 출력
  (차트/표/CSV/프리셋 전부 무변경 재사용). 연간 그레인 가드(캡션 안내).
- UI: 플랫 multiselect → 카테고리 그룹 피커, 파생연산 yoy/ttm 추가, 다기업 비교 모드.

### 결정 7 — 전수 인벤토리 감사: 2-pass
- **Pass 1 (SQL, 수 분)**: fact_v2 미매핑 acode 상위 빈도, 미승격 캐노니컬별 행수·corp×fy 커버,
  기존 테이블별 연도 커버.
- **Pass 2 (표본 심층, 30~60분)**: `scripts/audit_table_inventory.py` — 층화표본 ~300사
  (시장×업종×규모) × {최신 사업보고서, 2020, 2016}. TABLE 요소 순회(expand_table_grid 재사용),
  수치셀 ≥30% = 숫자표, 직전 헤딩 키워드 분류(~40개 항목 유형), `ITEM_STATUS` 맵과 대조.
- **산출물**: `docs/prd/10_data_inventory.md` — 항목|절|최적소스|상태|출현빈도 매트릭스.
  이후 각 Phase 완료 시 상태 갱신 (목표 3의 수용 기준 문서).
- 선택: 189K 파일 전수 제목-레벨 스캔(정규식, 파싱 없음) — 사용자 실행, 옵션.

---

## Phase별 실행 계획 (각 Phase = 세션 1개 규모, 0·1·3·4는 상호 독립)

### Phase 0 — 전수 인벤토리 감사 (쿼터 0, 최우선 — 3~5단계 리스크 제거)
- 생성: `scripts/audit_table_inventory.py`, `docs/prd/10_data_inventory.md`
- 검증: 10사 인라인 실행, 헤딩 분류 정밀도 30건 육안
- 사용자 실행: 300사 표본 스윕(30~60분), (선택) 전수 제목 스캔

### Phase 1 — extended_financials 뷰 + 차트빌더 노출 (쿼터 0)
- 수정: `collector/db.py`(migration `2026_07_extended_financials_view`), `app/cache.py`,
  `app/views/chart_builder_page.py`(그룹 피커+extended 카테고리), `scripts/dq_assertions.py`(n_facts 가드)
- 생성: `app/registry/extended.py`(한글라벨 ~30종, eps=원/주 단위), `app/data/extended.py`,
  `app/compute/sources.py`
- 검증: 삼성전자 goodwill/자기주식/이자지급 FY2023 vs DART 원문 대조, lease_liability SUM 의미
  확인, 차트빌더 수동 확인
- 사용자 실행: 없음 (뷰는 즉시)

### Phase 2 — 주주환원 + 회사 일반현황 수집 (개발 1세션 + 백필 ~4~7일 야간 쿼터)
- 생성: `collector/dart_periodic.py`(6 API + 체크포인트 테이블 `periodic_api_progress` —
  no-data 응답도 기록해 쿼터 재소비 방지), `scripts/collect_periodic_apis.py`
  (`--api alotMatter --years 2020-2025 --resume`), `app/data/shareholder_return.py`,
  `app/data/company_profile.py`
- 수정: `collector/models.py`(6테이블: dividend_facts/treasury_activity/employee_stats/
  other_investments/exec_pay_summary/exec_pay_individual), `scripts/collect_new.py`(⑤-3 비치명적),
  `app/views/company_page.py`("💸 주주환원" 탭 신설 + 임원·지분 탭에 직원·보수·출자 확장),
  `app/cache.py`, `app/registry/extended.py`+`sources.py`(dividend/employee kind)
- 검증: 100사×FY2023 표본(~200콜), 유명 배당주 5사 DPS 대조, 배당성향 재계산 vs 공시값 허용오차
- 사용자 실행 (야간 1커맨드/일, 2,557사×연도≈2,600콜/API/년):
  1일차 alotMatter 2020+ → 2일차 tesstk → 3일차 empSttus → 4일차 otrCpr+hmvAuditAll(+indvdlByPay)
  → 5~7일차 alotMatter/tesstk 2015~2019 확장

### Phase 3 — 부문·수출/내수 매출 파서 (쿼터 0, 로컬 파일)
- 생성: `fin2/extract/sales_section.py`(find_sales_tables+map_sales_table →
  segment×item×channel×period_year), `scripts/collect_sales_metrics.py`(rcept 멱등)
- 수정: `collector/db.py`(biz_metrics.channel 가산), `collector/models.py`,
  `collector/biz_metrics.py`(sync 진입), `fin2/extract/biz_section.py`(_SALES_KW 폐기 가드 → 라우팅,
  이중 캡처 방지), `scripts/collect_new.py`(⑤-4), `app/data/biz.py`+`company_page.py`
  (매출 구성 패널: 부문 스택 + 수출비중 라인), 차트빌더 biz kind
- 검증: 삼성전자/S-Oil 프로토 → 20사 → 부문합≈std_v2 revenue ±20% 단위가드(cf_da 철학) →
  100~300사 스윕 트리아지 (B4 확립 절차 동일)
- 사용자 실행: 전수 백필(수 시간, 쿼터 0)

### Phase 4 — 비용의 성격별 주석 파서 + EBITDA 상승 (쿼터 0, 로컬 파일)
- 생성: `fin2/extract/expense_nature.py`(rd_note.py 모델, note.da_total/depreciation/amortization/
  employee_benefits/raw_materials_used 방출), `collector/expense_nature_sync.py`
  (cf_da_sync 클론: depreciation IS NULL 대상 → 재표준화→분기→달력)
- 수정: `scripts/collect_new.py`(④-2 확장), `app/registry/extended.py`
- 검증: golden set 전후 da_total/ebitda NULL율 diff, da/매출 [0.3%,60%] 가드 재사용,
  Gate B 무영향 확인(note는 비face), 100사 스윕 → EBITDA 천장 이동 리포트
- 사용자 실행: 전수 백필 + 재표준화 스윕 (장시간)

### Phase 5 — 차트빌더 고급 기능 (쿼터 0)
- 수정: `app/compute/derived.py`(yoy/ttm 연산), `app/registry/units.py`(원/억원/조원 스케일 토글),
  `app/views/chart_builder_page.py`(밸류에이션 시계열 섹션 — 기존 `cache.valuation_series` 재사용;
  다기업 비교 모드 2~4사), `app/views/chart_panel.py`(corp별 색상 변형),
  `app/data/presets.py`(스키마 버전 키, 구 프리셋 호환)
- 검증: yoy/ttm 단위테스트 + AppTest + 수동 UI 확인

---

## 1차 산출물: PRD 문서 세트 (승인 후 즉시 작성 — 이번 실행의 첫 작업)

기존 `docs/prd/` 번호 컨벤션(05_visualization·06_screener·05_06_checklist·09_improvement_roadmap)을 따라:

| 문서 | 내용 |
|---|---|
| `docs/prd/10_gap_fill_plan.md` | 마스터 계획 (이 문서의 Context+아키텍처 결정 전문) |
| `docs/prd/11_phase0_inventory_audit.md` | Phase 0 PRD: 전수 인벤토리 감사 (2-pass 방법·ITEM_STATUS 룰북·산출물 스펙) |
| `docs/prd/12_phase1_extended_financials.md` | Phase 1 PRD: extended_financials 뷰 + 차트빌더 노출 |
| `docs/prd/13_phase2_periodic_apis.md` | Phase 2 PRD: 주주환원+일반현황 6 API 수집 (테이블 스키마·쿼터 스케줄) |
| `docs/prd/14_phase3_sales_section.md` | Phase 3 PRD: 부문·수출/내수 매출 파서 |
| `docs/prd/15_phase4_expense_nature.md` | Phase 4 PRD: 비용의 성격별 주석 파서 + EBITDA 상승 |
| `docs/prd/16_phase5_chart_builder.md` | Phase 5 PRD: 차트빌더 고급 기능 |
| `docs/prd/10_16_checklist.md` | 전 Phase 체크리스트 (항목별 체크박스 + 검증 기준 + **Phase별 권장 /model**) |

Phase 0의 감사 결과 매트릭스는 생성 산출물이므로 PRD가 아닌 `docs/data_inventory_matrix.md`에 저장
(PRD 11이 스펙, 매트릭스가 결과물).

### Phase별 권장 모델 (체크리스트에 명기, 각 Phase 착수 시 /model 전환 안내)

| Phase | 권장 모델 | 근거 |
|---|---|---|
| PRD 문서 작성 | Sonnet | 정형 문서화, 설계는 이미 확정 |
| Phase 0 인벤토리 감사 | **Fable/Opus** | 헤딩 분류 룰북 설계·표 유형 판별이 판단 집약적 |
| Phase 1 extended 뷰 | Sonnet | SQL 뷰+카탈로그 노출, 패턴 명확 |
| Phase 2 API 수집 | Sonnet | dart_extra/dart_capital 기존 패턴 복제 |
| Phase 3 매출 파서 | **Fable/Opus** | 이질적 표 파싱 — B4 이력상 트리아지 반복 多 |
| Phase 4 비용성격 파서 | **Fable/Opus** | 표준화 파이프라인(재표준화→분기→달력) 접점, 회귀 위험 |
| Phase 5 차트빌더 | Sonnet | UI 증분, 기존 컴포넌트 재사용 |

(Pro 요금제 쿼터 관리 원칙: 판단 집약 Phase만 상위 모델, 나머지는 Sonnet으로 절약.)

---

## 검증 총칙 (기존 절차 준수)
- 각 파서: 프로토타입 → 표본 스윕(100~300사) → 버그 트리아지 → 테스트(fin2/tests) →
  전수 백필(사용자 터미널) → 커버리지 리포트
- 장시간 잡은 전부 사용자 실행 (에이전트 백그라운드 금지 — 기존 운영교훈)
- 각 Phase 완료 시 `docs/prd/10_data_inventory.md` 상태 갱신
- DART 쿼터: Phase 2 백필만 소모 (야간 스케줄), 나머지 Phase 전부 쿼터 0
