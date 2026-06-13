# PRD 01a — 결산월 변경 라벨링 설계 (Fiscal-Year-End Change)

> PRD 01(Downloader)의 "결산월 변경 이력" 항목 상세 설계. **설계 문서 — 승인 후 구현.**
> 총괄: `00_pm_master_plan.md`. 근거 데이터·결정: 2026-06-13 세션.

## 1. 문제 (증거 기반)

DART 정기보고 라벨(`filings.fiscal_year`/`fiscal_period`)이 **단일 결산월(최신 annual 기준)을 전 연도에 소급 적용**해 계산된다(`filing_collector.compute_fiscal_year_period`, `_detect_fiscal_month`). 결산월(FYE)을 바꾼 기업에서 이게 깨진다.

**삼성증권(00104856) 실측** — 2013년에 3월→12월 결산 전환:
- `사업보고서 (2013.03)` (2013-06-28 제출): 3월결산 **정상 12개월** (Apr2012~Mar2013).
- `(2013.06)` Q1 · `(2013.09)` H1: 9개월 **전환 stub**(Apr~Dec 2013)의 분기/반기.
- `사업보고서 (2013.12)` (2014-03-31 제출): stub-year 연간(9개월).
- 이후 `(2014.03)` Q1 … = 12월결산 정상 cadence.

**결함**:
1. `(2013.03)` 와 `(2013.12)` 둘 다 `(fiscal_year=2013, FY)` 로 계산 → **키 충돌**. `is_final` 이 stub(`2013.12`)만 남기고 정상연도(`2013.03`)를 `is_final=False` 로 **섀도**.
2. `std_v2` 의 "삼성증권 2013 FY" = **9개월 stub** → 시계열이 …2012(Mar)→**2013(9개월)**→2014(Dec)… 로 왜곡. 정상 12개월(~Mar2013) 데이터는 소실/오라벨.
3. 완전성 격자가 stub-year 에 존재하지 않는 **Q3 2013 을 기대** → 가짜 NOFIL.

**규모**: 결산월 변경 기업 **160사**. 같은 달력연도 2 annual 충돌(전환 stub) **149사**, 섀도된 annual ~100–200건(기재정정 제외 후). 파일은 모두 다운로드됨 — **라벨/귀속 결함**(다운로드 누락 아님).

## 2. 결정된 규약 (사용자, 2026-06-13)

**기말연도 유지 + stub 분리**:
- `fiscal_year` = 기간이 끝나는 **달력연도**(기존 규약 유지). 비12월 결산 전 기업의 기존 라벨 **불변**.
- `fiscal_period` = **그 시점 FYE**(time-aware)로 계산.
- 전환 **stub(12개월 미만)** 은 `is_stub=True` 플래그 + `period_end_date` 로 식별 → 같은 `(corp, fy, FY)` 의 정상연도와 **공존**(충돌 해소).
- 영향: 전환 149사만 국소 처리, cascade 도 그 범위.

삼성증권 결과:
```
보고서          실제기간       fiscal_year  is_stub  period_end
사업(2012.03)  '11.4~'12.3    2012        false    2012-03-31
사업(2013.03)  '12.4~'13.3    2013        false    2013-03-31   ← 정상 12개월(복원)
사업(2013.12)  '13.4~'13.12   2013        true     2013-12-31   ← stub 9개월
사업(2014.12)  '14.1~'14.12   2014        false    2014-12-31
분기(2013.06)  Q1(stub)       2013(Q1)    true     2013-06-30
반기(2013.09)  H1(stub)       2013(H1)    true     2013-09-30
```
Q3 2013 은 존재하지 않음 → 완전성 격자에서 미기대(가짜 NOFIL 제거).

## 3. 스키마 변경 (멱등 마이그레이션, `db.py _run_migrations`)

### filings (추가)
- `period_end_date` DATE — report_nm `(YYYY.MM)` → 해당 월 말일.
- `period_end_month` SMALLINT — MM.
- `fye_month_at_time` SMALLINT — 이 보고서 시점에 유효한 결산월(FYE timeline 도출).
- `is_stub` BOOLEAN DEFAULT FALSE — 전환 12개월 미만 회계기간.

### statement_source (PK 확장)
- `is_stub` BOOLEAN 추가 → PK = `(corp_code, fiscal_year, fiscal_period, basis, statement, is_stub)`.

### std_financials_v2 (PK 확장)
- `is_stub` BOOLEAN 추가 → PK = `(corp_code, fiscal_year, fiscal_period, statement_type, version, is_stub)`. (`period_end` 컬럼은 이미 존재.)

### 호환 view `standard_financials`
- `is_stub` 컬럼 노출(additive). 기본 소비자 쿼리는 무영향(필요 시 `WHERE NOT is_stub` 로 정상연도만).

## 4. 라벨링 알고리즘

### 4.1 period_end 도출
- `report_nm` 의 `(YYYY.MM)` → `period_end_month`, `period_end_date`(그 달 말일). 패턴 없으면(구형) filed_at 폴백 + 로그.

