# TODO — 계층2 pre-2015 2차 패스 실행 체크리스트 (2026-08-10)

> 설계 = [`pre2015_layer2_backfill_plan_2026-08-10.md`](pre2015_layer2_backfill_plan_2026-08-10.md)
> (설계 초안, 사용자 승인 대기). 마스터 허브 = [rearchitecture_4layer.md](rearchitecture_4layer.md).
> 상태표기: ☐ todo · ◐ 진행중 · ☑ 완료. **이 문서는 계획일 뿐 — 실행은 별도 승인 후 착수.**
> [파서/로더 파이프라인 편입 절차](../runbook_new_parser_pipeline_integration.md)를 Phase 6에 그대로 적용.

---

## 사전 결정 필요 (Phase 1 착수 전, 계획서 §6 참고) — ☑ 2026-08-10 사용자 결정
- ☑ Q1. K-GAAP 전용 표(이익잉여금처분계산서/결손금처리계산서) — **포함**
- ☑ Q2. 상장폐지 8개 corp의 pre-2015분 — **제외**(기본안 그대로)
- ☑ Q3. 승인 단위 — **Phase 1만 먼저 실행, 결과 보고 후 재확인 요청**(전체 일괄승인 아님)

---

## Phase 1 — 구조 정밀 실측 (읽기 전용, T4 부활+확장) — ☑ 완료(2026-08-10, 3라운드)
- ☑ 1-1. 층화 표본 설계: 1999~2014(16개년) × report_type(annual/half/quarter) × 4건/스트라텀
  = 188건. 스크립트 = `scripts/probe_pre2015_structure.py`(읽기 전용, DB/report_lines 미변경)
- ☑ 1-2. 인코딩 실측 완료 — EUC-KR 78.7%·UTF-8 21.3%, 188/188 파싱 성공(오류 0).
  **기존 `_parse_xml_file`/`_detect_xml_encoding` 폴백이 이미 전량 커버 — 추가 작업 불요**
  (계획서 §3의 인코딩 우려는 기우였음이 확인됨)
- ☑ 1-3. TITLE 계층 구조 스냅샷 — **경계 확정**: 1999~2009 SECTION-2/TITLE 100% 유지,
  **FY2010 과도기, FY2011부터 TITLE 완전 소멸**(`pre2015_span_boundary_probe_2026-08-10.md`).
  K-GAAP 전용 표 61.2%(115/188)는 TITLE 구간에서만 발견. 2011~2014 다수(SPAN도 아닌
  케이스, BS 기준 87%)는 3차 표본(`pre2015_label_pattern_probe_2026-08-10.md`, 계정
  라벨앵커 방식으로 전환)에서 규명: **CF 91%(52/57) 적중 — "연결 현금흐름표"/"현금흐름표"
  평문 텍스트가 표 4~6엘리먼트 앞에 안정적으로 위치**(태그·번호매김 없음). BS/IS는
  요약블록(SPAN, hop 2~3)과 본문(평문, hop 4~5) 두 계층이 섞여 적중률이 낮음(46%/18%,
  구분 규칙은 미확정). **Phase 2 설계 방향 도출**: 계정라벨 앵커 전략을 CF부터 pilot,
  TITLE(1999~2009)/앵커(2011~2014) 연도 분기 라우팅 제안 — 상세 = 위 세 문서
- ☑ 1-4. 본문 TABLE ROWSPAN/COLSPAN 사용 확인(2004~2008년 표본 75%) — 기존 R11
  `expand_table_grid` 재사용 가능성 높음(정밀 검증은 Phase 2)
- ☑ 1-5. 단위 선언 표기(`단위 : 원`/`단위 : 천원`) 확인 — 현재 `text.declared_unit` 패턴과
  큰 차이 없어 보임(정밀 검증은 Phase 2)
- ☑ 1-6. K-GAAP 전용 표 출현 빈도 61.2%(115/188) 집계 완료
- ☑ 1-7. 산출물 작성 완료 = [`docs/qa/pre2015_structure_probe_2026-08-10.md`](../qa/pre2015_structure_probe_2026-08-10.md)
- **게이트**: 이 Phase 완료+보고 없이 Phase 2 착수 금지. 사용자 승인 하에 3라운드(층화188건
  → 밀도165건 → 앵커기반48건)까지 진행, 경계(FY2011)와 2011~2014 구간의 실사용 가능한
  탐지 전략(계정라벨 앵커, CF 91% 적중)까지 확보 — **Phase 1 완료로 판단, Phase 2 착수는
  별도 승인 대기**.

