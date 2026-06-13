# PRD 03 — Financial DB Builder (파싱·표준화·분기환산·달력정규화 전문가)

> 역할 #3. 입력: 게이트 A 통과 보고서 파일. 출력: `fact_v2`→`statement_source`→`std_financials_v2`(+분기 이산행) + `std_financials_calendar`(Layer 2).
> 총괄: `00_pm_master_plan.md`. 다음 단계: 게이트 B(`04_db_validation.md`). 연관 설계: `01a_fiscal_month_change_design.md`.

## 1. 목표

게이트 A 를 통과한 보고서의 **연간·별도 포함 재무제표 본문 + 주석 재무항목**을 파싱하여 DB화한다.
- 금액 단위는 **원(KRW) 단일 단위**로 통일(이미 구현).
- **반기·연간 수치를 분기 데이터로 환산**: H1−Q1=Q2, FY−ΣQ=Q4 (flow 한정).
- 계정명은 **일반기업 vs 금융업** 기준 대표기업 보고서로 표준화.
- **2층 모델**: ① 원본(as-filed) = 보고서 회계기간 그대로(진실원, Gate B 적용) ② 달력 정규화(calendarized) = 전 기업을 12월 달력기준으로 통일(파생, 비교·시각화용). 자세히 §5.3.

## 2. 비범위

- 보고서-vs-DB 100% 일치 판정(게이트 B, PRD 04). 본 전문가는 **추출·표준화·환산**까지.
- 다운로드·다운로드 검증(PRD 01/02).

## 3. 입력·출력 계약

- **입력**: 게이트 A PASS 파일 + `statement_source` 선택 대상.
- **출력**:
  - `fact_v2`: 원천 셀(acode·canonical_account·basis·col_index·period_type·is_cumulative·adecimal·**amount_won**).
  - `statement_source`: (corp,period,basis)별 BS/IS/CF 각각 단일 source filing.
  - `std_financials_v2`(Layer 1): 표준화 행 + **분기 이산행**(Q1/Q2/Q3/Q4, 회계기준) + 표준화 계정.
  - `std_financials_calendar`(Layer 2): 12월 달력기준 분기/연간 파생행(파생 플래그). §5.3.

## 4. 재사용 자산

| 단계 | 파일·함수 |
|------|-----------|
| E(추출) | `fin2/extract/acontext.py`·`xbrl.py`(Track A)·`text.py`(Track B)·`notes.py`·`cf_da.py` |
| 단위 | XBRL `ADECIMAL` 권위, `amount_won = 표시값 × 10^(-ADECIMAL)` (이미 원 단일) |
| R(정합) | `fin2/reconcile.py` `select_source()` (anchor>적시정정>완전성>filed_at>rcept) |
| S(표준화) | `fin2/standardize/rules.py`·`build.py` (규칙엔진) |
| 계정 매핑 | `fin2/taxonomy/concept_map.py`(XBRL), `parser/common/account_mapper.py`+`account_maps/*`(텍스트) |

> ⚠ file:line 은 구현 시 재확인.

### 기존 동작 (재사용, 재작성 금지)
- ADECIMAL 단위 권위, 원 단일 저장. ACONTEXT 로 basis/period/누적 판정.
- BS/IS/CF 독립 source 선택(over-supersede 구조 제거). 적시 기재정정 우선(±400일 가드).
- interim 누적컬럼 정합(Track B `_interim_cumulative_cols`) — H1/Q3 누적값 정확 추출.
- 미매핑 계정은 NULL 로 **무손실 보존**(acode 유지 → backfill 가능).

## 5. 신규 작업

### 5.1 ★ 분기 환산 모듈 `fin2/standardize/quarterly.py`
- **대상**: flow(IS/CF)만. BS 는 시점 잔액 → **불가침**.
- **공식**:
  - `Q1(이산) = Q1누적`
  - `Q2 = H1누적 − Q1누적`
  - `Q3(이산) = Q3누적 − H1누적`
  - `Q4 = FY − Q3누적`
