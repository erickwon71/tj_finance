# 설계 — verification 캠페인을 주석(note_lines)·사업의 내용(biz)으로 확장 (2026-10-27)

> 상태: **P1·P2 완료, P3(biz) 진행 중(2026-10-27 밤)** — 기계 모듈·scope CLI·fix 경로 구현, 전수 기계 패스 가동. 주석(note) 기계 모듈은 미착수. 사용자 결정(2026-10-27): 주석과 사업의 내용 **모두**, **전수 표 대조**.
> 실행은 이 문서를 검토한 뒤 사용자가 별도로 요청할 때 시작한다.
> 선례: `verification_machine_compare_design_2026-09-24.md`(report_lines 기계대조),
> `verification_schema_two_worktree_design_2026-09-24.md`(스키마·두 워크트리), `docs/verification/WORKFLOW.md`.

## 0. 한 줄 요약

report_lines 에서 쓴 "원문 XML ↔ DB 기계대조 → 불일치만 모델이 웹뷰 확인 → 일치는 1% audit" 방식을
note_lines(주석)와 biz_section_tables(사업의 내용)에 확장한다. 대조 단위는 **재무제표 행/셀이 아니라 표(table)** 이고,
계층2 원칙(R0-2, 인쇄된 값만)은 그대로 적용한다.

## 1. 대상과 규모 (2026-10-27 실측, 추정치)

| 대상 | 테이블 | 행 수(추정) | 크기 | 구조 |
|---|---|---|---|---|
| 주석 | `note_lines` | 2억 5,363만 | 94 GB | 평탄화 행: `table_seq`, `col_index`, `col_label`, `header_hint`, `depth`, `node_role`, `value_won`, `value_raw` |
| 주석(표 메타) | `report_tables` | 1,691만 | 6.7 GB | 표 단위 메타 (주석 표 포함 여부는 §6 에서 확인) |
| 사업의 내용 | `biz_section_tables` | 58.6만 | 1.5 GB | **원본 grid 무손실 저장** (계층2 스토어) |
| 사업의 내용(계층3) | `biz_metrics` | 776만 | 2.2 GB | long-format 구조화 값. 계층3 이므로 이번 대조 대상 아님 |
| 기타 | `doc_section_tables` | 103.7만 | 0.8 GB | 문서 섹션 표 (API→문서 전환 테이블의 원천) |

- 대조는 **계층2 저장물 ↔ 원문 XML** 이다. `biz_metrics` 는 계층3 이라 값 해석이 들어가므로 이번에는 보지 않는다(필요 시 별도 트랙).
- 기간은 report_lines 와 같게 **2015+** 로 시작한다.

## 2. 설계 원칙

1. 계층2 = 인쇄된 값만(R0-2). 기계가 "인쇄값과 다른 값이 계층2 에 있다"를 찾는 것이 목적이다. 보정은 계층3.
2. 기계는 **파서 독립**이어야 한다(파서 버그로 양쪽이 같이 틀려 일치하는 것 방지). 그래서 `machine_compare.py` 를 확장하지 않고
   **주석용·사업용 모듈을 따로** 둔다(재무제표 전용 가정: 섹션 제한, 열 선택, 행 정렬, 단위 다수결 등이 주석에서는 맞지 않는다).
3. 거짓 일치보다 거짓 불일치를 택한다(`errs toward mismatch`). 결정 못 하면 모델로 넘긴다.
4. 진행 상태는 전부 `verification` 스키마에 둔다.

## 3. 대조 단위: 표 단위 전수 대조

기계가 원문 XML 의 대상 섹션에서 표를 모두 뽑아 DB 표와 짝짓고, 짝마다 아래를 본다.

| 검사 | 설명 | 결과 종류(`error_types` 후보) |
|---|---|---|
| 표 짝짓기 | 원문 표 ↔ DB 표(`table_seq` / `biz_section_tables` 행). 짝 없으면 | `missing_table`(신규), `extra_table`(신규) |
| 행 수·열 수 | 원문 grid 와 DB 행/열 개수 | `missing_row`, `extra_row` (기존 재사용) |
| 셀 값 | 숫자는 값, 텍스트는 정규화 문자열 비교 | `value_mismatch`, `sign_flip`, `unit_scale` (기존) |
| 라벨·열이름 | 행 라벨, `col_label`, `header_hint` | `label_mismatch` (기존) |
| 표 귀속 | 표가 속한 주석 번호·섹션 경로 | `section_misassign`(신규) |