## Phase 2 — 파서 설계 — ☑ 설계 완료(2026-08-10), 승인 대기
- ☑ 2-1. **결정: 기존 함수(`assign_tables_to_dart_sections`/`iter_section_elements`) 무변경,
  신규 모듈**(깊이인식 경계walk + 확장 분류기, 연도 라우팅). 근거: 원문 실측으로 근본원인
  확정(중첩 SECTION 하위표제에서 즉시 리셋되는 기존 결함) + 수정 프로토타입 검증(2004~2007
  annual 8/8=100%).
- ☑ 2-2. **결정: 포함, 신규 코드 `APPR`**(사전결정 Q1과 일치). DB 마이그레이션 불요(`statement`
  컬럼 CHECK 제약 없음, 실측 확인). 2008년 급락 원인은 Phase 3 후속(§3-2).
- ☑ 2-3. **결정: `table_extractor.py` 수정 없이 전량 재사용**(TU 셀·ROWSPAN/COLSPAN 프로토타입
  검증 완료).
- ☑ 2-4. **결정: 단위 판정(`declared_unit`) 수정 없이 전량 재사용**(K-GAAP TABLE-GROUP 구조상
  단위 선언이 직전 형제 메타표에 위치 — 기존 가정과 일치, 원문 확인).
- ☑ 2-5. 설계 문서 작성 완료 = [`pre2015_layer2_backfill_phase2_design_2026-08-10.md`](pre2015_layer2_backfill_phase2_design_2026-08-10.md).
  **사용자 승인 대기 — Phase 3(구현) 착수는 별도 승인 필요.**
- **잔여 미해결(설계 문서 §3, Phase 3로 이관)**: 1999~2003 half/quarter 저조(네 번째 구조 변종,
  앵커 폴백 필요) · 2008년 APPR 급락 원인 미규명 · 2009~2010 전환기 라우팅 순서(신규경로 우선,
  빈 결과 시 기존 2015+ 경로 폴백) · 1999~2003 전반 표본 재확대 필요.

## Phase 3 — 구현 + 단위 테스트 — ☑ 완료(2026-08-10)
- ☑ 3-1. Phase 2 설계 구현 — 신규 모듈 `fin2/extract/legacy_pre2015.py`(3함수: `iter_section_
  span_depth_aware`·`classify_pre2015_statement_heading`·`detect_pre2015_body_statement_
  tables`) + `report_lines.py::extract_report_lines` 라우팅(`report_fiscal_year<=2010` 게이트,
  섹션코드 단위 병합 — 문서 단위 all-or-nothing 폴백은 canary 로 손해 확인돼 교체) +
  `SECTION_CODE_OF`/`_SECTION_META` 에 `APPR_C`/`APPR_S` 가산(DB 마이그레이션 불요, 실측
  재확인). 2015+ 소비 경로는 한 줄도 안 건드림.
- ☑ 3-2. 카나리아(188건, 1999~2014, 1999~2003 은 20건 확대) `extract_report_lines()` 직접
  호출 실측(읽기전용, DB 미기록) + 신규 회귀 테스트 12건(`fin2/tests/test_pre2015_legacy_
  layout.py`) + `pytest tests/ fin2/tests/` 전체 통과(455 passed, 무관 기존 실패 1건은
  트랙 착수 전부터 main 에 존재) + Gate B 무영향 확인(독립 `_TEXT_SECTION_META` 라 미참조).
  결과·잔여 미해결 상세 = [`pre2015_phase3_canary_verify_2026-08-10.md`](../qa/pre2015_phase3_canary_verify_2026-08-10.md)
  — 2004~2008 BS/IS/CF 회복(설계문서 프로토타입과 일치), 2009~2010/1999~2000/2008 APPR 은
  잔여항목①②③④ 그대로 미해결(Phase3 범위 밖으로 이관, 설계 단계부터 예정됐던 것과 동일).

