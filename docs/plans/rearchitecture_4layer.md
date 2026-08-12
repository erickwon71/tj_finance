# 4계층 재설계 — 마스터 허브 (살아있는 문서)

> **이 문서가 재설계 전체의 단일 진입점이다.** 계층별 세부는 아래 문서 맵의 링크로 이어진다.
> 날짜 없는 이 파일을 계속 갱신한다(개별 문서는 시점 스냅샷·상세). 새 세션은 여기서 시작해
> "현재 시작점"(§5)의 최신 핸드오프로 들어간다.
>
> 최종 갱신: **2026-08-09(일곱 번째) — 재설계 본류(브리지 swap 계획, §5 전체) 완전 종료.**
> C-1 렌더 확인(headless, 금융 5프로필+baseline 전부 크래시 없음·revenue 설계대로)과 Streamlit UI
> 풀스모크(실제 브라우저, 4개사+스크리너 실행, headless 실측과 수치 완전일치)까지 마쳐
> [`layer3_v3_bridge_swap_2026-07-25.md`](layer3_v3_bridge_swap_2026-07-25.md) §4 단계 1~7·G1~G4
> **전 항목 완료**. 지난 세션이 보류했던 push(`d707a03`+`9dd4851`+`cc03326`+`482abce`)와 팔로업
> ③(`layer2_note_heading_fix_verify.py` REGRESSED 오탐)도 모두 종료됨. **다음 액션 = §7 후속
> (pre-2015 2차 패스·v3-native 품질게이트·v2 폐기) 중 우선순위 결정**, 그전엔 새 트랙 착수 여부를
> 사용자와 논의.
> (하루치 전체 정리 = [session_summary_2026-07-31](../qa/session_summary_2026-07-31.md))
>
> **08-01 병행 트랙 2건**(재설계 범위 밖 — 각자 별도 문서가 정본, 아래 요약만 링크):
> - **사업의 내용 카탈로그 + R0 원칙** — [handoff_biz_catalog_r0_2026-08-01](../qa/handoff_biz_catalog_r0_2026-08-01.md).
>   `biz_metrics`/`order_backlog` 신규 적재(계층2 우회는 **2026-08-09 해소 완료** — §6 R1 항목 참고)
>   + `docs/PARSING_RULES.md` 단일화(R0~R9). R0 원칙은 계층2 파서에도 적용 가능하니 계층2 작업 전 일독 권장.
> - **데일리 파이프라인 자동화**(상장폐지 원문 NAS 이관 + KRX 휴장일 스킵) — 정본은
>   [collection_pipeline_restore_2026-07-31](collection_pipeline_restore_2026-07-31.md) §13·§14 +
>   [handoff_collection_pipeline_2026-07-31](../qa/handoff_collection_pipeline_2026-07-31.md)(갱신됨).
>   계층1(다운로드) 운영 강화이며 계층2/3 데일리 재편입은 여전히 Phase 5 대기.
>
> **08-04~08-07 병행 트랙**(재설계 범위 밖 — 계층2 적재공백 감사 및 R4-2 파생 백로그, **트랙 종료**):
> 189건 원인 전수분해([handoff_layer2_gap_analysis_2026-08-04](../qa/handoff_layer2_gap_analysis_2026-08-04.md)) →
> 조용한 손실 6종 수정+외화(USD) 지원+상장폐지 데이터 정리
> ([handoff_layer2_silent_loss_2026-08-05](../qa/handoff_layer2_silent_loss_2026-08-05.md)) →
> ⓪-4 file_path 재발 방지 + 08-04 원인표 재확인, 활성기업 잔여공백 **24건**으로 확정 및
> 정밀 재분해(신규 패턴 "XML 파싱 자체 실패" 9건 발견,
> [handoff_delisting_filepath_and_gap_recheck_2026-08-05](../qa/handoff_delisting_filepath_and_gap_recheck_2026-08-05.md)) →
> 그 잔여공백에서 파생된 "미착수 후보 3건"을 한곳에 정리
> ([handoff_r4_2_remaining_backlog_2026-08-06](../qa/handoff_r4_2_remaining_backlog_2026-08-06.md)) →
> **2026-08-07 3건 전부 종료**: ①"표못잡음" 6건 추정 → 실측 3건(이노시뮬레이션 2건은 신규
> 파서 폴백 `_split_headed_multi_statement_table`로 해결·R4-2 §3 등재, 자비스 1건은 원문
> 자체에 계정 데이터가 없어 파서로 불가·정상 보류) · ②표제 인식 수정(`0b93816`) 소급 미반영
> 260건 추정 → 전수 스캔 실측 **55건**, 전량 백필 완료(순수 회수, 손실 0) · ③08-04 트랙
> download-only 백로그 72건 중 **64건 해소**(잔여 8건은 원문이 PDF뿐이라 파서로 불가·정상
> 종결). **부수 발견**: ③ 재감사 중 16개사에서 Gate B `line_value_diff` 856건 검출 →
> 원인은 데이터 손상이 아니라 감사기(`fin2/audit/face_audit.py`)가 표 위치·basis 식별에
> 낡은 로직을 쓰던 자체 버그(추출기는 2026-07-17 재설계로 이미 해결한 문제를 감사기만
> 못 따라감), `_detect_body_statement_tables` 재사용으로 수정 후 재감사 value_diff **0**
> (`75d526e`). 전부 main 병합·push 완료(`3e9fef6`). **이 트랙은 여기서 완전히 닫혔다** —
> 재개할 남은 후보 없음, 새 세션은 본류(§5) 또는 신규 트랙을 선택한다.

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
| 1 다운로드 | ✅ 기존 유지 + 운영 자동화 진행 중 | raw_report 심링크 = SD카드(`/Volumes/dart_data`). NAS 원복 별도. **2026-08-01**: 상장폐지 확정분 원문 NAS 이관 자동화 + KRX 휴장일 스킵 데일리 배선(정본=[collection_pipeline_restore](collection_pipeline_restore_2026-07-31.md)) — 계층2/3 데일리 재편입은 Phase 5 대기 그대로 |
| 2 report_lines | ✅ 엔진·검증·**1차(2015+)+2차(pre-2015) 적재** 완료 | 1차: **102,067 filing · 63.5M행 · 2,534사**(min year 2014, 정정본 포함 9,377필링·6.8M행). **2차(pre-2015, 2026-08-11 완료)**: 신규 모듈(`docs/PARSING_RULES.md` R13) + 전량백필 81,660/82,005건(99.6%, 활성유니버스 1,551개사) · report_lines 22.2M행 · BS항등식 전수 98.8% 성립. 데일리 배선(`collector/note_lines_sync.py::FY_MIN`)도 1999로 낮춰 향후 재수집분 자동 반영. ⚠ **PDF-only 1,405건만 미적재**(3차 신규파서 필요, 별도 트랙) |
| 3 취합 std_v3 | ✅ **정제 완료 + pre-2015 반영** | **297,429행 · 2,525사**(2026-08-11, `--year-min 1999` 전량재빌드로 pre-2015 112,849행 신규 반영, 오류0) · parity ~98% · inspect 전량 v3정답 · 업종 프로파일(보험/은행/증권/한국금융NULL) · **정본선택+기재정정 델타패치 반영**. `standard_financials` 뷰의 std_v2 UNION 폴백은 pre-2015도 이제 `NOT EXISTS` 하나로 통일(중복행 버그 발견+수정, 마이그레이션 `2026_08_standard_financials_v3_pre2015_dedup`) — PDF-only 등 std_v3 미커버 잔여만 폴백 |
| 4 App swap | ☐ **미착수** | Path A 설계 완료(std_v3 직접소비). 앱 비사용 중·std_v2=교차검증용 |

