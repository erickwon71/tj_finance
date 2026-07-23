# L3-4 DIFF full-population classification (FY, v2 version=1, 2015+)

Rows = per-metric cells where BOTH std_v3 and std_v2 exist for the (corp,fy,period,basis) key (join; coverage-only cells counted as v3only/v2only).

| metric | both | MATCH | MATCH% | amended | rcept_diff | sign_flip | inspect | unit_1000x | v2_tiny | v2_huge | rounding | fin_catalog | v3only | v2only |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| total_assets | 42,459 | 41,709 | 98.23 | 408 | 180 | 0 | 48 | 6 | 22 | 5 | 32 | 49 | 167 | 73 |
| total_equity | 42,402 | 41,674 | 98.28 | 439 | 171 | 0 | 47 | 6 | 11 | 2 | 26 | 26 | 204 | 89 |
| retained_earnings | 42,039 | 41,296 | 98.23 | 343 | 187 | 0 | 145 | 6 | 9 | 2 | 26 | 25 | 295 | 195 |
| cash | 41,895 | 41,507 | 99.07 | 72 | 140 | 0 | 79 | 4 | 10 | 5 | 21 | 57 | 161 | 558 |
| revenue | 41,816 | 41,178 | 98.47 | 200 | 102 | 0 | 100 | 0 | 19 | 8 | 21 | 188 | 311 | 382 |
| operating_income | 42,503 | 41,888 | 98.55 | 250 | 183 | 3 | 71 | 0 | 11 | 1 | 20 | 76 | 118 | 61 |
| net_income | 42,336 | 41,410 | 97.81 | 353 | 182 | 3 | 231 | 1 | 11 | 4 | 26 | 115 | 113 | 215 |
| cfo | 42,238 | 41,659 | 98.63 | 165 | 181 | 0 | 183 | 0 | 2 | 3 | 3 | 42 | 174 | 94 |
| **TOTAL** | **337,688** | **332,321** | **98.41** | **2,230** | **1,326** | **6** | **904** | **23** | **95** | **30** | **175** | **578** | **1,543** | **1,667** |

## Disposition roll-up (all 8 metrics)

- (a) NORMAL  amended    (재작성 반영·회귀아님)             2,230  41.6% of DIFF
- (a) NORMAL  rcept_diff (다른 정본filing·회귀아님)        1,326  24.7% of DIFF
- (b) REGRESS sign_flip  (부호결함 ★조사)                    6  0.1% of DIFF
- (b) REGRESS inspect    (양측 정상스케일·실질차 ★조사)          904  16.8% of DIFF
- (c) v3-WIN  unit_1000x (×1000 단위불일치·v3정답)           23  0.4% of DIFF
- (c) v3-WIN  v2_tiny    (v2 과소·오셀렉트·v3정답)            95  1.8% of DIFF
- (c) v3-WIN  v2_huge    (v2 과대·오셀렉트·v3정답)            30  0.6% of DIFF
- (c) LONGTL  rounding   (허용오차·양성)                   175  3.3% of DIFF
- (c) LONGTL  fin_catalog(금융업 매출alias)               578  10.8% of DIFF
- cov         v3only     (split-table 복구·우위)       1,543  
- cov         v2only     (v3 결측·catalog gap)       1,667  

  DIFF total = 5,367   (b) 조사대상 = 910  (17.0% of DIFF)

## (b) INSPECT anatomy — sign structure per metric

| metric | inspect | sign_opposite | same_sign |
|---|---:|---:|---:|
| cash | 79 | 1 | 78 |
| cfo | 183 | 21 | 162 |
| net_income | 231 | 49 | 182 |
| operating_income | 71 | 10 | 61 |
| retained_earnings | 145 | 6 | 139 |
| revenue | 100 | 0 | 100 |
| total_assets | 48 | 0 | 48 |
| total_equity | 47 | 2 | 45 |
| **TOTAL** | **904** | **89** | **815** |

부호반대 = inspect 의 10% → 잔여 (b) 는 **부호규약 불일치가 지배적**(net_income·cfo 집중).

## (b) INSPECT faithfulness — v3 vs filed line (col0, any role)

v3 값이 정본 filing 의 당기(col0) report_lines 값 중 하나와 정확히 일치하면 v3 는 실제 기재된 셀을 재현한 것(값 조작/오산 아님) → 그 DIFF 는 **v2(구 체인) 불일치**(v3 날조 아님). 불일치분은 조립/파생값으로 추가 드릴 대상.

| metric | inspect | v3==filed | v3-충실% | 불일치(드릴) |
|---|---:|---:|---:|---:|
| total_assets | 48 | 33 | 69 | 15 |
| total_equity | 47 | 36 | 77 | 11 |
| retained_earnings | 145 | 132 | 91 | 13 |
| cash | 79 | 62 | 78 | 17 |
| revenue | 100 | 85 | 85 | 15 |
| operating_income | 71 | 54 | 76 | 17 |
| net_income | 231 | 213 | 92 | 18 |
| cfo | 183 | 170 | 93 | 13 |
| **TOTAL** | **904** | **785** | **87** | **119** |

→ inspect 의 **87%** 는 v3 가 filed 최상위값을 정확 반영 (v2 구 체인 오류). 나머지 119 건이 v3 조립/라인선택 드릴 대상(부호정규화·sub-line 등).

## (b) INSPECT sample — top 8 by relative gap (both well-scaled, same-source, material — ★원문대조 대상)

| metric | corp | name | induty | fy | basis | v3 | v2 | relgap | rcept |
|---|---|---|---|---|---|---:|---:|---:|---|
| cash | 01170865 | 네오셈 | 292 | 2018 | sepa | 16,304,354,337 | 256,172,282 | 62.646 | 20190401003994 |
| cfo | 00965318 | 이노시뮬레이션 | 58221 | 2021 | cons | 2,999,408,943 | 131,250,910 | 21.852 | 20220331001729 |
| operating_income | 01112889 | 피엔에이치테크 | 20119 | 2015 | sepa | 912,899,210 | -89,000,000 | 11.257 | 20160822000053 |
| total_assets | 00760971 | 크래프톤 | 5821 | 2020 | sepa | 1,648,710,972,486 | 139,609,250,000 | 10.809 | 20210331003279 |
| cfo | 01022902 | 애드바이오텍 | 21230 | 2019 | sepa | 531,783,876 | -74,535,448 | 8.135 | 20210318000646 |
| cfo | 00311216 | 에이치엔에스하이텍 | 262 | 2018 | cons | 2,504,395,819 | -354,694,101 | 8.061 | 20190624000078 |
| retained_earnings | 01112889 | 피엔에이치테크 | 20119 | 2016 | sepa | -4,077,555,103 | -527,000,000 | 6.737 | 20170331004685 |
| cash | 01090471 | SFA넥셀 | 292 | 2016 | sepa | 11,737,313,491 | 1,520,885,317 | 6.717 | 20170331003810 |
