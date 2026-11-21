# note 다통화(외화 금액) 저장 계획 (2026-11-21, TODO A-4)

상태: **구현됨(2026-11-21, 사용자 결정: 권장안 B · 주요 4통화 · 외화 열+병기 셀 전부 · 2015+ 먼저).** 규칙 R370(`docs/rules/10_layer2_parse.md`).
계획과 달라진 점: ① 자식 행을 `note_line_id` FK 가 아니라 **셀 위치**(rcept_no·basis·table_seq·row_order·col_index·seq)로 묶었다 — `USD 2,364,000` 만 찍힌 셀은 note_lines 행이 없고, 행 id 를 받아 오지 않아도 돼 적재가 단순하다. ② 표지 증거 수준을 `evidence` 열로 남겼다(`header_code_only` 는 원화 환산액일 수 있음). ③ 금액은 `amount_printed`(인쇄 숫자 그대로) + `declared_scale`(표가 그 통화에 선언한 배수, 없으면 NULL)로 나눴다.
배경: 2026-10-30 사용자 결정으로 note 는 원화 금액만 적재한다(셀 첫 줄). 외화 저장은 스키마 변경이 필요해 요청이 있을 때 시작하기로 했다(메모리 `note-total-missing-r294d-r296-2026-10-30`). 2026-11-21 사용자가 시작을 요청했다.

## 1. 현재 상태

- 외화 **단독 선언 표**(`(단위: USD)`)는 이미 표 단위로 처리한다: `report_tables.currency`(USD 490표·JPY 6표), 셀은 `unit_source='fx_declared'`, value_won 에 표시통화 금액이 그대로 들어간다(`fin2/extract/units.py` FX_ONLY, R257·R305). 계층3 소비자는 이 행을 걸러야 한다.
- **혼합 표**(원화 + 외화 열/줄)는 원화만 적재한다. 외화는 버려지거나 value_raw 에만 남는다.
  - 외화 열: 머리글 `외화금액`·`USD`·`EUR`·`JPY`·`CNY` 열의 셀은 value_won 이 NULL (비금액 표지로 처리, `units.py` NON_MONEY_ONLY·CONTAMINATION_MARKERS).
  - 한 셀에 원화+외화 병기: `67,293,600USD 2,364,000`, `5,789,000 (USD 5,000,000)`, `103,080,000US$2,000,000JPY50,000,000`. 첫 줄 원화만 value_won, 나머지는 value_raw 에만(R294).
- `note_lines` 에는 통화 열이 없다. 열: `value_won, adecimal, unit_source, col_label, header_hint, value_raw ...`.

## 2. 규모 (추정 — note_lines 1% 표본 ×100, 2026-11-21 측정, 정확한 집계 아님)

- note_lines 약 2.64억 행 중 머리글(col_label·header_hint)에 외화 표지가 든 셀 ≈ 280만(1.06%). 그중 value_won 이 NULL ≈ 207만, value_won 이 있는 것 ≈ 72만(원화 열인데 머리글에 `외화`·`$` 가 같이 있는 경우 등 — 분류 필요).
- value_raw 에 통화 코드·기호가 직접 찍힌 셀 ≈ 3.9만, 그중 value_won NULL ≈ 1만.
- 상위 머리글: `전기말>외화금액`, `전기말>외화`, `USD`, `당기말>외화금액`, `EUR`, `JPY`, `CNY` (외화 차입·외화자산부채·계약 현황 표).
- ⚠ 표지 정규식이 넓어(`$`, `외화`, `날짜` 가 섞임) 실제 외화 금액 셀 수는 이보다 적다. 구현 전 정밀 집계가 먼저다.

## 3. 설계 선택지

### A. note_lines 에 열 추가 (`fx_currency`, `fx_value`)
- 장점: 단순, 셀 1:1.
- 단점: 한 셀에 외화가 둘 이상(`USD …`+`CNY …`)이면 못 담는다. 2.6억 행 테이블에 열 추가(PG11+ 는 NULL 기본값이라 메타데이터 변경만이지만 이후 재적재 UPDATE 가 팽창 유발 — 11-18 note_lines 98→54GB 정리 직후라 부담).