## Phase 4 — 파일럿 백필 + 검증 — ◐ 실행 완료, 발견사항 보고 후 사용자 판단 대기(2026-08-10)
- ☑ 4-1. 표본 26개사(필링수 상위18+무작위8, 활성유니버스) 1999~2014 전체 filing 파일럿
  적재 완료. `load_report_lines.py`에 `--fy-min`/`--fy-max` 신설(기존 2015+ 기본동작 무변경)
  해 재사용 — 2,032건, 오류0, report_lines 576,684행.
- ☑ 4-2. BS 항등식(자산=부채+자본) 검사(1,188건 깨끗한 표본) — 96.6% 성립. **34건(2.9%,
  4개사 집중·KG케미칼이 31건) 실질 위반 발견 → 근본원인 규명**: 연도무관 공용 컬럼압축
  로직(`_emit_section_lines`)이 비표준 금액표기(`(-)N`)를 파싱실패로 처리 → 전기값이 당기
  열로 밀려 들어감. **Phase3 신규모듈 결함 아님**(공용 코드, 이번 트랙 미수정 영역) — 기존
  이상치탐지도 미포착. 상세 = [`pre2015_phase4_pilot_verify_2026-08-10.md`](../qa/pre2015_phase4_pilot_verify_2026-08-10.md).
- ☑ 4-3. 실패율 측정 — 0행 420/2,032(20.7%) 원문대조로 3버킷 분류: corrupted(5.3%, 원본
  손상·우리문제아님) · no_fs_section(11.7%, 절단 또는 요약전용 정상문서) · 진짜잔여갭(3.7%,
  설계단계부터 예정된 범위와 일치). **Phase3 자체는 건전, 새 결함 없음.**
- ☑ 버그 수정 완료(2026-08-10, 사용자 승인) — 2곳 수정 필요했음: `parse_amount`(값 해석)
  + `table_extractor._NUMBER_PATTERN`(그보다 먼저 도는 게이트, 하나만 고치면 무효였음을
  재적재로 직접 확인). 회귀테스트 9건, pytest 전체통과, 파일럿 재적재(오류0) 후 재검증
  — 항등식 위반 45→40건 감소. **잔여 34건은 다른 원인**(KG케미칼 전 filing의 "부채총계
  당기열만 괄호" 반복 패턴 — 결합행은 항상 정확해 진짜 부호는 양수로 추정되나, 원문만으론
  확정 불가) → **R0 원칙상 의도적 미수정**(부호 뒤집기는 계층2 범위 밖 판단). 상세 =
  `pre2015_phase4_pilot_verify_2026-08-10.md` §3~4.
- ☑ 이상치 탐지 보강 완료(2026-08-10, 사용자 요청 — Phase5 전제조건) — `fin2/audit/
  line_anomaly.py::detect_bs_identity_anomalies` 신설(BS 항등식 위반 표시, 값은 안 고침
  — SCE↔BS 교차대조와 같은 원칙). 회귀테스트7건, pytest 전체통과(471 passed). 파일럿
  재적재로 검증: KG케미칼 케이스 정확히 `bs_identity_confirmed`/`SIGN`/high/제안값 일치로
  잡힘, 파일럿 전체 신규 이상치 134건. 상세 = `pre2015_phase4_pilot_verify_2026-08-10.md` §4.
- **다음 액션**: Phase5(전량백필 81,660건, 파일럿의 약 40배·추정 5시간대) 착수 — 사용자가
  "직접 타단에서 실행"으로 방식 확정. `--active-only` 플래그 신설(Q2 결정=상장폐지 8개사
  제외를 반영, 기본 끔이라 기존 2015+ 동작 무변경) + `--status`에 pre-2015 진행 블록 추가.
  아래 Phase5 실행 명령 참고 — **다음 세션 시작점 = 사용자가 실행한 결과 확인**.

## Phase 5 — 전량 백필 (81,660건, 실측 갱신 — 원 추정 79,283건에서 유니버스 드리프트 반영)
— ☑ 완료(2026-08-10, 사용자가 별도 터미널에서 실행 · 2026-08-11 세션에서 결과 검증)

```bash
cd /Users/taejin/Project/tj_finance
source .venv/bin/activate
caffeinate -i nohup python scripts/load_report_lines.py \
  --fy-min 1999 --fy-max 2014 --active-only \
  > /tmp/pre2015_phase5_backfill.log 2>&1 &
```

