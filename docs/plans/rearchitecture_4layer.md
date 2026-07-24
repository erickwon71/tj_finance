# 4계층 재설계 — 마스터 허브 (살아있는 문서)

> **이 문서가 재설계 전체의 단일 진입점이다.** 계층별 세부는 아래 문서 맵의 링크로 이어진다.
> 날짜 없는 이 파일을 계속 갱신한다(개별 문서는 시점 스냅샷·상세). 새 세션은 여기서 시작해
> "현재 시작점"(§5)의 최신 핸드오프로 들어간다.
>
> 최종 갱신: **2026-07-24** · 현재 시작점 = [handoff_layer3_profiles_2026-07-24](../qa/handoff_layer3_profiles_2026-07-24.md)

---

## 1. 무엇을 / 왜

파서가 "값·canonical·취합"을 동시에 판단하다 **금융업 이중섹션**(평면 fact 로 합산-vs-제외 구분
불가)에서 막혔다. → 책임을 **4계층으로 분리**:

| 계층 | 책임 | 산출물 |
|---|---|---|
| **1 다운로드** | DART 원본 보고서 수집·보관 | `raw_report/` (XML/PDF) |
| **2 파서(충실전사)** | 원문 tree 를 판단 없이 그대로 전사 (단위만 원 정규화) | `report_lines` |
| **3 취합(값판단)** | 매핑·금융업 합산·정본선택·파생계정·업종 프로파일 = **값판단 전부 여기** | `std_financials_v3` |
| **4 App** | 계층3 산출을 시각화·스크리너에 소비 | Streamlit 앱 |

원설계·확정결정: [rearchitecture_4layer_2026-07-19](rearchitecture_4layer_2026-07-19.md)

---

## 2. 현재 상태 (2026-07-24)

| 계층 | 상태 | 실측 / 요지 |
|---|---|---|
| 1 다운로드 | ✅ 기존 유지 | raw_report 심링크 = SD카드(`/Volumes/dart_data`). NAS 원복 별도 |
| 2 report_lines | ✅ 엔진·검증·**1차적재(2015+)** 완료 | **102,067 filing · 63.5M행 · 2,534사** (min year 2014). **정정본 포함 적재**(정정 filing 9,377·6.8M행). ⚠ **pre-2015·PDF-only 미적재**(2·3차 신규파서 필요) |
| 3 취합 std_v3 | ✅ **정제 사실상 완료** (최종 재빌드 대기) | **185,214행 · 2,534사** · parity ~98% · inspect 전량 v3정답 · 업종 프로파일(보험/은행/증권/한국금융NULL) · **정본선택+기재정정 델타패치 반영**(3,338행/955사 정정 provenance). ⚠ **`--recheck` 완료 후 `build_std_v3.py --all` 재빌드 필수** |
| 4 App swap | ☐ **미착수** | Path A 설계 완료(std_v3 직접소비). 앱 비사용 중·std_v2=교차검증용 |

**남은 큰 덩어리**: ① 계층2 **2차(pre-2015)·3차(PDF-only)** 소급 적재(신규 파서) ② 계층3 **최종 재빌드**
(`--recheck` 후) ③ **계층4 구현 + L3-5 swap**(앱 재배선·구 체인 제거·데일리/야간잡 재설치).

> 📌 **정정(기재정정) 처리 = 완료.** 07-19 체크리스트가 "계층2 4차 패스"로 잡았던 **정본선택 + 정정
> 반영**은 실제로는 **계층3 combine 으로 흡수**되어 구현됨(원본 base + 각 정정본이 건드린 셀만 델타
> 패치, `amended_by` 계보 기록). 따라서 위 "계층2 2·3차 미적재"는 **원본 raw 적재 범위**(pre-2015·PDF)
> 이야기지 정정 처리 미비가 아니다. 설계=[L3-1b 정본선택](../qa/layer3_L3-1b_filing_selection_2026-07-22.md)·
> [L3-1 조합엔진](../qa/layer3_L3-1_combine_prototype_2026-07-22.md).

