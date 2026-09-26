# verification 캠페인 운영 가이드 (공통 규칙)

설계: `docs/plans/verification_schema_two_worktree_design_2026-09-24.md`
CLI: `scripts/vq.py` (모든 명령은 `--help`)

## 1. 한눈에 보기

| | 검증 = `camp_run` | 수정 = `camp_err_review` | main |
|---|---|---|---|
| DB 계정 | `tjf_verify` (public 읽기 전용) | `tjf_fix` (public 쓰기, 스키마 변경 불가) | 관리자 |
| 하는 일 | DART 원문 vs DB 대조, 이슈 등록, fixed 이슈 재확인 | 이슈를 오류유형별 배치로 묶어 파서 수정 → 재적재 → fixed | 데일리 파이프라인, init/sync, 이관 |
| 실행 방식 | `scripts/verify_runner.sh` 가 슬롯마다 `claude -p` 1회 | 대화형 `claude`, 배치 1개 = 세션 1개 | 기존대로 |
| 이어하기 | 러너가 알아서(`vq.py claim`) | `vq.py fix-queue` | — |

모든 진행 상태는 `verification` 스키마에 있다. 세션 메모리나 마크다운은 진행상태의 근거가 아니다.

## 2. 상태

- 슬롯(회사 × 사업연도 × 보고서): `pending` → `in_progress`(점유, lease 2시간) → `passed` | `has_issues` | `blocked`(3회 실패)
- 필링(슬롯 안의 rcept): `pending` · `passed` · `has_issues` · `skipped`
- 이슈: `open → fixing → fixed → closed`, 재확인에서 틀리면 `reopened → fixing`. 오등록은 `withdraw`(open → closed).
  - 검증 계정만 가능: 등록, `fixed → closed/reopened`, `closed → reopened`
  - 수정 계정만 가능: `open/reopened → fixing`, `fixing → fixed`
  - `fixed` 는 해당 필링의 데이터가 실제로 바뀐 재적재(load_seq 증가)가 있어야만 된다
- 모든 상태 변경은 트리거가 `issue_events` / `progress_events` 에 자동 기록한다(이 이력은 수정·삭제 불가).

## 3. 재적재와 검증이 섞이지 않는 장치 (자동)

1. report_lines 에 걸린 트리거가 커밋 시점에 필링마다 **내용 해시**를 계산한다. 내용이 바뀌었을 때만 `load_seq` 가 +1 되고,
   `filing_load_events` 에 누가(워크트리), 어떤 코드(git commit), 왜(reason) 바꿨는지 남는다.
   같은 결과로 다시 파싱하면 아무것도 바뀌지 않는다.
2. 점유(lease) 중인 슬롯의 필링을 수정 계정이 바꾸려 하면 트리거가 커밋을 거부한다.
   `batch reload` 는 그 건을 `deferred` 로 두었다가 다음 실행 때 다시 시도한다.
3. 점유 중에 적재가 바뀌면(데일리 파이프라인 등) `pass`/`issue add` 가 거부된다. 다시 `show` 해서 확인해야 한다.
4. passed 필링의 내용이 바뀌면 그 필링은 pending 으로 돌아가고, 슬롯은 다시 큐에 들어간다.
   `show` 가 "이전 판정 이후 바뀐 scope" 를 알려주므로 그 scope만 다시 대조하면 된다(기존 R139 하드 차단을 대체).
5. 새 정정본이 적재되면 기존 슬롯에 자동으로 편입된다. 슬롯이 passed 였으면 pending 으로 돌아간다.

## 4. 검증 러너 운영

실행: tmux 세션 `verify` 로 띄운다. 터미널을 닫아도 계속 돌고, 원격(tailscale ssh)에서 붙어 볼 수 있다.

```bash
tmux new-session -d -s verify -c /Users/taejin/Project/tj_finance/.claude/worktrees/camp_run 'caffeinate -i scripts/verify_runner.sh 2>&1 | tee -a logs/verify_runner/runner.out'
```

진행 화면 보기(빠져나올 때는 Ctrl-b 다음 d):

```bash
tmux attach -t verify
```

- 러너 스크립트 자신이 바뀌면 회차 사이에 스스로 재시작한다. 단 **재시작 기능이 없는 옛 버전으로 떠 있던 러너**는 한 번 수동으로 다시 띄워야 한다.
  2026-09-24 12:14 에 띄운 러너가 그랬다. `ps` 에 스크립트 경로가 상대경로로 보이면 한 번도 재실행되지 않은 것이다.

정지(현재 슬롯을 끝낸 뒤 멈춤):

```bash
touch ~/.claude/notify/STOP_VERIFY
```

재개하려면 파일을 지우고 다시 실행한다:

```bash
rm ~/.claude/notify/STOP_VERIFY
```

