# L3-1 조합엔진 프로토타입 — 결과 (2026-07-22)

> 계획 = `docs/plans/layer3_rebuild_plan_2026-07-22.md`(L3-1) · 선행 = `layer3_option_a_probe_2026-07-22.md`
> 코드 = `fin2/layer3/combine.py` · 드라이버 = `scripts/layer3_combine_probe.py`·`layer3_combine_ablation.py`
> **읽기전용. DB 무변경.**

## 0. 한 줄
하이브리드 조합엔진(라벨카탈로그 + 이식한 `_resolve`/`_reduce_conflict`)을 계층2 report_lines 에
걸어 6지표를 조립. **엔진 자체는 건전**(같은 filing 주면 std_v2 ~90% 재현·CONFLICT 0). 잔여
CONFLICT 는 **filing 버전 다중성**(정본 미선택), MISSING 은 출처매칭, DIFF 는 오히려 개선.

## 1. 무엇을 만들었나
- `fin2/layer3/combine.py` — 신 체인 조합엔진(프로토타입). fact_v2 아닌 **report_lines** 를 읽음.
  - 구 체인 `build._resolve`/`_reduce_conflict` 이식: 단일→확정 / 다중→최엄격 stage / 자동해소 /
    그래도 갈리면 **보류**(추측 없음, 결측>오염). acode→**label_raw** 로 신호 적응(비유동·광의 정규식).
  - node_role·section_path·table_seq 를 후보에 실어둠(잔여충돌 분석·2차 규칙 근거용).
  - 스코프 = DIRECT_MAP(6지표 전부 직접매핑). 합산/파생 규칙은 후속.

## 2. 측정 (n=400, seed=7, FY, 2015+)

**A. plain 프로브(해소 없음) → combine(해소 있음):** CONFLICT 대폭 감소.

| 지표 | plain CONFL | combine CONFL | plain MATCH | combine MATCH | combine DIFF |
|---|---:|---:|---:|---:|---:|
| revenue | 18 | 6 | 339 | 350 | 1 |
| net_income | 16 | 10 | 344 | 349 | 2 |
| retained_earnings | 33 | 11 | 325 | 345 | 2 |
| total_assets | 10 | 9 | 352 | 352 | 1 |

**B. ablation(std 의 bs/is_rcept 를 그대로 먹임 = 같은 filing):** CONFLICT → 0.

| 지표 | CONFL | MATCH | DIFF | MISSING | match% |
|---|---:|---:|---:|---:|---:|
| revenue | 2 | 354 | 1 | 35 | 90.3 |
| operating_income | 0 | 359 | 3 | 37 | 90.0 |
| net_income | 0 | 360 | 1 | 37 | 90.5 |
| total_assets | 0 | 361 | 1 | 37 | 90.5 |
| total_equity | 0 | 361 | 1 | 37 | 90.5 |
| retained_earnings | 0 | 356 | 2 | 36 | 90.4 |

## 3. 잔여의 정체 (덤프 실측)

### CONFLICT = filing 버전 다중성 (정본 미선택) — ★핵심
combine 이 한 (corp,fy,period,basis) 의 **모든 rcept** 를 pool 해서 생김. 실측:
- `00152862 2021`: 원본(3월) 455B vs 정정(8월) 397B → std=397B(정정)
- `00106641 2015`: 원본(2016) 16.94조 vs **2021년 재작성** 16.13조 → std=16.94조(원본)
- `00530121 2017`: filing 3개 → 값 3개

→ 4계층 계획의 **계층2 4패스="기간당 원문 1개 선택(정본)"** 이 아직 안 돼서 나는 충돌.
   ablation 에서 같은 filing 주면 **전량 소멸**(§2B). **라벨/해소 문제 아님.**

### MISSING(~9%) = 출처매칭
그 (corp,fy,period,basis) 키에 report_lines 행 부재. std 가 다른 리포트/열/basis 에서 채운 것
(옵션A 드릴에서 이미 확인). → **L3-2 출처우선순위**.

### DIFF(1~3) = 개선 (회귀 아님)
신 엔진이 **exact·role=P 의 총계 '이익잉여금(결손금)'(자본 레벨)** 채택, 구 std_v2 는 **fuzzy·
role=S 의 하위항목 '미처분이익잉여금'** 채택. 총계가 맞음 → **신 엔진이 구 체인보다 정확.**
(00346610 2018·00409140 2017 실측.)

## 4. 판정
- ✅ 하이브리드 조합엔진 건전성 확인. 같은 filing 조건에서 std_v2 재현·CONFLICT 0.
- ✅ node_role 규칙을 **아직 안 넣고도** 충돌의 대부분이 filing 다중성으로 설명됨 → node_role 은
     정본 선택 후 잔여(진짜 소계 이중계상)에만 필요할 가능성. 선(先) 정본, 후(後) node_role.
- ⚠ DIFF 는 소수이나 개선 방향. 최종 전수 parity 때 사람 표본대조 1회 권장(L3-4).

## 5. 다음 (★결정 필요 — 아키텍처 분기)
잔여 CONFLICT 의 원인 = **정본(filing) 선택** 미실행. 이걸 어디서 하나:
- **(A) 계층2 4패스**로 — 원래 4계층 계획대로 report_lines 에 정본 플래그(기간당 rcept 1개).
  이후 계층3 는 정본만 읽음. 계획 정합적.
- **(B) 계층3 선택 스텝**으로 — combine 진입 전 rcept 1개 선택(reconcile 로직 계층3 편입).

어느 쪽이든 **정본 선택 규칙**(원본 vs 정정 vs 재작성 중 무엇을 정본으로)이 필요. std_v2 실측:
정정은 정정을 채택(00152862), 후년 재작성은 원본 유지(00106641) → "해당 회계연도의 자체
보고서 중 최종 정정본, 단 후속 연도의 소급재작성은 별개" 규약으로 보임. L3-2(출처매칭)와 함께 설계.