> ⚠ **주의 3종**: (a) **V2는 정답 아님** — 검증은 DART 원문 기준. (b) **야간 잡 전량 삭제 유지** — swap 전까지
> 구 체인 오염 방지 [[nightly-jobs-paused-phase-a3]]. (c) 앱은 아직 std_v2(교차검증용 보존).

---

## 3. 문서 맵 (계층별)

### 계층2 — report_lines
- [rearchitecture_4layer_2026-07-19](rearchitecture_4layer_2026-07-19.md) — 원설계·확정결정
- [rearchitecture_4layer_2026-07-19_checklist](rearchitecture_4layer_2026-07-19_checklist.md) — 원 체크리스트(**stale, 이 허브가 대체**)
- [sce_statement_of_changes_in_equity_2026-07-21](sce_statement_of_changes_in_equity_2026-07-21.md) — 자본변동표(SCE) 편입 설계
- [layer2_split_table_gap_2026-07-23](../qa/layer2_split_table_gap_2026-07-23.md) — "제목표/데이터표 분리" 추출 갭 근본원인
- [layer2_full_load_report_2026-07-22](../qa/layer2_full_load_report_2026-07-22.md) — 전량적재 1차패스 결과보고

### 계층3 — 취합 std_v3
- [★financial_sector_revenue_standards](financial_sector_revenue_standards.md) — **금융섹터 revenue 표준 단일 출처**(증권=순영업수익 NET·보험/은행=gross·한국금융지주=NULL·잔여·회귀). 섹터별 census 결정 누적
- [layer3_rebuild_plan_2026-07-22](layer3_rebuild_plan_2026-07-22.md) — 재계획(결정 4개 잠금)
- [layer3_design_2026-07-22](layer3_design_2026-07-22.md) — 조합 설계(출처 우선순위·불확실성 지도)
- [layer3_option_a_probe_2026-07-22](../qa/layer3_option_a_probe_2026-07-22.md) — 옵션A 검증 프로브
- [layer3_L3-1_combine_prototype_2026-07-22](../qa/layer3_L3-1_combine_prototype_2026-07-22.md) — L3-1 조합엔진
- [layer3_L3-1b_filing_selection_2026-07-22](../qa/layer3_L3-1b_filing_selection_2026-07-22.md) — L3-1b 정본선택
- [layer3_L3-2_source_matching_2026-07-22](../qa/layer3_L3-2_source_matching_2026-07-22.md) — L3-2 출처매칭
- [layer3_cellkey_normalization_finding_2026-07-22](../qa/layer3_cellkey_normalization_finding_2026-07-22.md) — 셀키 정규화 보류 판단
- [layer3_L3-3_std_v3_build_2026-07-23](../qa/layer3_L3-3_std_v3_build_2026-07-23.md) — L3-3 std_v3 스키마·빌더
- [layer3_L3-4_diff_classification_2026-07-23](../qa/layer3_L3-4_diff_classification_2026-07-23.md) — L3-4 v2/v3 DIFF 분류·판정 (+[tables](../qa/layer3_L3-4_diff_classification_tables_2026-07-23.md))
- [insurer_revenue_composition_2026-07-24](insurer_revenue_composition_2026-07-24.md) — 업종별 revenue/영업이익 표준화 설계

### 계층4 — App swap
- [layer4_industry_tearsheet_design_2026-07-24](layer4_industry_tearsheet_design_2026-07-24.md) — 업종 tearsheet + 스크리너 revenue (**Path A** 확정)
- [sce_equity_movement_detail_2026-07-24](sce_equity_movement_detail_2026-07-24.md) — SCE 자본변동 상세 추출+앱 표출 (신규 테이블 `sce_equity_movements`, gap-fill과 비중복)

---