**남은 큰 덩어리**: ① 계층2 **주석 전반 전사**(D&A 등 파생계정 소스, swap 선행 · [notes plan](layer2_notes_transcription_2026-07-25.md)) +
**2차(pre-2015)·3차(PDF-only)** 소급 적재(신규 파서) ② 계층3 **enrichment 완성 + 최종 재빌드** ③ **계층4
구현 + 브리지 swap**([plan](layer3_v3_bridge_swap_2026-07-25.md), 앱 재배선·구 체인 제거·데일리/야간잡 재설치).

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
- [★layer2_notes_transcription_2026-07-25](layer2_notes_transcription_2026-07-25.md) — **주석(note) 전반 전사**(D&A·R&D 등 파생계정 소스). `_emit_note_lines` 활성화+백필, 파편 note추출기 흡수. 볼륨(주석=표96%) 관건. **swap 선행**
- [docs/PARSING_RULES.md](../PARSING_RULES.md) — **파싱 규칙 단일 진입점(2026-08-01 신설)**. R0(지배 원칙: 있으면 파싱·없으면 넘어감, 거짓부재 금지)~R9 + 원문 XML 함정 15종. 계층2 파서 신설·수정 전 필독. 배경 = [handoff_biz_catalog_r0_2026-08-01](../qa/handoff_biz_catalog_r0_2026-08-01.md)(병행 트랙, §0 참고) — 그 세션에서 확립된 원칙이나 R0 자체는 계층2 전반에 적용
- [★pre2015_layer2_backfill_plan_2026-08-10](pre2015_layer2_backfill_plan_2026-08-10.md) — **pre-2015 2차 패스 — Phase 1~6 전부 완료(2026-08-11)**. XML 79,283건·활성 1,551개사 스코프, 신규 모듈(`docs/PARSING_RULES.md` R13) + 전량백필 81,660건(err0) + 데일리 배선(`FY_MIN` 1999로 하향) + 문서화. 잔여 = Phase7(std_v3 백필, 별도 승인). 실행 체크리스트 = [pre2015_layer2_backfill_todo_2026-08-10](pre2015_layer2_backfill_todo_2026-08-10.md)(Phase1~6 전부 ☑)
- [★std_v3_native_gate_b_plan_2026-08-11](std_v3_native_gate_b_plan_2026-08-11.md) — **§7 후속 1번, 계획 초안(실행 대기)**. `face_audit`이 std_v2 전용 하드코딩이라 std_v3 행의 `gate_b_status`가 키 조인으로 v2 감사결과를 빌려쓸 뿐 v3 값 자체를 감사하지 않음(pass 표시 v3 행의 9.5%가 실제론 v2와 값이 다름). `source_version` 컬럼 신설 등 결정 지점 정리.

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
- [★layer3_v3_bridge_swap_2026-07-25](layer3_v3_bridge_swap_2026-07-25.md) — **브리지 swap 마스터**(std_v2→std_v3 뷰 전환, enrichment v3-native, C-1 자동). enrichment: capex/fcf/net_debt ✅완료(`d43974e`), D&A/shares=계층2 주석전사 선행
- [layer4_industry_tearsheet_design_2026-07-24](layer4_industry_tearsheet_design_2026-07-24.md) — 업종 tearsheet + 스크리너 revenue (**Path A** 확정)
- [sce_equity_movement_detail_2026-07-24](sce_equity_movement_detail_2026-07-24.md) — SCE 자본변동 상세 추출+앱 표출 (신규 테이블 `sce_equity_movements`, gap-fill과 비중복)

---

## 4. 핸드오프 타임라인 (세션 진입점, 최신순)
- 2026-08-11(본류, §7 후속 1번 — **Phase1~7 전부 완료, 트랙 종료**) [pre2015_layer2_backfill_todo](pre2015_layer2_backfill_todo_2026-08-10.md) —
  Phase5(전량백필 81,660건, err0) 결과를 DB 직접검증(BS항등식 전수 98.8% 성립·상장폐지 정상제외)
  + Phase6(파이프라인 편입: 데일리 배선 갭 발견+수정 `note_lines_sync.py::FY_MIN` 2015→1999 ·
  `docs/PARSING_RULES.md` R13 신설 · pytest 471 passed) + Phase7(std_v3 백필 297,429행 ·
  뷰 중복버그 발견+수정 · std_v2는 보존 결정) 전부 완료. 상세는 §5 최신 갱신 블록.
- 2026-08-09(본류, §5 4번 C-1 렌더 확인 작업 중 발견 — **트랙 종료**) [std_v3_dq_shares_period_backfill_plan](std_v3_dq_shares_period_backfill_plan_2026-08-09.md) —
  C-1 렌더 확인 중 `std_financials_v3`의 `data_quality`·`period_end`·`shares_out` **3개 컬럼이
  전량(100%) NULL**임을 발견(스크리너가 `data_quality<3`을 직접 필터링해 모집단 668개사
  조용히 누락 등 치명적 피해). Phase 1(DQ/period_end 인라인 산출, v2 로직 이식)→Phase 2
  (shares_out 계층2 신설 — `report_shares_outstanding` 신규 테이블+`fin2/extract/
  shares_transcribe.py`+전 filing 소급백필 95,862행/94.5%)→Phase 3(`build_std_v3 --all`
  전량재빌드 2,525corp·184,580행+6종 검증) 전부 완료. **스크리너 모집단 1,852→2,520개사로
  정확 회복**, 기업은행 FY2025 매출 19.0조 등 원래 버그리포트 사례 전부 해소 확인. DQ=3 판정도
  실제 작동 확인(동국홀딩스 인적분할·제주은행 별도 항등식위반 정확히 캐치). `docs/PARSING_RULES.md`
  R12(발행주식수 계층2 cross-cutting 스칼라) 신설. 부수발견(범위밖): 제주은행 별도 자산=부채
  항등식 위반·삼성증권 FY2025 net_income NULL — combine 레이어 기존 결함, 별도 트랙 필요.
  실행체크리스트 = [`std_v3_dq_shares_period_backfill_todo_2026-08-09.md`](std_v3_dq_shares_period_backfill_todo_2026-08-09.md)
  (Phase1~4 전부 ☑). C-1 렌더 확인은 이 트랙 완료로 재개 가능해짐 — §5 최신 갱신 참고.