- 매 회차 `git merge --ff-only origin/main` 을 하므로, 수정 워크트리가 push 한 코드가 자동으로 반영된다. 러너 스크립트 자신이 바뀌면 회차 사이에 스스로 재시작한다.
- 예산: 5시간 창당 `runner.slots_per_window`(기본 12), 7일 `runner.weekly_slots`(파일럿 후 설정). 값은 `verification.kv` 에 있어 코드 수정 없이 조정된다.
  **2026-09-24 파일럿 30회 실측 후 튜닝(Max x5)**: `runner.pace_mode=on`.
  - 5시간 창: 계정 사용률이 `runner.max_5h_pct`(70) 이상이면 리셋까지 대기한다.
  - 주간: 상한 = 100 − `runner.reserve_7d_pct`(40) × 남은기간비율 − `runner.safety_7d_pct`(5).
    수정·대화형 몫을 남은 기간에 비례해 보장한다.
  - `runner.slots_per_window`=60 은 안전장치로만 둔다.
  - 실측: 회당 주간 ≈0.13%p, 5h ≈1.6%p, 평균 4.6분. 근거는 설계 §11.
  회차마다 `runner_runs.usage_5h_*`/`usage_7d_*` 에 계정 사용률(%)을 시작·끝으로 남긴다. 다른 세션과 한도를 공유하므로 차이는 상한값이다. 이 값으로 파일럿 후 예산을 정한다.
- 사용량 한도 메시지가 오면 리셋 시각까지 쉰다. 이 경우 재시도 횟수는 늘지 않는다.
- 연속 3회 실패, 디스크 여유 50GB 미만, 코드 동기화 실패일 때만 텔레그램 알림을 보내고 정지한다.
- 로그: `logs/verify_runner/<날짜>/` (30일 뒤 자동 삭제).
- 파일럿 옵션(환경변수): `VQ_MODEL`(기본 sonnet), `VQ_MAX_TURNS`(120), `VQ_RUN_TIMEOUT`(2700초), `VQ_CLAUDE_ARGS`(추가 플래그).
- 탭 정리(2026-09-25 변경): 회차가 끝날 때마다 러너가 **열린 DART 탭을 전부 훑어서**, 캠페인 필링이면서 지금 점유 중인 슬롯이 아닌 탭을 AppleScript 로 닫는다(`vq.py stale-tabs`). 모델이 같은 회사의 다른 기간 공시를 비교용으로 여는 경우와 러너 재시작으로 이력을 잃는 경우에도 남지 않는다. 캠페인 대상이 아닌 공시 탭(직접 연 탭)은 건드리지 않는다. 처음 한 번 macOS 가 "터미널이 Chrome 을 제어" 권한을 물으면 허용한다.

## 4-1. 기계 대조 (2026-09-24~, 설계 `docs/plans/verification_machine_compare_design_2026-09-24.md`)

기계가 먼저 모든 pending 필링을 원문 XML 과 대조한다. clean 은 기계가 pass 하고, 나머지는 모델 러너가 발견 항목만 웹뷰로 확인한다.
clean 슬롯의 1%(`machine.audit_pct`)는 모델이 전체를 다시 대조한다.

실행: tmux 세션 `verify_machine` 로 camp_run 워크트리에서 `scripts/machine_daemon.sh` 를 상시 기동한다.
`machine_pass.run()`/`.recheck()` 의 claim 루프는 claim 할 게 없으면 스스로 끝나는 게 설계다(무한폴링으로
바꾸면 안 됨) — 그래서 데몬이 매 주기(기본 10분)마다 ① `machine recheck`(수정 배치가 `fixed` 로 넘긴
이슈를 재적재 결과로 재검증 — close/reopen) 를 한 번 돌리고, ② 미대조 pending 필링 수를 확인해 0보다
크면 워커 6개를 다시 띄우고 빌 때까지 기다린다. 재적재·데일리 신규 필링·수정 배치의 `fixed` 이슈가
쌓여도 사람이 챙길 필요가 없다(2026-09-26: `machine recheck` 가 아무도 안 돌려서 481건 방치돼 있던 것을
발견하고 데몬에 편입).

```bash
tmux new-session -d -s verify_machine -c /Users/taejin/Project/tj_finance/.claude/worktrees/camp_run 'caffeinate -i scripts/machine_daemon.sh'
```

정지(진행 중인 배치는 끝까지 돌고 정지):

```bash
touch ~/.claude/notify/STOP_MACHINE
```

재개(정지 파일 삭제 후 tmux 세션 다시 기동):

```bash
rm ~/.claude/notify/STOP_MACHINE
```

진행 확인(`기계대조:` 줄의 미대조 필링 수가 줄어든다):

