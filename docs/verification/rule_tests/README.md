# 규칙 이해 시험 (모델 간 판정 일치 확인용)

검증·수정 규칙(`verify_prompt.md`, 수정 워크트리 `CLAUDE.local.md`, `PARSING_RULES.md` R0-1)을 고친 뒤,
작은 모델(Haiku)이 Sonnet/Opus 와 같은 판정을 내리는지 확인하는 사례 모음이다. 규칙을 바꾸면 다시 돌린다.

실행: 서브에이전트(model=haiku 3회, sonnet 1회)에게 규칙 파일과 사례 파일만 읽히고 답 줄만 출력하게 한 뒤 아래 기대 답과 비교한다.
- verify: 규칙 = `docs/verification/verify_prompt.md`
- fix: 규칙 = `.claude/worktrees/camp_err_review/CLAUDE.local.md` + `docs/PARSING_RULES.md` 의 R0-1·R6 절

## 결과 기록

| 날짜 | 문서 | 사례 | Haiku | Sonnet | Opus |
|---|---|---|---|---|---|
| 2026-10-09 | 판정표 v3(7b54d42) | verify v1 16 | 3/3 회 16/16 | 16/16 | 16/16 |
| 2026-10-09 | 판정표 v3(7b54d42) | verify v2 22 | 11/22 · 13/22 | 15/22 | - |
| 2026-10-09 | 판정표 v3(7b54d42) | fix v2 14 | 7/14 · 7/14 | 10/14 | - |
| 2026-10-09 | 판정표 v4 | verify v2 22 | 4/4 회 22/22 | 22/22 | - |
| 2026-10-09 | 판정표 v4 | fix v2 14 | 3/3 회 14/14 | 14/14 | - |
| 2026-10-09 | 판정표 v4 | verify v1 16 (기대 답 v4 기준) | 16/16 | - | - |

## 기대 답 — verify_cases_v1.md (판정표 v4 기준)

1 I1 기계오탐 · 2 I1 기계오탐(차이 1) · 3 I3 source_defect · 4 C2 이슈 없음 ·
5 C3 sign_flip + I3 source_defect(D·S 둘 다 안 닫힘) · 6 C3 unit_scale · 7 아무것도 안 함 · 8 아무것도 안 함 ·
9 I3 source_defect · 10 C3 label_mismatch · 11 C3 sign_flip + I3 source_defect · 12 C3 missing_row ·
13 하나씩 확인 · 14 이 필링 대조 안 함 · 15 close · 16 기계오탐

## 기대 답 — verify_cases_v2.md

1 C1 · 2 C1 · 3 C1 · 4 C1 · 5 sign_flip + value_mismatch, I1 · 6 C2 이슈 없음, I1 ·
7 기말 셀 C2 + ① I3 source_defect 1 · 8 배당 셀 C2 + ① I3 source_defect 1 · 9 sign_flip, I2 ·
10 sign_flip 1(evidence 에 계정명 차이) · 11 period_misassign · 12 unit_scale ·
13 A 는 pending 으로 두고 B 처리 후 done · 14 close · 15 reopen · 16 닫힘 · 17 대조 대상 아님 ·
18 일괄 등록 · 19 하나씩(종류별 10건 미만) · 20 `이익잉여금 @ 2022.12.31` / `이익잉여금 @ 2023.12.31` ·
21 extra_row × 2(scope 마다) · 22 하나씩(표본에 unit_scale)

## 기대 답 — fix_cases_v2.md

1 F5-b defer · 2 F5-a no_fix · 3 F4 파서 수정 · 4 F4 파서 수정(A 만 ③ 통과) · 5 F4 no_fix(② 실패) ·
6 F5-a no_fix(R169 확정) · 7 F0 no_fix(R206) · 8 F3 no_fix(③ 실패) · 9 F2 no_fix(정규화 같음) ·
10 F1 defer(다른 원인) · 11 F4 파서 수정(인쇄 근거 + ①②③) · 12 F4 no_fix(277 미인쇄) ·
13 F5-a no_fix(천원 표 허용오차 안) · 14 fixed 가능