- 주석: 표 1개가 `note_lines` 의 `(rcept_no, table_seq)` 한 묶음이다. 평탄화(행×열 → 행)를 되돌려 grid 로 비교한다.
- 사업의 내용: `biz_section_tables` 가 grid 를 그대로 저장하므로 grid 대 grid 비교가 가능해 **상대적으로 쉽다**. 이쪽을 먼저 한다.
- 주석에는 서술형 문단도 있다. **표만** 대조하고 서술문은 이번 범위 밖이다(`note_lines` 가 문단을 싣는지는 §6 에서 확인).

## 4. 스키마 변경안 (적용은 승인 후, 러너 STOP 후 `vq.py admin apply-schema`)

1. **scope 확장**: `progress_filings.verified_scopes` / `verified_scope_hashes` 에 `note`, `biz` scope 추가.
   슬롯 상태는 scope 별로 독립이어야 한다(report_lines 는 passed, note 는 pending 가능).
   방법 후보: (a) `progress` 에 scope 컬럼 추가 후 PK 확장, (b) scope 별 별도 progress 테이블. **미결정 — §7 질문 1.**
2. **load_seq 트리거**: `note_lines`(94 GB)와 `biz_section_tables` 에 내용 해시 트리거를 건다.
   94 GB 테이블의 트리거 비용(재적재 시 rcept 단위 delete-then-insert 이므로 문장 단위 트리거는 부적합, 문장 후 통계/트랜잭션 단위 해시)을 먼저 측정한다.
   트리거 없이는 재적재 후 passed 무효화가 동작하지 않는다.
3. **machine_checks**: scope 컬럼 추가(현재 필링 단위 1행 → 필링×scope).
4. **error_types**: 위 신규 코드 3종 추가.
5. 이슈 셀 키: 현재 `(rcept, basis, statement, 계정, 열)`. 표 단위 키 `(rcept, scope, table_seq, 행, 열)` 로 일반화. 같은 셀 재등록 차단(결론난 셀)도 이 키를 쓴다.

## 5. 단계

| 단계 | 내용 | 산출 | 쿼터 영향 |
|---|---|---|---|
| P0 | 이 문서 검토·결정 | — | 없음 |
| P1 | **읽기 전용 표본 측정**: 사업의 내용 표 200개·주석 표 200개를 골라 단순 규칙 기계대조를 시험 구현, 일치율·오탐 유형 집계 | `scratchpad` 측정 결과, 이 문서 §6 갱신 | 없음(모델 미사용) |
| P2 | 스키마 변경 + 트리거 (러너 STOP, 백업 확인 후) | 마이그레이션, 테스트 | 없음 |
| P3 | `biz` 기계 모듈(`fin2/verification/machine_compare_biz.py`) + `vq.py machine run --scope biz` | 모듈, 회귀 테스트 | 없음 |
| P4 | `note` 기계 모듈 | 모듈, 회귀 테스트 | 없음 |
| P5 | 모델 러너 확장: `verify_prompt.md` 에 표 단위 판정표, scope 선택(`runner.model_for`) | 프롬프트, verify_sim A/B | 파일럿 소량 |
| P6 | 2015+ 전수 기계 1회전 → 불일치만 모델 | 결과 보고 | 모델 대기 규모 확인 후 결정 |

- 각 단계 끝에서 멈추고 사용자 확인을 받는다. 특히 P2(스키마)는 CLAUDE.md "되돌리기 어려운 작업"에 해당하므로 08:00~22:00 에는 알리고 대기, 야간에는 승인된 범위만 진행한다.
- 파서/로더가 바뀌면 `docs/runbook_new_parser_pipeline_integration.md`(데일리 두 call site 배선·소급 백필·검증)를 따른다. 이번 트랙은 파서를 바꾸지 않고 **검증만** 늘리므로 발견된 결함의 수정 배치에서 적용한다.

## 6. P1 에서 확인할 열린 사실 (지금은 모름)

