# 업종 프로파일 파생 revenue — Phase 0 성분 face 존재율 census (2026-08-17)

읽기전용 census. design: `gateb_industry_derived_revenue_design_2026-08-17.md` §4 Phase 0.

모집단: 4539행 / 46개사


## bank

| component | matched | unmatched | read_failed | no_rcept | no_file | 매칭률(matched/검증가능) |
|---|---|---|---|---|---|---|
| fee_revenue | 717 | 20 | 0 | 0 | 2 | 97.3% |
| insurance_revenue | 153 | 0 | 0 | 0 | 1 | 100.0% |
| interest_revenue | 779 | 20 | 0 | 0 | 2 | 97.5% |
| other_op_revenue | 184 | 6 | 0 | 0 | 0 | 96.8% |

## credit_finance

| component | matched | unmatched | read_failed | no_rcept | no_file | 매칭률(matched/검증가능) |
|---|---|---|---|---|---|---|
| fee_revenue | 148 | 82 | 0 | 0 | 0 | 64.3% |
| interest_revenue | 148 | 82 | 0 | 0 | 0 | 64.3% |
| other_op_revenue | 43 | 42 | 0 | 0 | 0 | 50.6% |

## insurance

| component | matched | unmatched | read_failed | no_rcept | no_file | 매칭률(matched/검증가능) |
|---|---|---|---|---|---|---|
| insurance_revenue | 252 | 26 | 0 | 0 | 0 | 90.6% |
| investment_revenue | 228 | 50 | 0 | 0 | 0 | 82.0% |

## securities

- gross_fallback(검증대상 아님, 일반경로 통과): 499행

| component | matched | unmatched | read_failed | no_rcept | no_file | 매칭률(matched/검증가능) |
|---|---|---|---|---|---|---|
| operating_income | 1774 | 284 | 673 | 0 | 0 | 86.2% |
| sga | 1784 | 274 | 673 | 0 | 0 | 86.7% |

## 미매칭 표본 (component 별 최대 5건)


### bank.fee_revenue

| corp_code | fy | fp | basis | value_won |
|---|---|---|---|---|
| 00688996 | 2011 | H1 | separate | 657,967,000,000 |
| 00688996 | 2011 | Q3 | separate | 678,169,000,000 |
| 01203312 | 2021 | FY | consolidated | 44,487,000,000 |
| 01203312 | 2022 | FY | consolidated | 32,014,000,000 |
| 01203312 | 2022 | H1 | consolidated | 17,293,000,000 |

### bank.interest_revenue

| corp_code | fy | fp | basis | value_won |
|---|---|---|---|---|
| 00688996 | 2011 | H1 | separate | 3,434,740,000,000 |
| 00688996 | 2011 | Q3 | separate | 3,585,986,000,000 |
| 01203312 | 2021 | FY | consolidated | 237,662,000,000 |
| 01203312 | 2022 | FY | consolidated | 521,928,000,000 |
| 01203312 | 2022 | H1 | consolidated | 207,688,000,000 |

### bank.other_op_revenue

| corp_code | fy | fp | basis | value_won |
|---|---|---|---|---|
| 00858364 | 2024 | FY | consolidated | 817,000,079,756 |
| 00858364 | 2025 | FY | consolidated | 756,684,108,170 |
| 00858364 | 2025 | H1 | consolidated | 390,266,801,231 |
| 00858364 | 2025 | Q1 | consolidated | 220,606,698,888 |
| 00858364 | 2025 | Q3 | consolidated | 564,315,585,835 |

### credit_finance.fee_revenue

| corp_code | fy | fp | basis | value_won |
|---|---|---|---|---|
| 00124805 | 2017 | FY | consolidated | 27 |
| 00124805 | 2017 | H1 | consolidated | 409,363,759 |
| 00124805 | 2017 | Q3 | consolidated | 544,782,524 |
| 00124805 | 2018 | FY | consolidated | 28 |
| 00124805 | 2018 | H1 | consolidated | 28 |

### credit_finance.interest_revenue

| corp_code | fy | fp | basis | value_won |
|---|---|---|---|---|
| 00124805 | 2017 | FY | consolidated | 26 |
| 00124805 | 2017 | H1 | consolidated | 13,324,445,880 |
| 00124805 | 2017 | Q3 | consolidated | 14,316,769,124 |
| 00124805 | 2018 | FY | consolidated | 27 |
| 00124805 | 2018 | H1 | consolidated | 27 |

### credit_finance.other_op_revenue

| corp_code | fy | fp | basis | value_won |
|---|---|---|---|---|
| 00124805 | 2017 | FY | consolidated | 31 |
| 00124805 | 2017 | H1 | consolidated | 1,348,921,479 |
| 00124805 | 2017 | Q3 | consolidated | 634,093,579 |
| 00124805 | 2018 | FY | consolidated | 31 |
| 00124805 | 2018 | H1 | consolidated | 31 |

### insurance.insurance_revenue

| corp_code | fy | fp | basis | value_won |
|---|---|---|---|---|
| 00103176 | 2023 | FY | consolidated | 2,635,092,000,000 |
| 00103176 | 2023 | H1 | consolidated | 653,407,000,000 |
| 00103176 | 2023 | Q1 | consolidated | 651,285,000,000 |
| 00103176 | 2023 | Q3 | consolidated | 1,973,422,000,000 |
| 00103176 | 2024 | FY | consolidated | 2,619,653,000,000 |