- 2026-08-08(병행, 재설계 범위 밖 — **트랙 종료**) [note_span_fix_plan](note_span_fix_plan_2026-08-07.md) — 바로 아래 항목(08-07 2회차)이 연 note_lines/SCE 열 오귀속(R11) 트랙의 **Phase 1~4 전부 완료**. Phase 1(측정: `LV′` 라벨영역 규칙 확정)→Phase 2(구현: `expand_table_grid`+`_grid_header_split`/`_grid_body_rows`, `docs/PARSING_RULES.md` R11/R11-1/R11-2)→Phase 3(검증: 전수 census 결함 0건, 진행 중 R11 자체 회귀 2종 발견+수정)→Phase 4(**DB 반영**: note_lines 전량 재적재 245M→**247.2M행**(+0.73%, 1차 시도 외부요인 중단→`RESUME_NOTES=1` 재개로 완주) + std_v3 재빌드(184,298→184,580행) + 재검증(DB 직접 대조·Gate B `line_value_diff=0`·D&A 재확인) 전부 통과). 부수 개선: `collector/storage_guard.py`에 opt-in SD 폴백(`ensure_root`) 신설. **다음 세션이 이 트랙에서 시작할 필요 없음** — Phase 5(문서·메모리 마감)까지 마치면 완전 종결.
- 2026-08-07(병행, 재설계 범위 밖, 같은 날 2회차) [handoff_note_lines_span_misattribution](../qa/handoff_note_lines_span_misattribution_2026-08-07.md) — 위 항목(08-08, Phase 1~4 완료)으로 대체됨. 바로 아래 항목(같은 날 1회차)의 §4-1(외화열) 진단을 뒤집음 — 원인은 헤더 정규식이 아니라 `parser/xml/table_extractor.py`가 **본문 행에서 ROWSPAN/COLSPAN을 전혀 확장하지 않는** 구조적 결함(POSCO·풍강 원문 대조로 확정). note_lines 원문 전수 재파싱(101,327건, 오류 0) 완료 — 값 2억4,550만 개 중 **2,819만 개(11.48%) 컬럼 오귀속, 필링의 99.0% 영향**. report_lines(본문) 영향은 미측정. 코드/DB 변경 없음(조사만, census 스크립트는 `scripts/census_note_span_misattribution*.py`로 영구 보존) — 다음 세션 첫 작업 = 수정 로직 설계.
- 2026-08-07(병행, 재설계 범위 밖 — ⚠**진단 번복됨, 위 항목 참고**) [handoff_unit_multiplier_misattribution](../qa/handoff_unit_multiplier_misattribution_2026-08-07.md) — 07-31 이 "셀 병합 결함"이라 부른 것을 재조사 → 단일 결함이 아니라 **단위(배수) 오귀속 최소 3종**(외화열 오적용·계정별 예외단위·미상)으로 재분류. `PARSING_RULES.md` 부록C의 "✅완료" 표기가 biz_metrics 한정임을 발견(report_lines/note_lines 쪽은 미조치) — 이 부분은 유효. 외화열(§4-1) 원인 진단은 위 2회차 항목에서 뒤집힘.
- 2026-08-07(병행, 재설계 범위 밖 — **트랙 종료**) R4-2 파생 백로그 3건 전부 완료(①표못잡음 실측3건·②표제인식 소급 55건 백필·③download-only 64/72건 해소) + 부수 발견 Gate B 오탐 856건 해소(감사기 표 식별 버그, `75d526e`). 정본 문서 없음(메모리 기록: `r4-2-backlog-items-2-3-done-2026-08-07`·`r4-2-item1-headed-multistmt-done-2026-08-07`·`key-bugs-fixed` #9), 원출처는 아래 08-06 항목
- 2026-08-06(병행, 재설계 범위 밖) [handoff_r4_2_remaining_backlog](../qa/handoff_r4_2_remaining_backlog_2026-08-06.md) — 08-04/08-05 트랙이 남긴 미착수 후보 3건을 한곳에 정리(구현 없음, 정리만). 다음날(08-07) 위 항목에서 3건 전부 처리됨
- 2026-08-05(병행, 재설계 범위 밖) [handoff_delisting_filepath_and_gap_recheck](../qa/handoff_delisting_filepath_and_gap_recheck_2026-08-05.md) — ⓪-4 file_path 재발버그 수정+소급교정, 활성기업 잔여공백 **24건** 확정·정밀분해(신규 패턴 XML파싱자체실패 9건)
- 2026-08-05(병행, 재설계 범위 밖) [handoff_doc_default_unit_gap5](../qa/handoff_doc_default_unit_gap5_2026-08-05.md) — R4-1 신설(문서 전체 기본단위) + 특수건설류 별개결함 분리
- 2026-08-05(병행, 재설계 범위 밖) [handoff_r4_2_merged_title_table](../qa/handoff_r4_2_merged_title_table_2026-08-05.md) — R4-2 신설(제목+데이터 병합 표·제목없는 표 2종 폴백), 특수건설·팬엔터테인먼트·포시에스 3건 복구
- 2026-08-05(병행, 재설계 범위 밖) [handoff_xml_parse_failure_xbrl_finding](../qa/handoff_xml_parse_failure_xbrl_finding_2026-08-05.md) — XML파싱실패 재확인(진짜 6건)+DART XBRL 원문 대체 경로(`ifrs.do`) 발견(조사만, 코드/DB 변경 없음)
- 2026-08-05(병행, 재설계 범위 밖) [handoff_layer2_silent_loss](../qa/handoff_layer2_silent_loss_2026-08-05.md) — 계층2 조용한 손실 6종 수정+외화(USD) 지원+상장폐지 데이터 정리, 공백 189→24
- 2026-08-04(병행, 재설계 범위 밖) [handoff_layer2_gap_analysis](../qa/handoff_layer2_gap_analysis_2026-08-04.md) — 계층2 적재공백 189건 원인 전수분해 착수
- 2026-08-01(병행, 재설계 범위 밖) [handoff_biz_catalog_r0](../qa/handoff_biz_catalog_r0_2026-08-01.md) — 사업의 내용 27항목 신규적재(`biz_metrics` 7.81M행·2,524사, `order_backlog` 24,687행) + R0 원칙 확립 + `docs/PARSING_RULES.md` 단일화 + 거짓부재 결함 10건 수정 + 전수 재적재(오류0·회귀130). 미결: 계층2 편입 여부
- 2026-08-01(병행, 재설계 범위 밖) [handoff_collection_pipeline_2026-07-31 갱신](../qa/handoff_collection_pipeline_2026-07-31.md) — 상장폐지 원문 NAS 이관 자동화(⓪-4)+KRX 휴장일 스킵(⓪-0) 데일리 배선. 정본=[collection_pipeline_restore §13·§14](collection_pipeline_restore_2026-07-31.md). 신규 테스트 19건·pytest 149/149
- **2026-07-31** [handoff_f1_f2_units](../qa/handoff_f1_f2_units_2026-07-31.md) — ★**현재 시작점(재설계 본류)** · 세션 전체 정리 = [session_summary](../qa/session_summary_2026-07-31.md) · 재적재 결과 = [phase4_reload](../qa/phase4_reload_2026-07-31.md). F1(단위 판정 표→**열** 단위, 오염 제거)·F2(헤더 삭제→`header_hint` 전사) 구현. 구·신 차분에서 **본문·SCE 변화 0**. 미선언 11.2M셀·수주/가동률 공백 규명 완료. **Phase 4 재적재까지 완료**(DB 108.9→74 GB · 오염 6,130,738행→0 · note_lines 246.6M행)
- 2026-07-30(밤) [handoff_coverage_gaps](../qa/handoff_coverage_gaps_2026-07-30b.md) — 검증도구 3종(단위 census·문서 census·낭비 원장) 신설 + 전수 실측(오염 6.13M행·미귀속 19.8%·회수가능 52.3GB)
- 2026-07-30(낮) [handoff_layer2_sanitize_da](../qa/handoff_layer2_sanitize_da_2026-07-30.md) — DART XML 이스케이프 결함 수정+전량 재적재, D&A FY 97.4%
- 2026-07-26 [handoff_layer2_notes](../qa/handoff_layer2_notes_2026-07-26.md) — 계층2 주석 전사 완료(note_lines 2.1억행)+계층3 note→D&A 매핑 착수점. ★D&A "주석에 없음" 진단 정정
- 2026-07-24 [handoff_layer3_profiles](../qa/handoff_layer3_profiles_2026-07-24.md) — 계층3 정제완료+업종 프로파일+IS추출갭 복구
- 2026-07-23 [handoff_layer3_skeleton](../qa/handoff_layer3_skeleton_2026-07-23.md) — 계층3 골격완성(L3-1~4 baseline)
- 2026-07-22 [handoff_layer2_complete](../qa/handoff_layer2_complete_2026-07-22.md) — 계층2 전량적재 완료·계층3 방향확정
- 2026-07-21 [handoff_rearchitecture](../qa/handoff_rearchitecture_2026-07-21.md) — 계층2 엔진·검증 완료
- 2026-07-19 [handoff_rearchitecture](../qa/handoff_rearchitecture_2026-07-19.md) — 4계층 재설계 착수

---

## 5. 현재 시작점 · 다음 액션 (순서)

> **2026-07-31 갱신** — 아래 1~2번(계층2 주석 전사 · 계층3 재빌드)은 끝났다. 그 뒤로
> 계층2 값 정확성 작업(F1 단위 열귀속 · F2 header_hint · F3 표 정규화)과 **전량 재적재**까지
> 마쳤다: DB 108.9 → **74 GB**, note_lines **246.6M 행**, 비금액 열 오염 6,130,738 → **0**.
> 다음 액션은 [현재 핸드오프 §0-1](../qa/handoff_f1_f2_units_2026-07-31.md) 을 따른다
> (1순위 = 셀 병합 결함 처리 방향 결정 · 2순위 = 구 계약을 보는 검증도구 4종 갱신).
> 아래 목록은 브리지 swap 쪽 흐름으로 계속 유효하다.
>
> **2026-08-07 갱신** — 08-01~08-07 은 전부 본류 밖 병행 트랙(§0 참고, 계층2 적재공백
> 감사 + R4-2 파생 백로그 3건 + Gate B 감사기 버그)이었고 08-07 부로 그 트랙이 **완전히
> 종료**됐다. 본류(아래 1~5번)는 07-31 이후 진행이 없어 순서·상태 그대로 유효.
>
> **2026-08-07 재갱신(같은 날 세 번째)** — "셀 병합 결함 처리방향 결정"(7/31 1순위)은
> **원인 재규명 + 정밀 전수조사까지 끝났다.** 진짜 원인은 `parser/xml/table_extractor.py`의
> 본문 행 추출이 ROWSPAN/COLSPAN을 확장하지 않는 구조적 결함이고, note_lines 값의
> **11.48%(2,819만 개)가 컬럼 오귀속**, 필링의 99.0%가 영향권이다. 새 시작점 =
> [handoff_note_lines_span_misattribution](../qa/handoff_note_lines_span_misattribution_2026-08-07.md)
> (다음 세션 첫 작업 = 수정 로직 설계). 그다음 2순위(구 계약을 보는 검증도구 4종 갱신)는
> 순서 그대로 유효.
>
> **2026-08-09 갱신** — 본류 착수 전 상태 점검(§1 ①controlling_ni 소급 재표준화 확인) 중
> `std_financials_v3`(브리지 swap 이후 앱이 옮겨갈 목표 테이블)에서 controlling_ni 대량 공백
> 재발(23%만 채움, 삼성전자도 NULL)을 발견 → 원인규명·수정·전량 재빌드까지 완료
> ([계획서](std_v3_controlling_ni_gap_fix_plan_2026-08-08.md), 브랜치
> `fix/std-v3-controlling-ni-separate-basis`, 미머지). **커버리지 23.0%→85.4%**
> (157,637/184,580행), 원문대조 50건 불일치 0. 브리지 swap(위 3번)의 전제조건인 "v3 데이터
> 품질" 중 이 항목은 해소됨 — swap 착수 전 main 머지 필요.
>
> **2026-08-09 갱신(같은 날 두 번째) — §5 3번 "뷰 브리지 교체" 실행**: main 머지·push 확인
> 후(위 항목 전제조건 충족) [`layer3_v3_bridge_swap_2026-07-25.md`](layer3_v3_bridge_swap_2026-07-25.md)
> §4 순서대로 착수 — `standard_financials` 뷰를 std_v3(2015+)+std_v2 UNION ALL 폴백으로 교체
> (`collector/db.py` 마이그레이션 `2026_08_standard_financials_v3_bridge_swap`). 원안(§2, pre-2015만
> UNION)에서 **폴백 조건을 확장**해 2015+ 중 std_v3 미빌드 corp-period(6,390건)도 std_v2 로
> 폴백시켜 G1(커버리지 무손실)을 실측으로 충족(구뷰 263,792행→신뷰 279,860행, 손실 0·순증
> 16,068). G2 표본대조에서 std_v2 와 값이 다른 2~6% 는 표본조사 결과 std_v2 쪽 "comparative
> bleed"(다른 시점 필링의 비교연도 값이 잘못 유입) 버그를 std_v3 가 바로잡은 것으로 판단.
> G3(금융 industry_lines)·G4(데이터 계층 스모크) 통과, pytest 439/1(무관) 유지. **미커밋**(git
> 승인 대기) — 상세는 위 문서 최신 갱신 블록. 다음 = 커밋 승인 → §5 4~5번(검증도구 4종 갱신,
> C-1 렌더 확인) 또는 Streamlit UI 풀스모크.
>
> **2026-08-09 갱신(세 번째) — 검증도구 4종 갱신 완료.** `ed12b5e` push 확인 후 착수, 계획서
> [`verification_tools_4_refresh_2026-08-09.md`](verification_tools_4_refresh_2026-08-09.md)로
> 진행. 조사 중 계획에 없던 확장(R11 grid 재작성 미반영·FX/문서기본단위 폴백 누락) 발견 →
> 사용자 승인 후 `layer2_forward_cells.py` 전면 재작성까지 포함해 완료. 커밋 `2adae75`+
> `b9e36e9` **push 완료**(`origin/main`=`b9e36e9`). 다음 세션 시작점 = [핸드오프
> `handoff_verification_tools_4_refresh_2026-08-09.md`](../qa/handoff_verification_tools_4_refresh_2026-08-09.md)
> — ① `layer2_note_heading_fix_verify.py` REGRESSED 2건(00121969·00133812) 원인규명(팔로업,
> 우선순위낮음) ② 본류 복귀 = 아래 §5 4~5번(C-1 렌더 확인·Streamlit UI 풀스모크).
>
> **2026-08-09 갱신(네 번째) — §5 4번(C-1 렌더 확인) 진행 중 std_v3 DQ/period_end/shares_out
> 전량NULL 발견→해소 완료, 트랙 종료.** [`std_v3_dq_shares_period_backfill_plan_2026-08-09.md`](std_v3_dq_shares_period_backfill_plan_2026-08-09.md)
> 참고(§4 최신 항목). Phase1~4 전부 완료 — 스크리너 모집단 1,852→2,520개사 정확 회복, `docs/
> PARSING_RULES.md` R12 신설. **커밋 완료**: 브랜치 `fix/std-v3-dq-period-shares-backfill`
> 커밋 `4f57576`(main 아님 — default 브랜치 직커밋 금지 정책, main 머지·push는 미실행).
> **다음 세션 시작점**(전부 [`..._todo_2026-08-09.md`](std_v3_dq_shares_period_backfill_todo_2026-08-09.md)
> "잔여 작업" 절에 상세 기록): ① main 머지·push 여부 결정 ② 부수발견 2건 원인규명(제주은행
> 별도 자산=부채 항등식 위반·삼성증권 FY2025 net_income NULL, 둘 다 combine 레이어 기존결함
> 추정) ③ `layer2_note_heading_fix_verify.py` REGRESSED 2건 원인규명(여전히 유효) ④ C-1
> 렌더 확인 재개(데이터 정상화로 재개 가능) ⑤ Streamlit UI 풀스모크.
>
> **2026-08-09 갱신(다섯 번째, 같은 날 후속 세션) — 부수발견 2건 ①②(제주은행/기업은행 신탁계정
> 오귀속·삼성증권 등 119개사 net_income 폴백 누락) 원인규명+수정+검증 전부 완료, 트랙 종료.**
> `fin2/layer3/combine.py`에 `_trust_account_table_seqs`(신탁계정 좁은 신호 배제) +
> `is.net_income` 폴백 신설. **교훈**: 처음 "table_seq=0 우선" 일반규칙을 시도했다가 검증 중
> 네오셈(01170865)에서 정반대 사례를 발견해 회귀 직전 되돌리고 훨씬 좁은 신호로 재구현 — 상세는
> [[std-v3-side-findings-trust-account-net-income-2026-08-09]]. 영향 119개사(9,734행)만 scoped
> rebuild(254초, `--all` 62분 불필요 — enrichment가 건드린 컬럼을 전혀 참조하지 않음을 코드검토+
> 전수대조로 확인). 항등식 위반 41→0행, net_income NULL 470/119개사→0/0. main 커밋 `9dd4851`.
> **다음 세션 최우선 액션 = push 여부 결정**(로컬 main이 origin 대비 `d707a03`+`9dd4851` 2커밋
> 앞섬, 사용자가 이번 세션엔 보류 선택). 그다음 본류 §5 4~5번(C-1 렌더 확인·Streamlit 풀스모크),
> 그다음 ③(REGRESSED 2건, 우선순위 낮음).
>
> **2026-08-09 갱신(여섯 번째, 같은 날 후속 세션) — push 결정 + ③ REGRESSED 2건 원인규명 모두
> 완료, 본류 재개 준비 끝.** ① push: 위 2커밋 + 문서갱신(`cc03326`) 그대로 origin에 push.
> ② `layer2_note_heading_fix_verify.py`의 `00121969`·`00133812` REGRESSED — 원인은 이 검증
> 스크립트가 `etree.parse(recover=True)`로 원문을 **직접** 파싱해, 운영 파이프라인
> (`parser/xml/dart_xml_parser._parse_xml_file`)이 적용하는 `sanitize_dart_xml()` 이스케이프
> 복구를 건너뛰고 있었던 것. 두 필링 모두 원문에 실제 마크업 결함(미이스케이프 `&`, 깨진 속성
> 따옴표)이 있어, sanitize 없이 recover 모드로 파싱하면 뒷부분 구조가 통째로 유실됨
> (00133812: 주석 39~44번 전체 소실) → DB 베이스라인과 어긋나 REGRESSED 오탐. **운영
> 파이프라인·DB 데이터는 처음부터 문제 없었음**(소급 조치 불필요) — 스크립트만 `_parse_xml_file`
> 로 교체해 수정. 재검증: 두 필링 UNCHANGED 전환, 150개사 재표본(n=265) REGRESSED/PARSE_ERROR
> 0건. 커밋 `482abce`, **push 완료**(origin/main과 완전 동기화, ahead/behind 0).
> **다음 세션 시작점 = 본류 §5 4~5번만 남음**(C-1 렌더 확인 → Streamlit UI 풀스모크). 팔로업
> 트랙은 전부 종료.
>
> **2026-08-09 갱신(일곱 번째, 같은 날 후속 세션) — §5 4~5번(C-1 렌더 확인·Streamlit 풀스모크)
> 완료, 재설계 본류(브리지 swap 트랙) 전체 종료.** 상세는
> [`layer3_v3_bridge_swap_2026-07-25.md`](layer3_v3_bridge_swap_2026-07-25.md) 맨 아래 갱신 블록.
> 요약: `industry_lines`를 직접 소비하는 UI는 아직 없음(향후 별도 작업)이나, "C-1 자동성립"의
> 핵심인 **뷰의 조립 `revenue`를 tearsheet·스크리너가 그대로 읽어 자동 정정되는 것**은 headless
> (bank·insurance·securities·credit_finance·revenue=NULL 오버라이드·비금융 baseline 6종) +
> 실제 브라우저(Streamlit 기동, Claude in Chrome) 양쪽에서 크래시 0건·수치 완전일치로 확인.
> **다음 세션 시작점 = §7 후속 트랙**(pre-2015 2차 패스로 std_v2 UNION 제거·v3-native 품질게이트로
> face_audit v2 의존 제거·데일리 파이프라인 배선·v2 폐기) — 우선순위는 다음 세션에 사용자와 결정.
>
> **2026-08-10 갱신 — 후속 트랙 중 "pre-2015 2차 패스" 계획 초안 작성.**
> [`pre2015_layer2_backfill_plan_2026-08-10.md`](pre2015_layer2_backfill_plan_2026-08-10.md)
> (+ 실행 체크리스트 [`pre2015_layer2_backfill_todo_2026-08-10.md`](pre2015_layer2_backfill_todo_2026-08-10.md)).
> DB 직접 쿼리로 스코프 갱신(과거 추정 70,374건 → **XML 79,283건·활성 1,551개사**, PDF-only
> 1,405건은 별도 3차 트랙으로 분리, 상장폐지 8개사는 유니버스 헌장상 제외) + FY1999 샘플
> 원문 직접 대조로 구조 실측(SECTION-2/TITLE 골격은 유지되나 연결/별도 구분이 리프 TITLE이
> 아니라 상위 헤딩 계층에 있음을 확인 — "신규 파서 필요" 판단은 유효, 단 "완전히 다른 포맷"은
> 아님). **설계 초안만 완료, 실행요청 대기**(정책상 자동 실행 금지) — Phase 1(구조 실측, 밀린
> T4 부활)부터 사용자 승인 필요.
>
> **2026-08-10 갱신(같은 날 두 번째) — 사용자 결정(Q1=K-GAAP 표 포함·Q2=상장폐지 제외·Q3=Phase1
> 먼저) 후 Phase 1(층화표본 188건, 읽기전용) 실행.** 인코딩은 기존 인프라가 완전히 커버(추가
> 작업 불요, 188/188 파싱 성공). **★신규 발견**: 1999~2011은 SECTION-2/TITLE 계층 유지되나
> 2012~2014 표본(SUN&L FY2013 원문대조 확인)은 표제가 TITLE이 아니라 문단 내 굵은
> `<SPAN>` 인라인 마크업 — 데이터는 있으나 TITLE 기반 검출이 전혀 못 찾음. 즉 "K-GAAP구서식
> vs 2015+신서식" 이분법이 아니라 **최소 3세대**(TITLE계층형/SPAN인라인형/2015+현행형)일
> 가능성. 경계 연도 미확정. 상세 = [`pre2015_structure_probe_2026-08-10.md`](../qa/pre2015_structure_probe_2026-08-10.md).
> **Phase 1 "완료" 대신 사용자 확인 요청 상태**(계획서 원 범위를 넘어선 신규 발견 때문) — 후속
> 표본으로 경계를 좁힐지 여기서 판단할지 다음 세션 결정 필요.
>
> **2026-08-10 갱신(같은 날 세 번째) — 사용자 승인으로 후속 표본 2라운드 추가 실행, Phase 1
> 완료.** ①밀도표본(연도당 15건, 2004~2014)으로 경계 확정: 1999~2009 TITLE 100% 유지,
> **FY2011부터 TITLE 완전 소멸**. ②SPAN 가설은 부분원인뿐임을 발견(2011~2014 다수는
> 태그 없는 평문 라벨, 제출대행사별 마크업 상이) → 전략 전환: 계정 라벨(자산총계/당기순이익/
> 영업활동으로 인한 현금흐름)로 표를 먼저 찾고 근접 평문에서 연결/별도만 읽는 "앵커 기반"
> 방식으로 3차 표본(48건) 실행 → **CF 91%(52/57) 적중**, hop거리 4~6으로 매우 안정적.
> BS/IS는 요약블록(SPAN)과 본문(평문) 두 계층이 섞여 적중률 낮음(46%/18%, 구분규칙 미확정).
> 산출물 3종: [`pre2015_structure_probe`](../qa/pre2015_structure_probe_2026-08-10.md)·
> [`pre2015_span_boundary_probe`](../qa/pre2015_span_boundary_probe_2026-08-10.md)·
> [`pre2015_label_pattern_probe`](../qa/pre2015_label_pattern_probe_2026-08-10.md)(전부
> 2026-08-10). **Phase 2(파서 설계) 착수는 별도 승인 대기** — 제안 방향은 연도 분기
> 라우팅(TITLE 1999~2009 / 앵커기반 2011~2014) + CF부터 pilot.
>
> **2026-08-10 갱신(같은 날 네 번째) — Phase 2(파서 설계) 완료.** 원문·프로덕션 함수 직접
> 실행(무변경)으로 근본원인 재규명: 병목은 TITLE 유무가 아니라 `assign_tables_to_dart_
> sections`/`iter_section_elements`가 중첩 SECTION 하위표제("가.대차대조표")에서 **즉시
> 리셋**하는 결함 — 1999~2008 실측 **0%**(2011~2014 는 반대로 이미 100%, 우연히 이 결함을
> 피해감). 수정 프로토타입(신규모듈, 기존함수 무변경)으로 2004~2007 annual 8/8=100% 회복
> 검증. 결정 4가지(§2-1~2-4): 신규모듈+연도라우팅(기존함수 무변경) · K-GAAP전용표 포함(신규
> 코드 APPR, DB마이그레이션 불요) · table_extractor/단위판정 전량 재사용. 설계문서 =
> [`pre2015_layer2_backfill_phase2_design_2026-08-10.md`](pre2015_layer2_backfill_phase2_design_2026-08-10.md).
>
> **2026-08-10 갱신(같은 날 다섯 번째) — 사용자 승인으로 Phase 3(구현) 착수+완료.** 신규
> 모듈 `fin2/extract/legacy_pre2015.py`(3함수) + `report_lines.py` 라우팅(`report_fiscal_
> year<=2010`, 섹션코드 단위 병합 — canary 로 문서단위 all-or-nothing 폴백의 손해를 발견해
> 교체) + `SECTION_CODE_OF`/`_SECTION_META` APPR 가산. 프로덕션 함수로 실측(188건, 1999~2014,
> DB 미기록) — **2004~2008 BS/IS/CF 회복 재확인**(설계문서 프로토타입과 일치), 회귀 테스트
> 12건 신설, `pytest tests/ fin2/tests/` 전체 통과(무관 기존 실패 1건 제외), 2015+ 소비
> 경로 무변경·Gate B 무영향 확인. 잔여 미해결(2009~2010 전환기·1999~2000·2008년 APPR 급락)
> 은 설계 단계부터 Phase3 범위 밖으로 이관 예정이었던 항목 그대로 미해결. 상세 =
> [`pre2015_phase3_canary_verify_2026-08-10.md`](../qa/pre2015_phase3_canary_verify_2026-08-10.md).
> **다음 = Phase 4(파일럿 백필, DB 기록 시작) 착수 여부 — 별도 승인 필요**(체크리스트
> [`pre2015_layer2_backfill_todo_2026-08-10.md`](pre2015_layer2_backfill_todo_2026-08-10.md)).
>
> **2026-08-10 갱신(같은 날 여섯~아홉 번째) — Phase 4(파일럿 백필+검증) 실행, 사용자
> 승인으로 DB 기록 시작.** 26개 활성 corp(1999~2014, 2,032건) 실제 적재 — 오류 0. 실패율
> 20.7%는 대부분 설명됨(원본손상 5.3%·원문에 재무제표 섹션 자체 없음 11.7%·설계단계부터
> 예정된 잔여 3.7%) → Phase3 신규모듈 자체는 건전 재확인. BS 항등식(자산=부채+자본) 검증
> 중 **공용코드 버그 발견+수정**: 일부 K-GAAP filer 의 `(-)N` 비표준 금액표기가
> `parser/common/amount_normalizer.py::parse_amount` 와 `parser/xml/table_extractor.py::
> _NUMBER_PATTERN` **두 게이트 모두**를 막아 전기값이 당기열로 밀려들어감(연도무관 공용
> 코드, 2015+ 에도 이론상 영향권 — 둘 다 고쳐야 실제로 값이 바뀜을 재적재로 직접 확인).
> 위반 45→40건 감소. **잔여 34건(주로 KG케미칼)은 다른 패턴**(부채총계 당기열만 괄호 관례)
> 이라 R0 원칙상 부호를 추론해 고치지 않고, 대신 `fin2/audit/line_anomaly.py::detect_bs_
> identity_anomalies` 신설(SCE↔BS 교차대조와 같은 원칙 — 값은 안 고치고 표시만) 로 안전망
> 확보·검증 완료(파일럿에서 134건 신규 이상치, KG케미칼 케이스 정확히 SIGN/high 로 잡힘).
> `pytest tests/ fin2/tests/` 전체 통과(471 passed, 무관 기존 실패 1건 제외). 상세 =
> [`pre2015_phase4_pilot_verify_2026-08-10.md`](../qa/pre2015_phase4_pilot_verify_2026-08-10.md).
> **Phase5(전량 백필 81,660건) 실행 명령 준비 완료, 사용자가 별도 터미널에서 직접 실행
> 예정**(`load_report_lines.py --fy-min 1999 --fy-max 2014 --active-only`, 신설된
> `--active-only` 로 Q2 결정=상장폐지 8개사 제외 반영) — **다음 세션 시작점 = 실행 결과
> 확인**(체크리스트 [`pre2015_layer2_backfill_todo_2026-08-10.md`](pre2015_layer2_backfill_todo_2026-08-10.md)
> "Phase 5" 절) → Phase6(파이프라인 편입·문서화) → Phase7(std_v3 백필, 별도 승인).
> **미커밋 상태**(사용자가 다음 세션과 함께 커밋하기로 결정).
>
> **2026-08-11 갱신 — Phase5(전량백필) 결과 확인 + Phase6(파이프라인 편입) 전부 완료.**
> 사용자가 별도 터미널에서 Phase5 실행 완료(`load_report_lines.py --fy-min 1999 --fy-max
> 2014 --active-only`, 5.32시간) → 이번 세션에서 DB 직접검증: err0, 대상 82,005건 중
> 81,660건(99.6%) done · report_lines 22.2M행, 상장폐지 8개사 정상제외(0행), **BS 항등식
> 전수검사 98.8% 성립**(52,343건). 큰폭 위반 346건 중 179건(51.7%)이 이상치안전망
> (`bs_identity_confirmed`/`SIGN`/`high`)에 정상 포착됨을 원문 5건 대조로 확인 — KG케미칼
> 국한이 아니라 63개사(동남합성·HLB파나진·에스엠벡셀 등)에서 재현, 안전망이 스케일에서도
> 정상 동작. **새 결함 없음, Phase5 완료 판정.**
>
> **Phase6(파이프라인 편입) — ★배선 갭 발견+수정**: 6-1 두 call site 확인 중
> `collector/note_lines_sync.py`(`scripts/collect_new.py`의 두 call site가 공유하는 데일리
> 진입점)의 `FY_MIN`이 여전히 2015로 남아있어, `extract_report_lines()` 자체는 pre-2015를
> 처리할 수 있는데도 **데일리 경로가 pre-2015 filing을 영영 못 보는 상태**였음을 발견(전량
> 백필은 배치 스크립트 수동 실행으로만 커버되고 있었음). 실측 확인: KG케미칼 rcept
> `20120330001058`의 report_lines를 지우고 옛 기본값(2015)으로 데일리와 같은 진입점
> (`sync_layer2_lines`)을 호출하니 0행(갭 재현) → `FY_MIN` 을 1999로 낮추자 696행 정상
> 복원. 향후 corp 재상장·기재정정 등으로 pre-2015 구간이 재수집되는 경우를 대비. 6-2
> `docs/PARSING_RULES.md` R13 신설(+ T20/T21 함정 카탈로그 추가) · 6-3 `pytest tests/
> fin2/tests/` 471 passed(무관 기존 실패 1건 그대로, Gate B는 `note_lines_sync.py`/`FY_MIN`을
> 참조하지 않아 무영향) · 6-4 이 문서 §2/§3/§5 갱신(지금). **Phase6 완료.**
>
> **다음 세션 시작점 = Phase7(std_v3 백필, 별도 승인 필요)** — `fin2/layer3/build.py`로
> pre-2015 corp-year를 std_v3에 반영해야 `standard_financials` 뷰의 std_v2 UNION 폴백
> 구간을 제거할 수 있다(이 트랙의 완료 조건, §5 5번). **미커밋 상태 유지**(누적 변경분 다수 —
> `pre2015_layer2_backfill_plan_2026-08-10.md` §7-1~3 참고), 커밋 여부는 다음 세션 판단.
>
> **2026-08-11 갱신(같은 날 두 번째) — "Phase7까지 진행하고 한 번에 커밋해줘" 지시로
> Phase7(std_v3 백필) 완료, 이 트랙 전체 종료. pre-2015 2차 패스 트랙 종료.**
> 7-1: `scripts/build_std_v3.py --all --year-min 1999` — `build_corp()`가 이미 `year_min`을
> 일반 파라미터로 지원해 코드 수정 없이 재사용. 백그라운드 101.4분, 2,525corp·297,429행
> (184,580→+112,849 pre-2015 신규), 오류0.
> **7-2 — ★뷰에서 실제 버그 발견+수정**: `standard_financials` 뷰의 std_v2 분기가
> `s.fiscal_year < 2015 OR NOT EXISTS(...)`로 짜여 있어, std_v3가 pre-2015를 채운 뒤에도
> `fiscal_year<2015`가 무조건 참이라 **std_v2가 계속 UNION ALL 돼 73,574개 corp-period가
> 뷰에서 중복**되고 있었음(매출/자산 등이 사실상 2배로 잡히는 상태 — 손 놓았으면 앱에
> 그대로 노출될 뻔함). 마이그레이션 `2026_08_standard_financials_v3_pre2015_dedup`으로
> OR 조건을 없애고 `NOT EXISTS` 하나로 통일 — 재검증: 뷰 319,135행·중복 0. **G1(무손실)
> 재확인**: 기존 std_v2 pre-2015 적격 키 88,915건 전부 새 뷰에 여전히 존재. **G2 표본대조**
> 무작위 15건 중 14건 완전일치, 1건 불일치(EG 00261054)는 원문대조로 v2의 기존 "comparative
> bleed" 결함(1년 뒤 필링에서 비교연도 값이 잘못 유입, 08-09 세션에 이미 확인된 것과 같은
> 클래스)임을 확인 — v3가 정답, 새 결함 아님.
> **7-3(std_v2 폐기)**: 사용자 결정 = **"v2는 지우지 말고 그대로 두자"**. 설계문서 재확인
> 결과 애초에 이 트랙 하나로는 완전 폐기 조건이 안 됨(뷰의 `gate_b_status`가 여전히 v2
> 기반 `face_audit` 의존 — §7 항목2 "v3-native 품질게이트"가 별도 필요). 물리적 삭제는
> 안 함, 이 트랙이 만든 전제조건(뷰 중복 없는 정확한 폴백)까지만 완료 처리.
> `pytest tests/ fin2/tests/` 471 passed(무관 기존 실패 1건 그대로) 재확인.
> **이 문서 §2도 갱신(계층3 행)**. 브랜치 생성 후 Phase1~7 누적 전체를 한 번에 커밋 —
> 상세는 `pre2015_layer2_backfill_todo_2026-08-10.md`(Phase1~7 전부 ☑).
> **다음 세션 시작점 = 마스터허브 §7 후속 트랙 나머지**(v3-native 품질게이트로 face_audit
> v2 의존 제거 → 그 후에야 std_v2 완전 폐기 가능 · 3차 PDF-only 패스 · 야간 잡 재설치 등,
> 우선순위는 다음 세션에 사용자와 결정).
>
> **2026-08-11 갱신(같은 날 세 번째) — §7 후속 1번(v3-native 품질게이트) 조사+계획서 작성.**
> "v2 왜 못 지우나" 질문에서 착수: 원인 확정 — `scripts/gateb_audit.py`(Gate B 감사기, `face_audit`
> 대장을 채우는 유일한 경로)가 `std_financials_v2` 전용으로 하드코딩돼 있고, `standard_financials`
> 뷰는 std_v3 행에도 `gate_b_status`를 **키 조인으로 v2 감사결과를 빌려주는 것**뿐임을 코드+DB
> 실측으로 확정(현재 "pass" 표시 v3 행 243,684건 중 22,935건(9.5%)이 `total_assets` 값 자체는
> v2와 달라 실제로 대조된 적이 없음). 감사 판정 엔진(`fin2/audit/face_audit.py`)은 dict 기반이라
> 재사용 가능 — 문제는 러너 배선과 `face_audit` PK에 버전 구분이 없어 v2/v3 병행 감사 시 서로
> 덮어쓰는 것(신규 `source_version` 컬럼 필요). 설계문서 =
> [`std_v3_native_gate_b_plan_2026-08-11.md`](std_v3_native_gate_b_plan_2026-08-11.md).
> **계획 초안만 완료, 실행요청 대기**(정책상 자동 실행 금지) — Phase 0(구조 확인)부터 사용자
> 승인 필요.
>
> **2026-08-11 갱신(같은 날 네 번째, 세션 마무리) — Phase 0~2 전부 완료, Phase 3(전량 실행)은
> 사용자 터미널에서 진행 중.** Phase 0(구조확인: is_stub/is_discrete·source_rcepts 결측
> 둘 다 걸리는 것 없음) → Phase 1(`face_audit.source_version` 마이그레이션 적용+
> `gateb_audit.py --source v3` 구현, git 무회귀 확인) → Phase 2(원문대조: 22,935건 중
> both_present_differ 11,179건에서 6표본 검증 — **6건 전부 v3가 동등 이상**, 3건은 std_v2
> "comparative bleed" 결함 재확인, 2건은 v3의 최신정정우선 정본선택이 더 정확, 1건은 v3가
> 더 정밀; 부수발견으로 v3 자체의 진짜 라벨매핑 버그 1건도 신규 확정 — trade_payables가
> "장기매입채무및기타채무"에 오매칭). 상세 = [`std_v3_native_gate_b_plan_2026-08-11.md`](std_v3_native_gate_b_plan_2026-08-11.md).
> Phase 3(std_v3 전체 297,429행 감사)를 이 세션이 백그라운드로 시도했으나 47분·97개사
> 진행 후 환경에 의해 강제종료(데이터 손상 없음, 멱등 재개 가능 확인) — 이후 사용자가
> 본인 터미널에서 직접 실행 중(`gateb_audit.py --source v3 --fy-min 1999 --no-line-audit`,
> 진행속도 기준 완료까지 약 15~20시간 예상). **코드 미커밋**(`collector/db.py`·
> `collector/models.py`·`scripts/gateb_audit.py`·계획서, DB엔 마이그레이션만 적용됨).
> **다음 세션 시작점 = 사용자가 전달할 전량 실행 결과 확인 → Phase 4(뷰 JOIN 조건 갱신)**.
>
> **2026-08-12 갱신 — Phase 3 완료 확인 + fail 패턴 원문대조 조사(Phase 3-부록) 완료, 신규
> 제안 §8.** `gateb_v3_full.log`(사용자 터미널, 약 12시간) 확인 — 2,525개사 전량·`err=0`,
> DB 실측(297,429행)과 정확히 일치. 누적 in-scope 일치율 98.1%(pass 197,635/pending
> 96,012/fail_b 2,688/fail_a 1,094). fail을 그냥 숫자로 안 두고 대표사례 원문대조로 3가지
> 서로 다른 버그를 분리: **(A)** revenue fail_b의 93.6%가 증권사·금융지주 집중 — 신영증권
> 실측으로 "금융업 매출정의 차이" 가설 기각, std_v3 concept/context 선택 결함으로 추정
> (메커니즘 미확정). **(B, 신규·중요)** trade_payables fail_a에서 정확히 ×1000 배율 클러스터
> 발견 → 노루페인트 실측으로 **Gate B 감사기 자체가 문서 기본단위(doc_default_unit, R4-1)를
> 안 읽어 발생하는 오탐**임을 확정, 전체 fail_a/b 재스캔으로 규모 확정(fail_a 53건/23개사·
> fail_b 8건/5개사, 합계 28개사 — trade_payables 국지적 문제 아니고 reader 전반 결함).
> **(C)** trade_payables 나머지 ~285건은 00825959류 account_maps 라벨매핑 결함이 반복됨을
> 3개사 추가 확인(코아스/FSN/솔루스첨단소재), 배율이 기업마다 달라 이질적 버그. **결론: Phase
> 4보다 (B) 수정이 먼저인 게 나음**(안 그러면 오탐이 fail_a에 계속 섞임) — 옵션 4개(§8-A~D)
> 정리, **사용자 결정 대기, 코드 미수정**. 상세 = [`std_v3_native_gate_b_plan_2026-08-11.md`](std_v3_native_gate_b_plan_2026-08-11.md) §7 Phase 3-부록 · §8.

