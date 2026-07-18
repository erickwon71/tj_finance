# 전수 조사 — concept_map "개념 collapse" 판단 지점 감사 (2026-07-18)

> 발단: `cf.dividends_paid` 에서 `ifrs-full_DividendsPaid`(자본변동표/SCE 값, 범위 밖)와
> `…ClassifiedAsFinancingActivities`(현금흐름표 값)가 **한 canonical 로 collapse** → ε 규칙이
> 자본변동표 값을 잘못 채택. 사용자 지적: (1) SCE 는 현 scope 밖 (2) concept_map(=우리가 쓰는
> "ifrs library")에 오류 가능성. → concept_map 의 **복수 개념 → 단일 canonical** 지점을 전수 감사.

## 방법
`fin2/taxonomy/concept_map.py` 에서 **2개 이상 ACODE 가 한 canonical 로 매핑되는** 20종 추출 →
전 `fact_v2`(Track A = xbrl_acode, col0·비차원)에서 (canonical,rcept,basis) 그룹별로 **서로 다른
개념이 서로 다른 값**을 낸 보고서 수(값충돌)를 단일 패스로 측정.

## 측정 결과 (값충돌 많은 순)

| canonical | 복수개념 그룹 | **값충돌** | 접힌 개념 | 유형 |
|---|---:|---:|---|---|
| `bs.lease_liability` | 17,942 | **17,895** | Current + Noncurrent LeaseLiabilities | **C 합산** |
| `cf.borrowings_proceeds` | 7,346 | **6,925** | Short + Long term Proceeds | **C 합산** |
| `cf.borrowings_repaid` | 5,553 | **5,230** | Short + Long Repayments | **C 합산** |
| `bs.long_term_investment` | 4,197 | **4,128** | OtherNoncurrentFinancialAssets + FVOCI-noncurrent | **B 광의/부분** |
| `cf.dividends_paid` | 8,924 | **3,019** | **DividendsPaid(SCE)** + Financing + Operating | **A SCE누수** |
| `bs.trade_receivables` | 2,307 | **2,267** | TradeAndOtherCurrent + ShortTermTrade | **B 광의/협의** |
| `bs.trade_payables` | 2,026 | **2,014** | TradeAndOtherCurrent + ShortTermTrade | **B 광의/협의** |
| `cf.short_term_investment_net` | 2,056 | **1,963** | Proceeds(+) + Purchase(−) | **D 부호반대** |
| `cf.tax_paid` | 1,285 | **1,280** | IncomeTaxesPaidRefund(net) + PaymentsOfIncomeTaxes | **B/D** |
| `bs.short_term_investment` | 568 | **547** | CurrentFinancialAssets(rollup) + Other(부분) | **B 롤업/부분** |
| `cf.govt_grant` | 515 | **466** | Financing-grant + Investing-grant | **D 다른구간** |
| `bs.current_bonds` | 342 | **317** | CurrentPortionOfBonds + …ConvertibleBonds | **C 합산** |
| `is.interest_revenue` | 282 | **272** | RevenueFromInterest + EffectiveInterestMethod | **B 광의/특정** |
| `bs.long_term_debt` | 321 | **270** | Noncurrent + LongTermGross + Longterm | **B Gross/net** |
| `cf.acquisition_of_subsidiaries` | 185 | **143** | ObtainingControl + PurchaseOfInvestmentsInSubs | **B/D** |
| `is.operating_income` | 83 | 64 | dart_OperatingIncomeLoss + ProfitLossFromOperating | A′ 동의어(반올림) |
| `bs.right_of_use_asset` | 0 | 0 | RightofuseAssets/RightOfUseAssets | SAFE(대소문자) |
| `bs.short_term_debt` | 0 | 0 | Shortterm/Current/dart Borrowings | SAFE(rule_additive_debt 합산) |
| `cf.capex` | 0 | 0 | …ClassifiedAsInvesting + bare PPE | SAFE(충돌 0) |
| `cf.capex_intangible` | 0 | 0 | …ClassifiedAsInvesting + bare | SAFE(충돌 0) |

**총 값충돌 ≈ 46,000 보고서-그룹.** v1(max-abs)은 이걸 **소리 없이 큰 값으로** 채웠다(예:
lease_liability=max(유동,비유동)=대개 비유동 → 총리스부채 과소). strict 재구축은 보류(결측)로
드러냈다. = 재구축이 없앤 오염의 큰 축.

## 유형별 진단 + 권장 조치

