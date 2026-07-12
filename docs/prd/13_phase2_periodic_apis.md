# PRD 13 — Phase 2: 주주환원 + 회사 일반현황 (정기보고서 API 6종 수집)

> 마스터 계획: `10_gap_fill_plan.md`. 체크리스트: `10_16_checklist.md`. 권장 모델: **Sonnet**
> (dart_extra.py/dart_capital.py 기존 패턴 복제 — 판단 요소 적음).

## 0. 왜 이 PRD 인가

우선순위 ①(주주환원)과 ④(회사 일반현황)를 채운다. 둘 다 DART 가 **구조화 API** 로 제공하는
정기보고서 첨부서류라 파싱 리스크 없이 API 계약만 맞추면 된다 — B3(대주주)/B2(자본이벤트) 때
확립된 수집기 패턴을 그대로 복제.

## 1. 목표

6개 DART API 수집 + DB 테이블 + 앱측 파생지표(배당성향·총주주환원율) + company_page 신규 탭.

## 2. 범위 — 대상 API (전부 `corp_code + bsns_year + reprt_code` 컨벤션, `exctvSttus`/`hyslrSttus`
와 동일)

| API | 우선순위 | 내용 |
|---|---|---|
| `alotMatter` | ① 주주환원 | 배당에 관한 사항 — 주당배당금, 배당성향, 배당총액, 배당수익률 |
| `tesstkAcqsDspsSttus` | ① 주주환원 | 자기주식 취득·처분 현황 |
| `empSttus` | ④ 일반현황 | 직원 현황 — 부문별 인원·평균급여·근속연수 |
| `otrCprInvstmntSttus` | ④ 일반현황 | 타법인 출자현황 |
| `hmvAuditAllSttus` | ④ 일반현황 | 임원 전체의 보수총액/평균 |
| `indvdlByPay` | ④ 일반현황 | 5억원 이상 개인별 보수 (기존 `hmvAuditIndvdlBySttus`=이사·감사 개인별과 별개,
  두 API 병존 가능성 있으므로 착수 시 DART 문서로 정확한 엔드포인트명 재확인) |

## 3. 비범위

- 스크리너 필터 통합(향후).
- 분기 보고서의 동일 항목(정기보고서 사업보고서 기준만, bsns_year 단위 연 1회).

## 4. 설계

### 4.1 수집기 — `collector/dart_periodic.py`(신규)

`dart_extra.py::_get`/`fetch_executives` 패턴을 따르는 공통 루프:

```python
def fetch_periodic(api_name: str, corp_code: str, fiscal_year: int) -> list[dict]: ...
def sync_periodic(session, api_name: str, corp_code: str, fiscal_year: int) -> int: ...
```

- 각 API 응답 필드를 해당 테이블 컬럼으로 매핑 + **raw JSONB 원본 보존**(캡티브 필드명 변이 대비,
  B2 자본이벤트에서 확립된 관례).