**완료(2026-07-25)**: `--recheck` + `build_std_v3 --all` 재빌드 · 금융섹터 revenue census 종결(보험/은행/
증권/여신전문 프로파일 + 잔여 KSIC 프로파일 불필요, 원문대조 PASS) · **브리지 swap enrichment steps 1-2**
(capex/fcf/net_debt v3-native, `d43974e`).

**진행 방향 = 브리지 swap([plan](layer3_v3_bridge_swap_2026-07-25.md)) — 그 선행이 계층2 주석 전사.**
1. **★계층2 주석 전반 전사**([notes plan](layer2_notes_transcription_2026-07-25.md)): `_emit_note_lines`
   활성화(`include_notes=True`)+백필 → 계층3가 D&A/da_total/ebitda(+R&D) 파생. **볼륨(주석=표96%) 실측 선결.**
   파편 note추출기(notes.py·cf_da.py·rd_note.py) 흡수.
2. **계층3 enrichment 완성 + 재빌드**: 주석 반영 후 `build_std_v3 --all`. shares_out 은 계층2 일반현황(별도 테이블) — ✅ 완료(2026-08-09, `report_shares_outstanding`).
3. **뷰 브리지 교체 + G2(v3=원문 기준) + C-1**(자동): tearsheet 금융블록·스크리너 정규화 revenue.
4. **SCE 자본변동 상세**(독립): 계층3 추출 → `sce_equity_movements` → 앱 표출. 설계 = [SCE 문서](sce_equity_movement_detail_2026-07-24.md).
5. **(별도 규모) 계층2 소급 적재**: 2차 pre-2015(브리지 UNION 제거용, ✅ 완료 2026-08-11) ·
   3차 PDF-only — 신규 파서. **설계 초안 작성 완료(2026-08-11)**: 실측 스코프 3,509건
   (pre-2015 1,405+2015+ 2,104, 1,417개사, 기존 적재 0건) + 기존 legacy PDF 코드 2세대
   (`parser/pdf/*`, `fin2/extract/pdf.py`) 재사용성/아키텍처 정합성 검토 완료. 계획 =
   [pdf_only_parser_plan_2026-08-11.md](pdf_only_parser_plan_2026-08-11.md), todo =
   [pdf_only_parser_todo_2026-08-11.md](pdf_only_parser_todo_2026-08-11.md). **실행요청 대기.**

