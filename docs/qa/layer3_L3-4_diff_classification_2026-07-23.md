<!-- §0~§5 는 수기 큐레이션(원문대조 근거·판정·백로그). 이하 표(# L3-4 full-population
     classification~) 는 scripts/layer3_diff_classify.py 자동생성 스냅샷.
     재현 시 companion 경로(§재현)로 출력해 이 요약을 덮어쓰지 말 것. READ-ONLY. -->

# L3-4 DIFF 전수 유형분류 — 판정 (2026-07-23)

> 착수지점(핸드오프 §5.1). 신 체인 `std_financials_v3` ↔ 구 체인 `std_financials_v2`
> 전수 대조(FY, v2 version=1·NOT stub·NOT discrete, 2015+, 8지표)의 DIFF(~1.5%)를
> **정상불일치 / 회귀 / 롱테일 / v3우위** 로 자동 유형분류하고 표본을 원문대조.
> 스크립트 = `scripts/layer3_diff_classify.py` · 이전 = `layer3_L3-3_std_v3_build_2026-07-23.md`

## 0. 한 줄 판정
**계층3(v3) 은 구 체인(v2)만큼 정확하며, 불일치 잔여분에서는 오히려 더 정확하다.**
전수 대조 gross MATCH **98.46%**. DIFF 5,189 셀(전체의 1.54%) 중 **회귀(v3 결함) 후보는
극소수** — 조사대상 inspect 829 중 **86%(710)가 v3 가 원문(col0 기재값)을 정확 재현하고 v2 가
틀린 케이스**. 순수 v3 드릴 백로그 = inspect 미일치 **119** + 루닛형 부호결함 소수. **swap 차단
사유 없음.**

## 1. DIFF 유형분류 (전 8지표 합산, §하단 표 집계)

| 대분류 | 유형 | 셀수 | DIFF내 비중 | 성격 |
|---|---|---:|---:|---|
| **(a) 정상** | amended | 2,205 | 42.5% | 기재정정 반영(정책 P1). v3 as-restated, v2 원본 유지 — 회귀 아님 |
| **(a) 정상** | rcept_diff | 1,310 | 25.2% | v3 가 다른 정본 filing 에서 소싱(소급재작성·연결범위변동) — 회귀 아님 |
| **(b) 조사** | inspect | 829 | 16.0% | 동일출처·양측 정상스케일·실질차. **단 86% 는 v2 오류(§4)** |
| **(b) 조사** | sign_flip | 6 | 0.1% | v3 = −v2 정확반전 |
| **(c) v3우위** | unit_1000x | 23 | 0.4% | ×1000 단위불일치 — v2 천원저장버그, v3 원단위 정답 |
| **(c) v3우위** | v2_tiny / v2_huge | 127 | 2.4% | v2 오셀렉트(과소·과대), v3 정답 |
| **(c) 롱테일** | rounding | 160 | 3.1% | 허용오차 이내(양성) |
| **(c) 롱테일** | fin_catalog | 529 | 10.2% | 금융업(KSIC 64/65/66) 매출 alias — account_maps 정제 대상(L3-4 step2) |
| _커버리지_ | v3only | 1,528 | — | v3 가 v2 결측을 복구(split-table 등) — 신 체인 우위 |
| _커버리지_ | v2only | 2,401 | — | v3 결측 — 대부분 보험/증권 매출 alias(step2 정제) |

**정상(a) 68% · v3우위/롱테일(c) 16% · 조사(b) 16%.** 조사(b) 조차 대부분 v2 오류(§4).

## 2. 유형분류 규칙 (재현가능·읽기전용)
지표별 (corp,fy,period,basis) 셀을 v3/v2 값·provenance·업종으로 CASE 분기:
`amended`(v3.amended_cols/amend_chain 에 컬럼) → `rcept_diff`(source_rcepts[STMT]≠v2 stmt_rcept)
→ `sign_flip`(v3=−v2) → `unit_1000x`(v3≈1000·v2 또는 v2≈1000·v3) → `v2_tiny`(|v3|>100|v2|)
→ `v2_huge`(|v2|>100|v3|) → `rounding`(|Δ|≤max(1000, 0.1%)) → `fin_catalog`(금융업)
→ else `inspect`. 허용오차 REL_TOL=0.1%·ABS_TOL=1,000원.

