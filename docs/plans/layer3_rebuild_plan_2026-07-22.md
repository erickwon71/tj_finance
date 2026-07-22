# 계층3 재계획 — 신 체인 단독 진행 (결정 확정, 2026-07-22)

> 상위 = `docs/plans/rearchitecture_4layer_2026-07-19.md` · 방향 = `docs/plans/layer3_design_2026-07-22.md`
> 검증근거 = `docs/qa/layer3_option_a_probe_2026-07-22.md`(옵션A 프로브: 2015+ 표준화 성립·DIFF≈0)
> 핸드오프 = `docs/qa/handoff_layer2_complete_2026-07-22.md`
>
> **성격: 계획 문서(WIP). 실행은 별도 요청 대기(auto-execute 금지).**

## 0. 확정 방향
**신 체인 단독 진행.** 구 체인(fact_v2 → statement_source → std_v2, `text.py` 파서)은
계층3 검증·swap 완료 후 **폐기**한다. 병행 유지 안 함.

## 1. 확정된 결정 (2026-07-22, 사용자 선택)

| # | 항목 | 결정 |
|---|---|---|
| 1 | 조합(충돌해소) 엔진 | **하이브리드** — build.py 검증 규칙(소계·충돌해소) 이식 + node_role(P/S)·출처우선순위 1차 |
| 2 | 계층3 산출 테이블 | **새 테이블(std_v3) 후 swap** — 구 std_v2 와 병행 대조·롤백 안전망 |
| 3 | 구 체인 폐기 시점 | **swap 검증 후 제거** — parity 통과·앱 전환 완료 뒤 일괄 |
| 4 | report_lines 인덱스 | **쿼리패턴 확정 후 측정기반** — 과잉 인덱스 방지 |

## 2. 빌드 순서 (위 결정에서 도출)

### L3-1. 조합엔진 프로토타입 (하이브리드) — ✅ 완료 (2026-07-22)
결과 = `docs/qa/layer3_L3-1_combine_prototype_2026-07-22.md`. 코드 = `fin2/layer3/combine.py`.
- 구 체인 `build._resolve`/`_reduce_conflict` 이식(acode→label_raw 적응), DIRECT_MAP 6지표.
- 측정: ablation(std 의 bs/is_rcept 주입)에서 **CONFLICT→0·std_v2 ~90% 재현** → 엔진 건전성 확인.
- ★발견: pooled combine 의 잔여 CONFLICT 는 **filing 버전 다중성(원본+정정+재작성 공존)** 이 원인.
  같은 filing 주면 소멸 → **라벨/해소 문제 아님, 정본(filing) 선택 미실행 때문.**
- DIFF(1~3)은 회귀 아니라 개선(신 엔진이 총계 이익잉여금 채택, 구 체인은 fuzzy 미처분 sub-line).
- node_role 규칙은 아직 미적용 — **정본 선택 후 잔여(진짜 소계 이중계상)에만 필요할 가능성**.

### L3-1b. 정본(filing) 선택 — ✅ 완료 (2026-07-22, 계층3 선택 스텝 채택)
결과 = `docs/qa/layer3_L3-1b_filing_selection_2026-07-22.md`. 코드 = `combine.select_canonical_rcept`.
- 결정: **(B) 계층3 선택 스텝**(사용자). combine 진입 전 정본 rcept 1개 선택.
- 규칙: `filings.is_final`(다운로드 계층의 최종 [기재정정]) 재활용. std_v2 와 **97.5% 일치**.
- 측정: CONFLICT pooled ~18 → 정본선택 후 ~1(ablation 수준). DIFF ~0.7%(다수 combine 개선).
- ⚠ **미결 정책(비차단, 2.5%)**: 소급재작성 처리 — (P1)최신정정 우선(현 is_final, as-restated) vs
  (P2)원본+근시일정정, 수년후 재작성 별개(std 방식, as-filed). std_v3 기본값을 L3-2/L3-4 에서 확정.