---

## 6. 확정 결정 (잠금)
- **4계층 분리** — 파서=충실전사(판단 없음), 취합=별도 계층 (2026-07-19).
- **★보고서 직접 read = 계층2 전용**: 원문 보고서 파일을 읽어 DB 적재하는 것은 **오직 계층2**(→
  report_lines). 계층3·4·기타 어떤 코드도 보고서를 직접 읽지 않는다 — **검증(원문 대조·감사) 목적만 예외**.
  파생계정(D&A 등)의 소스가 주석이면 **계층2가 주석을 전사**하고 계층3는 report_lines 에서만 읽는다.
  (2026-07-25, 사용자 지침. 위반 예=폐기한 "cf_da.py 를 std_v3 백필".)
  ✅ **위반 해소 완료(2026-08-09)**: `collector/biz_metrics.py`/`collector/order_backlog.py`가
  '사업의 내용' 본문표를 원문 DART XML 에서 직접 read 하던 예외를 없앴다. `biz_section_tables`
  (도메인 컬럼 `production`/`sales`/`catalog`/`order_backlog` 4종 공용)를 계층2 원본 grid
  저장소로 일반화하고, 두 sync 함수를 이 테이블만 읽도록 재작성 — 원문 파일을 여는 지점은
  `fin2/layer2/biz_raw_tables.py::ensure_biz_raw_tables`(온디맨드 계층2 쓰기 가드) 하나뿐이다.
  Phase 0~6(실측→스키마→계층2 신설→계층3 재배선→파이프라인 확인→전량 소급백필→검증) 전부 완료,
  검증 결과: 150개사 표본 전/후 diff `biz_metrics` 568,926행 0건 불일치·`order_backlog` 4,666행 중
  1건만(원문대조로 확인된 무해한 개선, 회귀 아님) · pytest 443 passed(무관 기존결함 1건 그대로) ·
  Gate B 무영향. 상세 = [`biz_content_layer2_migration_2026-08-09.md`](biz_content_layer2_migration_2026-08-09.md)
  (설계) · [`biz_content_layer2_migration_todo_2026-08-09.md`](biz_content_layer2_migration_todo_2026-08-09.md)
  (실행 체크리스트, Phase 0~6 전부 ☑). 남은 것은 Phase 7(마감: 문서 갱신·커밋)뿐.
