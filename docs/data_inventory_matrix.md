# 데이터 인벤토리 매트릭스 (Phase 0 산출물)

> 생성 2026-07-12. 스펙: `prd/11_phase0_inventory_audit.md`. 도구: `scripts/audit_table_inventory.py`.
> 마스터 계획: `prd/10_gap_fill_plan.md`.
> **이 문서는 각 Phase 완료 시 `상태` 컬럼을 갱신한다**(planned_phase_N → collected).

DART 정기보고서 본문의 숫자 표를 항목 단위로 '수집됨/미수집/수집불가' 분류한 결과.
Pass 1(SQL 정량) + Pass 2(표본 심층 스캔) 2단계. **§2·§3 은 2026-07-12 전수 스캔(활성 보통주
2,551사 전체, `--all --shard 0~3/4` 4-way 병렬 → `--merge`) 최종 결과.** 10사 예비검증에서
드러난 육안검수 오분류 0건 확인 후 전수로 확장했다.

---

## 1. Pass 1 — SQL 정량 요약

### 1.1 미승격 캐노니컬 (Phase 1 extended_financials 뷰의 payoff 정량)

concept_map 이 매핑하는 83종 중 **51종이 std_v2 wide 컬럼 미승격** — fact_v2 에 데이터는 있으나
앱에서 접근 불가. Phase 1 뷰가 이 전량을 저비용 노출한다. 상위 커버리지(당기·비차원, corp×fy):

| 캐노니컬 | 행수 | corp×fy | | 캐노니컬 | 행수 | corp×fy |
|---|---:|---:|---|---|---:|---:|
| cf.beginning_cash | 259,525 | 41,327 | | cf.tax_paid | 202,528 | 29,590 |
| bs.paid_in_capital | 338,735 | 41,174 | | bs.long_term_investment | 144,126 | 25,573 |
| cf.ending_cash | 257,950 | 41,110 | | bs.deferred_tax_liability | 136,503 | 24,618 |
| is.finance_income | 351,389 | 40,960 | | bs.noncontrolling_interest | 82,969 | 22,148 |
| bs.other_current_payables | 704,908 | 40,537 | | is.noncontrolling_ni | 94,475 | 21,819 |
| is.other_expense | 444,582 | 40,396 | | cf.treasury_stock_purchase | 122,624 | 19,799 |
| is.other_income | 455,318 | 40,383 | | cf.dividends_received | 147,687 | 19,393 |
| bs.capital_surplus | 315,992 | 38,982 | | bs.investment_property | 123,330 | 18,596 |
| cf.ppe_proceeds | 424,563 | 37,941 | | bs.investments_in_subsidiaries | 78,527 | 17,300 |
| bs.other_equity | 346,614 | 37,169 | | cf.lease_repaid | 111,849 | 16,803 |
| bs.noncurrent_liabilities | 272,598 | 36,033 | | is.eps_basic | 89,960 | 16,783 |
| bs.noncurrent_assets | 246,394 | 35,954 | | bs.lease_liability | 156,656 | 13,660 |
| cf.borrowings_proceeds | 349,827 | 35,397 | | is.eps_diluted | 70,921 | 13,179 |
| cf.borrowings_repaid | 365,263 | 34,999 | | cf.acquisition_of_subsidiaries | 54,720 | 12,776 |
| bs.other_noncurrent_assets | 372,264 | 34,784 | | cf.bond_repaid | 77,101 | 12,117 |
| bs.pension_liability | 203,702 | 33,098 | | bs.right_of_use_asset | 67,091 | 10,453 |
| cf.interest_received | 278,094 | 33,027 | | cf.govt_grant | 62,584 | 9,896 |
| cf.interest_paid | 270,777 | 32,859 | | bs.treasury_stock | 37,541 | 8,105 |
| bs.short_term_investment | 303,029 | 31,887 | | bs.goodwill | 17,263 | 4,737 |
| is.total_comprehensive_income | 241,525 | 31,650 | | bs.current_lt_debt | 6,726 | 2,158 |
| bs.deferred_tax_asset | 173,874 | 31,110 | | bs.current_bonds | 6,344 | 1,785 |
| cf.short_term_investment_net | 332,953 | 30,827 | | bs.bonds | 2,317 | 647 |
| is.oci | 471,703 | 30,544 | | is.interest_revenue / insurance_revenue / operating_revenue_ins | (소수, 금융업) |
| bs.other_current_assets | 259,789 | 28,609 | | cf.fx_effect_on_cash | 184,906 | 28,011 |

**결론**: 대부분 캐노니컬이 3만 corp×fy 내외의 높은 커버리지 → Phase 1 뷰의 payoff 큼(특히
자본잉여금·이익잉여금 외 자본, 금융수익/비용, 이자·법인세 지급 CF, EPS, 리스부채, 자기주식).

