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

실행(검증 워크트리, tmux 안에서):

```bash
cd /Users/taejin/Project/tj_finance/.claude/worktrees/camp_run
```

```bash
caffeinate -i scripts/verify_runner.sh
```

정지(현재 슬롯을 끝낸 뒤 멈춤):

```bash
touch ~/.claude/notify/STOP_VERIFY
```

재개하려면 파일을 지우고 다시 실행한다:

```bash
rm ~/.claude/notify/STOP_VERIFY
```

- 매 회차 `git merge --ff-only origin/main` 을 하므로, 수정 워크트리가 push 한 코드가 자동으로 반영된다.
- 예산: 5시간 창당 `runner.slots_per_window`(기본 12), 7일 `runner.weekly_slots`(파일럿 후 설정). 값은 `verification.kv` 에 있어 코드 수정 없이 조정된다.
- 사용량 한도 메시지가 오면 리셋 시각까지 쉰다. 이 경우 재시도 횟수는 늘지 않는다.
- 연속 3회 실패, 디스크 여유 50GB 미만, 코드 동기화 실패일 때만 텔레그램 알림을 보내고 정지한다.
- 로그: `logs/verify_runner/<날짜>/` (30일 뒤 자동 삭제).
- 파일럿 옵션(환경변수): `VQ_MODEL`(기본 sonnet), `VQ_MAX_TURNS`(120), `VQ_RUN_TIMEOUT`(2700초), `VQ_CLAUDE_ARGS`(추가 플래그).
- 탭 정리: 회차가 끝날 때마다 러너가 **그 슬롯의 접수번호가 URL에 든 Chrome 탭만** AppleScript로 닫는다. `claude -p` 는 세션마다 새 탭 그룹을 만들어 이전 회차 탭을 볼 수 없고, 턴 상한이나 타임아웃으로 끊긴 회차는 탭을 닫지 못하기 때문이다. 직접 연 다른 DART 탭은 건드리지 않는다. 처음 한 번 macOS 가 "터미널이 Chrome 을 제어" 권한을 물으면 허용한다.

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