- **적재순서 = 전량적재 → 계층3** (구 '계층3→전량'을 뒤집음, 2026-07-19).
- **계층3 = 신 체인 단독**: 새 std_v3 빌드 후 swap, 구 체인은 swap 후 제거 (2026-07-22).
- **정본선택·정정 반영 = 계층3 소관**(구 '계층2 4차'에서 이관): 원본 base + 기재정정 델타패치, 값의미=
  as-restated이되 무손실(정정이 안 건드린 셀 보존) (2026-07-22).
- **업종 revenue** (보험·은행=GROSS 합산), **증권=순영업수익 NET**(영업이익+판관비, 시계열 절벽 해소),
  **한국금융지주형=NULL**. 섹터별 census 로 확정 — 상세·잔여는 [금융섹터 revenue 표준](financial_sector_revenue_standards.md) (2026-07-24).
- **계층4 = Path A**: std_v3 직접소비(사이드채널 없음). 앱 비사용·std_v2 교차검증용 (2026-07-24).
- **SCE 적재 유지**: 역할 = 주주환원 '1차 출처'(gap-fill이 대체) 아님 → **자본변동 상세 분해**(성분×
  변동사유 매트릭스, 신규 테이블 `sce_equity_movements` → 앱 표출). 헤드라인은 gap-fill (2026-07-24).
