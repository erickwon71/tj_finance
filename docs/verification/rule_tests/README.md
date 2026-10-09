# 규칙 이해 시험 (모델 간 판정 일치 확인용)

검증·수정 규칙(`verify_prompt.md`, 수정 워크트리 `CLAUDE.local.md`, `PARSING_RULES.md` R0-1)을 고친 뒤,
작은 모델(Haiku)이 Sonnet/Opus 와 같은 판정을 내리는지 확인하는 사례 모음이다. 규칙을 바꾸면 다시 돌린다.
기대 답은 **현재 규칙**(판정표 v5: 부호 복원만 허용, 2026-10-09) 기준이다. 규칙을 바꾸면 기대 답도 함께 고친다.

실행: 서브에이전트(model=haiku 3회, sonnet 1회)에게 규칙 파일과 사례 파일만 읽히고 답 줄만 출력하게 한 뒤 아래 기대 답과 비교한다.
- verify: 규칙 = `docs/verification/verify_prompt.md`
- fix: 규칙 = `.claude/worktrees/camp_err_review/CLAUDE.local.md` + `docs/PARSING_RULES.md` 의 R0-1·R6 절
- 실행 중 문서가 바뀌지 않도록 규칙 파일을 스크래치 디렉터리에 복사해 그 사본을 읽힌다.

## 결과 기록 (행동 기준 일치 수)

| 날짜 | 문서 | 사례 | Haiku | Sonnet | Opus |
|---|---|---|---|---|---|
| 2026-10-09 | v3(7b54d42) | verify v1 16 | 3/3 회 16/16 | 16/16 | 16/16 |
| 2026-10-09 | v3(7b54d42) | verify v2 22 | 11/22 · 13/22 | 15/22 | - |
| 2026-10-09 | v3(7b54d42) | fix v2 14 | 7/14 · 7/14 | 10/14 | - |
| 2026-10-09 | v4(8efb54e) | verify v2 22 | 4/4 회 22/22 | 22/22 | - |
| 2026-10-09 | v4(8efb54e) | fix v2 14 | 3/3 회 14/14 | 14/14 | - |
| 2026-10-09 | v4(8efb54e) | verify v3 18 (실데이터 모양) | 약 9~11/18 | 약 10/18 | - |
| 2026-10-09 | v4(8efb54e) | fix v3 14 | 약 6~8/14 | 9/14 | - |
| 2026-10-09 | v5 초안(⑤ 문구 전) | verify v3 18 | 3/3 회 17/18(13번 ⑤) | 18/18 | - |
| 2026-10-09 | v5 초안 | fix v3 14 | 3/3 회 14/14 | 14/14 | - |
| 2026-10-09 | v5(부호만·⑤ 예시) | verify v3 18 | 2/3 회 18/18, 1회 17/18(3번 ② 날짜) | 18/18 | - |
| 2026-10-09 | v5 | fix v3 14 | 2/2 회 14/14 | 13/14(6번 음수 인쇄)·출력 잘림 | - |
| 2026-10-09 | v5 | fix v2 14 (기대 답 v5) | 14/14 | - | - |
| 2026-10-09 | v5 최종(② 날짜 예시·F7-a 음수 확인) | verify v3 18 / fix v3 14 | 18/18 | fix 14/14 | - |

## 기대 답 — verify_cases_v1.md

1 I1 기계오탐 · 2 I1 기계오탐(차이 1) · 3 I3 source_defect · 4 C2 이슈 없음 ·
5 C3 sign_flip + I3 source_defect(D·S 둘 다 안 닫힘) · 6 C3 unit_scale · 7 아무것도 안 함 · 8 sign_omitted → ① 항등식 규칙(사례에 계산 정보 없음: 항등식 규칙대로) ·
9 I3 source_defect · 10 C3 label_mismatch · 11 C3 sign_flip + I3 source_defect · 12 C3 missing_row ·
13 하나씩 확인 · 14 이 필링 대조 안 함 · 15 close · 16 기계오탐

## 기대 답 — verify_cases_v2.md

1 C1 · 2 C1 · 3 C1 · 4 C1 · 5 sign_flip + value_mismatch, I1 · 6 C2 이슈 없음, I1 ·
7 기말 셀 C3 sign_flip(원문이 음수 인쇄라 C2 아님) + ① I3 source_defect 1 · 8 배당 셀 C2 + ① I3 source_defect 1 · 9 sign_flip, I2 ·
10 sign_flip 1(evidence 에 계정명 차이) · 11 period_misassign · 12 unit_scale ·
13 A 는 pending 으로 두고 B 처리 후 done · 14 close · 15 reopen · 16 닫힘 · 17 대조 대상 아님 ·
18 일괄 등록 · 19 하나씩(종류별 10건 미만) · 20 `이익잉여금 @ 2022.12.31` / `이익잉여금 @ 2023.12.31` ·
21 extra_row × 2(scope 마다) · 22 하나씩(표본에 unit_scale)