### 4.2 per-corp FYE timeline
- 기업의 **annual 보고서들**을 period_end 순으로 정렬 → `(period_end, fye_month=MM)` 시퀀스.
- `fye_month_at_time(period_end_x)` = period_end_x 이하에서 가장 가까운 annual 의 MM(없으면 최초 annual MM). → 각 보고서가 *그 시점* FYE 로 라벨됨.

### 4.3 stub 탐지
- 연속한 두 annual 의 period_end 간격이 **12개월 미만**이면 뒤 annual = `is_stub=True`(전환 단축 회계기간).
- stub 회계기간 내 interim(Q1/H1/Q3)도 `is_stub=True` 상속(같은 회계기간 소속).

### 4.4 fiscal_year / fiscal_period
- `fiscal_year` = `period_end_year`(규약 유지).
- `fiscal_period` = `compute_fiscal_year_period(report_type, period_end_year, period_end_month, fye_month_at_time)` — 단 fiscal_month 인자에 **소급 최신값이 아니라 fye_month_at_time** 사용.
- stub 회계기간은 9/6/3개월 등 → 존재하는 기간만 라벨(없는 Q3 등은 미생성).

### 4.5 is_final 그룹 키 변경 (충돌 해소의 핵심)
- 현 `_update_is_final_flags` 의 PARTITION = `(corp, report_type, fiscal_year, fiscal_period)`.
- → **`(corp, report_type, period_end_date)`** 로 변경. 정상연도(2013-03-31)와 stub(2013-12-31)이 **다른 그룹** → 둘 다 `is_final=True`(정정본만 그룹내 dedup). 섀도 해소.

## 5. Cascade (영향 149사, 의존성 순)

1. **filings 재라벨**: period_end/fye_at_time/is_stub/fiscal_period 재계산 + is_final 재그룹(4.5). 영향 corp 한정 스크립트(`scripts/relabel_fiscal_change.py`, 멱등).
2. **download_task 보정**: 재그룹으로 새로 is_final=True 가 된 (구 섀도) annual 에 task 존재 확인(이미 completed 면 OK).
3. **re-extract**(`extract2 --corp`): 구 섀도 annual 이 fact_v2 에 없으면 추출(`report_fiscal_year/period` 가 새 라벨로 기록). 영향 corp 만.
4. **reconcile2**: 그룹 키에 `is_stub` 추가(filings JOIN 으로 획득) → statement_source 에 정상/ stub 두 행 공존.
5. **standardize2**: std_v2 에 `is_stub` 반영(정상/stub 분리 레코드).
6. **view 갱신**: standard_financials 에 is_stub 노출.
7. **완전성 격자 regime-aware**(`check_period_completeness`): FYE timeline 세그먼트별 기대기간 생성, stub-year 는 존재 기간만 기대, 전환월의 phantom 분기 제외.

> ⚠ 전수 fin2-all 재실행 금지(디스크/시간). **영향 149사만** 타깃 재처리.

## 6. 검증 (DoD)

- **삼성증권**: 2013 정상연도(12개월, 2013-03-31)와 stub(9개월, 2013-12-31)이 std_v2 에 **둘 다** 존재. 연간 매출 시계열 …2012→2013(정상)→2014 연속(stub 은 플래그로 분리). Q3 2013 완전성 NOFIL 사라짐.
- 전환 149사 표본 수동검증(라벨·stub·시계열 연속성).
- 완전성 재측정: regime-aware 후 NOFIL 대폭 감소(구조적 잔여만).
- golden 5/5 + parity 무회귀(비전환 기업 라벨 불변 확인 — parity 의 비전환 키 added/removed 0 기대).
- fin2 전체 테스트 통과.

## 7. 위험 / 롤백

- **PK 확장**(statement_source/std_v2 에 is_stub) = 스키마 변경. 기존 행 is_stub=False 디폴트 → 기존 키 불변(비전환 무영향). 마이그레이션 멱등.
- **view 재정의** 필요(is_stub 컬럼) → 트랜잭션 내 CREATE OR REPLACE. 롤백=이전 정의.
- 비전환 기업에 회귀 없어야 함(라벨 불변) — parity 로 가드.
- 라벨 변경은 영향 corp 한정 + 마커(is_stub/period_end)로 추적·되돌리기 가능.

## 8. 신규/수정 파일 (구현 시)

- 수정: `collector/models.py`(filings·statement_source·std_v2 컬럼/PK), `collector/db.py`(마이그레이션 + view 재정의), `collector/filing_collector.py`(period_end·fye_at_time·is_stub·is_final 그룹), `fin2/reconcile.py`(is_stub 그룹키), `fin2/standardize/build.py`(is_stub 전파), `scripts/check_period_completeness.py`(regime-aware grid).
- 신규: `scripts/relabel_fiscal_change.py`(영향 corp 재라벨+cascade 오케스트레이션, 멱등), 테스트(전환 케이스).