### A. SCE(자본변동표) 등 범위 밖 개념 누수 — **매핑 제거**
- `cf.dividends_paid` ← `ifrs-full_DividendsPaid`: IFRS 정의상 "소유주 분배로 인식한 배당액"
  = **자본변동표 개념**(발생주의). 현금흐름표 값은 `…ClassifiedAsFinancingActivities/
  …OperatingActivities`. 코드도 이미 인지(`parser/xml/dart_xml_parser.py:377` 주석).
  → **`ifrs-full_DividendsPaid` 를 cf.dividends_paid 에서 제거**(SCE 범위 밖). ...Classified 2종만 유지.
  Track A 로만 배당 있는 비표준 태깅 보고서는 결측(결측>오염). 값충돌 3,019 해소.

### C. 서로 다른 부분 → 합쳐야 하는데 alternate 로 collapse — **합산 규칙**
`bs.short_term_debt` 가 값충돌 0 인 이유 = `rule_additive_debt` 가 부분(단기+유동성장기+사채)을
**합산**하기 때문. 같은 패턴을 다음에 적용(부분을 별도 sub-canonical 로 매핑 → 규칙이 합산):
- `bs.lease_liability` = 유동 + 비유동 리스부채 (**최대 충돌 17,895**)
- `cf.borrowings_proceeds` / `cf.borrowings_repaid` = 단기 + 장기
- `bs.current_bonds` = 사채유동분 + 전환사채유동분
- `cf.short_term_investment_net` = 처분(+) + 취득(−) → 부호 포함 **순액 합산**(canonical 명이 _net)

### B. 광의 vs 협의 / 롤업 vs 부분집합 — **granularity 확정(사용자 판단)**
같은 canonical 에 "넓은 개념"과 "좁은 개념"이 함께 매핑 → 무엇을 그 칼럼의 정의로 볼지 결정 필요:
- `bs.trade_receivables`: 매출채권및기타(광의) vs 순수 매출채권(협의) — 무엇이 우리 정의?
- `bs.trade_payables`: 동일
- `is.interest_revenue`: 총이자수익 vs 유효이자율법 이자수익 (DB손해보험 사례)
- `bs.short_term_investment`: CurrentFinancialAssets(총) vs Other(부분) — 총을 쓰면 부분 제거
- `bs.long_term_investment` / `bs.long_term_debt`: FVOCI 부분·Gross/net 혼재

### D. 성격이 다른 항목을 collapse — **분리 또는 재정의(사용자 판단)**
- `cf.short_term_investment_net`: 유입·유출 부호 반대 → C(순액합산)로 처리 가능
- `cf.govt_grant`: 재무활동 보조금 vs 투자활동 보조금 = 다른 CF 구간(합산? 분리?)
- `cf.tax_paid`: net 환급포함 vs 총지급액 (표준 CF 라인 = …ClassifiedAsOperating 우선 = B)
- `cf.acquisition_of_subsidiaries`: 지배력획득 현금 vs 종속기업투자취득 (다른 개념)

### SAFE (조치 불요)
`is.operating_income`(동의어·반올림, ε로 확정) · `bs.right_of_use_asset`(대소문자) ·
`bs.short_term_debt`·`cf.capex`·`cf.capex_intangible`(충돌 0 — 규칙/동의어로 이미 처리).

## 참고 — rules.py 파생 판단(2차, applied_rules 로 추적 가능·plan §2 원칙3 허용)
`rule_cash_with_deposits`(현금+예치금 합) · `rule_additive_capex`·`rule_additive_da`·
`rule_additive_debt`(부분 합산, abs 사용) · `rule_net_income_fill`·`rule_controlling_ni_fill`·
`rule_revenue_from_cogs_gp`·`rule_revenue_fallback`(보험/이자 가드) · `rule_rd_fallback` ·
`rule_derive_ebitda/fcf/net_debt`. 대부분 투명 파생이나 **abs()·or 0** 은 부호/결측 판단이 섞임
(plan §2-A Tier 2). concept_map(A~D) 정리 후 별도 검토.

## 결정 필요 (사용자)
1. **A**: `ifrs-full_DividendsPaid` 매핑 제거 확정? (SCE 범위 밖)
2. **C**: lease_liability·borrowings_proceeds/repaid·current_bonds·short_term_investment_net 를
   **합산 규칙**으로 전환? (rule_additive_debt 패턴)
3. **B**: trade_receivables/payables·interest_revenue·short_term_investment 등 **granularity 정의**.
4. **D**: govt_grant·tax_paid·acquisition_of_subsidiaries 처리 방침.
