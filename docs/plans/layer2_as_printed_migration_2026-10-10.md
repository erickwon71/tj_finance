# 계층2 "인쇄된 값만" 이행 설계 (R0-2, 2026-10-10)

> 상태: **2015+ 이행 완료(2026-10-10 05시, 야간 사용자 지시)** — 결과·아침 확인 항목 `docs/qa/layer2_as_printed_impact_2026-10-10.md`. 결정 기록은 4-1·4-2절. 남은 것: D3(이슈 정리), drift 755필링, 5단계 verify_sim 재시험, 2015 이전.

## 1. 목표와 근거

- 목표: 계층2(`report_lines`)에는 DART 에 인쇄된 값만 남기고, 원문 오류로 보이는 값의 수정(부호 복원 등)은 계층3 에서 R0-1 증명으로만 한다(`docs/PARSING_RULES.md` R0-2).
- 근거(2026-10-09 측정):

| 항목 | 수치 |
|---|---|
| 계층2 에서 부호를 바꾼 셀(기계대조 `sign_restored`) | 108,124셀 / 18,087필링 (전체 셀 3,758만의 0.29%) |
| 검증 이슈 중 `sign_flip` | 86,312 / 93,287 = 92.5% (그중 SCE 85,200) |
| 미해결 SCE `sign_flip` | 9,917 (동결 ① 8,006 포함) |
| 수정 배치 중 부호·SCE 관련 | 64 / 118 = 54% |
| 계층2 부호 복원 규칙 | PARSING_RULES 약 24절, 그중 R0-1 과 어긋난 "정합화 대기" 12개 |
| 계층3 의 SCE 사용 | 없음(`fin2/layer3` 는 BS·IS·CF 만 읽음) |
| 모델 간 판정 차이의 주원인 | 복원 여부 추론(C2) — 모델 일치 시험 `docs/verification/model_parity_2026-10-09.md` |

## 2. 계층2 에서 값을 바꾸는 코드 (이행 대상)

`fin2/extract/report_lines.py::extract_report_lines` 의 후처리 체인(약 2180~2265행)과 셀 읽기 단계:

| 묶음 | 함수(파일) | R번호 | 바꾸는 것 | 계층3 이후 |
|---|---|---|---|---|
| CF overlay | `overlay_dividends_paid_sign`, `overlay_tax_expense_value` (`report_lines_inline_xbrl_overlay.py`) | R18, 법인세 overlay | inline XBRL 태그로 CF 배당 부호·법인세 값 덮어쓰기 | 계층3 키(cf.dividends_paid, is.tax_expense)에서 증명 시 적용 |
| SCE 원문결함 교정 | `apply_source_defect_fixes`, `verify_row_drops` (`sce_source_defects.py`) | R183 | 행 이동·삭제·값 교정·빈 칸 채움 | R0-1 상 후보 아님 → 폐기(원문대로) |
| SCE 부호 체인 | `repair_sce_sign_loss`, `apply_manual_sign_fixes`, `repair_sce_row_identity`, `rerun_sign_loss_after_row_identity`, `repair_sce_balance_tolerance`, `repair_sce_sibling_cells`, `apply_dated_balance_signs`, `apply_as_printed_cells` (`sce_sign_repair.py`) | R162·-d·-e·-e2·-manual·R185~R193·R188·R189·R190-d·R206·R215 | SCE 셀 부호 | 계층3 에 SCE 소비처가 생길 때 R0-1 증명 함수로 |
| CF 현금 부호 | `repair_cf_cash_sign_loss` (`cf_cash_sign_repair.py`) | R163 | CF 현금 조정 구간 셀 부호 | 계층3 CF 키에서 증명 시 |
| 숫자 오타 | `apply_source_typo_fixes` (`parser/xml/table_extractor.py:1964`) | R159·R159 보강 | 셀 숫자 교정 | 폐기(원문대로). 마침표 구분자 해석(R158 `_repair_dot_grouped_cells`)은 **읽기**라 유지 |