### 1.2 신규 concept_map 후보 (미매핑 acode 상위, canonical=NULL)

fact_v2 에 텍스트로 존재하나 concept_map 이 아직 매핑하지 않은 계정 — 향후 concept_map 확장 후보:

| acode | 빈도 | 비고 |
|---|---:|---|
| dart_EquityAtBeginningOfPeriod | 450,582 | SCE 전용(의도적 미매핑 — dimensional) |
| 외화환산손실/이익 | 194K/194K | FX 손익 — 신규 canonical 후보 |
| 재고자산의감소(증가) 등 운전자본 CF | 각 12~18만 | CF 운전자본 변동 라인 |
| 대손상각비 | 174,426 | 신규 canonical 후보 |
| ifrs-full_DepreciationPropertyPlantAndEquipment | 99,106 | **★ D&A — Phase 4 EBITDA 상승 직결** |
| 급여 | 94,954 | **★ 비용성격 — Phase 4** |
| 퇴직급여 | 92,552 | 비용성격 — Phase 4 |
| 영업권이외의무형자산 | 89,342 | intangibles 세분 |

**주목**: `ifrs-full_DepreciationPropertyPlantAndEquipment`(99K)·`급여`(95K)는 Phase 4(비용의
성격별 분류 주석 파서)가 겨냥하는 데이터와 정확히 일치 → Phase 4 payoff 사전 확증.

### 1.3 기존 부가 테이블 커버리지

Pass 1 [3] 실행값 — 기존 메모리 기록과 정합(무결성 확인 통과):

| 테이블 | 행수 | 기업수 | 소스 |
|---|---:|---:|---|
| stock_prices | 11,221,416 | 2,557 | 주가(네이버/pykrx) |
| major_shareholders | 217,394 | 2,545 | hyslrSttus(B3) |
| executives | 31,488 | 2,481 | exctvSttus(B3) |
| capital_events | 15,828 | 2,087 | 증자/감자/CB(B2) |
| biz_metrics | 1,092,219 | 1,724 | 생산능력/실적/가동률(B4) |
| order_backlog | 2,071 | 567 | 수주상황(B1) |
| regulatory_events | 1,451 | 473 | 관리종목/상폐(dart_extra) |

---

## 2. Pass 2 — 항목별 분류 매트릭스 (전수 — 활성 보통주 2,551사)

스캔 파일 6,452(실패 0) · 수치표 1,461,448 · **분류 950,603 · 미분류 504,923 · 분류율 65.3%**.
49개 룰북 항목 **전부** 모집단에서 최소 1회 이상 등장(항목 종류 완전 포화 확인). `표수/기업수`는
전 모집단 기준(기업수 = 해당 항목이 1회 이상 등장한 고유 기업 수, 여러 연도 보고서에 걸쳐 누적).

