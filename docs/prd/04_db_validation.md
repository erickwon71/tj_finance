# PRD 04 — DB Validation (게이트 B · 100% 일치 검증 전문가) ★본 과제 최우선

> 역할 #4. 입력: PRD 03 산출물(`std_financials_v2`/`fact_v2`) + 원본 보고서.
> 출력: 보고서×계정 단위 PASS/FAIL 감사대장. **게이트 B** 운영. 총괄: `00_pm_master_plan.md`.

## 0. 왜 이 PRD 가 최우선인가

> 본 과제의 최고 중요 요구사항: **DB 금액 = 보고서 금액 100% 동일.**
> 현재 파이프라인에는 **보고서-vs-DB 검증이 전혀 없다**(기존 검증은 전부 DB-vs-DB parity 또는
> DB 내부 회계항등식). 원본을 다시 읽어 DB 와 대조하고, **틀리면 promote 를 막는** 게이트가 이 PRD 다.

## 1. 목표

게이트 A 통과 보고서의 **재무제표 본문(BS/IS/CF) 전 계정 라인**을 원본에서 재추출하여,
DB 값과 **보고서 표시단위 기준 100% 일치**하는지 판정한다. 불일치하면 그 (corp,year,period,basis)
는 `standard_financials`(view) 가 노출하지 못하게 차단한다.

## 2. 범위 (사용자 확정)

- **1단계(본 PRD)**: 재무제표 **본문(face)** 전 계정 모든 라인. 연결·별도 모두.
- **2단계(후속)**: 주석 재무항목.
- **일치 기준**: `round(DB_amount_won × 10^ADECIMAL) == 보고서_표시값`. **표시단위 자리까지 정확 일치**. 표시단위 이하(보고서에 없는 자리)는 검증불가로 인정.

## 3. 비범위

- 추출·표준화 로직 수정(PRD 03). 본 전문가는 **판정·차단**만 — 수정이 필요하면 PRD 03 에 회부.
- 회계항등식 검증은 보조 신호로만 사용(일치 판정의 1차 근거는 보고서 표시값).
- **Layer 2(달력 정규화 `std_financials_calendar`)는 게이트 B 비대상** — 어느 단일 보고서에도 명시되지 않은 파생값이므로 보고서-vs-DB 100% 일치를 적용하지 않는다. 게이트 B 는 **Layer 1(원본/as-filed `std_v2`)** 에만 적용. Layer 2 는 내부 정합성(ΣCQ=CY, native=보고FY)으로 검증(PRD 03 DoD).

## 4. 입력·출력 계약

- **입력**:
  - 원본 보고서 파일(게이트 A PASS).
  - DB: `fact_v2`(amount_won·adecimal·acode·basis·col_index·canonical_account), `std_financials_v2`.
- **출력**: 감사대장 테이블 `face_audit`(가칭).
  - 컬럼(안): rcept_no·corp·fiscal_year·fiscal_period·basis·statement·account_label·report_value·report_unit·db_amount_won·db_displayed·match(bool)·mismatch_reason·checked_at.
  - 키 단위 롤업: (corp,year,period,basis) PASS = 그 모든 본문 계정 라인 match=True.

## 5. 신규 모듈 `fin2/audit/face_audit.py` (가칭)

### 5.1 보고서 진실표 추출 (표준화와 독립)
- 보고서의 **본문 BS/IS/CF face 표**를 `(계정라벨, 표시값, 표시단위)` 튜플로 직접 재추출.
- **표준화 파이프라인과 독립**한 경로(독립 추출이라야 같은 버그를 양쪽이 공유하지 않음).
- col_index=0(당기) 컬럼만 1차 대상(비교연도 컬럼은 별도).

### 5.2 DB 값 표시단위 환산 후 대조
- DB 값을 표시단위로 환산: `db_displayed = round(amount_won × 10^ADECIMAL)`.
- 보고서 표시값과 **정확 일치** 판정.
- 매칭 단위: (corp,year,period,basis,statement,계정,col_index=0). 계정 매칭은 acode/canonical 우선, 미매핑은 라벨 정규화로 보조.