- ☑ 5-1. 실행 완료 — 로그 SUCCESS: `[load-lines all] 완료 5.32h — done 79,628 / skip 0 /
  error 0 · report_lines 21,587,652행 · 이상치 3,947건`(ERROR grep 0건 재확인). `--status`
  pre-2015 블록: 대상 82,005 중 done 81,660(99.6%, 파일럿 2,032 + 이번 79,628 신규
  = 정확히 일치), report_lines 22,179,789행.
- ☑ 5-2. DB 직접 교차검증(2026-08-11) — target(filed_at<2015·active·xml·completed)=
  79,283건과 정합. 상장폐지 8개사 pre-2015분 = report_lines 0행(제외 정상 동작 확인).
  report_lines 보유 filing 64,148/79,283(80.9%) — 나머지는 "본문 섹션 없음→보류"
  (Phase4-3에서 이미 버킷 분류된 정상 결측 패턴과 일치, 신규 결함 아님). **BS 항등식
  전수 검사**(자산/부채/자본 3종 모두 있는 52,343개 rcept×basis×col) = **98.8% 성립**
  (파일럿 96.6%→버그수정후보다도 양호, 전체 확대 후에도 안정). 위반 606건 중 이상치
  테이블(`bs_identity_confirmed`, `SIGN`/`high`)에 정확히 잡힌 167건을 무작위 5건 원문
  수치 대조 — 전부 "부채총계 부호반전 + 부채와자본총계 결합행이 자산과 일치"패턴으로
  확정판정 근거 확인(KG케미칼과 같은 클래스가 동남합성·HLB파나진·에스엠벡셀 등 다른
  회사에서도 재현됨을 확인, 안전망이 스케일에서도 정상 동작). 잔여 위반(원단위 반올림
  소액 18건 + 확정불가라 low 신뢰도로만 표시된 OTHER 다수)은 설계대로 R0 원칙상 값
  미수정·표시만 — 신규 결함 아님. **Phase5 완료로 판단.**

## Phase 6 — 파이프라인 편입 + 문서화 (필수) — ☑ 완료(2026-08-11)
- ☑ 6-1. **두 call site 배선 확인 — ★갭 발견+수정**. `scripts/collect_new.py`의 두 call site
  (메인 ④-3 · `--standardize-only` 재개)는 둘 다 `_sync_layer2_lines()` → `collector/
  note_lines_sync.py::sync_layer2_lines()`라는 **같은 하나의 진입점**을 공유하는데, 이 모듈의
  `FY_MIN`이 여전히 2015로 남아있어 `f.fiscal_year>=2015` 로 대상을 걸러 **데일리 경로가
  pre-2015 filing을 영영 못 보는 상태**였다(`extract_report_lines()` 자체는 이미 pre-2015를
  처리하는데도). 실측 확인: KG케미칼(00101220) rcept `20120330001058`의 report_lines를
  지우고 옛 기본값(2015)으로 `sync_layer2_lines`를 호출하니 0행(갭 재현) → `FY_MIN`을 1999로
  낮추자(코드 수정) 모듈 기본값만으로 696행 정상 복원(수동 override 없이). 두 call site가
  같은 함수를 공유하므로 이 한 줄 수정으로 둘 다 해소.
- ☑ 6-2. `docs/PARSING_RULES.md` R13 신설(연도 라우팅·basis 권위·K-GAAP APPR 코드·데일리
  배선 갭 전부 근거 파일:줄과 함께) + 부록A T20(중첩 하위표제 즉시리셋)·T21(`(-)N` 비표준
  금액표기) 신규 + 부록B 원출처 추가.
- ☑ 6-3. `pytest tests/ fin2/tests/` — 471 passed(무관 기존 실패 1건 `test_biz_section.py::
  test_lxintl_facility_table_dropped`은 이 트랙 착수 전부터 main에 있던 것, 그대로). Gate B
  (`fin2/audit/line_audit.py` 등)는 `note_lines_sync.py`/`FY_MIN`을 전혀 참조하지 않아
  코드상 무영향 확인(grep 0건) — 오늘 변경분이 필터(대상범위)일 뿐 추출로직이 아니라서
  Gate B 영향 경로 자체가 없음.
- ☑ 6-4. `rearchitecture_4layer.md` §2(상태표 계층2 행)·§3(문서맵)·§4(타임라인)·§5(진행블록)
  전부 갱신 완료.