- **누적 판별**: `fact_v2.is_cumulative`·`period_type` 로 누적/3개월 컬럼을 정확히 구분(이미 저장됨). 3개월(이산)으로 들어온 분기는 그대로 사용, 누적은 차감.
- **결측 처리**: 필요한 구성요소(예 Q2 에 H1·Q1) 중 하나라도 없으면 **미생성**. 추정·보간 금지.
- **저장**: `std_financials_v2`(Layer 1) 에 분기 이산행 추가.
  - `fiscal_period` ∈ {Q1, Q2, Q3, Q4}(회계기준), `applied_rules @> ["quarterly_derived"]` 마커.
  - 각 이산분기는 **`period_end`(3/6/9/12월말) 보유** → Layer 2 calendarization 의 원자(atom)가 된다(§5.3).
  - 원본 누적행(H1/FY/Q1누적/Q3누적)도 보존(소비자가 둘 다 조회 가능).
  - **BS 행 불가침**.
- **자기검증**: `Q1+Q2+Q3+Q4 = FY`, `Q1+Q2 = H1`, `Q1+Q2+Q3 = Q3누적` 성립 여부 측정.

### 5.2 ★ 계정 표준화 (일반 vs 금융 2버킷)
- **버킷**: 상세 업종 세분 대신 **① 일반기업(비금융) ② 금융업** 2버킷.
  - 근거: K-IFRS 본문 구조는 금융/비금융에서만 본질적으로 갈린다(금융업은 매출원가·매출총이익 없이 영업수익·이자수익 구조, DART 도 금융업 별도 표시양식). 비금융 내부는 IFRS 가 본문 구조를 동질화 → 세부 업종 세분의 표준화 효용 낮음.
  - 금융 버킷이 단일 reference 로 부족하면(은행 대출채권 vs 보험 책임준비금 vs 증권 수수료수익 차이) **은행/보험/증권/지주** 하위세분.
- **방법**:
  1. 각 버킷 시총상위 대표기업 자동선정(KRX 업종분류로 금융/비금융 구분).
  2. 대표기업 **최근 연간보고서**의 계정체계를 **reference dictionary** 로 추출.
  3. `account_maps/*`·`concept_map` 의 미매핑·불일치를 버킷별 reference 로 보강.
  4. **Claude 후보 도출 → 사용자 확정 → 반영**.
- **산출물**: 버킷별 reference 사전 + 갭리포트(보강 전후 미매핑률).

### 5.3 ★ 2층 모델 + Layer 2 Calendarization (`fin2/standardize/calendar.py`)

**배경(실측)**: 한국 정기보고서 기말일은 결산월과 무관하게 **달력분기말(3/6/9/12월)** 에 정렬된다(전체 filings 99.8%, 활성기업 2,547/2,557 정렬). 따라서 이산분기를 **달력분기로 재배열·합산**해 전 기업을 12월 달력기준으로 정규화할 수 있다(벤더 표준 기법 = calendarization).

**2층 모델**:
- **Layer 1 (원본/as-filed)** = `std_v2`(view `standard_financials`). 각 보고서 회계기간 그대로(stub 포함). **Gate B 100% 일치 적용 = 진실원. 대체 금지.**
- **Layer 2 (달력 정규화)** = 전 기업 12월 달력분기 + 달력연도 연간(=ΣQ). **파생 플래그 필수**, 비교·시각화·스크리닝용. **Gate B 미적용**(어느 단일 보고서에도 명시되지 않은 계산값).

**표현 = 별도 테이블 `std_financials_calendar` + view `calendar_financials`** (권장; 근거 하단):
- PK: `(corp_code, calendar_year, calendar_period, statement_type, basis, version)`.
- `calendar_period` ∈ {**CQ1, CQ2, CQ3, CQ4, CY**} — 회계 Q1..FY 와 **토큰 분리**(혼동·중복합산 방지).
- 값 컬럼: `std_v2` 와 동일(BS/IS/CF/파생).
- 플래그·추적:
  - `derivation` ∈ {**native**(12월결산=달력=회계, 정확) | **recomposed**(비12월=2개 회계연도 합성) | **partial**(분기 결측)}.
  - `is_complete`(CY 가 4분기 완비) · `period_end`(CY=12-31, CQ=분기말) · `source_lineage`(구성한 회계 (fy,fp) JSONB) · `data_quality`.