### B. 별도 자식 테이블 `note_fx_amounts` (권장)
- 열: `note_line_id`(FK, note_lines.id), `seq`(셀 안 순서), `currency`(3), `amount_exact`(numeric, 인쇄값 그대로), `adecimal`, `scale`(표시 배수), `source`(`cell_line`·`col_header`·`paren_tail`), `printed`(원문 조각).
- 외화 열 셀(value_won NULL)은 note_lines 행은 그대로 두고 자식에 외화 금액을 건다. 병기 셀은 원화 첫 줄은 기존대로, 나머지 외화는 자식 행 N개.
- 장점: 기존 2.6억 행 테이블 불변(롤백 = `DROP TABLE`), 다중 통화 셀 수용, 행 수 수백만 규모라 작음. 소비자는 JOIN 으로만 접근해 기존 쿼리 영향 0.
- 단점: 소비자 쿼리가 한 번 더 JOIN. note_lines 행이 재적재로 삭제되면 FK CASCADE 로 자식도 지워지고 재적재가 다시 채운다(재적재 경로에 자식 적재를 같이 넣어야 함).

### C. 표 단위 통화만 (`note_tables` 에 currency) — 비권장
혼합 표(열마다 통화가 다름)를 못 다룬다. 현재 report_tables.currency 방식의 연장일 뿐 요구를 못 채운다.

**권장: B.** (사용자 결정 필요 1)

## 4. 지키는 원칙

- **계층2 = 인쇄된 값만(R0-2).** 통화 코드는 열 머리글·셀에 인쇄된 것만 읽는다. 환율 환산·원화 환산 값은 만들지 않는다(필요하면 계층3).
- 원화 value_won 의미는 바꾸지 않는다(원화만). 자식 테이블의 금액은 **표시통화 단위 그대로**.
- 판독 단계(`parser/xml/dart_xml_parser.py`) 변경은 본문 표로 새기 쉽다(R296 교훈). note 구간에만 적용하고 `tests/test_r258_r259_stacked_amount_cells.py` 를 돌린다.

## 5. 작업 순서 (착수 지시 후)

1. 정밀 집계: 외화 셀 유형 분류(열 / 병기 / 단독) — 위 2번의 표지 오염 제거. 통화 코드 목록 확정.
2. 규칙 문서: `docs/rules/10_layer2_parse.md` 에 R3xx 신설(`적용 계층: 2 — 읽기`), 진입점 색인 한 줄. 규칙 문서는 main 에서만 수정.
3. DDL: `note_fx_amounts` + 인덱스(note_line_id), 권한(tja_reader 읽기), `consumer_guide` 에 설명 추가.
4. 판독·적재 코드: `fin2/extract/units.py` 와 note 적재 경로. 단위 테스트.
5. A/B: 무작위 150필링 + 외화 표 많은 필링으로 기존 value_won 불변·본문 변화 0 확인(TOOL_VERSION 올리기 전).
6. 검증 기계: 외화 꼬리를 버리는 mn 규칙(R294 계열)이 새 적재와 충돌하지 않는지 조정, `scope retriage`.
7. **배선(runbook 필수)**: `docs/runbook_new_parser_pipeline_integration.md` — ① `scripts/collect_new.py` 두 call site(메인 + `--standardize-only`), ② 소급 백필, ③ 회귀·원문 대조·Gate B 무영향.
8. 소급 백필: note 전용 재적재. 과거 36,766필링 재적재가 약 12시간이었음 — 외화 포함 필링만 골라 재적재하면 줄어든다(대상 수는 1번 집계 뒤 산정). 2015+ 먼저, 2015 이전은 [[data-scope-load-all-quality-2015-first]] 방침대로 뒤.

## 6. 사용자 결정이 필요한 것

1. 설계 B(자식 테이블) 로 갈지.
2. 저장 범위: (가) 외화 열 + 병기 셀 전부, (나) 외화 열만 먼저, (다) 통화가 `USD`·`EUR`·`JPY`·`CNY` 인 것만.
3. 소급 범위: 2015+ 만 먼저 / 전 기간.
4. 소비자(tj_asset)가 실제로 쓸 용도가 있는가 — 없다면 우선순위를 B-1·B-3 아래로 둘 수 있다(Pro 요금제 예산, 야간 1배치 한도 고려).

## 7. 하지 않는 것

- 환율 환산, 원화 환산 값 생성.
- note_lines 기존 행 값 변경.
- 본문 재무제표(report_lines)의 외화 처리 변경 — 이미 report_tables.currency 로 처리 중.