## Phase 7 (후속 트랙, 사용자 승인 "Phase7까지 진행하고 한 번에 커밋해줘") — ☑ 완료(2026-08-11)
- ☑ 7-1. std_v3 백필(`scripts/build_std_v3.py --all --year-min 1999`, `fin2/layer3/build.py::
  build_corp`는 이미 `year_min` 파라미터를 일반적으로 지원해 **코드 수정 없이** 그대로 재사용
  가능했음). 백그라운드 실행 101.4분(6,086초), **2,525corp · 297,429행(184,580→+112,849
  pre-2015 신규) · 오류 0**. pre-2015만 보면 1,603개 corp·112,849행, data_quality 분포
  1(정상) 109,140 · 2(경고) 2,752 · 3(오류) 957(0.85%, BS항등식 등 기존 검증로직이 그대로
  적용된 결과 — report_lines 단계 위반율 1.2%와 정합).
- ☑ 7-2. `standard_financials` 뷰 std_v2 UNION 구간 정리 — ★단순 "제거"가 아니라 **먼저
  실제 버그를 발견**: 뷰의 std_v2 분기가 `s.fiscal_year < 2015 OR NOT EXISTS(...)`로
  짜여 있어, 7-1로 std_v3가 pre-2015를 채운 뒤에도 `fiscal_year<2015` 조건이 무조건 참이라
  **std_v2 쪽이 계속 UNION ALL 돼 corp-period 73,574쌍이 중복행**으로 뷰에 나타나고 있었음
  (적용 전 실측: 뷰 392,709행, 중복 73,574그룹 — 매출·자산 등이 사실상 2배로 잡히는 상태).
  마이그레이션 `2026_08_standard_financials_v3_pre2015_dedup`(`collector/db.py`) 로 그 OR
  조건을 없애고 **`NOT EXISTS` 하나로 통일**(2015+/pre-2015 동일 취급 — std_v3에 없는
  corp-period만 std_v2로 폴백, PDF-only 1,405건 등 이 트랙 스코프 밖도 자동으로 계속
  폴백됨). `init_db()`로 적용, 재검증: 뷰 319,135행·**중복 0**. **G1(무손실) 재확인**:
  기존 std_v2 pre-2015 적격 키(88,915건) 전부 새 뷰에 여전히 존재(0건 소실). pre-2015
  뷰 행 128,190건 중 112,849건은 std_v3(신규)·15,341건은 여전히 std_v2 폴백(std_v3가
  못 채운 잔여, 대부분 예정된 갭). **G2 표본대조**(무작위 15건, v3/v2 둘 다 값 있는
  경우): 14/15 완전일치(diff 0%), 1건 불일치(EG 00261054 FY2012 Q3 연결, v3=726.7억
  vs v2=850.3억) → 원문 대조로 원인규명: v3 소스=`20121114000012`("분기보고서
  2012.09", 그 분기 자신의 정본 filing)·v2 소스=`20131129000055`("분기보고서
  2013.09", **1년 뒤 필링에서 비교연도 열이 잘못 유입** — 08-09 브리지swap 때 이미
  확인된 v2 "comparative bleed" 결함과 같은 클래스, v3가 원문 기준으로 올바름). **새
  결함 아님, v3가 정답.**
- ☑ 7-3. std_v2 폐기 — **사용자 결정: "v2는 지우지 말고 그대로 두자"**(2026-08-11). 설계
  문서(`layer3_v3_bridge_swap_2026-07-25.md` §7) 재확인 결과 이 트랙 하나만으론 완전
  폐기 조건이 애초에 안 됨 — 뷰의 `gate_b_status` 컬럼이 여전히 std_v2 기반 `face_audit`에
  의존 중(§7 항목2 "v3-native 품질게이트"가 별도 후속 트랙으로 남아있어야 함). **물리적
  삭제(테이블 DROP·v2 파이프라인 코드 제거)는 하지 않음** — 이 트랙이 만든 전제조건(뷰
  중복 없는 정확한 UNION 폴백)까지만 완료로 처리. 완전 폐기는 마스터허브 §5 후보 4번
  트랙(v3-native 품질게이트)이 별도로 필요.
- ☑ 검증: `pytest tests/ fin2/tests/` 471 passed(무관 기존 실패 1건 그대로).

**이 트랙(pre-2015 2차 패스) 전체 종료.**