```bash
cd /Users/taejin/Project/tj_finance && .venv/bin/python scripts/vq.py status
```

- 모델 게이트: `vq.py machine gate --value on` 이면 모델 러너는 기계가 끝낸 슬롯만 집는다. off 면 예전처럼 모든 pending 을 집는다.
- 필링 하나를 저장 없이 시험 대조: `vq.py machine try --rcept 20240320001504`
- 재적재된 필링은 기계 판정이 stale 이 되어 다음 워커 기동 때 다시 대조된다. 데일리 신규 필링도 같다 —
  이제 데몬이 자동으로 다시 띄우므로 사람이 챙길 필요 없다.
- 폴링 주기는 `VQ_MACHINE_POLL_S`(기본 600초), 워커 수는 `VQ_MACHINE_WORKERS`(기본 6)로 조정 가능.
- 기계 판정은 `verification.machine_checks` 에 남는다. 모델이 기계 오판을 확인하면 pass 노트에 `기계오탐:` 을 적는다. 이것을 모아 규칙을 개선한다.

## 5. 수정 워크트리 시작 절차

1. 터미널 준비

```bash
cd /Users/taejin/Project/tj_finance/.claude/worktrees/camp_err_review
```

```bash
git fetch origin && git merge --ff-only origin/main
```

```bash
source /Users/taejin/Project/tj_finance/.venv/bin/activate
```

```bash
python scripts/vq.py whoami
```

`"role": "fix"` 가 아니면 멈추고 `.env` 의 `DATABASE_URL`(`tjf_fix@`)을 확인한다.

2. 현황 확인

```bash
python scripts/vq.py fix-queue
```

3. Claude 세션을 시작한다

```bash
claude
```

첫 프롬프트: `vq.py fix-queue 보고 답이 온 판단·진행 중 배치가 있으면 이어서, 없으면 가장 큰 error_type 묶음으로 새 배치를 만들어 진행해`

4. 세션 1회의 흐름
   1. `batch new`
   2. 원인 조사
   3. 파서 수정
   4. `pytest tests/ fin2/tests/`
   5. `PARSING_RULES.md` 에 R번호 추가
   6. commit, `git push origin HEAD:main`
   7. `batch reload <id>`
   8. `batch mark-fixed <id>`
      - 코드로 고치지 않고 주차한 이슈(원문 결함 등)는 `--exclude 1,2 --note "사유"` 로 빼야 한다. 트리거는 "필링이 재적재됐는가"만 보므로, 빼지 않으면 값이 그대로여도 fixed 가 된다(batch #25 사고). 뺀 이슈는 open 으로 돌아간다.
   9. `batch set <id> --status done`
5. 배치가 끝나면 `/clear` 하거나 세션을 끝낸다. 다음 배치는 1부터 다시 한다.

## 6. 텔레그램 판단

- 묻는 것은 수정 워크트리뿐이고, `vq.py ask` 로만 묻는다. 카테고리는 `irreversible` · `policy` · `scope` · `source_ambiguity` 넷이다.
- 선택지 2~4개, 권장안, 선택지별 결과 한 줄이 필수다. 같은 key 로 대기 중인 판단이 있으면 새로 보내지 않는다.
  대기 중 판단은 최대 3건, 즉시 발송은 하루 5건까지다.
- 22–08시에는 `irreversible` 만 만들 수 있고, 발송은 08:00 다이제스트가 한다.
- 만료(기본 24시간): `irreversible` 은 절대 자동 적용하지 않는다. 나머지는 권장안이 적용된다.
- 폰에서 버튼을 누르면 기록된다. 메시지에 답장하면 자유 입력 답이 된다. 봇에게 `/pending` 을 보내면 대기 목록을 받는다.
- 봇은 launchd(`com.taejin.claude.decision-bot`)로 상주한다. `~/.claude/notify/link_chat.sh` 를 다시 돌릴 일이 있으면 봇을 먼저 멈춘다.
  같은 토큰으로 getUpdates 를 쓰는 곳이 둘이면 충돌한다.

## 7. 관리(main 에서)

- `python scripts/vq.py status`: 진척·이슈·디스크
- `python scripts/vq.py admin init --era 2015+`: 새 필링과 슬롯 반영(멱등). 08:00 다이제스트가 매일 실행한다.
- `python scripts/vq.py admin audit-sample --pct 2`: passed 슬롯 표본 추출(검증자 오판 측정용)
- 2015 이전으로 확장할 때: `python scripts/vq.py admin init --era 2011-14`
- 백업: `scripts/vq_backup.sh` 가 매일 `pg_dump -n verification` 을 남긴다(최근 30개 보관).
- 스키마를 고쳤으면: 러너를 STOP 하고 → `python scripts/vq.py admin apply-schema` → 러너를 재개한다.