- ⚠ 잔여 CONFLICT(filing 내부 이중섹션·다중 revenue)는 **node_role/출처우선순위**가 풀 몫(다음).

### L3-2. 출처매칭(MISSING) — ◐ 부분완료 (2026-07-22)
결과 = `docs/qa/layer3_L3-2_source_matching_2026-07-22.md`.
- ✅ **basis 폴백 구현**: 단일 basis 기업(연결 없음→별도) 반대basis 폴백. MATCH ~90→91.5%.
- ⚠ **NO_LINES(7.1% 기간) 규명**: 자체연도 보고서 report_lines 미추출 → std 는 이웃해 비교열
  (col_index 1/2)에서 채웠음. **결정 필요**: (a)Layer-2 완성=자체연도 백필(당기열 권위, 권고) vs
  (b)비교열 백필(std 재현 쉬우나 재작성 얽힘). L3-3 빌드 전 확정.

### L3-2(orig). 출처매칭(MISSING) 규칙 — 원래 메모
- 프로브 MISSING(~9%)의 정체 = 그 (corp,fy,period,basis) 키에 report_lines 행 부재
  (std 가 다른 리포트/열/basis 에서 채운 케이스). 어느 리포트/열(col_index 0/1/2)/basis 에서
  채울지 규칙화. 구 std_v2 lineage(bs/is/cf_rcept)를 참고자료로.

### L3-3. std_v3 테이블 + 빌더
- 새 테이블 `std_financials_v3` — std_v2 **동일 값 컬럼 계약** + lineage·applied_rules·value_lineage.
- 2015+ 전량 빌드(102,633 filing 스케일).

### L3-4. parity 회귀 (프로브 전수 확대)
- 현재 400표본 프로브 → **전 유니버스** std_v3 ↔ 구 std_v2 대조.
- DIFF 목록화 → **정상 불일치(소급재작성·연결범위변동) vs 회귀** 분류(핸드오프 ⚠4종 중 하나).

### L3-5. swap + 구 체인 제거
- 앱(P5 호환 뷰)을 std_v3 로 재배선.
- 검증 후 구 체인 일괄 제거: `fact_v2`·`statement_source`·구 `std_v2`·`text.py` 텍스트트랙.

### L3-6. 성능 (측정기반)
- L3-3/4 의 실제 빌드·조회 쿼리 프로파일 → 느린 지점에만 `node_role`/`label_raw` 인덱스.

### L3-7. 후속
- 2차 패스(pre-2015 70,374건) — 2015+ 확실해진 뒤.
- 야간 잡 재가동 — **신 체인 기준으로** 재설치([[nightly-jobs-paused-phase-a3]]).

## 3. 되돌아올 트리거
L3-1/2 중 "2015+ 표준화 가정이 깨진다"고 판단되면 `layer3_design §4` 로 복귀. 프로브 시점엔
미발생. pre-2015 진입은 2015+ 확정 후.

## 4. 미결정 (다음 결정 대기 — 핵심 빌드 비차단)
- 보정 적용: `report_line_corrections`/`report_line_anomalies` 를 계층3 빌드 시 적용할지(전문가
  권고=빌드 1회) vs 격리 유지. 대다수 SIGN 은 BS 대체로 무해 → held 유지가 기본.
- 단위오류 71건 탐지경로 신설 여부(BS·SCE 동반 부풀어 교차대조 불가).
- 주석 적재(볼륨 5배) — 배당·이익잉여금처분 완결성. 별도 단계.

## 5. 다음 착수 후보
**L3-1b(정본 선택)** — L3-1 완료로 드러난 선결 의존성. 아키텍처 분기(계층2 4패스 A vs 계층3
선택 스텝 B) 결정 후 착수. 정본 선택이 되면 CONFLICT 소멸 → L3-2(출처매칭) → L3-3(std_v3 빌드).