유지(읽는 방법, R0-2 표 왼쪽): R4 단위=열, R10 XBRL preferredLabel, R158·R202·R218, R6 NULL. **결정 필요 D1**: R169·R207(선언 단위가 스스로 모순인 표를 실제 단위로 읽기 — 숫자는 그대로, 원 환산이 1,000배 달라짐)을 계층2 읽기로 둘지 계층3 으로 옮길지. 권장: 계층2 유지(숫자·부호는 인쇄 그대로이고 단위 해석이라 R0-2 의 "읽는 방법").

## 3. 단계

**0단계 — 측정(DB 무변경, 승인 불요)**
- 체인 스위치(환경변수 `TJF_LAYER2_AS_PRINTED=1`)를 넣고, 영향 필링(기계대조 `sign_restored`>0 18,087필링 + R183·R159·overlay 대상 rcept 목록)을 끔/켬으로 재추출해 셀 단위 차이를 규칙별로 센다.
- 계층3(std_v3) 키별 영향: 끔 상태로 계층3 을 메모리에서 재계산해 바뀌는 (corp, 기간, 키) 수와 크기를 센다. 특히 cf.dividends_paid·is.tax_expense·CF 소계.
- 산출: `docs/qa/layer2_as_printed_impact_2026-10-xx.md` (규칙별 셀 수, 계층3 키별 변화).

**1단계 — 계층3 증명 함수 (코드 + 테스트)**
- `fin2/layer3/sign_proof.py`: R0-1 1~2항을 그대로 구현(후보 = 양수 인쇄 셀의 부호, ① 닫힘 → ③ 무악화 → 셀 수 최소 → ② 유일, 허용오차 `machine_compare.identity_tolerance`). 증거 = 같은 필링 계층2 값(+ R0-1 3항의 같은 회사 정기보고서).
- 0단계에서 계층3 값이 바뀌는 키에만 적용(현재 BS·IS·CF). SCE 는 계층3 소비처가 없으므로 함수만 두고 적용은 소비처가 생길 때.
- R221(비용 부호)와 같은 자리(`combine.py` 후처리)에 둔다.

**2단계 — 계층2 체인 끄기 (코드)**
- 위 2절 표의 "계층2 → 폐기/계층3" 함수 호출을 extract 경로에서 제거(스위치 기본값 = 끔, 코드는 한 릴리스 뒤 삭제).
- 검증 도구: 기계대조의 `sign_restored` 예외 제거(DB = −S 는 언제나 발견), `verify_prompt.md` 의 C2·audit 예외 제거(셀은 C1 아니면 C3), 수정 판정표의 F5·F6·F7-a 를 "계층3 증명 함수" 기준으로 고침.
- 회귀 테스트: 괄호 빠진 픽스처 → 계층2 는 인쇄 부호, 계층3 은 증명될 때만 복원.
- `collect_new.py` 두 call site 는 같은 `extract_report_lines` 를 쓰므로 배선 변경 없음(런북 확인만).

**3단계 — 재적재 (승인 필요: 수시간)**
- 대상: 0단계 영향 필링(약 18,000+). `vq.py batch reload --sd` 로 샤드 병렬. 검증 러너·기계는 정지 상태에서.
- 이어서 영향 회사 계층3 재빌드.

**4단계 — 검증 이슈 정리 (승인 필요: 동결 해제 포함)**
- 재적재 후 DB = 원문 인쇄값이 된 셀의 `sign_flip`·`value_mismatch`·`missing_row`(R183) 등 이슈를 admin 스크립트로 일괄 close(evidence `[R0-2 이행] DB=원문`). 동결 ① 8,006건과 옛 동결 ②(R165)도 여기서 정리된다.
- `source_defect`(원문 산수 불일치)는 사실 기록이라 그대로 둔다. 수정 쪽 처리는 "계층3 증명 함수가 증명하면 계층3 값으로 복원, 아니면 원문대로"로 바뀐다.

