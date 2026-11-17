# Pro 요금제 전환에 따른 모델 슬롯·기계대조·fix 큐 정책 조정안 (2026-11-17, 검토 대기)

> 상태: **2026-11-17 적용 완료**(사용자 지시 "코드 전부 수정"). A·B·D는 반영했고, C-7(배치 #242~#244 확인, reopened 7,429건 분류)은 별도 세션에서 한다.
> 사용자 확인: Pro에서도 Claude Code로 Opus를 쓸 수 있다.
> 전환일: 2026-11-18. 요금제가 Max(x5)에서 Pro로 바뀌어 사용 한도가 대략 1/5로 줄어든다(5시간 창과 주간 한도 모두).

## 1. 현재 정책 (2026-11-17 확인)

| 항목 | 현재 값 | 위치 |
|---|---|---|
| 5시간당 실행 수 상한 `runner.slots_per_window` | 240 | `verification.kv` |
| 5시간 사용률 상한 `runner.max_5h_pct` | 80% | `verification.kv` |
| 주간 수정 세션 몫 `runner.reserve_7d_pct` / 안전 여유 `safety_7d_pct` | 30 / 5 | `verification.kv` |
| 사용률 기반 속도 조절 `runner.pace_mode` | on | `verification.kv` |
| 기계대조 게이트 `machine.gate` | on | `verification.kv` |
| 슬롯 모델 | 발견 확인=haiku, 전체 대조·재확인·audit=sonnet | `scripts/verify_runner.sh` L26–32, `runner.model_for` |
| 슬롯 제한 시간 / 최대 turn 수 | 2700초 / 120 | `verify_runner.sh` |
| 기계대조 워커 | 6개, 600초마다 확인 | `scripts/machine_daemon.sh` |
| 러너 자동 시작 | 켜짐, 1시간에 최대 1회, 하루 최대 6회 | `machine_daemon.sh` |
| `pace_wait` 설명 | "Max x5 tuning" | `fin2/verification/runner.py:102` |

## 2. 실측 (verification.runner_runs, 최근 60일)

| 주 | 실행 수 | 비용(USD 환산) | sonnet 1회당 5h 사용률 증가 | 주간 최고 사용률 |
|---|---|---|---|---|
| 09-21 | 655 | 962 | 1.16%p | 86% |
| 10-12 | 2,541 | 648 | 0.67%p | 89% |
| 10-19 | 2,254 | 232 | 0.84%p | 95% |
| 10-26 | 49 | 21 | 0.41%p | 49% |
| 11-09 | 56 | 25 | 0.91%p | 6% |

- 1회 비용: haiku 약 $0.035, sonnet 약 $0.6, 즉 sonnet이 약 17배 비싸다.
- Max(x5) 기준으로 sonnet 1회는 5h 창의 약 0.65~0.9%p, 주간의 약 0.06%p를 쓴다.
  **Pro에서는 약 5배인 5h 3~4.5%p, 주간 0.3%p 정도로 추정한다.** 1/5이라는 비율은 추정이므로 전환 후 실측으로 확인한다.
- 캠페인이 한창일 때(주 2,000건 이상)의 사용량은 Pro로 감당할 수 없다. 지금은 주 50건 수준이라 Pro로도 가능하다.

현재 대기열 (2026-11-17 10:00):
- 본문 대조: pending 슬롯 1,481개, 필링 1,505건, 그중 기계대조를 아직 하지 않은 필링 1,505건. open 이슈 2건.
- note scope: pending 9,724, has_issues 2,894, 기계 mismatch 13,737. biz scope: pending 300.
- fix 큐: 배정되지 않은 이슈 2건(column_misassign). `reloading` 상태로 멈춘 배치 3개(#242~#244, 10-28 biz). `reopened` 이슈 7,429건은 원인을 따로 확인해야 한다.

## 3. 핵심 판단

1. **기계대조는 모델을 쓰지 않으므로** 요금제와 관계없다. 오히려 지금보다 더 앞에 세워서, 모델이 맡을 일을 줄이는 1차 필터로 쓴다.
2. 앞으로 한도를 가장 많이 쓰는 것은 러너가 아니라 **대화형 수정 세션**이다(Opus, 긴 컨텍스트, 야간 자율 실행). 정책의 중심을 러너 속도 조절에서 수정 세션 예산 관리로 옮겨야 한다.
3. Pro는 claude.ai 채팅과 한도를 같이 쓴다. 러너 몫은 작게 잡고, 사람이 쓸 몫을 먼저 확보한다.

## 4. 수정 방향

### A. 모델 슬롯 (러너)
| 항목 | 현재 | 제안 | 이유 |
|---|---|---|---|
| `slots_per_window` | 240 | **8** | 사용률 측정이 실패할 때 실제로 막아 주는 장치. sonnet 8회는 Pro 5h 창의 약 30% |
| `max_5h_pct` | 80 | **40** | 5h 창의 나머지는 대화형·수정 세션 몫 |
| `reserve_7d_pct` | 30 | **60** | 주 초반에는 러너가 일찍 멈춘다 |
| `safety_7d_pct` | 5 | **10** | 주간 한도에 걸리면 수정 작업까지 멈춘다 |
| sonnet 슬롯(전체 대조·audit·recheck) | 언제든 실행 | **야간(22–08)에만** 실행 | 낮에는 haiku 발견 확인만. 코드 변경 필요: `runner.full_model_hours` kv와 `model_for`/`claim` 필터 |
| `MAX_TURNS` | 120 | **60** | 길게 늘어진 실행 1회가 Pro 5h 창을 크게 잡아먹는다. 넘은 실행은 incomplete로 남겨 다시 시도 |
| `pace_wait` 설명·메모리 | Max x5 | Pro 기준으로 수정 | |

- kv 값 4개는 DB만 바꾸면 바로 적용된다(러너 재시작 불필요). 야간 제한과 MAX_TURNS는 코드 변경이다.

### B. 기계대조
- 워커 수(6)와 확인 주기는 **그대로** 둔다. 모델을 쓰지 않으므로 요금 영향이 없다.
- 러너 자동 시작 `RUNNER_MAX_PER_DAY`를 6에서 **2**로 줄이고, 시작 시간을 **야간으로 제한**한다(코드 변경).
- 이미 기계 판정이 clean인 슬롯은 모델 실행 대상에서 빠지는지 확인한다(`machine.gate=on` 유지).
- note scope의 mismatch 13,737건은 모델 확인 대상에 넣지 **않는다**. 기계 규칙(mn*)을 보완해서 줄이는 방식만 쓴다.

### C. fix 큐 / 수정 세션
1. **기본 모델을 Sonnet으로 한다.** 규칙 설계나 어려운 근본 원인 분석일 때만 Opus로 전환한다(Pro에서도 Opus 사용 가능, 사용자 확인 2026-11-17).
2. **한 세션에 한 배치만 처리한다.** 배치 1개를 끝내면(커밋, 백필, mark-fixed) 세션을 닫는다. 컨텍스트가 길어질수록 한 번의 호출 비용이 커진다.
3. **세션을 시작하기 전에 사용량을 확인한다**(`claude-dashboard:check-usage`). 5h가 60% 이상이거나 주간이 남은 시간 비율을 넘었으면 큐 작업은 미룬다.
4. **야간 자율 실행에 상한을 둔다.** 하룻밤에 최대 1배치, 주간 사용률 70% 이상이면 하지 않는다. CLAUDE.md 야간 규약에 이 조건을 한 줄 추가하는 것을 제안한다.
5. **우선순위를 정한다.** (1) 데일리 파이프라인 장애 → (2) 시총 상위·DQ3 → (3) 열린 본문 이슈 → (4) note 남은 누락(약 9.7만 건, 속도를 늦춤). 큰 전수 재감사와 전수 재빌드는 모델을 쓰지 않으므로 그대로 진행한다.
6. 탐색과 집계는 서브에이전트나 대화형 grep 대신 **스크립트로 하고 결과만 읽는다**(기존 "사용자 실행 + 결과 공유" 방식을 강화).
7. 정리할 것: `reloading`으로 멈춘 배치 #242~#244 확인, `reopened` 7,429건의 원인 분류(대부분 기계 recheck로 닫을 수 있다면 모델 비용 0).

### D. 문서·메모리
- 프로젝트 CLAUDE.md의 "Max(x5)에 맞게 관리" 줄을 "Pro(2026-11-18~)"로 바꾼다(사용자 확인 후).
- 메모리 `user-plan-max-x5`를 Pro로 갱신한다.
- 전환 후 3일 동안 `runner_runs`의 `usage_5h_end - usage_5h_start`를 실측해서 위 숫자를 다시 조정한다.

## 5. 실행 순서 (승인 후)
1. 11-18 전에: kv 값 4개 변경(즉시 되돌릴 수 있음), 메모리와 CLAUDE.md 수정.
2. 코드: 야간 sonnet 슬롯 제한, MAX_TURNS 60, 자동 시작 야간·하루 2회. 테스트 후 커밋.
3. 11-18~20: 실측해서 재조정.
4. fix 큐 정리 항목(C-7)은 별도 세션에서 처리한다.

## 6. 적용 내역 (2026-11-17)
- kv: `slots_per_window` 240→8, `max_5h_pct` 80→40, `reserve_7d_pct` 30→60, `safety_7d_pct` 5→10, `full_model_hours` 신설 `22-8`.
- 코드:
  - `fin2/verification/runner.py`: `hours_wait`, `full_model_gate` 추가
  - `fin2/verification/ops.py`: `claim(exclude=)` 추가
  - `scripts/vq.py`: `claim --exclude`, `runner full-gate`, `runner defer` 추가
  - `scripts/verify_runner.sh`: 시간대 밖의 full-model 슬롯은 반납하고 건너뜀, `MAX_TURNS` 60
  - `scripts/machine_daemon.sh`: 자동 기동은 `22-8`에만, 하루 2회
- 문서: `docs/verification/WORKFLOW.md` §4 예산, 프로젝트 `CLAUDE.md` 요금제 줄과 수정 세션 규칙(C-1~C-6).
- 테스트: `fin2/tests/test_verification_ops.py::test_hours_wait_window`, `::test_claim_exclude_skips_named_slots`.