## 4. 핸드오프 타임라인 (세션 진입점, 최신순)
- **2026-07-24** [handoff_layer3_profiles](../qa/handoff_layer3_profiles_2026-07-24.md) — ★**현재 시작점**. 계층3 정제완료+업종 프로파일+IS추출갭 복구
- 2026-07-23 [handoff_layer3_skeleton](../qa/handoff_layer3_skeleton_2026-07-23.md) — 계층3 골격완성(L3-1~4 baseline)
- 2026-07-22 [handoff_layer2_complete](../qa/handoff_layer2_complete_2026-07-22.md) — 계층2 전량적재 완료·계층3 방향확정
- 2026-07-21 [handoff_rearchitecture](../qa/handoff_rearchitecture_2026-07-21.md) — 계층2 엔진·검증 완료
- 2026-07-19 [handoff_rearchitecture](../qa/handoff_rearchitecture_2026-07-19.md) — 4계층 재설계 착수

---

## 5. 현재 시작점 · 다음 액션 (순서)

**지금 진행 중**: 사용자 `--recheck` 실행 중(요약재무 추출수정 전 코퍼스 소급, ~9.5h). 완료 대기.

1. **★`--recheck` 완료 → `build_std_v3.py --all` 재빌드**(25분). 재추출분+이번 세션 전 프로파일 std_v3 반영.
2. **계층4(P2) 구현** — Path A(std_v3 직접소비): 업종 tearsheet + 스크리너 정규화 revenue.
   설계 = [layer4 문서](layer4_industry_tearsheet_design_2026-07-24.md). ★재빌드 후 착수(현 std_v3 stale).
3. **SCE 자본변동 상세**(신규, 재빌드와 독립): 계층3 추출 → `sce_equity_movements` → 앱 표출(배당
   지배/비지배·자사주 취득/소각·주식보상·이익잉여금 사용처). recheck 완료 후 착수.
   설계 = [SCE 상세 문서](sce_equity_movement_detail_2026-07-24.md).
4. **L3-5 swap**(최종): 앱 std_v2→std_v3 재배선 · 구 체인 제거(fact_v2·std_v2·text.py) · report_lines
   데일리 배선(`collect_new.py` **두 call site**) · 야간 잡 재설치(deploy/launchd) · 최근 IPO 6사 sync 재개.
5. **(별도 규모) 계층2 소급 적재**: 2차 pre-2015 · 3차 PDF-only — 신규 파서 개발 필요. 우선순위 협의.

---

## 6. 확정 결정 (잠금)
- **4계층 분리** — 파서=충실전사(판단 없음), 취합=별도 계층 (2026-07-19).
- **적재순서 = 전량적재 → 계층3** (구 '계층3→전량'을 뒤집음, 2026-07-19).
- **계층3 = 신 체인 단독**: 새 std_v3 빌드 후 swap, 구 체인은 swap 후 제거 (2026-07-22).
- **정본선택·정정 반영 = 계층3 소관**(구 '계층2 4차'에서 이관): 원본 base + 기재정정 델타패치, 값의미=
  as-restated이되 무손실(정정이 안 건드린 셀 보존) (2026-07-22).
- **업종 revenue** (보험·은행=GROSS 합산), **증권=순영업수익 NET**(영업이익+판관비, 시계열 절벽 해소),
  **한국금융지주형=NULL**. 섹터별 census 로 확정 — 상세·잔여는 [금융섹터 revenue 표준](financial_sector_revenue_standards.md) (2026-07-24).
- **계층4 = Path A**: std_v3 직접소비(사이드채널 없음). 앱 비사용·std_v2 교차검증용 (2026-07-24).
- **SCE 적재 유지**: 역할 = 주주환원 '1차 출처'(gap-fill이 대체) 아님 → **자본변동 상세 분해**(성분×
  변동사유 매트릭스, 신규 테이블 `sce_equity_movements` → 앱 표출). 헤드라인은 gap-fill (2026-07-24).
