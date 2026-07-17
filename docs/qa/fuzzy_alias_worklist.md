# 퍼지 alias 승격 작업목록 (자동 생성)

- 표본 보고서(본문 검출): **299**
- 퍼지를 끄면 std_v2 소비 canonical 을 잃는 보고서: **108 (36.1%)**

## 1. 퍼지가 유일 출처인 canonical (승격 우선순위)

| canonical | 영향 보고서 |
|---|---|
| `cf.investing` | 19 |
| `is.controlling_ni` | 18 |
| `bs.short_term_debt` | 18 |
| `is.net_income` | 12 |
| `is.noncontrolling_ni` | 11 |
| `bs.long_term_debt` | 9 |
| `is.revenue` | 8 |
| `is.cogs` | 8 |
| `bs.trade_receivables` | 6 |
| `cf.amortization` | 6 |
| `bs.controlling_equity` | 6 |
| `cf.rou_depreciation` | 5 |
| `cf.depreciation` | 5 |
| `cf.dividends_paid` | 5 |
| `is.rd_expense` | 4 |
| `is.tax_expense` | 4 |
| `is.depreciation` | 3 |
| `bs.trade_payables` | 3 |
| `is.rou_depreciation` | 2 |
| `is.amortization` | 2 |
| `bs.inventory` | 2 |
| `cf.capex` | 2 |
| `cf.capex_intangible` | 2 |
| `cf.financing` | 2 |
| `is.finance_cost` | 2 |
| `bs.intangibles` | 1 |
| `is.sga` | 1 |
| `cf.operating` | 1 |

## 2. 라벨 → 후보 canonical (판정 대상)

`판정` 열을 채울 것: **A**=alias 승격(정당한 표기변형) / **B**=무매핑 확정(과잉매핑) / **?**=원문 확인 필요

| 판정 | 원문 라벨(정규화) | → 후보 canonical | 붙은 alias | 유사도 | 보고서 | fact |
|---|---|---|---|---|---|---|
|  | `무형자산의처분` | `cf.ppe_proceeds` | `유형자산의처분` | 0.905 | 190 | 335 |
|  | `당기순이익(손실)` | `cf.net_income_cf` | `당기순이익` | 0.95 | 148 | 259 |
|  | `리스부채의상환` | `cf.lease_repaid` | `리스부채상환` | 0.971 | 124 | 227 |
|  | `투자부동산의취득` | `cf.investment_property_proceeds` | `투자부동산의처분` | 0.9 | 126 | 203 |
|  | `당기손익-공정가치측정금융자산` | `bs.short_term_investment` | `당기손익-공정가치금융자산` | 0.973 | 91 | 193 |
|  | `비유동리스부채` | `bs.lease_liability` | `유동리스부채` | 0.977 | 109 | 184 |
|  | `법인세환급(납부)` | `cf.tax_paid` | `법인세납부` | 0.896 | 102 | 174 |
|  | `당기순이익조정을위한가감` | `cf.net_income_cf` | `당기순이익` | 0.938 | 94 | 165 |
|  | `단기금융상품의취득` | `cf.short_term_investment_net` | `단기금융상품의증감` | 0.911 | 101 | 163 |
|  | `기타비유동금융부채` | `bs.other_current_payables` | `기타유동금융부채` | 0.97 | 96 | 159 |
|  | `기타포괄손익-공정가치측정금융자산평가손익` | `is.oci` | `기타포괄손익` | 0.926 | 81 | 153 |
|  | `기타포괄손익-공정가치측정금융자산` | `bs.short_term_investment` | `기타포괄손익-공정가치금융자산` | 0.976 | 81 | 153 |
|  | `단기금융상품의처분` | `cf.short_term_investment_net` | `단기금융상품의증감` | 0.911 | 88 | 140 |
|  | `당기손익으로재분류되지않는항목(세후기타포괄손익)` | `is.oci` | `기타포괄손익` | 0.922 | 84 | 139 |
|  | `환율변동효과반영전현금및현금성자산의순증가(감소)` | `cf.net_change_in_cash` | `현금및현금성자산의순증가(감소)` | 0.958 | 63 | 106 |
|  | `기타자산` | `bs.other_receivables` | `기타금융자산` | 0.911 | 43 | 106 |
|  | `당기손익으로재분류될수있는항목(세후기타포괄손익)` | `is.oci` | `기타포괄손익` | 0.922 | 79 | 105 |
|  | `유동충당부채` | `bs.other_current_payables` | `충당부채` | 0.96 | 62 | 104 |
|  | `배당금수취(영업)` | `cf.dividends_received` | `배당금수취` | 0.95 | 63 | 100 |
|  | `기타부채` | `bs.other_current_payables` | `기타유동부채` | 0.911 | 42 | 98 |

★ = std_v2 가 실제로 읽는 canonical (승격 효과가 지표로 나타남)