1. `note_lines` 가 서술 문단을 싣는가, 표만 싣는가.
2. `report_tables` 가 주석 표의 grid 를 보관하는가(그렇다면 note 대조도 grid 대 grid 가 가능해 훨씬 쉬워진다).
3. 원문 XML 에서 주석 섹션·사업의 내용 섹션을 파서 없이 찾는 단순 규칙이 충분한가(`II. 사업의 내용` 정정본에는 없는 경우가 있다 — `PARSING_RULES.md` 599~609행).
4. 필링당 표 수 분포 → 기계 실행 시간, 모델 대기 추정.
5. 2015+ 필링 수와 정정본 처리(원본·정정본 중 어느 쪽이 최신 소스인지는 섹션마다 다르다).

## 6-1. P1 측정 결과 (2026-10-27 야간, 읽기 전용)

스크립트: `scratchpad/p1_biz_probe.py`, `p1_note_probe.py`(저장소 밖 임시물. P3/P4 에서 `fin2/verification/` 모듈로 새로 작성한다).
원문은 `machine_compare` 와 같은 방식(lxml HTMLParser, 파서 비의존)으로 읽었다.

**사업의 내용 (`biz_section_tables`, 150필링 · 저장 표 2,113개)**

| 결과 | 표 수 | 비율 |
|---|---|---|
| grid 완전 일치 | 2,031 | 96.1% |
| 같은 셀·다른 배치 | 6 | 0.3% |
| 근접(Jaccard ≥ 0.8) | 69 | 3.3% |
| 불일치 | 7 | 0.3% |

- ★**실결함 단서**: 근접 사례의 차이는 모두 **`&` 이하 글자 소실**이다 (원문 `H&B사업본부` → DB `H사업본부`, `군산L&S1기` → `군산L1기`,
  `Micro-valve&stimuli-responsivehydrogel` → `Micro-valvehydrogel`). R224(`&cr;` 뒤 `&amp;` 소실)와 같은 유형이며,
  `fin2/extract/biz_section.py::_load_root` 가 `sanitize_dart_xml` 없이 `recover=True` 로 읽는 것이 원인 후보다. 아직 원인 확정·영향 전수 측정 전.
  계층2 충실도 위반이므로 fix 큐 첫 후보다(수정은 fix 워크트리에서).
- 커버리지: 사업의 내용 섹션의 숫자 표 4,820개 중 1,845개(38%)만 저장된다. 이는 `find_biz_subsections`/카탈로그가
  **고른 표만** 저장하는 설계 때문이다. 이번 결정(전수 표)에 따르면 나머지 62% 는 "저장 안 된 표"이며, 저장 범위를 넓힐지는
  fix 쪽 파서 확장 문제다. 검증으로는 `missing_table` 이슈 유형을 쓰되 **기계가 "대상 표"를 정하는 기준**(예: 숫자 셀 ≥ N개, 표 제목·직전 소제목)을 먼저 정해야 한다 → 사용자 결정 필요.
- 판정: 기계대조 적합성 **높음** (grid 대 grid, 파서 독립 구현 가능).

**주석 (`note_lines`, 60필링 · 값 있는 표 그룹 6,779개)**

| 결과 | 그룹 수 | 비율 |
|---|---|---|
| 유효숫자 다중집합 완전 일치 | 6,440 | 95.0% |
| 근접(≥ 0.8) | 144 | 2.1% |
| 낮음 | 195 | 2.9% |

- 비교는 단위 비의존(유효숫자, 끝 0 제거)이라 단위 오류(unit_scale)는 이 방식으로는 못 잡는다 → 본 구현에서 단위 선언을 같이 비교.
- 낮음·근접 사례를 열어 본 3건은 모두 **원문에는 있는데 DB 에 없는 숫자**였고 DB 에만 있는 값은 없었다.
  외화단위 표(`외화단위: 천USD`)처럼 value_won 이 의도적으로 NULL 인 셀이 섞였을 가능성이 있어, 결함과 설계상 제외를 가르는 규칙이 필요하다(P4).
- 원문 숫자 표 7,484개 중 6,005개(80%)가 DB 그룹과 짝지어졌다. 나머지 20% 는 값 없는 표, 소수점 표(측정에서 제외), 짝짓기 한계가 섞여 있어 P4 에서 분해한다.
- 낮음의 상당수가 2015 필링에 몰려 있다(구형 배치) — 연도별 분해는 P4.
- 판정: 기계대조 적합성 **중상**. 완전 일치율 95% 로 모델에 넘길 불일치 후보는 전체의 약 5% 수준이 될 전망이며, 이 중 설계상 제외를 규칙화하면 더 줄어든다.

