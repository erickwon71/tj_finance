# 검증 모델 일치 시험 (2026-10-09~10) — Haiku 로 낮출 수 있는가

**결론**: 기계 발견만 확인하는 슬롯(모델 작업의 대부분)은 **Haiku 3회 반복 = Sonnet** (11/11 슬롯 완전 일치, 이슈 문자열까지).
모델이 표 전체를 직접 읽고 계산하는 **전체 대조**(audit 1% 표본·no_source·적재 0행·fixed 재확인)는 Haiku 가 반복마다 흔들려 Sonnet 으로 남긴다.
→ `scripts/verify_runner.sh` 가 슬롯마다 모델을 고른다(`vq.py runner model`): 발견 확인 → haiku, 전체 대조·재확인 → sonnet.

## 방법

- 실제 model-ready 슬롯 14개(발견 종류별 층화: value 소량·대량, sce_identity, sce_arith, sign_omitted, bs_identity, missing_row, extra_row,
  unmatched_table, no_table, uncovered_cell, zero_row, audit, no_source)를 고정 스냅샷으로 만들고,
  운영과 같은 프롬프트·허용 도구로 `claude -p --chrome` 을 돌렸다. `vq.py` 는 쓰기를 기록만 하는 대역(`scripts/verify_sim/vq_shim.py`)으로 바꿨다(DB 무변경).
- 비교 단위: 필링별 판정(pass/issues/skip/보류) + 등록 이슈 집합(rcept·basis·statement·정규화 계정명·열 표기·error_type). 하나라도 다르면 "다름".

## 결과

| 라운드 | 문서·도구 | 실행 | 슬롯 일치 | 주된 차이 원인 |
|---|---|---|---|---|
| r0 기준선 | verify_prompt v6, 기계 mc7 | Haiku 1 · Sonnet 1 | **5/14** | Haiku 가 `vq.py` 를 짧은 형태로 불러 거부 → "허용 명령 거부 = 즉시 종료" 규칙대로 2턴 만에 종료(5회) · source_defect 열 이름 문자열(`자본금` vs `자본>자본금`) · 같은 셀을 Sonnet 은 sign_flip, Haiku 는 자체 C2 계산으로 미등록 |
| r2 | v7 초안 | Haiku 1 | — | 기계 버그 발견: SCE 열 번호가 1부터인 필링을 한 칸 밀려 대조(가짜 발견 59건), 부호 복원 판정이 열 단위라 다른 블록의 원문 산수 불일치가 정상 복원을 막음, 항등식 발견의 기초·기말이 DB 값 |
| r3 | v7 + 기계 mc8 | Haiku 3 · Sonnet 2 | 8/14 (발견 슬롯은 대부분 일치) | Haiku 1회가 웹뷰 셀 오독 · 원문에 같은 기초 라벨이 두 번 → 블록 혼동 · no_table 기준 모호 · audit·no_source 전체 대조에서 Haiku 누락/오독 · Sonnet 이 `#롤포워드` 로 열 표기 |
| **r4** | **v7 최종** | Haiku 3 (발견 슬롯 0~10) · Sonnet 1 (전 슬롯) | **14/14** | — |

비용(실측): Haiku ≈ $0.02~0.04/슬롯, Sonnet ≈ $0.4~0.9/슬롯(약 17~20배).

## 결과를 같게 만든 변경 (원칙: 모델이 계산하거나 문자열을 만들지 않게 한다)

1. **발견 확인**(mismatch 필링): 모델은 웹뷰에서 그 셀이 DB 값인지만 본다(DB 값이면 기계오탐, 아니면 등록). 항등식 발견은 `src_broken` 으로만 정한다(I3 등록 / I2 아님). C2·항등식 재계산 금지.
2. **이슈는 도구가 만든다**: `vq.py machine issues-json --findings <번호>` — error_type(`cell_error_type`)·열 표기(`<DB 열> @ <블록 기말일>`)·`(#n)`·source_defect 의 원문 기말값. evidence `[확인 mcN]`.
3. **등록 안전장치**(`ops.add_issues`): 미해결 이슈 셀은 롤백 대신 건너뛰고 보고, 같은 제출 안 반복 라벨 `(#n)`, 외화 source_unit → evidence, source_defect 열 꼬리 `#항등식` 강제.
4. **명령 형태**: 항상 전체 경로. 짧은 형태가 거부된 것은 "허용 명령 거부" 가 아니다(다시 부른다).
5. **기계 mc8**: 위 세 버그 수정 + 항등식 발견에 `db_col`·`src_start/src_end`, 허용오차 항 수 = 0 아닌 항.
6. audit 필링의 항등식·부호 복원은 기계 결과로 판정, `no_table`·`unmatched_table`(신탁계정 등) 기준 명시, 못 읽은 셀이 있으면 pass 하지 않음.

## 남은 차이와 한계

- 전체 대조(no_source)에서 Sonnet 끼리도 한 번 `label_mismatch` 를 더 찾은 실행이 있었다(r3 sonnet_2). 전체 대조는 표 전체를 사람처럼 읽는 일이라 완전한 결정성은 없다 — 대상은 전체 슬롯의 약 3%.
- 표본은 14슬롯이다. 규칙·도구를 바꾸면 `scripts/verify_sim/` 으로 다시 돌린다.
- 기계 mc8 변경 전, 열이 밀린 필링에서 등록된 기존 이슈와 "음수 인쇄 셀 반전"을 복원으로 보고 기계가 이미 pass 한 필링은 소급 확인하지 않았다(별도 결정 필요).

## 다시 볼 시점 (2026-10-10)

계층2 를 "인쇄된 값만"으로 바꾸는 이행(`docs/PARSING_RULES.md` R0-2, `docs/plans/layer2_as_printed_migration_2026-10-10.md`)이 끝나면
검증 규칙의 C2(부호 복원 판단)·audit 예외·기계 `sign_restored` 가 없어진다. 그때 `verify_prompt.md` 를 고친 뒤
**`scripts/verify_sim` 으로 Haiku/Sonnet 일치를 다시 확인하고** 러너를 재개한다(러너·기계는 2026-10-10 01:20 부터 정지).
이 시험에서 남은 관찰: 전체 대조(no_source)는 Sonnet 끼리도 판독 누락으로 결과가 갈린 실행이 있었다(r7: BS 한 셀·SCE 라벨) — 규칙 모호가 아니라 판독 누락.