### insurance.investment_revenue

| corp_code | fy | fp | basis | value_won |
|---|---|---|---|---|
| 00103176 | 2023 | FY | consolidated | 717,315,000,000 |
| 00103176 | 2023 | H1 | consolidated | 164,337,000,000 |
| 00103176 | 2023 | Q1 | consolidated | 224,662,000,000 |
| 00103176 | 2023 | Q3 | consolidated | 510,833,000,000 |
| 00103176 | 2024 | FY | consolidated | 754,363,000,000 |

### securities.sga

| corp_code | fy | fp | basis | value_won |
|---|---|---|---|---|
| 00104856 | 2010 | Q3 | consolidated | 401,058,762,108 |
| 00104856 | 2011 | H1 | consolidated | 290,485,419,039 |
| 00104856 | 2011 | Q1 | consolidated | 146,812,129,013 |
| 00104856 | 2011 | Q3 | consolidated | 444,512,430,836 |
| 00110893 | 2010 | Q3 | consolidated | 243,692,321,922 |

### securities.operating_income

| corp_code | fy | fp | basis | value_won |
|---|---|---|---|---|
| 00104856 | 2010 | Q3 | consolidated | 210,368,392,583 |
| 00104856 | 2011 | H1 | consolidated | 151,885,183,205 |
| 00104856 | 2011 | Q1 | consolidated | 71,208,489,028 |
| 00104856 | 2011 | Q3 | consolidated | 245,711,221,213 |
| 00104856 | 2013 | FY | consolidated | 229,128,869,266 |

---

## 분석 (원문대조 3건, 2026-08-17)

census 완료 후 unmatched 표본 중 3건을 원문 대조했다(R0/R9 — 집계로 끝내지 않음).
**두 개의 서로 다른 원인**이 unmatched 를 설명한다.

### 원인 1 — Track B "연결 basis 통째 미검출" (일반 리더 결함, 프로파일 무관)

| corp | 파일 | 결과 |
|---|---|---|
| 00104856(삼성증권) 2010Q3 | `20100216000166.xml` | Track B, 474행, **basis={'separate'} 뿐 — consolidated 0행** |
| 00103176(흥국화재) 2023FY | `20240430000965.xml` | Track B, 263행, **basis={'separate'} 뿐 — consolidated 0행** |

두 파일 모두 `_detect_body_statement_tables`(텍스트 리더)가 연결재무제표 섹션 자체를
못 찾는다. 이 basis 의 **모든** BS/IS/CF 필드가 영향받는다(revenue 파생 성분만이 아님) —
즉 이 census 가 프로파일 특유의 문제가 아니라 **기존 Gate B Track B 리더의 사각지대**를
드러낸 것이다. securities unmatched 284/274 건과 insurance unmatched 26/50 건 상당수가
이 패턴일 가능성이 높다(표본 2건으로 확정, 전체 비중은 미측정 — 범위 밖).
→ **① 문서 범위 밖의 별도 리더 결함**. 후속 트랙 후보로 기록.

### 원인 2 — credit_finance 00124805(푸른저축은행) revenue 자체가 손상된 값

| fy/fp | revenue(std_v3) | industry_lines |
|---|---|---|
| 2017 FY/Q1, 2018 전체 | **84~87원** | `fee_revenue=27~28, interest_revenue=26~27, other_op_revenue=31~32` |
| 2017 H1/Q3 (같은 회사) | 15,082,731,118 / 15,495,645,227원 | 정상 스케일 성분 |

같은 회사·인접 분기인데 FY/Q1 만 **원 단위 두 자릿수**(저축은행 revenue 가 87원일 수 없음)이고
H1/Q3 는 150억원대로 정상이다. `industry_profiles.py::compose()`가 이 필링들에서 엉뚱한
(스케일이 다른) fact 를 골랐다는 뜻 — **std_v3 데이터 결함**이지 감사기 문제가 아니다.
census 의 unmatched 판정(값이 face 에 없음)은 **정확했다** — 이 잘못된 revenue 는 Phase 2
파생검증에서 여전히 fail 로 남을 것이다(설계 §5 "새 진짜 결함이 드러날 수 있다"의 실례).
→ 이 corp/period 8건은 **별도 std_v3 버그 트랙**(layer3 compose() 스케일 오선택) 후보.
   Phase 1/2 를 막지 않음 — 오히려 Phase 2 가 이걸 fail 로 정확히 잡아낼 것.

### census 자체의 결론

- 프로파일 4종 모두에서 **값-멤버십 직접대조**(canonical 무관)가 실제로 작동한다 — bank
  96.8~100%, insurance 82~90.6%, securities(read_failed 제외) 86%대. 설계 §3-A 가 가정한
  "concept_map 갭 1건"이라는 전제와 달리, **fee_revenue/other_op_revenue/investment_revenue
  전용 canonical 이 Track A/B 어디에도 없는데도** 값 매칭만으로 검증 가능함이 실측 확인됐다
  (Phase 2 설계 §3-B 의사코드는 canonical 매칭이 아니라 값 매칭이므로 이 결과와 정합).
- securities `read_failed` 673/2731(24.6%) 는 대부분 2015 이전 구형 포맷(EUC-KR 등)으로
  추정 — 이 구간은 애초에 §8 미결에서 "대상 아님"으로 명시된 범위와 겹친다.
