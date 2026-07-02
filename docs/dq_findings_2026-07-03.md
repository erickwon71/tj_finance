# 데이터 무결성 조사·수정 결과 (2026-07-03)

P0 무결성 도구(I1 교차검증 · I3 SQL 어서션)가 드러낸 이슈를 조사하고, 실제 파이프라인 버그와
sandbox 합성/시드 데이터·기존 known-gap 을 구분해 처리한 기록. (B 단계.)

## 1. operating_income == net_income (영업이익=순이익) — ✅ 수정 완료

**증상**: as-reported(FY/Q1) 행 중 영업이익이 순이익과 **원 단위까지 정확히 일치** 660사·3,204행.
정상적으로 이럴 확률은 0(순이익=영업이익−영업외−세금). 소형·중형주 다수(텔레칩스·아이디스·
투비소프트 등), 합성 의심 대상(삼성/SK)과 무관.

**근본원인**: **Track B(텍스트) 추출**이 손익계산서에서 **순이익 라인을 `is.operating_income`
canonical 로 오매핑** → 같은 canonical·col0 에 영업이익 실제값과 순이익값이 함께 존재.
`build._collect` 의 **max-abs 중복해소**가 (대개 더 큰) 순이익값을 영업이익으로 오선택.
- 예) 아이디스 2023 연결: is.operating_income 후보 {0, 22.6B(실제), 25.28B(=순이익)} → max-abs=25.28B.
- Gate B(보고서==DB)는 통과했음 — 독립 reader 도 같은 텍스트표를 같게 읽기 때문. **교차검증(I1)이
  아니면 못 잡는 케이스** = I1 도입 가치 입증.

**수정**(`fin2/standardize/build.py::_collect`): 비-interim(FY/Q1)에서 operating_income==net_income
이면, 순이익과 다른 비영(非0) 영업이익 후보 중 max-abs 를 재채택. **op≠ni 인 정상 26k 행은
불변**(버그 signature 있을 때만 발동) → 회귀 없음.

**적용**(`scripts/fin2_fix_op_eq_ni.py`): 영향 660사 standardize→quarterly→calendar 재실행.

**검증**: 아이디스 2023 vs DART **12 MATCH / 0 MISMATCH**(영업이익 22.6B=DART 실측). golden 5/5,
test_rules 9/9. 어서션 `operating_income_eq_net_income`(dq_assertions.py, WARN) 로 잔여·재발 추적.

**잔여**: interim(H1/Q3)·대체후보 없는 케이스는 미교정(어서션 WARN 으로 추적). interim 은 누적/3개월
구분이 있어 별도 처리 필요.

## 2. 자산총계 <= 0 (as-reported) — 대부분 known-gap

237행 중 **230행(97%)이 pre-2011 K-GAAP**(is_ifrs=false/null) = `docs/known_gaps_db_coverage.md` 의
구형 K-GAAP 구조적 미커버. **7행만 2011+ IFRS** → 실제 추출 버그 후보(개별 조사 대상, 소량·저우선).
소비계층은 `data_quality<3` 필터라 대부분 화면 노출 안 됨. I3 어서션이 상시 추적.

## 3. 미래 period_end — sandbox 합성/시드

std_v2 8행(포시에스 00939942·프레스티지바이오파마 01510489, 2026 Q3 period_end 2026-09-30).
6월 결산사의 회계 Q3 는 원래 2026-03-31 이어야 하나 미래일자 → **이 env 의 합성/시드 데이터**
(메모리 기록과 정합). 달력화 가드(`calendar._is_calendarizable_end`)가 전파는 차단. Layer-1 잔존분은
소스(합성) 이슈라 파이프라인 수정 대상 아님. I3 어서션이 상시 감시(실 운영에선 소스 정상화 시 소멸).

## 4. 연결 자산 < 별도 자산 (2,765) — 혼재, 개별조사 필요

일부는 **별도 ×10^6 단위오류 의심**(예: 별도 자산이 연결의 10^6 배), 일부는 정상 예외(지주 구조),
일부는 **기재정정 노이즈**(I1 교차검증에서 DART=최신정정본 vs DB=최초제출 차이). 일괄수정 불가 →
WARN 유지, 표본 조사 후 단위오류만 선별 수정 권장(후속).

## 참고 — I1 교차검증 해석 주의
DART `fnlttSinglAcnt` 는 **최신(정정 반영) 값**을 주고 DB 는 **최초 제출(as-filed)** 이라, 기재정정
기업(예: 금양 2022)은 매출·자산·순이익이 통째로 다를 수 있음 — 이는 버그가 아니라 정정 시점 차이.
교차검증 MISMATCH 는 (a)추출버그 (b)정정 시점차 (c)sandbox 합성 을 구분해 해석해야 함.