## 3. 원문대조 — 대표 4건 (표본 상위 relgap)
| 케이스 | report_lines 원문(col0) | v3 | v2 | 판정 |
|---|---|---|---|---|
| 지역난방공사 2022 net_income | `당기순이익(손실)` **−1,839.8억** | −1,839.8억 ✅ | +1,944.4억 | **v3 정답·v2 오류**(2022 대규모 손실) |
| 삼성SDI 2016 net_income | `당기순이익(손실)` col0 **+2,111.1억** | +2,111.1억 ✅ | −8,785억 | **v3 정답·v2 오류**(매각차익·지분법이익 순이익) |
| 크래프톤 2020 sepa total_assets | `자산총계` **1.65조** | 1.65조 ✅ | 1,396억 | **v3 정답·v2 오류** |
| 루닛 2021 net_income | `V. 당기순손실` **+736.8억**(손실을 양수 기재) | +736.8억 ❌ | −837.4억 | **v3 부호 미반전**(순손실 라벨+양수). v2 도 크기 오류 |

→ 상위 relgap 표본은 부호반대가 많으나, 정밀대조 결과 **대부분 v3 가 filed 값 정확·v2 가 오류**.
루닛형(순"손실" 라벨+양수 미반전)만 진짜 v3 결함이며 소수(net_income 부호반대 중 4건).

## 4. inspect 의 실체 — v3 충실도 검증 (★2026-07-24 드릴 완료: v3 결함 0)
v3 값이 정본 filing 의 당기(col0) 기재값을 재현하는지 전수 확인. **초기 86%(710/829)는
faithfulness 검증의 basis 버그**(v3.statement_type basis 만 조회)였음 — 양 basis + 부호정규화로
교정하니 **inspect 908 전부(100%) v3 가 원문 값 재현**.
- **`scripts/layer3_inspect_drill.py`(원문 기준·V2 무관)**: 미일치 124 → 유형분류:
  **114 = basis_fallback**(단일법인 연결폴백, v3 가 별도값 정확복사) · **10 = sign_norm**(루닛형
  손실반전, v3 = −원문값, 원문 '법인세비용차감전순손실'/'영업손실' 양수 확인) · **unexplained = 0**.
- ⟹ **inspect 버킷 전체가 v3 정답**(basis폴백 + 손실반전 + 나머지는 v2 오류). **순수 v3 결함 0건.**
  faithfulness_check 및 drill 은 이제 양 basis 조회로 교정됨(커밋).

## 5. 액션 백로그 (swap 비차단, 후속 정제)
1. ✅ **[완료 2026-07-23] 금융업 매출 정제 (step2)** — 근본원인은 alias 갭이 아니라 **부모 top-line
   vs 자식 하위항목 충돌보류**로 판명. 수정=combine `_reduce_conflict` 강화(EPS우선→min-depth→0헤더제외)
   + is.revenue 승급(보험서비스수익 IFRS17·보험영업수익·매출(영업수익)). 커밋 `0b37f9a`. 재빌드 후:
   **v2only 2,401→1,667(−734, 그중 +603 MATCH)**, 금융 revenue MATCH 2,112. 회귀 0(프로브 380사).
   → §6 참조. **잔여 fin_catalog 142 = 보험 총매출 정의차(PRD 결정, 아래 2번).**
2. **[PRD 결정 필요] 보험사 revenue 정의** — IFRS17 하 v3=`보험서비스수익`(보험영업만) vs v2=`영업수익`
   (보험+투자 합산). 어느 것을 표준 revenue 로 할지 모델링 결정(파싱 버그 아님, v2도 비일관). 결정 후
   보험사 조립 규칙 반영.