### 5.3 감사대장 기록 + 롤업
- 라인별 match/mismatch_reason 기록.
- mismatch_reason 분류(안): `VALUE_DIFF`(값 다름)·`UNIT_MISMATCH`(단위 오인식)·`MISSING_IN_DB`(보고서엔 있고 DB 엔 없음)·`EXTRA_IN_DB`(DB 엔 있고 보고서엔 없음)·`LABEL_UNMATCHED`(계정 매칭 실패).

## 6. 게이트 B 동작 (차단)

- 통과조건: (corp,year,period,basis) 의 **본문 전 계정 라인이 모두 match=True**.
- 단 하나라도 mismatch → **promote 차단**(view 미노출), 감사대장에 FAIL+사유.
- promote 제어 방식(안): `std_financials_v2` 에 `gate_b_status` 플래그 → `standard_financials` view 가 `WHERE gate_b_status='pass'` 로 필터. 통과분만 단계적 노출.

## 7. 재사용 자산

| 용도 | 파일·함수 |
|------|-----------|
| golden 케이스(스모크) | `fin2/tests/golden/golden.yaml`, `golden_check.py` |
| DB-vs-DB 회귀(보조) | `fin2/tests/parity.py` |
| 회계항등식(보조 신호) | `analyzer/verifier.py` (assets=liab+equity 등) |
| 재추출-대조 패턴 참고 | `scripts/diag_cf_da_hybrid.py` (D&A 재추출해 legacy 대조한 선례) |

> ⚠ 단, 위 도구는 전부 보조다. **게이트 B 의 1차 근거는 원본 보고서 표시값** 이다.

## 8. 완료기준 (DoD)

- 모집단의 **본문 전 계정 표시단위 일치율** 측정 + **실패목록** 산출(재현가능).
- 게이트 B 통과분만 `standard_financials` 노출(promote 차단 동작 검증).
- 표본 검증(예: 삼성전자·신흥에스이씨·리메드·큐로셀 최근 연간/분기)에서 본문 전 계정 100% 일치 또는 mismatch 사유 명확.
- **100% 일치가 promote 전제** 임이 코드/뷰 레벨에서 강제됨.

## 9. 운영 순서 (선행 의존성: 다운로드 완전성)

> ⚠ **전제**: 게이트 B 는 디스크의 원본 보고서를 대조하므로, **현재 시점까지 필요한 전 보고서가
> 확보·검증(PRD 01 완주 + 게이트 A)된 뒤**라야 전수 감사가 완전하다. 보고서가 없으면 그건
> 불일치(mismatch)가 아니라 **완전성 갭**이며 PRD 01/02 의 책임이다. 따라서 본 PRD 의 *전수* 감사는
> 완전성 확보 이후에 돈다.

1. **(완전성 확보 이전, 병행 가능) 도구 파일럿**: 디스크에 이미 있는 표본 보고서로 `face_audit` **추출기 자체의 신뢰성**만 검증(보고서 진실표가 올바로 추출되는지). 생산 감사 아님.
2. **(완전성 확보 이후) 전수 감사**: 게이트 A PASS 모집단 전체를 보고서-vs-DB 로 감사 → 불일치 규모·클래스 측정.
3. mismatch_reason 별 트리아지: 단위 오인식 / 추출 누락 / 정정본 선택 오류 / 보고서 자체 비정형 등.
4. 클래스별 회부: 다운로드 품질 → PRD 02/01, 추출·표준화 → PRD 03.
5. 게이트 B 통과분 단계적 promote.

## 10. 위험

- 보고서 face 표가 비정형(병합셀·다단헤더·K-GAAP)이라 진실표 추출 자체가 틀릴 위험 → 추출기 자체를 표본으로 검증(메타 검증). face_audit 의 추출 오류와 DB 의 추출 오류를 구분해야 함.
- 게이트 B 가 대량 FAIL → view 가 비어 소비자 영향. 완화: 단계적 promote + legacy 비교로 회귀/개선 구분.
- 계정 매칭(라벨↔canonical) 실패가 `LABEL_UNMATCHED` 오탐 유발 → PRD 03 표준화와 연동해 매칭률 개선.
