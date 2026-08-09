# 검증도구 4종 갱신 — 계획서 (2026-08-09)

> 상태: **완료**(2026-08-09, 사용자 승인 후 실행). [`rearchitecture_4layer.md` §5](rearchitecture_4layer.md)
> 2순위 항목. 실행 중 §5 판단(B)의 전제가 부분적으로 뒤집혔고(fact_v2 채워지는 중), (A)의
> 범위도 초안 예상보다 커졌다(R11 grid 재작성·FX/문서기본단위 폴백 누락 추가 발견) — 상세는
> §5(실행 결과 갱신) 참고. 결과 요약은 [`phase4_reload_2026-07-31.md` §4](../qa/phase4_reload_2026-07-31.md)에도 반영.

## 0. 배경

`docs/qa/phase4_reload_2026-07-31.md` §4 "남은 부채"에서 아래 4개 검증도구가 **F1/D4(2026-07-31
전량 재적재) 이후의 새 로더 계약을 반영하지 못하고 구 계약을 본다**고 기록됨. 각 스크립트
docstring 에 이미 경고가 달려 있음. 08-09 뷰 브리지 swap(`ed12b5e`)까지 반영해 재조사함.

## 1. 대상 4종 — 현재 상태 실측

| 도구 | 구계약 문제 | 재확인(08-09) |
|---|---|---|
| `scripts/layer2_forward_cells.py` | 주석 스코프를 `declared_unit(tb) is None → 폐기`로 셈. F1/D4 이후 로더는 **데이터행이 있으면 전사**(단위 미선언이면 `value_won`만 비움) | 코드 그대로(`declared_unit(table) is None` 판정 미변경) — 여전히 구계약 |
| `scripts/layer2_note_drop_audit.py` | 동일 전제 | `declared_unit(table) is None` 미변경 — 여전히 구계약 |
| `scripts/layer2_note_heading_fix_verify.py` | 동일 전제 (표 필터가 "실제 추출기와 같은 필터 재사용"이라 서술되지만 `declared_unit(table) is None` 직접 판정) | 동일 — 미변경 |
| Gate B **Phase B 라인대조**(`scripts/gateb_audit.py` + `fin2/audit/line_audit.py`) | `fact_v2`가 **비어 있음**(구 XBRL 체인 은퇴) → match 0 / missing 전량 | **부분 해소**: XBRL 원문 파서(08-06 완료, `8943a1c`)가 `fact_v2`를 채우기 시작함. 현재 `fact_v2` **1,451,930행 / 2,956개 rcept**. 그러나 `face_line_audit`은 이미 **121,418개 rcept**에 대해 실행된 상태 — `fact_v2` 커버리지가 전체의 **~2.4%**뿐이라 대다수 rcept는 여전히 "missing 전량"으로 신호 없음 |

## 2. 판단

**(A) 주석 스코프 3종(`layer2_forward_cells`/`layer2_note_drop_audit`/`layer2_note_heading_fix_verify`)**
— 세 파일 모두 **같은 결함, 같은 수정**. docstring이 이미 정확한 처방을 적어 둠:
  1. 주석 스코프 판정을 `declared_unit(tb) is None` → `_table_has_data_rows(tb, minimum=1)`로 교체
  2. "방출" 버킷을 **값 채움**(value_won 있음) / **원문만**(value_raw만, 단위 미확정) 두 갈래로 분리

  세 스크립트가 판정 로직을 중복 소유(각자 `declared_unit`을 직접 import해서 판정). 이번에
  고칠 때 공용 헬퍼로 뽑아낼지(예: `fin2/extract/report_lines.py`에 `note_table_kept(tb)` 같은
  판정 함수 추가 후 3곳이 공유), 아니면 3곳 각각 패치할지 결정 필요 — **공용화 권장**
  (재발 방지: 로더 계약이 다음에 또 바뀌면 지금처럼 3곳이 동시에 낡는 걸 막음).

**(B) Gate B Phase B(`fact_v2` 라인대조)**
— 이건 F1/D4/뷰스왑과는 **별개 원인**(구 XBRL 체인 vs 신규 XBRL 원문 파서 진행률)이라 (A)와
  같은 방식의 "코드 수정"이 아니라 **커버리지 확장 대기** 문제에 가까움. 두 가지 선택지:
  - ① 지금은 **문서만 갱신**(docstring 경고를 "2,956개 rcept만 신호 있음, 나머지는 완성도
    지표 아님"으로 정정) — 코드는 이미 맞게 짜여 있고 fact_v2 채워지는 대로 자동으로 신호가
    늘어나는 구조이므로 손댈 게 없을 수 있음.
  - ② XBRL 파서 커버리지를 더 넓히는 게 우선순위인지 사용자 판단 필요(별도 트랙, 이 계획
    범위 밖).
  - **본 계획 범위는 ①(문서 정정)로 한정**하고, 커버리지 확장은 별도 트랙으로 분리 제안.

**뷰 브리지 swap(08-09)과의 관계**: `gateb_audit.py`의 Phase A는 `std_financials_v2`를 직접
조회(뷰를 거치지 않음, L77). 뷰 스왑은 Gate B 자체 로직에 영향 없음 — Gate B는 원래 "v2
승격 여부 판정" 도구라 v2를 직접 보는 게 맞음. **범위 밖으로 판단**(별도 논의 필요하면
표시만).

## 3. 제안 작업 순서