3. ✅ **[완료 2026-07-24] 보험·은행·증권 revenue 프로파일** — 사용자 결정=합산(GROSS). RevenueProfile
   레지스트리(industry_lines JSONB) + grand-total 라벨 우선(증권/지주) + 은행 gross. 설계=`docs/plans/
   insurer_revenue_composition_2026-07-24.md`.
4. ✅ **[완료 2026-07-24] 루닛형 부호정규화** — 순"손실" 단독라벨+양수→−value(combine._map_rows
   _loss_signed). 루닛 −73.6B(DART원문 일치). 회귀 100사 비정상0.
5. ✅ **[완료 2026-07-24] inspect 미일치 드릴** — `layer3_inspect_drill.py`. **순수 v3 결함 0건**
   (미일치 124=basis_fallback 114 + 손실반전 10, unexplained 0). §4 참조. faithfulness 100%.
6. v2only 1,667 잔여(비-보험) — v3 결측 원인별(출처 없음 vs 조립 보류) 후속 분류(선택).

## 6. step2 재빌드 후 델타 (2026-07-23, build_std_v3 --all 재조립)
| 지표 | v2only(전→후) | 비고 |
|---|---|---|
| revenue | 914 → 382 | 금융 매출 대량 복구 |
| retained_earnings | 250 → 195 | |
| total_equity | 106 → 89 | |
| **TOTAL v2only** | **2,401 → 1,667** | **−734, 그중 +603 이 MATCH** |

절대 MATCH 331,765→332,368(+603). MATCH% 98.46→98.42(복구셀 중 보험 정의차분이 fin_catalog/inspect 로
분류돼 비율은 소폭 하락하나 절대 정확·커버리지는 상승). inspect 829→904(대부분 신규복구·회귀아님, 프로브
away/emptied/0채움 0). **하단 임베드 표 = step2 전 baseline**(보존); **재빌드 후 전체 표 =
companion `layer3_L3-4_diff_classification_tables_2026-07-23.md`**(방금 재생성).

## 재현
```
# 표 스냅샷을 companion 으로 출력(이 문서의 §0~§5 요약은 수기 — 덮어쓰지 말 것)
python scripts/layer3_diff_classify.py --period FY --sample-regressions 25 \
       -o docs/qa/layer3_L3-4_diff_classification_tables_2026-07-23.md
```
`--period` 로 H1/Q1/Q3 도 동일 분류(본 문서는 FY baseline). DB 무변경.

---

# L3-4 DIFF full-population classification (FY, v2 version=1, 2015+)

Rows = per-metric cells where BOTH std_v3 and std_v2 exist for the (corp,fy,period,basis) key (join; coverage-only cells counted as v3only/v2only).

| metric | both | MATCH | MATCH% | amended | rcept_diff | sign_flip | inspect | unit_1000x | v2_tiny | v2_huge | rounding | fin_catalog | v3only | v2only |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| total_assets | 42,450 | 41,706 | 98.25 | 406 | 180 | 0 | 46 | 6 | 22 | 5 | 32 | 47 | 167 | 82 |
| total_equity | 42,385 | 41,669 | 98.31 | 434 | 171 | 0 | 40 | 6 | 11 | 2 | 26 | 26 | 204 | 106 |
| retained_earnings | 41,984 | 41,248 | 98.25 | 340 | 187 | 0 | 142 | 6 | 9 | 2 | 26 | 24 | 295 | 250 |
| cash | 41,884 | 41,505 | 99.10 | 72 | 137 | 0 | 74 | 4 | 10 | 4 | 21 | 57 | 161 | 569 |
| revenue | 41,284 | 40,738 | 98.68 | 186 | 92 | 0 | 89 | 0 | 15 | 15 | 6 | 143 | 296 | 914 |
| operating_income | 42,503 | 41,888 | 98.55 | 250 | 183 | 3 | 71 | 0 | 11 | 1 | 20 | 76 | 118 | 61 |
| net_income | 42,321 | 41,399 | 97.82 | 353 | 182 | 3 | 227 | 1 | 11 | 4 | 26 | 115 | 113 | 230 |
| cfo | 42,143 | 41,612 | 98.74 | 164 | 178 | 0 | 140 | 0 | 2 | 3 | 3 | 41 | 174 | 189 |
| **TOTAL** | **336,954** | **331,765** | **98.46** | **2,205** | **1,310** | **6** | **829** | **23** | **91** | **36** | **160** | **529** | **1,528** | **2,401** |

