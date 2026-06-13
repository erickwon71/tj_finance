# PRD 01 — Report Downloader (보고서 다운로드 전문가)

> 역할 #1. 입력: corp 목록. 출력: raw_report 실파일 + `filings`/`download_tasks` 적재.
> 총괄: `00_pm_master_plan.md`. 다음 단계: 게이트 A(`02_download_validation.md`).

## 1. 목표

대상 기업(KOSPI/KOSDAQ 거래가능 보통주)의 정기보고서를 **빠짐없이** 확보한다.
- 기업·연도당: **분기 2건(Q1·Q3) + 반기 1건(H1) + 연간 1건(FY)**.
- **기재정정·첨부정정 수정본**까지 확보(원본 + 정정본 둘 다).
- 결산시점이 다른 기업, 결산시점이 **변경된** 기업을 정확히 판단해 기간 라벨을 부여.

## 2. 비범위

- 다운로드 유효성 판정(게이트 A, PRD 02 담당).
- 파싱·표준화(PRD 03). 본 전문가는 **파일 확보 + 메타 적재**까지만.

## 3. 입력·출력 계약

- **입력**: `corporations`(대상 기업, `fiscal_month`), DART OpenAPI/Legacy 뷰어.
- **출력**:
  - raw_report 실파일(`/Volumes/Data/raw_report` 심볼릭, OneDrive 금지).
  - `filings`: rcept_no·report_type·fiscal_year·fiscal_period·is_amendment·is_final.
  - `download_tasks`: status(pending→downloading→completed|failed|skipped)·file_path·file_size·attempts.

## 4. 재사용 자산 (기존 코드)

| 용도 | 파일·함수 |
|------|-----------|
| 메인 다운로드 | `collector/downloader.py` `run_downloads()`, `_pick_best_file_by_size()` |
| 폴백(PDF/HTML 뷰어) | `collector/legacy_downloader.py` `LegacyDartScraper.fetch()` |
| 공시목록 동기화 | `collector/filing_collector.py` `sync_filings()` |
| 기간 라벨 계산 | `collector/filing_collector.py` `compute_fiscal_year_period()` |
| 결산월 탐지 | `collector/filing_collector.py` `_detect_fiscal_month()` |
| 정정 판정 | `collector/filing_collector.py` `_is_amendment()` |
| 최신본 플래그 | `collector/filing_collector.py` `_update_is_final_flags()` |
| 보고서 유형 매핑 | `collector/config.py` `REPORT_TYPE_MAP` |
| 소실 복구 | `run.py reset-missing` |

> ⚠ 위 file:line 은 작성시점 기준. 구현 시 현재 코드로 재확인.

### 기존에 이미 동작하는 것 (재사용, 재작성 금지)
- is_final + 정정쌍 원본 동시 다운로드 대상 선정(`filing_collector.py:404-422` 인근).
- 비12월 결산 기간 계산(`compute_fiscal_year_period` 의 `months_into = (period_end_month - fiscal_month) % 12`).
- DART 오류코드 처리(013/014/020) 및 Legacy 뷰어 폴백(세션쿠키·viewDoc 위치파싱 — `key-bugs-fixed` 참조).

## 5. 신규/보강 작업

### 5.1 결산월 변경 이력 (★)
- **문제**: `corporations.fiscal_month` 는 단일값(최신 연간 기준). 기업이 결산월을 바꾸면(예 12월→3월) **변경 전** 보고서의 fiscal_year/period 계산이 틀어진다.
- **방향**: 기간 라벨을 *그 보고서 시점의* 결산월로 계산.
  - 각 보고서의 `(YYYY.MM)` 에서 그 시점 결산월을 도출(보고서별).
  - 또는 결산월 변경 이력 테이블(`corp_code, effective_from, fiscal_month`) 도입.
- **검증**: 결산변경 기업 표본의 변경 전/후 보고서가 모두 올바른 fiscal_year/period 를 갖는지.

### 5.2 첨부정정 탐지
- **문제**: `_is_amendment()` 가 `[기재정정]`만 본다. `[첨부정정]` 은 미탐지.
- **방향**: `[첨부정정]` 별도 플래그(`is_attachment_amendment` 등) 추가.
  - **다운로드 대상엔 포함**(원본+정정본 모두 확보).
  - 정정 종류 구분 신호는 PRD 03(표준화 source 선택)·PRD 04 가 사용. 다운로더는 확보·라벨링만.

### 5.3 결산시점이 다른/변경된 기업 판단
- 비12월 결산: 기존 로직 유지·검증.
- 결산변경: 5.1 로 처리. 변경 분기에 기간이 짧거나 긴 회계기간(예 9개월 결산기)이 생길 수 있음 → period 라벨 규칙을 PM·PRD03 과 합의(이 케이스는 별도 표기).

## 6. 완료기준 (DoD)

- `scripts/check_period_completeness.py` 기대그리드 대비 **NOFIL/NODL = 0**(마감유예 지난 분).
- 비12월·결산변경 기업의 fiscal_year/period 라벨이 정합(표본 수동검증 통과).
- 첨부정정 포함 정정본이 원본과 함께 확보됨.
- raw_report 가 로컬/외장 실파일(OneDrive 온디맨드 금지).

## 7. 위험

- DART 일일쿼터(020)로 전수 재다운로드 수일 소요 → resumable(`reset-missing`/idempotent) 유지.
- 디스크 용량(코퍼스 ~217G) → 저장위치·여유 모니터링.
- 014(파일없음, 구형) → Legacy 뷰어 폴백, 실패 시 skipped(정상).
