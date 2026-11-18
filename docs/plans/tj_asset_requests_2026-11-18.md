# tj_asset 요청 처리 계획 (2026-11-18)

요청 원본: `/Users/taejin/Project/tj_asset/docs/issues/tj_finance_requests_2026-11-18.md` (7건)
회신 파일: `/Users/taejin/Project/tj_asset/docs/issues/tj_finance_responses_2026-11-18.md` (tj_finance 가 갱신)
교환 방식: tj_asset 이 요청·점검 파일을 그 폴더에 두고, tj_finance 는 회신 파일만 고친다. `tj_finance_checks.md` 는 tj_asset 주간 실행이 덮어쓰므로 손대지 않는다.

## 1번: 세전이익 − 법인세 ≠ 순이익 (R341 후보, 적용 계층: 계층3)

### 분류 (2025 FY 연결 DQ<3, 116행)
분류 쿼리: 세션 scratchpad `classify116.sql` 과 같은 로직 → 수정 후 회귀 확인용으로 `scripts/` 에 옮길 것.

| 분류 | 행 | 판정 |
|---|---:|---|
| A `-ebt - tax = ni` | 2 | 삼성중공업·삼영이엔씨. `fin2/layer3/combine.py::_loss_signed` 가 '손실' 단독 라벨 + 양수를 뒤집음. 원문은 이익인데 라벨이 전년 '순손실' 그대로 |
| B `ebt + tax = ni` | 5 | 케이티앤지·서부T&D(법인세를 음수로 인쇄), CJ CGV, 대원(`법인세수익(비용)`), 엑사이엔씨. 계층2 는 인쇄값 그대로(정상), 계층3 이 부호 정규화를 안 함 |
| C 중단영업 | 97 | IS 에 '중단' 행 존재 또는 인쇄된 계속영업이익 = ebt − tax. 정당한 차이 |
| D 기타 | 12 | 개별 확인 필요 |

### 수정안 (✅ 2026-11-18 R341 로 반영 — 실측·결과는 `docs/rules/20_layer3_map.md` R341)

- 계획과 다른 점: 보정은 `layer3_cell_corrections` 가 아니라 R318 과 같은 결합 단계 항등식 판정이라 별도 기록 없음. D 12행은 모두 중단영업이었음(재분류). 남은 4행: 비투엔·에스코넥·아이텍·DH오토리드(계속영업이익 후보 갈림, 미조사).
1. **A — `_loss_signed` 가드**: 같은 기간·기준의 인쇄된 ebt, tax, ni(또는 계속영업이익)로 항등식 `ebt − tax = ni` 를 검사해, 뒤집지 않은 값이 항등식을 만족하면 뒤집지 않는다. 항등식으로 판정 불가하면 지금 동작 유지. ebt 외 `_LOSS_CANON`(net_income, operating_income 등)에도 같은 가드를 적용할지는 전수 측정 뒤 결정.
2. **B — 법인세 부호 정규화**: 인쇄된 ebt, ni 가 있을 때 `ebt − |tax| = ni` 또는 `ebt + |tax| = ni` 중 맞는 쪽으로 tax 부호를 정함(비용 = 양수). 둘 다 안 맞으면 인쇄 부호 유지. 보정은 `layer3_cell_corrections` 에 기록(R0-2).
3. **C — 표준 계정 추가**: `is.continuing_ni`, `is.discontinued_ni` 를 계층3 매핑에 추가 → `extended_financials` 로 노출. consumer_guide 에 한 줄 추가.
4. **D**: 12행을 하나씩 원문 대조해 A/B/C 로 흡수되는지, 새 원인인지 기록.

### 검증
- 2015+ 전 기간·전 기준에서 수정 전후 A/B 해당 행 수, 바뀐 셀 목록 전수 비교(표본 금지).
- 회귀 테스트: 삼성중공업 2025 FY(ebt +6,504억), 케이티앤지 2025 FY(tax +3,522억), 루닛 2021 '당기순손실' 양수(뒤집혀야 함, 기존 동작 보존).
- 계층3 재빌드 대상 회사만 재빌드, Gate B 무영향 확인. 데일리는 계층3 빌드 경로라 별도 배선 불필요한지 runbook 으로 확인.

## 2~7번
다음 세션부터 하나씩. 순서 제안: 6(차입금 NULL 구분) → 2(order_backlog) → 3(biz_metrics) → 5(적재 상태, 스키마 승인 필요) → 4(11-19 이후 재집계) → 7.