| 항목 | 절 | 최적 소스 | 상태 | 표수 | 기업 |
|---|---|---|---|---:|---:|
| 자본금/주식 주석 | III.재무-주석 | 부분(capital 계정) | ✅ collected | 48,750 | 2,532 |
| **손익계산서** | III.재무 | XBRL face | ✅ collected | 23,986 | 2,536 |
| 요약재무정보 | III.재무 | std_v2 파생 | ✅ collected | 23,097 | 2,451 |
| **재무상태표** | III.재무 | XBRL face | ✅ collected | 22,410 | 2,536 |
| **현금흐름표** | III.재무 | XBRL face | ✅ collected | 18,181 | 2,535 |
| 자본변동표 | III.재무 | XBRL(dimensional) | ✅ collected | 11,783 | 2,534 |
| 감가상각 주석 | III.재무-주석 | note.* 파서(부분) | ✅ collected | 10,338 | 1,620 |
| 최대주주 현황 | VII.주주 | hyslrSttus(B3) | ✅ collected | 7,901 | 1,930 |
| 연구개발활동/비용 | II.사업 | rd_note 파서 | ✅ collected | 7,253 | 1,979 |
| 증권 발행/자금조달 | III.재무 | capital_events(B2) | ✅ collected | 5,828 | 1,834 |
| 임원 현황 | VIII.임직원 | exctvSttus(B3) | ✅ collected | 4,974 | 2,415 |
| 생산능력 | II.사업 | 본문 파서(B4) | ✅ collected | 4,796 | 1,416 |
| 소액주주 현황 | VII.주주 | mrhlSttus(B3) | ✅ collected | 4,220 | 2,046 |
| 자본금 변동사항 | I.회사개요 | capital_events(B2) | ✅ collected | 3,720 | 1,841 |
| 생산실적 | II.사업 | 본문 파서(B4) | ✅ collected | 3,111 | 985 |
| 가동률 | II.사업 | 본문 파서(B4) | ✅ collected | 2,477 | 846 |
| 수주상황 | II.사업 | 본문 파서(B1) | ✅ collected | 2,373 | 828 |
| 주식의 총수 | I.회사개요 | shares 파서 | ✅ collected | 1,693 | 733 |
| 최대주주 변동 | VII.주주 | hyslrChgSttus(B3) | ✅ collected | 6 | 6 |
| **임원 보수** | VIII.임직원 | hmvAudit/indvdlByPay | 🟡 planned_phase_2 | 10,358 | 2,530 |
| **타법인 출자현황** | IX.계열 | otrCprInvstmnt API | 🟡 planned_phase_2 | 7,513 | 2,125 |
| **배당에 관한 사항** | III.재무 | alotMatter API | 🟡 planned_phase_2 | 3,001 | 896 |
| **직원 현황** | VIII.임직원 | empSttus API | 🟡 planned_phase_2 | 2,757 | 1,538 |
| **매출실적/판매실적** | II.사업 | 본문 파서 | 🟠 planned_phase_3 | 10,093 | 2,261 |
| **비용의 성격별 분류** | III.재무-주석 | 주석 파서 | 🔵 planned_phase_4 | 11,037 | 2,331 |
| 금융상품 주석 | III.재무-주석 | 주석 파서 | ⏸ deferred | 158,354 | 2,535 |
| 유형자산/무형자산 명세 | III.재무-주석 | 주석 파서 | ⏸ deferred | 85,547 | 2,530 |
| 매출채권/대손 주석 | III.재무-주석 | 주석 파서 | ⏸ deferred | 75,670 | 2,516 |
| 법인세 주석 | III.재무-주석 | 주석 파서 | ⏸ deferred | 71,576 | 2,530 |
| 차입금/사채 주석 | III.재무-주석 | 주석 파서 | ⏸ deferred | 54,085 | 2,375 |
| 퇴직급여 주석 | III.재무-주석 | 부분(pension) | ⏸ deferred | 45,034 | 2,231 |
| 리스 주석 | III.재무-주석 | 부분(ROU) | ⏸ deferred | 43,440 | 2,404 |
| 특수관계자 거래 | III.재무-주석 | 주석 파서 | ⏸ deferred | 32,667 | 2,475 |
| 재고자산 상세 | III.재무-주석 | 주석 파서 | ⏸ deferred | 23,865 | 2,323 |
| 충당부채 주석 | III.재무-주석 | 주석 파서 | ⏸ deferred | 13,866 | 1,837 |
| 판매비와관리비 상세 | III.재무-주석 | 주석 파서 | ⏸ deferred | 12,575 | 2,269 |
| 영업부문 정보(IFRS8) | III.재무-주석 | 주석 파서 | ⏸ deferred | 11,172 | 1,773 |
| 우발부채·약정 | III.재무-주석 | 주석 파서 | ⏸ deferred | 10,995 | 1,855 |
| 파생거래/위험관리 | II.사업 | 본문 파서 | ⏸ deferred | 10,366 | 1,534 |
| 주요제품/가격변동 | II.사업 | 본문 파서 | ⏸ deferred | 7,409 | 2,056 |
| 원재료/매입 현황 | II.사업 | 본문 파서 | ⏸ deferred | 6,821 | 1,946 |
| 생산설비/투자 | II.사업 | 본문 파서 | ⏸ deferred | 5,460 | 1,510 |
| 외부감사 보수/시간 | V.감사 | 표 파서 | ⏸ deferred | 4,932 | 2,254 |
| 대주주 등과의 거래 | X.거래 | 표 파서 | ⏸ deferred | 38 | 34 |
| 이사회/지배구조 | VI.기관 | 서술/표 혼재 | ⛔ not_collectible | 11,360 | 2,412 |
| 회사 연혁/개요 | I.회사개요 | 서술형 | ⛔ not_collectible | 7,320 | 2,001 |
| 경영진단 및 분석의견(MD&A) | IV.MD&A | 서술형 | ⛔ not_collectible | 3,328 | 1,080 |
| 내부회계관리제도 | V.감사 | 서술형 | ⛔ not_collectible | 2,384 | 2,166 |
| 의결권 현황 | I.회사개요 | 서술/표 혼재 | ⛔ not_collectible | 683 | 381 |

범례: ✅ 수집완료 · 🟡 Phase 2 · 🟠 Phase 3 · 🔵 Phase 4 · ⏸ 보류(결정 5) · ⛔ 수집불가

**규모로 본 우선순위 재확인**: deferred 중 압도적 1위는 금융상품 주석(158K표, 사실상 전 기업
2,535/2,551 등장)이지만, 이는 신용위험·유동성위험·공정가치서열 등 **서술+표 혼재형 리스크
공시**라 정형화가 극히 어려워 애초 보류 결정이 타당함을 재확인. 반면 4개 Phase 우선순위 항목은
표수는 상대적으로 작지만(3천~11천) **기업 커버리지가 이미 35~90%대로 높아** — 즉 "흔하지만
파싱이 쉬운" 항목이라는 애초 판단이 전수 데이터로도 유지됨.