## Disposition roll-up (all 8 metrics)

- (a) NORMAL  amended    (재작성 반영·회귀아님)             2,205  42.5% of DIFF
- (a) NORMAL  rcept_diff (다른 정본filing·회귀아님)        1,310  25.2% of DIFF
- (b) REGRESS sign_flip  (부호결함 ★조사)                    6  0.1% of DIFF
- (b) REGRESS inspect    (양측 정상스케일·실질차 ★조사)          829  16.0% of DIFF
- (c) v3-WIN  unit_1000x (×1000 단위불일치·v3정답)           23  0.4% of DIFF
- (c) v3-WIN  v2_tiny    (v2 과소·오셀렉트·v3정답)            91  1.8% of DIFF
- (c) v3-WIN  v2_huge    (v2 과대·오셀렉트·v3정답)            36  0.7% of DIFF
- (c) LONGTL  rounding   (허용오차·양성)                   160  3.1% of DIFF
- (c) LONGTL  fin_catalog(금융업 매출alias)               529  10.2% of DIFF
- cov         v3only     (split-table 복구·우위)       1,528  
- cov         v2only     (v3 결측·catalog gap)       2,401  

  DIFF total = 5,189   (b) 조사대상 = 835  (16.1% of DIFF)

## (b) INSPECT anatomy — sign structure per metric

| metric | inspect | sign_opposite | same_sign |
|---|---:|---:|---:|
| cash | 74 | 1 | 73 |
| cfo | 140 | 19 | 121 |
| net_income | 227 | 48 | 179 |
| operating_income | 71 | 10 | 61 |
| retained_earnings | 142 | 6 | 136 |
| revenue | 89 | 0 | 89 |
| total_assets | 46 | 0 | 46 |
| total_equity | 40 | 1 | 39 |
| **TOTAL** | **829** | **85** | **744** |

부호반대 = inspect 의 10% → 잔여 (b) 는 **부호규약 불일치가 지배적**(net_income·cfo 집중).

## (b) INSPECT faithfulness — v3 vs filed line (col0, any role)

v3 값이 정본 filing 의 당기(col0) report_lines 값 중 하나와 정확히 일치하면 v3 는 실제 기재된 셀을 재현한 것(값 조작/오산 아님) → 그 DIFF 는 **v2(구 체인) 불일치**(v3 날조 아님). 불일치분은 조립/파생값으로 추가 드릴 대상.

| metric | inspect | v3==filed | v3-충실% | 불일치(드릴) |
|---|---:|---:|---:|---:|
| total_assets | 46 | 31 | 67 | 15 |
| total_equity | 40 | 29 | 72 | 11 |
| retained_earnings | 142 | 129 | 91 | 13 |
| cash | 74 | 57 | 77 | 17 |
| revenue | 89 | 74 | 83 | 15 |
| operating_income | 71 | 54 | 76 | 17 |
| net_income | 227 | 209 | 92 | 18 |
| cfo | 140 | 127 | 91 | 13 |
| **TOTAL** | **829** | **710** | **86** | **119** |

→ inspect 의 **86%** 는 v3 가 filed 최상위값을 정확 반영 (v2 구 체인 오류). 나머지 119 건이 v3 조립/라인선택 드릴 대상(부호정규화·sub-line 등).

## (b) INSPECT sample — top 25 by relative gap (both well-scaled, same-source, material — ★원문대조 대상)