- delete-then-insert 멱등(corp_code+fiscal_year+api 그레인).
- **체크포인트 테이블 `periodic_api_progress`**(신규, models.py): `(corp_code, fiscal_year, api_name)`
  PK + `status`(ok/no_data/error) + `checked_at`. no_data 응답(DART status≠'000' "조회된 데이타가
  없습니다")도 반드시 기록 — 그래야 재실행 시 이미 확인한 no-data 케이스를 다시 조회해 쿼터를
  낭비하지 않는다(대주주/자본이벤트 백필 때의 쿼터 소진 교훈, `key-bugs-fixed.md` #6·#7 과 동일 패턴
  — 연속 쿼터초과 감지 시 즉시 중단+재개 안내를 이 스크립트에도 이식).

### 4.2 신규 테이블 (`collector/models.py`)

- `dividend_facts`(corp_code, fiscal_year PK 일부) — dps_common, dps_pref, stock_dividend_ratio,
  total_dividend_amount, payout_ratio, dividend_yield_common, raw JSONB.
- `treasury_activity` — acquisition_method, qty_planned/acquired/disposed/incinerated, raw JSONB.
- `employee_stats` — division, sex, employment_type, headcount, avg_tenure_years, total_salary,
  avg_salary.
- `other_investments` — investee_name, purpose, initial_qty/value, end_qty/value, book_value,
  investee_net_income.
- `exec_pay_summary` — total_exec_count, total_pay_amount, avg_pay_per_person.
- `exec_pay_individual` — person_name, position, total_pay_amount, pay_detail(JSONB).

### 4.3 백필 오케스트레이터 — `scripts/collect_periodic_apis.py`(신규)

`scripts/collect_shareholders.py` 와 동일 CLI 패턴: `--api alotMatter --years 2020-2025 --resume
--skip-existing`. 내부적으로 `periodic_api_progress` 체크포인트를 조회해 이미 처리된
(corp,fy,api)는 건너뜀. 연속 쿼터초과(status='020') N회 감지 시 즉시 중단 + 재개 명령 안내 출력.

### 4.4 일일 증분 — `scripts/collect_new.py`

신규 비치명적 단계 ⑤-3: 최근 신규 표준화된 기업의 **최신 fiscal_year 만** 6개 API 동기화(전수
백필과 별개, 매일 소규모 증분).

### 4.5 앱측 파생 — `app/data/shareholder_return.py`(신규), `app/data/company_profile.py`(신규)

- `shareholder_return.py`: `dividend_facts` + `treasury_activity` + `standard_financials`(연간
  controlling_ni, fcf) 조인 쿼리 하나. 파생:
  - 배당성향 = 공시된 `payout_ratio` 우선, 없으면 `total_dividend_amount / controlling_ni` 폴백.
  - 총주주환원율 = (총배당금 + 자사주 순취득금액) / controlling_ni (또는 /fcf 변형).
  - 자사주 순취득금액 소스 순서: `treasury_activity` → 없으면 Phase 1 `extended_financials` 의
    `cf.treasury_stock_purchase` 폴백.
  - 계산은 **앱측 pandas** — DB 뷰 추가 없음(단일 기업 온디맨드라 트리비얼, 재사용처 생기면 승격 검토).
- `company_profile.py`: employee_stats/other_investments/exec_pay_* 로더.

### 4.6 UI — `app/views/company_page.py`

- **신규 10번째 탭 "💸 주주환원"**: DPS/배당성향/총주주환원율 추이 차트 + 자사주 취득·처분 막대.
  기존 밸류에이션 탭의 배당수익률 라인과는 별개(밸류에이션 탭은 무변경).
- **기존 "👔 임원·지분" 탭 확장**: 직원 현황(부문별 인원·평균급여) + 임원보수 요약/개인별
  + 타법인 출자현황 패널 추가.
- **차트빌더**: `app/registry/extended.py`(Phase 1 산출물)에 "dividend"/"employee" kind 추가,
  `app/compute/sources.py` 에 대응 fetcher 추가.

## 5. 검증

- 표본 100사 × FY2023 실행(~200 API 콜, 쿼터 무시 가능 수준) — 응답 파싱 정확성 확인.
- 유명 배당주 5사(삼성전자·SK텔레콤 등) DPS 를 DART 공시 원문과 대조.
- 배당성향 재계산값이 공시된 `payout_ratio` 와 허용오차(±2%p) 내 일치하는지 표본 검증.
- `periodic_api_progress` 멱등성: 동일 (corp,fy,api) 재실행 시 API 재호출 없이 스킵 확인.

## 6. 사용자 실행 (야간 쿼터 스케줄, §마스터 PRD 결정 2)

2,557사 × 연도 ≈ 2,600콜/API/연도. 1일 1커맨드:
1. 1일차: `alotMatter` 2020+
2. 2일차: `tesstkAcqsDspsSttus`
3. 3일차: `empSttus`
4. 4일차: `otrCprInvstmntSttus` + `hmvAuditAllSttus`(+`indvdlByPay`)
5. 5~7일차: `alotMatter`/`tesstkAcqsDspsSttus` 2015~2019 확장

## 7. 완료 기준

- 6개 테이블 전부 스키마 생성 + 100사 표본 데이터 확인.
- "💸 주주환원" 탭 렌더 + AppTest 무예외.
- `collect_new.py` ⑤-3 단계가 비치명적으로 통합(실패해도 파이프라인 중단 없음).
- 전수 백필은 사용자 스케줄에 따라 순차 진행 — 이 Phase 의 코드 완료 기준에는 전수 백필 완주가
  필수는 아니나(쿼터 소요 수일), 재개 가능한 상태(체크포인트 동작)는 필수.
