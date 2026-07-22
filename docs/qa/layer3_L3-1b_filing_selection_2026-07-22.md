# L3-1b 정본(filing) 선택 — 결과 (2026-07-22)

> 계획 = `docs/plans/layer3_rebuild_plan_2026-07-22.md`(L3-1b) · 선행 = `layer3_L3-1_combine_prototype_2026-07-22.md`
> 코드 = `fin2/layer3/combine.py`(`select_canonical_rcept`) · 드라이버 = `scripts/layer3_combine_probe.py`·`layer3_diff_characterize.py`
> 결정: **계층3 선택 스텝**(사용자 2026-07-22) — combine 진입 전 rcept 1개 선택. **읽기전용·DB 무변경.**

## 0. 한 줄
L3-1 이 지목한 잔여 CONFLICT 원인(=filing 버전 다중성)을 **정본 선택**으로 해소. 다운로드
계층의 `is_final`(최종 [기재정정])을 정본 선택자로 채택 → **CONFLICT pooled ~18 → ~1 로 붕괴**.
잔여 DIFF ~0.7%(대부분 combine 이 구 체인보다 정확 or filing 정책 엣지).

## 1. 선택 규칙 — statement 단위 폴백 (`select_canonical_rcepts`)
filing 체인을 `is_final DESC, filed_at DESC, rcept_no DESC` 로 정렬하고, **BS/IS/CF 각각을
그 statement 의 report_lines 가 실제로 존재하는 가장 최신 filing 에서** 가져온다.

**★왜 filing 단위가 아니라 statement 단위인가 (사용자 지적 + 실측)**:
`is_final` 이 가리키는 정본이 **본문/재무제표를 안 가진 경우**가 있다 —
- **첨부정정 321건**: 본문 무변경(=원본과 동일), report_lines 없음이 정상.
- **본문정정 미추출 125건**: PDF-only 등으로 report_lines 없음(진짜 갭).

즉 `is_final` rcept 하나만 읽으면 이 446건이 전량 빈 값이 된다. statement 단위로 체인을 폴백하면:
- 첨부정정 **307/321** 회복(원본 본문 사용 — 정의상 내용 동일).
- 본문정정 **17/125** 회복(그 statement 있는 이전 filing).
- 나머지 ~122건은 어느 filing 에도 report_lines 없음 = 진짜 데이터 갭(PDF-only) → MISSING 으로
  표면화(L3-2 / PDF 패스 몫, 선택 문제 아님).

**구 std_v2 도 동일**: bs_rcept/is_rcept/cf_rcept 를 따로 저장 = statement 단위 출처 해소(검증된 설계).

**정본 자체의 근거(실측)**: std_v2 FY 2015+ bs_rcept 44,773건 중 **is_final 과 97.5% 일치**(43,652).
불일치 2.5%(1,121)= std 가 is_final 아닌 filing 채택 = 소급재작성 엣지(§4).

## 2. 측정 (n=400)

| | CONFLICT (pooled→선택) | DIFF | MISSING | MATCH% |
|---|---|---:|---:|---:|
| pooled(선택 없음) | 6~18 | 0~1 | ~35 | — |
| filing 단위 선택 | 0~9 | 1~5 | 41~43 (↑) | ~88.5 |
| **statement 단위 폴백**(최종) | **0~2** | 1~4 | **35~37** | **~90.0** |

statement 단위 폴백으로 CONFLICT 가 ablation(std 자체 rcept 주입) 수준으로 수렴하면서 **MISSING
도 회복**(첨부정정 폴백) → MATCH ~90%. filing 단위 선택의 MISSING↑ 부작용이 사라짐.

## 3. 잔여 DIFF 분류 (seed 7: SAME_RCEPT 9 · RCEPT_DIFF 8)

### RCEPT_DIFF (8) — filing 선택 정책 엣지, 엔진 버그 아님
우리 is_final rcept ≠ std_v2 bs/is_rcept. 소급재작성 등에서 정본 선택이 갈린 것. §4 정책 결정.

### SAME_RCEPT (9) — 같은 filing, 값 다름 (진짜 엔진 엣지)
- **combine 이 더 정확(총계 vs fuzzy sub-line)** — 다수:
  · 00346610 2018 retained: combine 이익잉여금 총계(exact,role=P) vs std 미처분(fuzzy,role=S)
  · 00409140 2017 retained: 동일 패턴
  · 00148276 2018 opinc: combine '영업이익'(exact) vs std '영업총이익'(fuzzy, 금융업 상위개념) ← std 오선택
- **진짜 재확인 대상(소수, L3-4 parity)**:
  · 01137383 2019 net_income: combine 유일후보 8.87B('XI.당기순이익') vs std 61.7B(후보에 없음
    → std 가 다른 위치/CF에서 취득). 1건, 희소.
  · 00442455 2020(rev/assets/equity): 같은 rcept 인데 신 체인 report_lines 값(69.71B)≠구 체인
    fact_v2 값(70.79B) — **동일 filing 파서 간 차이**(정정 반영 시점 추정). L3-4 에서 대조.

## 4. ★정책 결정 필요 — 소급재작성(2.5%, RCEPT_DIFF) 처리
is_final 은 **가장 늦은 [기재정정]** 을 정본으로 본다. 그러나 std_v2(구 체인)는 **수년 후 소급
재작성은 무시하고 원본 유지**한 사례가 있다(00106641 2015: is_final=2021정정 16.13조 vs
std=2016원본 16.94조). 두 정책:
- **(P1) 최신정정 우선(현 is_final)**: 항상 최신 [기재정정] = "현재 시점 정정 반영값(as-restated)".
- **(P2) 원본+근시일정정, 소급재작성 별개(std 방식)**: 회계연도 근처 정정만 반영, N년 후
  재작성은 원본 유지 = "당시 보고값(as-originally-filed)".
→ 금융 DB 성격상 둘 다 수요 있음(point-in-time vs 현행). **어느 것을 std_v3 기본으로?** 미결.
   비차단(97.5% 무관) — L3-2/L3-4 에서 함께 확정. 필요시 as-filed/as-restated 이중 뷰.

## 5. 판정 & 다음
- ✅ L3-1b 완료. 정본 선택으로 CONFLICT 붕괴, 엔진 건전성 유지. combine 이 구 체인 오선택을
  여러 건 교정(개선 방향).
- ⚠ 잔여 CONFLICT(filing 내부 이중섹션·다중 revenue) = **node_role/출처우선순위**가 풀 몫(다음
  refinement, 정본 선택 후로 미뤄둔 대로).
- **다음 = L3-2 출처매칭(MISSING ~9%)** — 정본 filing 에 없는 지표를 어느 리포트/열/basis 에서
  채울지. §4 재작성 정책과 함께 설계.