## 기대 답 — verify_cases_v3.md

1 I1 기계오탐(소계 빼고 닫힘) · 2 C2 이슈 없음(`>` 정규화) · 3 ② 해당 없음 → 기계오탐 · 4 `이익잉여금 @ 2023.12.31` / `이익잉여금 @ 2023.12.31 #항등식` ·
5 I3 source_defect · 6 기계오탐 · 7 C3 value_mismatch(원문 빈 칸) · 8 C3 sign_flip(음수 인쇄) ·
9 A 보류·B 할 일 없음·C pass(기계오탐), 요약 `pass 1 · … · 대조 보류 1` · 10 프롬프트 맨 끝 `---` 아래 임시 파일 경로 ·
11 I1 · 12 I1(자산 = 부채와자본총계) · 13 지배기업 소유지분 소계 + 비지배지분 · 14 `이익잉여금 @ 2022.12.31` ·
15 reopen · 16 C3 value_mismatch · 17 C3 sign_flip + I3 source_defect(⑥ 해당 없음) · 18 C3 value_mismatch + evidence `기계 clean 판정 누락`

## 기대 답 — fix_cases_v2.md

1 F7-b defer · 2 F7-a no_fix · 3 F6 파서 수정 · 4 F6 파서 수정(A 만 ③ 통과) · 5 F6 no_fix(② 실패) ·
6 F7-a no_fix(R169 확정) · 7 F0 no_fix(R206) · 8 F5 no_fix(③ 실패) · 9 F4-a no_fix(정규화 같음) ·
10 F2 defer(다른 원인) · 11 F6 no_fix(숫자 교정은 후보 아님) · 12 F6 no_fix · 13 F7-a no_fix(천원 표 허용오차 안) · 14 fixed 가능

## 기대 답 — fix_cases_v3.md

1 F0 defer(동결 ①) · 2 F7-b defer(R184) · 3 F4-b defer(R183) · 4 F3 no_fix · 5 F1 주차 · 6 F7-b defer(R190-d, 음수 인쇄) ·
7 F6 파서 수정(셀 수 최소 A) · 8 F6 no_fix · 9 F2→F3 no_fix · 10 F8 defer · 11 defer + `vq.py ask --category irreversible` ·
12 F7-b defer(야간에도) · 13 fixed 가능(push·재적재 전제) · 14 F4-a no_fix

## 결과 기록 — 4차(데이터 영역·생애주기 검토 반영, 기계 mc7, 2026-10-09)

| 문서 | 사례 | Haiku | Sonnet |
|---|---|---|---|
| v6(허용오차 ⌈항 수÷2⌉·mc7·데이터 영역 규칙) | verify v4 18 | 2/2 회 18/18 | 18/18 |
| v6 | fix v4 6 | 6/6 | 6/6 |
| v6 | verify v3 18 (회귀) | 18/18 | - |
| v6 | fix v3 14 (회귀) | 14/14 | - |

## 기대 답 — verify_cases_v4.md

1 같은 열(` [member]` 제거) · 2 ② 는 `2018.01.01 (기초자본)`, ① 은 `수정후 기초자본` · 3 예(띄어쓰기 무시) · 4 C1 · 5 C1(외화 미환산 비교) ·
6 extra_row 1건(필링·basis당), 롤포워드에서 제외 · 7 I1(자본과부채총계) · 8 I1(3항 → 2 단위, 차이 2) · 9 I1(5항 → 3 단위, 차이 2) ·
10 I3 source_defect(3항 → 2 단위, 차이 3) · 11 missing_row(★원문만) · 12 C1 · 13 그 항등식 해당 없음 · 14 9개월 열, C1 · 15 ⑤ 해당 없음 ·
16 `자본>이익잉여금 @ 2023.12.31` · 17 적재 scope 전체 대조 · 18 IS 로 바뀜(CIS 쓰지 않음)

## 기대 답 — fix_cases_v4.md

1 F6 no_fix · 2 F1 아님(적재 행 있음) → F4-c 파서 수정 · 3 F4-b defer(R160 정합화) · 4 F4-c 파서 수정(주석 열 오파싱) ·
5 `vq.py issues --type X --held` 로 찾고 `batch new --issues <id,...>` · 6 `mark-fixed --exclude --verdict no_fix` 후 `batch set --status done`(waiting_decision 금지)

★기대 답 변경: verify_cases_v1 9번(BS 1,000 = 600 + 398)은 허용오차 변경(3항 → 2 단위)으로 I1(이슈 없음)이다.
