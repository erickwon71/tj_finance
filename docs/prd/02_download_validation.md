# PRD 02 — Download Validation (게이트 A · 다운로드 검증 전문가)

> 역할 #2. 입력: PRD 01 산출물(raw_report 파일 + filings/download_tasks).
> 출력: 보고서 단위 PASS/FAIL 대장. **게이트 A** 운영. 총괄: `00_pm_master_plan.md`.

## 1. 목표

다운로드된 보고서가 **유효하고 완전한지** 판정하여, 결함 있는 보고서가 DB화(PRD 03)로
넘어가지 못하게 차단한다. 다운로더(PRD 01)와 **역할 분리** — 다운로더는 받고, 본 전문가는 검증한다.

판정 대상:
- 결산시점이 다른/변경된 기업 포함, 기업·연도당 **Q1·H1·Q3·FY 4건 + 정정본**이 모두 확보됐는가.
- 각 파일이 손상 없이 재무제표를 담고 있는가.

## 2. 비범위

- 금액 정확성(보고서-vs-DB)은 게이트 B(PRD 04). 본 게이트는 **파일·완전성 수준**까지.
- 다운로드 재시도(PRD 01).

## 3. 입력·출력 계약

- **입력**: raw_report 파일, `filings`, `download_tasks`, `corporations.fiscal_month`(+변경 이력).
- **출력**: 보고서 단위 PASS/FAIL 대장(신규 테이블 `download_validation` 또는 스크립트 리포트).
  - 컬럼(안): rcept_no·corp·fiscal_year·fiscal_period·status(PASS/FAIL)·fail_reason·checked_at.
  - fail_reason 분류: `MISSING_FILE`·`ZERO_BYTE`·`BAD_MAGIC`·`TRUNCATED`·`NO_STATEMENTS`·`AMEND_INCOMPLETE`·`PERIOD_MISSING`.

## 4. 재사용 자산

| 용도 | 파일·함수 |
|------|-----------|
| 기대 기간 그리드 | `scripts/check_period_completeness.py` `build_expected_grid()`, `cell_status()` |
| 다운로드 커버리지 | `scripts/check_download_coverage.py` |
| 섹션 탐지(재무제표 존재 확인용) | `parser/.../section_detector` (PRD 03 추출기와 공유) |

> ⚠ file 경로는 구현 시 재확인.

### 기존 동작 (재사용)
- 기대그리드: 기업 첫 기간~오늘, 결산월 기반 Q1/H1/Q3/FY 셀 생성, 마감유예(Q:45·FY:90일) 지난 셀만 검사.
- 셀 상태: OK(is_final+completed) / NODL(filing 있고 미다운로드) / NOFIL(filing 레코드 없음).

## 5. 신규/보강 작업 (현재 사전검증 부재)

### 5.1 파일 무결성
- **0바이트/절단**: file_size==0 또는 디스크 실파일과 `download_tasks.file_size` 불일치.
- **매직바이트**: ZIP=`PK`, PDF=`%PDF`. 불일치 시 BAD_MAGIC.
- 다운로드 직후 + 대장 갱신 시 강제 검사.

### 5.2 재무제표 존재 확인
- 다운로드 문서에 **BS·IS·CF face 표가 실제로 있는지** 섹션 탐지 dry-run 으로 판정.
- "다운로드 성공이나 재무제표 없음"(예: 표지/요약만, 첨부 누락) 케이스를 `NO_STATEMENTS` 로 식별.
- ⚠ 이 단계는 *존재 여부*만 본다(금액·계정 정확성은 게이트 B).

### 5.3 정정 완전성
- 정정본(`is_amendment` 또는 첨부정정)이 있는 기간은 **원본 + 정정본 둘 다** completed 인지.
- 누락 시 `AMEND_INCOMPLETE` → PRD 01 재다운로드 요청.

### 5.4 기간 완전성
- 기대그리드 대비 누락 셀(`PERIOD_MISSING`) 집계. 결산변경 기업은 PRD 01 의 변경 이력 반영된 그리드 사용.

## 6. 게이트 A 동작

- 통과조건: (파일 무결) ∧ (재무제표 존재) ∧ (정정 완전) ∧ (기간 완전).
- FAIL → 해당 (corp, year, period) 를 PRD 03 진입 차단 목록에 기록 + PM 리포트.
- PASS 모집단 = PRD 03 입력.

## 7. 완료기준 (DoD)

- 게이트 통과 모집단이 명확히 정의되고, **실패목록이 재현가능**(같은 입력 → 같은 판정).
- fail_reason 별 집계가 PM 대시보드에 보고됨.
- 결산변경/비12월 기업이 기대그리드에서 정확히 다뤄짐.

## 8. 위험

- 섹션 탐지가 K-GAAP/구형 포맷에서 약함 → `NO_STATEMENTS` 오탐 가능. 포맷별 화이트리스트·예외처리.
- 게이트가 과도하게 엄격하면 모집단이 급감 → fail_reason 별 단계적 적용(치명 결함 우선 차단).