**결론**: 전수 표 대조는 현실적이다. 사업의 내용을 먼저 하는 결정이 맞다(저장 구조가 grid 라 구현이 가장 단순하고, 첫 결함 단서가 이미 나왔다).

## 6-3. P3 진행 (biz, 2026-10-27 밤)

구현 (모두 `fin2/verification/`, 테스트 `fin2/tests/test_machine_biz.py` 7건):
- `machine_biz.py` (mb2) — 파서 독립(lxml HTML 파서 + 자체 span 전개)으로 원문 표를 읽고, 저장 표(`biz_section_tables` 행)마다 셀 겹침이 가장 큰 원문 표를 짝지어 grid 를 비교한다. 공백·`&cr;`·빈 칸은 무시. 발견 종류: `cell`·`row_missing`·`row_extra`·`extra_table`. 원문 사업의 내용 섹션의 숫자 표 중 저장 안 된 것은 **세기만** 한다(`unstored_numeric_tables`, 대상 표 기준 미결정 — §6-1).
- `machine_pass_scope.py` — 필링 단위 기계 패스: 지연 베이스라인 → 대조 → `scope_machine_checks` 기록 → clean 이면 필링 passed, 섹션도 저장 표도 없으면 skipped, 나머지는 pending. 원문은 **SD 미러 우선**(NAS stat 이 필링당 0.4초라 분당 40건 → 370건).
- `scope_issues.py` — 발견 → 이슈(scope biz, table_ref=table_ord, 행 라벨+`[r행c열]`). biz 발견은 글자 그대로의 차이라 **기계가 직접 등록**한다. `recheck` 는 재적재된 fixed 이슈를 다시 대조해 일치하면 closed, 아니면 reopened.
- `ops.py` — `fix_queue`/`issues_of_type`/`batch_new` 가 scope 를 가린다(기본 report, 다른 scope 이슈가 report 배치로 쓸려 들어가지 않게), `fix_batches.scope` 컬럼, `batch_reload` 가 scope 로 `_reload_rcept`(report·note) / `_reload_biz`(biz: 계층2 `biz_section_tables` 다시 쓰기 + 계층3 `biz_metrics`·`order_backlog` 재빌드)를 고른다. `withdraw_released`·`recheck_list` 는 아직 report 전용.
- `vq.py scope run|status|show|register|register-all|recheck --scope biz`, `fix-queue|issues|batch new --scope`.

**첫 결과**: 처음 4천 필링에서 mismatch 약 15%, 셀 발견의 99% 가 하나의 원인 — `biz_section._load_root` 가 `sanitize_dart_xml` 없이 읽어 `&`·`<` 뒤 글자가 사라짐 → **R287** 로 수정(규칙 문서 `rules/10_layer2_parse.md`). 두 번째 유형(단위 표의 앞 빈 칸 138쌍)은 값이 아닌 배치 흔적이라 mb2 에서 비교에서 뺐다.

## 7-0. 확정된 결정 (사용자, 2026-10-27 야간)

1. **슬롯 구조 = 별도 progress 테이블**(scope 별). 기존 report_lines 러너·digest 는 건드리지 않는다.
2. **우선순위 = 사업의 내용 먼저**, 주석은 그 뒤.
3. **쿼터가 부족하면 report_lines 우선.** note/biz 모델 확인은 report_lines 모델 대기분 뒤로 간다(기계 단계는 제한 없음).
4. **대조 대상 = 표 형태의 숫자 항목.** 서술문은 이번 범위 밖.
5. **구성은 report_lines 와 동일**: 검증(`tjf_verify`, camp_run)과 수정(`tjf_fix`, camp_err_review)을 별도 워크트리·별도 DB 계정으로 두고,
   이슈 → fix 큐 → 오류유형별 배치 → 파서 수정 → 재적재 → `fixed` → 재확인 흐름을 note/biz scope 에서도 그대로 쓴다.
   따라서 이슈·배치·load_seq·재확인 장치가 scope 를 알아야 한다(§4 의 스키마 작업에 포함). 재적재 함수는 이미 `ops._reload_rcept` 가
   note_lines 를 같이 다시 쓰므로 note 는 그대로 쓸 수 있고, biz 는 `biz_section_tables` 재적재 경로를 `batch reload` 에 연결해야 한다.