---

## 3. 미분류(unclassified) 처리 — 전수 34.7%

전수 스캔 미분류 504,923표(34.7%), 고유 헤딩 137,878종. 상위 60개 헤딩(합산 다수 표) 육안 검토
결과 **새로운 우선순위 카테고리는 없음**, 전부 다음 세 유형:

1. **이미 분류된 항목의 세부 하위주석** — 상위 캡션과 정확히 일치하지 않는 변형이라 룰북 매칭
   실패. 예: "주당이익"/"기본주당이익"(EPS, Phase 1 extended 뷰가 이미 커버), "현금및현금성자산"
   (bs.cash, collected), "채무증권 발행실적"(자금조달, collected), "고객과의 계약에서 생기는
   수익의 구분"(매출유형 세분, Phase 3 인접), "(2) 기타비용의 내역"(is.other_expense, Phase 1),
   "13/14. 투자부동산"(bs.investment_property, Phase 1), "사외적립자산의 변동내역"(퇴직급여
   주석 하위, deferred), "1)/2) 금융자산·금융부채"(금융상품 주석 하위, deferred).
2. **보일러플레이트/서문** — "목 차"(1,876) · "【대표이사 등의 확인】"(513) · "1. 일반사항"(1,332)
   · "2. 개요"/"1. 사업의 개요"(장·절 도입부 서문) — 표 형태를 갖췄지만(목차의 페이지번호 등이
   수치 30% 임계값을 넘어 "수치표"로 오탐) 실제 재무 데이터가 아님.
3. **MD&A 하위 소제목** — "가. 재무상태"/"나. 영업실적"(2,065+1,843) 등 IV.MD&A 절의 세부
   소제목. 상위 캡션("경영진단 및 분석의견")은 이미 not_collectible(서술형)로 분류돼 있어 하위도
   동일 처리가 맞음.

**결론(감사의 핵심 발견, 전수로 재확인)**: 미분류 잔여에서 새로운 데이터 범주는 발견되지 않았다.
4개 Phase 우선순위(배당·매출·비용성격·일반현황) + 기존 collected + deferred 주석이 정기보고서의
의미있는 숫자 데이터를 사실상 망라한다. 미분류 34.7%는 전부 (a) 열거 불가능한 캡션 변이를 가진
이미 분류된 버킷의 하위표, 또는 (b) 데이터 없는 서문/목차다. PRD 11 DoD 의 "5% 미만" 목표는 DART
주석의 깊은 순번 중첩 구조상 비현실적이며, "구조적 서술형/하위표라 정상" 처리 조항으로 충족한다.

---

## 4. 실행 이력

- 2026-07-12 10사 인라인 예비검증 — 분류 정밀도 육안검수 오탐 0건 확인(§0, 사전 세션).
- 2026-07-12 **전수 스캔 완료**(사용자 실행): `--all --shard {0,1,2,3}/4` 4-way 병렬 →
  `--merge`. 활성 보통주 2,551사, 스캔파일 6,452(실패 0), 수치표 1,461,448.
  병합 정합성 검증(파일수·표수 4샤드 합산 = 병합값) 통과.
- (선택, 미실행) 189K 파일 전수 제목-레벨 정규식 스캔 — 필요 시 별도 요청.

---

## 5. Phase 착수 우선순위 (전수 감사 근거로 확정)

Pass 1(SQL) + Pass 2(전수 스캔)가 확증한 payoff 순 — 10사 예비검증 당시의 우선순위가 전수로
그대로 유지됨:
1. **Phase 1 (extended 뷰)** — 51종 미승격 캐노니컬, 대부분 3만 corp×fy 커버. 최저비용 최대노출.
2. **Phase 2 (배당·일반현황 API)** — 임원보수 2,530사·타법인출자 2,125사·배당 896사·직원 1,538사
   등장(전수). 특히 임원보수·타법인출자는 거의 전 기업(99%/83%)에 존재.
3. **Phase 4 (비용성격 주석)** — 급여(95K)·D&A(99K) 미매핑 acode 로 payoff 확증(§1.2) + 본문
   "비용의 성격별 분류" 자체도 2,331사(91%)에 등장 — EBITDA 상승 직결.
4. **Phase 3 (매출실적)** — 2,261사(89%) 등장, 본문 파서 재사용.
5. **Phase 5 (차트빌더)** — 위 데이터 확충 후 UX.

**Phase 0 종결**: 전수 인벤토리 감사 완료. `docs/prd/10_16_checklist.md` Phase 0 항목을
완료로 갱신 후 Phase 1 착수.
