# DEF-4 잔여 예외처리 — 구조무관 안전제거(1회성 스크립트)

## Context

DEF-4 메인 수정(fin2/extract/text.py Q1 interim_flow) + 전수 재처리로 인접연도 CQ1 중복이
4,046→60(98.5%)로 감소했으나, 잔여 26쌍(same-rcept)은 **구조가 제각각인 pre-2011 구 K-GAAP +
현대 소수 변종**이라 메인 파이프라인으로는 못 잡힌다. 읽기전용 조사 결과, 이들의 원천 표
구조가 이질적(교차빈셀 분기 IS표 / 요약재무표 red herring / 기타)이라 **진짜 전기값을
신뢰성 있게 복원하는 것은 취약**함을 확인.

사용자 결정(2026-07-10): **① 메인 파이프라인(2015+ 정상경로)은 그대로 두고, ② 예외 케이스는
격리된 1회성 스크립트로 DB 보정**(프로젝트 기존 패턴 `scripts/fin2_kgaap_gap.py`와 동일 철학).
보정 방식은 **안전 제거** — 원값 복구가 아니라, 위조 중복을 걷어내 "데이터 없음"으로 만든다
(DEF-4의 "없는 데이터 > 틀린 데이터" 원칙 일관).

**공통 시그니처(구조무관)**: 모든 잔여 케이스에서 `같은 보고서(rcept)·같은 basis 안에서
col1(전기, col_index=1)의 금액 == col0(당기, col_index=0)`. 분기보고서에서 당기와 전년동기가
소수점까지 동일한 건 사실상 항상 추출 버그(실제 우연 아님) → 안전하게 제거 가능.

## 접근 (안전 제거 + 재파생)

메인 코드는 **한 줄도 수정하지 않음**. 순수 추가 스크립트 + 기존 pass2 재사용.

### 1) 대상 탐지 (self-validating)
`fact_v2`에서 **Q1 보고서**(`report_fiscal_period='Q1'`) 중, 같은 `(rcept_no, basis,
canonical_account)`에 대해 `col_index=0`과 `col_index=1`의 `amount_won`이 동일(≠0)한 보고서.
`is.revenue`를 센티넬로 (rcept, basis) 후보를 산출. 이는 기존 DQ 어서션
`fact_v2_q1_duration_col0_eq_col1`(현재 326셀)과 동일 판정식 → 재사용.
- **다른 rcept 간 우연 동일값은 대상 아님**(한 보고서 내부만 검사) → 진짜 우연/휴면사 미영향.
- 정상 파싱된 현대 보고서(col0≠col1)는 애초에 후보에서 제외 → 회귀 위험 0.

### 2) fact_v2 위조 셀 제거 (가역적)
대상 (rcept, basis)의 **flow 계정(`canonical_account LIKE 'is.%' OR 'cf.%'`) 중 `col_index >= 1`
행을 삭제**. 신뢰 가능한 당기값(col0)만 남긴다. col1(위조 중복)·col2(오라벨된 시프트값) 동시 제거.
- BS(instant)는 이 duration 버그와 무관 → 미대상(scope 최소화).
- **가역성**: 삭제 전 대상 행을 `docs/qa/results/def4_exception_deleted_facts.csv`로 덤프(복원용).

### 3) 재파생 (기존 pass2 재사용)
col1/col2 제거로 (fy-1)/(fy-2) 비교컬럼 앵커가 사라지면, 해당 연도 CQ1은 자연히 공백이 된다.
영향 corp 목록을 파일로 산출 후 **기존 `scripts/def4_reprocess_pass2.py --corps-file <affected>`
그대로 실행** — stale comparative+discrete 삭제 → comparative→분기→달력 재빌드. 새 재파생 코드 없음.
(own 행/reconcile 은 col0 미변경이라 재실행 불필요.)

### 4) 확장성
스크립트는 "한 보고서 내 col0==col1 위조 제거"라는 **구조무관** 규칙이라, 구 K-GAAP·현대 변종·
향후 미지 변종까지 동일 규칙으로 커버(별도 케이스 핸들러 불필요). 3개 현대 잔재도 자동 포함.

## 안전장치
- **백업**: 실행 직전 (a) `python scripts/backup_db.py --out-dir ~/tj_finance_db_backups`
  (std_v2/calendar 포함, fact_v2는 스키마만) + (b) 스크립트가 삭제할 fact_v2 행 CSV 덤프
  → 파생층은 백업, 삭제 fact 셀은 CSV로 완전 가역.
- **--dry-run**: 대상 (rcept,basis) 수·삭제 예정 행 수·영향 corp 수만 출력, DB 미변경.
- 기업/보고서 단위 커밋, resume 파일 지원(중단 재개).
- C5(dart_chain) 실행 중에는 착수 안 함 — 탐지 쿼리가 88M행 fact_v2 셀프조인이라 무거움. **C5 종료 후 실행**.

## 대상 파일
- **신규**: `scripts/def4_exception_remove_dup.py` — 탐지(§1)+fact_v2 제거·덤프(§2)+영향 corp 목록 출력.
  구조=`scripts/fin2_kgaap_gap.py`의 1회성·resumable 패턴 미러링, `store_facts` 대신 DELETE.
- **재사용(수정 없음)**: `scripts/def4_reprocess_pass2.py`(재파생), `scripts/diag_calendar_cq1_dup.py`(검증),
  `scripts/dq_assertions.py`(재발 추적, 이미 어서션 2건 보유).
- **미수정**: `fin2/extract/text.py` 등 메인 추출 파이프라인 전부(사용자 요구).

## 검증 (end-to-end)
1. `--dry-run`으로 대상 규모 확인(예상: DQ 326셀에 대응하는 보고서 수, 영향 corp 수) → 이상 시 중단.
2. 실제 실행 → `def4_reprocess_pass2.py --corps-file` 재파생.
3. `python scripts/diag_calendar_cq1_dup.py` → 인접연도 CQ1 same-rcept 잔재 **26 → ~0**(rev=0 휴면·타-rcept 우연만 잔존) 확인.
4. `python scripts/dq_assertions.py --sample` → `fact_v2_q1_duration_col0_eq_col1` 및
   `calendar_adjacent_year_cq1_identical` WARN 카운트가 급감(→ 잔여는 설명가능)했는지 확인.
5. 앱 라이브: 대표 잔재 1~2사(예 광동제약 00103592) 분기 재무제표에서 해당 전기 CQ1이
   위조 중복이 아니라 공백으로 표시되는지 스크린샷.

## 커밋 대상
- 신규 스크립트 + (있으면) 삭제 fact CSV. 재처리 자체(DB 변경)는 커밋 아님.
- `DEF-4.md`에 예외처리 결과(잔재 26→~0) 기록.