**5단계 — 확인**
- 기계대조 전체 재실행(재적재로 stale) → `sign_restored` 0, 새 `value` 발견 수 = 0단계 측정과 일치하는지.
- `scripts/verify_sim` 으로 Haiku/Sonnet 일치 재시험, Gate B·계층3 회귀(`pytest tests/ fin2/tests/`).

## 4. 결정 필요 사항

| # | 질문 | 권장 |
|---|---|---|
| D1 | R169·R207 단위 교정은 계층2 에 둔다(읽는 방법) / 계층3 으로 옮긴다 | 계층2 유지 |
| D2 | 3단계 재적재 실행 시점(수시간, 러너·기계 정지) | 0~2단계 결과 검토 후 |
| D3 | 4단계 동결 ①(8,006)·R165 정리를 이행 결과로 일괄 처리 | 일괄 처리(셀이 원문과 같아지므로 판단이 필요 없어짐) |
| D4 | 계층2 복원 코드: 스위치로 끄고 1릴리스 뒤 삭제 / 즉시 삭제 | 스위치 후 삭제 |

### 4-1. 사용자 결정 (2026-10-10 01:40~02:00)

| # | 결정 |
|---|---|
| D2 | 시간이 긴 작업(측정·재적재·계층3 재빌드)은 야간에 직접 실행 |
| D5 | R183·R159 도 계층3 에서는 정상화한다 — "계층3 에서 적용 가능한 논리적 방법은 모두 적용" |
| D6 | inline XBRL 태그(R18·법인세 overlay)도 계층3 증거로 인정 |
| D7 | SCE 도 계층3 정상화 대상 |
| D8 | 검증 도구 규약 변경 + 5단계 Haiku/Sonnet 재시험 순서 동의 |
| 범위 | **2015+ 먼저**, 2015 이전은 같은 규칙으로 나중에 |
| 미결 | D1(R169·R207 단위 — 계층2 유지로 진행, 이의 시 재논의), D3(동결 ①·R165 이슈 일괄 close — 아침 확인), D4(설명 후 재확인) |

### 4-2. 구현 결정 (설계 변경)

1절 계획의 "계층3 증명 함수를 새로 작성"(1단계) 대신, **기존 규칙 코드를 그대로 두고 결과를 계층3 테이블로 옮겼다.**
- 이유: D5~D7 로 계층3 이 기존 규칙 전부를 써야 하고, 그중 R18·법인세 overlay 는 원문 파일(inline XBRL)이 있어야 해서 DB 만 읽는 계층3 빌드 안에서는 다시 계산할 수 없다.
- 방식: 적재 시 규칙 끔(인쇄값 → `report_lines`)·켬 두 번 추출, 차이를 `layer3_cell_corrections` 에 저장, 계층3 은 `report_lines_l3` 뷰로 읽는다. 상세는 `docs/PARSING_RULES.md` R0-2 "계층3 보정의 범위와 구현".
- 결과: 계층3(std_v3) 값은 이행 전과 같아야 한다 — 5단계에서 재빌드 전후 비교로 확인.
- R0-1 정합화(정합화 대기 표의 느슨한 규칙을 ①②③ 증명으로 조이는 일)는 이제 계층3 보정 규칙의 개선 과제로 남는다(별도 트랙).
- 미포함: XBRL `_drop_redundant_gap_totals`(R208)·`_drop_sce_phantom_cells`(R209)는 인쇄되지 않은 XBRL 셀을 거르는 "읽기"로 보고 계층2 에 둔다. note_lines 의 R159 오타 셀은 인쇄값으로 바뀌고 보정 행은 만들지 않는다(note_lines 소비처 영향은 측정 문서에 기록).

## 5. 위험

- 계층3 값 변화(특히 CF 배당·법인세): 0단계 측정으로 크기를 먼저 확인하고, 1단계 증명 함수가 같은 결과를 내는지 비교한다.
- 계층3 이 SCE 를 쓰기 시작하면 그때 증명 함수 적용이 필요하다(이 문서와 R0-2 에 명시).
- 재적재 중 데일리 파이프라인과 겹치지 않게 시간대를 잡는다.