6. 야간 위임: P1(읽기 전용)은 진행. **P2 스키마 변경은 되돌리기 어려운 작업이라 아침 확인 후** 진행한다.

## 6-2. P2 적용 결과 (2026-10-27 밤, 사용자 승인 후)

구현: `fin2/verification/schema.sql`(append-only 성격의 멱등 DDL), `ops.init_scope_era`, `vq.py admin init-scope --scope note|biz`.
회귀 테스트 `fin2/tests/test_verification_scopes.py` 3건 + 기존 verification 테스트 포함 106 passed. 적용 전 백업: verification 스키마 덤프(89MB).

| 항목 | 내용 |
|---|---|
| 별도 progress | `scope_progress`, `scope_progress_filings` (PK 에 scope). 기존 `progress*` 와 러너는 무변경 — report 94,590 슬롯 `passed` 그대로 |
| 적재 스탬프 | `scope_loads`(PK rcept+scope)·`scope_load_events`·`scope_load_dirty`. `note_lines`·`biz_section_tables` 에 **문장 단위 전이표 트리거** + 커밋 시 1회 확정(지연 제약 트리거, report_lines 와 같은 설계). 해시 키: note=basis, biz=domain |
| 기계 대조 결과 | `scope_machine_checks`(PK rcept+scope) |
| 이슈 | `issues` 에 `scope`(기본 `report`)·`table_ref` 추가, `basis` NULL 허용, `statement` 에 NOTE/BIZ. 모양 제약 `issues_scope_shape_check`(biz=basis 없음, note·biz=table_ref 필수). 유일 인덱스 `ux_vissues_active_cell_v2`(scope·table_ref 포함) |
| 상태기계 | `trg_issue_before/after`·`refresh_slot` 이 scope 를 안다: found/fixed 는 scope 의 `scope_loads` 기준, report 슬롯은 scope='report' 이슈만 센다, 비-report 는 `refresh_scope_slot` |
| 오류유형 | `missing_table`·`extra_table`·`section_misassign` 추가 |
| 슬롯 초기화 | biz·note 각 94,131 슬롯 / 106,010 필링 (모두 pending) |
| 베이스라인 | 전수 해시 계산(94GB 풀스캔)을 피하려고 **지연 방식**: 슬롯 확인·이슈 등록 때 `ensure_scope_baseline` |

측정(롤백 트랜잭션): note_lines 4,895행 필링 1건의 delete+insert 83ms, 확정 해시 78ms. 대량 재적재에서도 부담이 작다.
**아직 안 한 것(P3)**: 기계 모듈, 러너/`vq.py` 의 scope 인식(claim·show·issue add·fix-queue·batch reload), `batch reload` 의 biz 재적재 경로.
fix 큐에서 파서 수정 후 재적재가 되려면 P3 에서 `ops._reload_rcept` 가 `biz_section_tables` 를 다시 쓰는 경로(`collector/biz_metrics.py` 계열)를 연결해야 한다.

## 7. (이전) 사용자 결정이 필요한 것 — 위 7-0 으로 모두 답함

1. **슬롯 구조**: scope 별로 독립 상태가 되도록 (a) 기존 `progress` 에 scope 컬럼 추가(PK 변경) vs (b) 별도 progress 테이블. 권장은 (b)(기존 러너·digest·텔레그램 보고에 영향이 적다). 단 코드 중복이 생긴다.
2. **우선순위**: 사업의 내용(grid 보유, 쉬움)을 먼저 할지, 주석(규모 4배, 어려움)을 먼저 할지. 권장은 사업의 내용 먼저.
3. **모델 쿼터 배분**: report_lines 모델 대기분이 남아 있다면 note/biz 는 기계 단계까지만 먼저 돌리고 모델 확인은 뒤로 미룰지.
4. **서술문**: 이번 범위에서 제외(표만)해도 되는지.

## 8. 위험

- 94 GB 테이블 트리거·인덱스 추가는 시간이 길고 디스크를 쓴다 → 사전에 디스크 여유와 백업 상태 확인.
- 주석 표는 형태가 다양해(중첩 헤더, 병합 셀, 각주) 기계 오탐이 많을 수 있다 → P1 의 일치율이 낮으면 전수 모델 확인 대신 표 유형별 계층 접근으로 재설계(사용자와 상의).
- 러너·기계 워커가 도는 중 스키마를 바꾸면 안 된다(STOP 후 적용).