1. `fin2/extract/report_lines.py`(또는 인접 모듈)에 주석 표 보존판정 공용 함수 추가
   (`_table_has_data_rows(tb, minimum=1)` 기반), 값채움/원문만 구분 헬퍼도 함께.
2. `layer2_forward_cells.py` 패치: 스코프 교체 + 방출 버킷 분리. **전수 재실행**(샤딩)해서
   새 기준선 숫자 확보.
3. `layer2_note_drop_audit.py` 패치: 동일 공용 함수로 교체. 재실행.
4. `layer2_note_heading_fix_verify.py` 패치: 동일. (이 도구는 회귀/복구 비교 목적이라 영향은
   작을 수 있음 — 우선순위 최하)
5. Gate B Phase B docstring 정정(코드 변경 없음) — `fact_v2` 커버리지 현황 수치 명시.
6. 4개 파일 모두 상단 "⚠ 구 계약" 경고 문구 제거(수정 완료 반영).
7. `docs/qa/phase4_reload_2026-07-31.md` §4 "남은 부채" 표를 갱신완료로 업데이트, 이 계획서
   링크 추가.

## 4. 리스크 / 확인 필요

- 세 스크립트가 각각 다른 목적(정방향 셀 집계 vs 표 폐기 사유 감사 vs 회귀·복구 검증)이라
  공용 함수로 묶을 때 인터페이스가 셋 다 맞는지 확인 필요(급하게 묶으면 3번째 도구 목적이
  흐려질 수 있음).
- 재실행 비용: `layer2_forward_cells.py --shard`가 전수 스캔이라 XML 파일 다수 open —
  시간이 걸림(사용자 실행 권장 이력 있음, [[feedback-long-running-commands]]).
- 새 기준선 숫자가 나온 뒤 "0이어야 하는 항목"(열절단·헤더행드롭·라벨없음)이 실제로 0인지
  확인까지가 완료 조건 — 숫자만 나오고 끝내지 않을 것([[feedback-verify-against-source]]).

## 5. 완료 조건 (Definition of Done) — 실행 결과

- [x] 3개 스크립트 스코프 판정 = 실제 로더(F1/D4)와 동일 코드 경로 — `note_table_retained()`
      공용 헬퍼(`fin2/extract/report_lines.py`)로 통일, `_emit_note_lines`도 같은 헬퍼로 리팩터
- [x] 방출 버킷이 값채움/원문만으로 분리돼 새 계약 반영 — `layer2_forward_cells.py`
      (`scan_grid_table`+`note_column_units`), `main()`의 표별 후보↔실제방출 대조도
      value_won 필터 제거(전량 카운트)로 수정
- [x] 전수 재실행 결과: 열절단·헤더행드롭·라벨없음 = 0 (또는 0이 아니면 원인 규명) — 300건
      표본에서 설명안됨 0 확정. 본문(BS/IS/CF) 열절단 3.8%는 **범위 밖**(row-기반 그대로,
      2026-07-30 결정으로 애초에 적재 대상 아닌 전기·전전기 열만 잘림, 기존에도 알려진 동작).
      주석·SCE 열절단은 R11로 구조적으로 0(더 이상 존재할 수 없는 실패모드)
- [x] Gate B Phase B docstring이 현재 `fact_v2` 커버리지(2,956/121,418 rcept)를 정확히 기술 —
      `fin2/audit/line_audit.py`·`scripts/gateb_audit.py` 갱신(코드 변경 없음)
- [x] `phase4_reload_2026-07-31.md` §4 갱신, 메모리 파일 기록

### 초안에 없던 추가 발견(실행 중, 범위 확장하여 함께 처리)

- **R11 grid 재작성 미반영**(2026-08-07/08) — `layer2_forward_cells.py`는 주석·SCE 추출이
  row-기반(`extract_rows`)에서 grid-기반(`_grid_header_split`/`_grid_body_rows`)으로 이미
  전환된 걸 모른 채 옛 경로를 시뮬레이션하고 있었다. 전면 재작성(`scan_grid_table` 신설).
  본문(BS/IS/CF)은 여전히 row-기반이라 그쪽 시뮬레이션(`scan_table`)은 원래도 정확했음.
- **FX/문서기본단위 폴백 누락**(2026-08-05 결정 미반영) — 표 자체 선언이 없어도
  `ColumnUnits`가 FX_ONLY로 살리거나 `document_default_unit()`으로 살아나는 표를
  `layer2_forward_cells.py`가 "단위미선언 폐기"로 과다계상하고 있었다(본문·SCE 공통).
  `resolve_table_unit()` 헬퍼로 수정.
- **F3 스키마 이전 미반영** — `layer2_note_heading_fix_verify.py`가 F3(2026-07-31) 리팩터로
  `note_lines`에서 `report_tables`로 옮겨간 `section_path` 컬럼을 옛 위치에서 참조해
  **크래시**하고 있었다(게이트 문제와 무관한 별개 결함). 쿼리 테이블 교체로 수정.
- **150개사 재실행에서 REGRESSED 2건 발견**(00121969, 00133812 consolidated) —
  `layer2_note_heading_fix_verify.py`의 REGRESSION 체크가 실제로 작동하게 된 뒤(게이트+스키마
  수정 전에는 크래시로 아예 못 돌았음) 처음 드러난 결과. 원인 미조사 — **팔로업 필요**.
