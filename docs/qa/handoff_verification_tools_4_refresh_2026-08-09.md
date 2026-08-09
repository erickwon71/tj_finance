# 핸드오프 — 검증도구 4종 갱신 완료, 다음 세션 시작점 (2026-08-09)

## 상태
- 검증도구 4종 갱신 작업 **완료**. 상세 = [`docs/plans/verification_tools_4_refresh_2026-08-09.md`](../plans/verification_tools_4_refresh_2026-08-09.md),
  결과 요약 = [`phase4_reload_2026-07-31.md` §4](phase4_reload_2026-07-31.md#4-남은-부채--검증도구가-구-계약을-본다-2026-08-09-갱신완료).
- git: `ed12b5e`(뷰 브리지 swap) **push 완료**. 오늘 작업은 `2adae75`로 커밋됐으나 **아직 push
  안 함**(사용자 지시 — 검토 후 push 결정).

## 다음 세션에서 할 것 (우선순위 순)

1. **`2adae75` push 여부 확인** — 가장 먼저. pytest 439/440 통과·300건 표본 검증 완료 상태.
2. **`layer2_note_heading_fix_verify.py` REGRESSED 2건 원인 규명** — `00121969`·`00133812`
   (둘 다 consolidated). 이 회귀 체크는 이번에 게이트+스키마 버그를 고치기 전까지 **크래시 때문에
   한 번도 제대로 못 돌았던 것**이라, 이 2건이 실제 회귀인지 이번에 처음 드러난 것뿐인지 원문
   대조가 필요. 우선순위는 낮음(본류 아님, [[feedback-verify-against-source]] 원칙대로 짐작 금지).
   재현: `python scripts/layer2_note_heading_fix_verify.py --corps 150` (REGRESSIONS 섹션 참고).
3. **본류 복귀** — [[bridge-swap-view-executed-2026-08-09]]가 열어 둔 §5 잔여 항목:
   - C-1(계층4) 실제 렌더 확인 — tearsheet 금융블록·스크리너 정규화 revenue가 새 뷰
     (`standard_financials`, std_v3+v2 UNION 폴백)로 정상 렌더되는지.
   - (선택) Streamlit UI 풀스모크 — 대표 금융·비금융 기업 페이지 실행 확인.

## 이번 세션 요약(참고, 상세는 위 문서들)

당초 "검증도구 4종 갱신"은 F1/D4(07-31)의 `declared_unit is None → 폐기` 게이트 하나만
고치면 되는 작업으로 계획됐으나, 실제 로더 코드를 확인하는 과정에서 계획에 없던 두 겹의
추가 결함을 발견해 사용자 승인 하에 범위를 넓혀 함께 처리했다:
- R11(08-07/08)로 주석·SCE 추출이 이미 grid 기반으로 전환됐는데 `layer2_forward_cells.py`는
  옛 row-기반 경로를 시뮬레이션 중이었음 → 전면 재작성.
- 2026-08-05 FX/문서기본단위 폴백 결정이 이 도구에 반영 안 돼 있어 "단위미선언 폐기"를
  과다계상하고 있었음 → `resolve_table_unit()`로 수정.
- 부수로 `layer2_note_heading_fix_verify.py`가 F3(07-31) 스키마 이전(`note_lines.section_path`
  → `report_tables.section_path`)을 못 따라가 크래시 나던 것도 발견·수정.

교훈: 작아 보이는 "검증도구 갱신"도 실제 로더를 먼저 읽어야 진짜 범위가 드러난다. 확장 지점을
발견할 때마다 AskUserQuestion으로 확인 후 진행([[feedback-plan-then-wait]]의 실행판).
