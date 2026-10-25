# 검증 러너 자동 기동 (기계대조 데몬이 대신 띄운다) — 2026-10-25

> 상태: 계획 + 구현 (사용자 지시 2026-10-25: "계획 문서 만들고 구현까지 진행").
> 대상: `scripts/machine_daemon.sh`, `fin2/verification/ops.py`.

## 1. 문제

- `verify_runner.sh` 는 claim 할 슬롯이 없고 미대조 필링도 없으면 **스스로 종료**한다(`대기 슬롯 없음 - 종료`).
- `machine_daemon.sh` 는 기계대조 워커만 띄우고 러너는 건드리지 않는다.
- 기계대조는 계속 새 모델 작업을 만든다 — 재적재로 pending 이 된 필링, 매일 들어오는 신규 필링,
  수정쪽의 fixed 이슈 재확인. 그런데 러너가 꺼져 있으면 **다시 켜 줄 주체가 없다**.
- 실측(2026-10-25 11:00대): 러너는 10-22 18:52 에 종료된 뒤 사흘간 꺼져 있었고,
  그 사이 `claim` 이 집을 수 있는 슬롯이 **15개** 쌓였다 (`status.machine.model_ready_slots`).

## 2. 설계

### 2.1 "러너가 할 일이 있는가"를 읽기 전용으로 센다

`claim()` 이 슬롯을 고르는 WHERE 절을 상수 `ops.CLAIMABLE_SQL` 로 빼고, `claim()` 과
새 함수 `ops.model_ready_slots(conn)` 이 **같은 상수**를 쓴다. 카운터가 실제 claim 과 어긋나
"슬롯이 있다고 띄웠는데 러너가 바로 종료" 하는 일을 막는다. 머신 게이트가 켜져 있으면
기존 `MODEL_READY_SQL`(기계가 본 뒤 사람 눈이 필요한 슬롯만)도 같이 적용한다.
값은 `vq.py status --json` 의 `machine.model_ready_slots` 로 노출한다.

### 2.2 데몬이 10분 주기로 띄운다

`machine_daemon.sh` 의 기존 폴링 루프(10분)에서 `status --json` 을 한 번만 호출하고,
`runner_autostart <model_ready_slots>` 를 부른다. 조건:

| 가드 | 동작 |
|---|---|
| `VQ_RUNNER_AUTOSTART=0` | 기능 끔 |
| `model_ready_slots` = 0 | 띄우지 않음 |
| `~/.claude/notify/STOP_VERIFY` 존재 | 띄우지 않음 (사용자가 일부러 멈춘 것) |
| `pgrep -f scripts/verify_runner.sh` 가 있음 | 이미 돌고 있음 — 띄우지 않음 |
| 마지막 기동 후 `VQ_RUNNER_AUTOSTART_MIN_GAP_S`(기본 3600초) 미만 | 띄우지 않음 |
| 오늘 기동 횟수 ≥ `VQ_RUNNER_AUTOSTART_MAX_PER_DAY`(기본 6) | 띄우지 않고 로그만 |

기동은 전용 detached tmux 세션 `verify_auto` (`VQ_RUNNER_TMUX_SESSION`) 에서
`caffeinate -i scripts/verify_runner.sh`. 기존 수동 세션 `verify` 는 건드리지 않는다.
기동 기록은 `logs/verify_runner/runner_autostart.log` (`epoch 날짜 시각 slots=N`), 기동 시 텔레그램 한 줄.

### 2.3 폭주 방지

- 러너는 연속 실패 시 스스로 정지하고 알림을 보낸다(exit 5) — 자동 기동은 시간 간격(1시간)과
  일일 한도(6회)로 그 정지를 무한 재기동으로 뒤집지 않게 한다.
- 사용량 예산은 러너의 `runner budget` 이 그대로 지킨다(자동 기동은 예산을 우회하지 않는다).
- 한도를 넘으면 로그에 남기고 사람이 본다.

## 3. 반영과 영향

- 코드는 main 에서 고치고, camp_run 워크트리의 데몬이 `git merge --ff-only` 로 받는다.
  데몬 스크립트가 바뀌면 데몬이 스스로 새 버전으로 재시작한다.
- **push 직후 첫 폴링에서 `model_ready_slots` > 0 이면 러너가 바로 기동된다** (현재 15개).
  모델 호출이므로 Max 한도를 쓴다. 원치 않으면 push 전에 `touch ~/.claude/notify/STOP_VERIFY`.
- 멈추는 법: `touch ~/.claude/notify/STOP_VERIFY` (러너·자동기동 둘 다 멈춤).

## 4. 검증

- `fin2/tests/test_verification_ops.py::test_model_ready_slots_counts_what_claim_can_pick`
  (pending 슬롯 1 → in_progress 0, `machine_status` 노출).
- `runner_autostart` 가드 6종을 tmux/pgrep/notify 를 스텁한 셸 스모크로 확인:
  0슬롯·최초기동·최소간격·재기동·일일한도·러너생존·STOP 파일.
- `bash -n scripts/machine_daemon.sh`, 관련 스위트 81건 통과.