- **flow(IS/CF)**: `CQn` = period_end 가 그 달력분기인 Layer 1 이산분기. `CY` = 그 달력연도 CQ1..CQ4 **합**(4개 모두 있을 때만; 아니면 partial → CY 미생성, 추정 금지).
- **stock(BS)**: **합산 금지**. `CQn` = 그 분기말 잔액. `CY` = **12-31 스냅샷**(=CQ4 잔액). 비12월사는 그들의 *분기(검토)* 보고서 12-31 잔액 사용 → **권위 약함 플래그**.
- **native 검증(공짜)**: 12월결산사 `CY flow == 보고 FY`(반올림 내) → Layer 1 대조 자기검증.

**빌드 순서**: Layer 1 이산분기(§5.1) → 각 분기 `period_end`(3/6/9/12) 로 `calendar_year`/`CQ` 매핑 → flow 합산·BS 12-31 스냅샷 선택 → `std_financials_calendar` upsert.

**예외**: FYE ∉ {3,6,9,12} 인 ~23사(1/2/5/7/8/10/11월 결산)는 기말이 달력분기 비정렬 → **달력화 불가**(`derivation` 미생성 / corp 플래그 `not_calendarizable`), Layer 1 만 유지.

**표현 선택 근거**(별도 테이블 vs std_v2 행 추가 vs 순수 view):
- *std_v2 행 추가* → `fiscal_period` 컬럼이 회계/달력 의미 혼재 → 합산 중복·오용 위험. **기각**.
- *순수 view* → 비12월 재배열·교차연도 합산·결측 NULL·플래그를 view 로 표현하기 어렵고 교차기업 스캔 느림. **기각**.
- **별도 테이블(채택)** → 의미 분리 명확, Layer 1·Gate B·기존 소비자(analyze/screen/dcf) 무영향, calendarization 로직 격리, view 로 노출.

**의존성**: 정확한 이산분기 도출은 ① 올바른 원본 라벨(`01a` 결산월 변경)과 ② 누적 리셋 지점이 선행돼야 한다 → Layer 2 는 Layer 1 정확화 위에 올라간다.

## 6. 완료기준 (DoD)

- 분기 재합산 자기일관성(`ΣQ=FY` 등) ≥ 목표치(측정 후 설정).
- 표준화 미매핑률 감소(reference 적용 전후 비교).
- golden 5/5 + parity 무회귀 + `fin2` 테스트 전부 통과.
- BS 행 불변(분기 환산이 BS 를 건드리지 않음).
- **Layer 2**: `ΣCQ = CY` 100%(is_complete 행) · `derivation=native` 행 `CY == 보고 FY`(반올림 내, 12월결산 표본) · 비12월 표본(삼성증권) 달력연도 시계열 연속 + 플래그 정확 · `not_calendarizable` 격리.

## 7. 위험

- 분기 환산이 누적/이산 오판별로 깨질 위험 → `is_cumulative` 신뢰성 검증 선행, 자기일관성 게이트로 차단.
- 표준화 버킷 분류 오류(지주·복합기업) → 금융 하위세분·예외목록.
- 환산행 추가가 게이트 B 부담 증가 → 게이트 B 는 본문(누적 원본) 우선, 환산행은 자기일관성으로 별도 검증.
- **Layer 2 calendarization 한계(반드시 플래그)**: ① `Q4=FY−9M` 이라 연말 일괄조정(법인세 정산·손상·감사조정)이 Q4 에 몰려 lumpy ② 반올림 누적(ΣCQ vs 보고 FY 표시단위 내 미세차 허용) ③ 비12월 12-31 BS 는 검토(미감사) 보고서 잔액 → 권위 약함 ④ 결측분기 → CY partial·미생성(추정 금지) ⑤ **Layer 2 는 Gate B 비적용**(파생값) — 소비자에 파생임을 명확히 표기.