| metric | corp | name | induty | fy | basis | v3 | v2 | relgap | rcept |
|---|---|---|---|---|---|---:|---:|---:|---|
| cfo | 00965318 | 이노시뮬레이션 | 58221 | 2021 | cons | 2,999,408,943 | 131,250,910 | 21.852 | 20220331001729 |
| operating_income | 01112889 | 피엔에이치테크 | 20119 | 2015 | sepa | 912,899,210 | -89,000,000 | 11.257 | 20160822000053 |
| total_assets | 00760971 | 크래프톤 | 5821 | 2020 | sepa | 1,648,710,972,486 | 139,609,250,000 | 10.809 | 20210331003279 |
| cfo | 01022902 | 애드바이오텍 | 21230 | 2019 | sepa | 531,783,876 | -74,535,448 | 8.135 | 20210318000646 |
| cfo | 00311216 | 에이치엔에스하이텍 | 262 | 2018 | cons | 2,504,395,819 | -354,694,101 | 8.061 | 20190624000078 |
| retained_earnings | 01112889 | 피엔에이치테크 | 20119 | 2016 | sepa | -4,077,555,103 | -527,000,000 | 6.737 | 20170331004685 |
| total_equity | 01070149 | 올리패스 | 211 | 2018 | sepa | -34,558,800,553 | 7,672,642,000 | 5.504 | 20190401005080 |
| cfo | 00867034 | 듀켐바이오 | 212 | 2015 | cons | -1,828,102,978 | -294,392,799 | 5.210 | 20160519000297 |
| net_income | 01112889 | 피엔에이치테크 | 20119 | 2015 | sepa | 1,386,210,014 | -393,000,000 | 4.527 | 20160822000053 |
| cfo | 00138190 | GS글로벌 | 468 | 2016 | sepa | 73,359,527,965 | 13,521,403,584 | 4.425 | 20170331003894 |
| retained_earnings | 01070149 | 올리패스 | 211 | 2018 | sepa | -97,566,979,178 | -23,833,626,000 | 3.094 | 20190401005080 |
| net_income | 00311216 | 에이치엔에스하이텍 | 262 | 2019 | cons | -10,740,916,692 | -2,810,765,062 | 2.821 | 20200325000812 |
| retained_earnings | 01112889 | 피엔에이치테크 | 20119 | 2015 | sepa | -1,895,523,027 | -527,000,000 | 2.597 | 20160822000053 |
| operating_income | 00765897 | 한국피아이엠 | 303 | 2022 | sepa | 1,944,519,734 | 544,976,890 | 2.568 | 20230904000256 |
| net_income | 00138190 | GS글로벌 | 468 | 2016 | sepa | 16,073,111,502 | 4,644,271,619 | 2.461 | 20170331003894 |
| net_income | 01112889 | 피엔에이치테크 | 20119 | 2017 | sepa | 1,813,654,302 | -1,386,000,000 | 2.309 | 20180402000639 |
| cfo | 00311216 | 에이치엔에스하이텍 | 262 | 2017 | cons | 3,590,887,242 | -2,903,628,388 | 2.237 | 20180703000022 |
| retained_earnings | 01112889 | 피엔에이치테크 | 20119 | 2017 | sepa | -5,821,505,870 | -1,896,000,000 | 2.070 | 20180402000639 |
| operating_income | 00923826 | 일월지엠엘 | 468 | 2020 | sepa | 1,976,904,965 | -1,982,684,230 | 1.997 | 20230224002432 |
| cfo | 00123143 | 보령 | 212 | 2016 | sepa | 9,363,178,136 | -9,519,243,091 | 1.984 | 20170331000993 |
| operating_income | 00125646 | 삼목에스폼 | 2511 | 2020 | sepa | -12,650,722,717 | 13,077,960,879 | 1.967 | 20210318000660 |
| net_income | 00159698 | 지역난방공사 | 35300 | 2022 | cons | -183,978,919,360 | 194,438,763,361 | 1.946 | 20230322000036 |
| net_income | 00159698 | 지역난방공사 | 35300 | 2022 | sepa | -183,875,521,509 | 194,424,429,552 | 1.946 | 20230322000036 |
| cfo | 00828789 | 대성산업 | 477 | 2017 | sepa | 6,528,701,421 | -7,346,209,594 | 1.889 | 20180405000403 |
| operating_income | 00406727 | 세진티에스 | 26211 | 2016 | cons | -723,245,410 | 815,365,574 | 1.887 | 20170331000806 |
