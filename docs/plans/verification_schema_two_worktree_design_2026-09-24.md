# verification 스키마 + 2-워크트리 운영 설계 (2026-09-24, 사용자 검토 대기)

> 저장 위치(승인 후): `docs/plans/verification_schema_two_worktree_design_2026-09-24.md`
> 이 문서는 **설계안**이다. 사용자 검토 후 구현은 별도 지시로 진행한다.

## Context — 왜 하는가

DART → DB 적재 검증을 몇 달간 진행한다. 지금은 작업 상태가 세 곳에 흩어져 있다.
- `public.layer2_review_queue`: rcept 단위 큐, pass 1,915 / fail 22 / pending 104,892, owner 컬럼 있음.
- 마크다운 이슈로그: `camp_run/docs/qa/layer2_review_campaign_issues_2026-09-20.md`, 2,058줄, #1~#41.
- 세션 메모리.

그래서 새 세션이 DB만 보고 이어받을 수 없다. 데이터가 섞인 실제 사고도 두 번 있었다.
- 검증 세션의 `next`/`redo`가 구코드로 재적재해서 수정 워크트리의 백필을 되돌렸다(R164, SCE 12,192행).
- 보지 않은 필링에 `pass`가 찍혔다(2026-09-21 owner 컬럼으로 수정).

**목표**: 작업 상태를 **전부 Postgres(`verification` 스키마)** 에 둬서, 어느 워크트리의 어느 세션이든
명령 하나로 이어서 작업할 수 있게 한다. 기존 큐 테이블과 마크다운 이슈로그는 이것으로 대체한다.
파서 규칙은 그대로 `docs/PARSING_RULES.md`(R번호)에 둔다.

**설계의 전제가 되는 실측 사실**
- DB `tj_finance`는 142 GB이고, 스키마는 `public` 하나뿐이다.
- 디스크: 460 GiB 볼륨 중 **129 GiB 여유(71% 사용)**.
- `report_lines`(26 GB, 6,200만 행)와 `note_lines`(94 GB)는 rcept 단위 delete+insert다
  (`fin2/extract/report_lines.py:1998`).
- 행에 **parser version이나 load id가 없다.**
- `status='pass'` 재적재 차단 가드가 이미 있다(`report_lines.py:1985-1995`, R139).

---

## 1. `verification` 스키마

일부러 작게 만든다. 크기 추정은 §5.

### 1.1 `verification.progress` — 회사 × 사업연도 × 보고서 1행

| 컬럼 | 타입 | 설명 |
|---|---|---|
| corp_code | varchar(8) FK corporations | PK |
| fiscal_year | smallint | PK |
| fiscal_period | varchar(2) | PK. `Q1`/`H1`/`Q3`/`FY` (`filings.fiscal_period`와 같은 코드) |
| era | varchar(8) | 지금은 `2015+`. 이후 `2011-14` 등을 추가할 때 스키마 변경 없이 확장 |
| corp_rank | int | init 시점 시총 순위 스냅샷(작업 순서) |
| status | varchar(12) | `pending` / `in_progress` / `passed` / `has_issues` (CHECK) |
| claimed_by | text | `in_progress`일 때 워크트리/세션 id |
| lease_until | timestamptz | 점유 만료 시각 — 죽은 세션이 슬롯을 영구히 잡지 못하게 |
| verified_scopes | text[] | 예 `{con.bs,con.is,...}`. 행이 있는 scope가 전부 들어 있어야 `passed` 가능(현행 게이트와 동일) |
| n_open_issues | int | `issues` 트리거가 유지 |
| passed_at, note | | |

한 슬롯에는 rcept가 여러 개 있다(최초본 + 정정본). 그래서 rcept마다 `progress_filings`에 행을 둔다.

### 1.2 `verification.progress_filings` — 슬롯 안의 rcept 단위

- 컬럼: `rcept_no` PK(FK filings) · `corp_code, fiscal_year, fiscal_period`(FK progress) · `is_amendment` ·
  `status`(`pending`/`passed`/`has_issues`/`skipped`) · `verified_load_seq` · `verified_at` · `note`.
- 슬롯은 모든 filing이 `passed`/`skipped`**이고** `n_open_issues = 0`일 때만 `passed`가 된다.

### 1.3 `verification.filing_loads` — 어떤 코드가 어떤 rcept를 적재했나

6,200만 행 테이블에 parser_version 컬럼을 넣는 대신 작은 테이블 하나를 둔다.

- 컬럼: `rcept_no` PK · `load_seq` int(재적재마다 +1) · `parser_commit`(git short SHA, 미커밋 변경이 있으면 `-dirty`) ·
  `load_run_id` · `loaded_at` · `loaded_by`(워크트리) · `reason`(`daily` / `fix_batch:<id>` / `backfill:R166`).
- `store_report_lines` / `store_report_tables` / `store_note_lines`와 **같은 트랜잭션** 안에서 기록한다.
- 요청의 "담당 parser 버전"은 여기서 나온다.

### 1.4 `verification.issues`

| 컬럼 | 설명 |
|---|---|
| issue_id bigserial PK | |
| corp_code, fiscal_year, fiscal_period, rcept_no | FK progress / filings |
| basis | `consolidated`(연결) / `separate`(별도) |
| statement | `BS`/`IS`/`CIS`/`CF`/`SCE` — 원문 표기대로 기록한다(DB는 CIS를 IS에 합쳐 둠) |
| account_label | 원문에 적힌 계정명 |
| db_label, db_row_order | DB 행 위치(행이 없으면 NULL) |
| column_label | SCE(자본금·이익잉여금 등)와 다열 표에서 필요 |
| db_value numeric | NULL = DB에 행 없음 |
| source_value numeric, source_value_raw text | 원문 값 + 원문 셀 문자열 그대로(`(1,234)`, `-`, U+3000 등) |
| source_unit | `원`/`천원`/`백만원` |
| error_type | FK `error_types` |
| status | `open`/`fixing`/`fixed`/`closed`/`reopened` (CHECK) |
| found_load_seq, found_parser_commit | 틀린 값을 만든 적재(`filing_loads`에서 복사) |
| fixed_parser_commit, fix_batch_id | 수정 워크트리가 채움 |
| rule_id | PARSING_RULES.md R번호(예 `R167`) |
| dart_url, evidence | 짧은 텍스트, 2,000자 이하(CHECK) — HTML·CSV 원문 저장 금지 |
| created_by, created_at, updated_at | |

- 중복 방지: (rcept_no, basis, statement, account_label, column_label)에 `WHERE status <> 'closed'` 부분 유니크 인덱스.
- 인덱스: 수정 큐용 `(status, error_type)`, 검증용 `(corp_code, fiscal_year, fiscal_period)`.

### 1.5 `verification.error_types`(코드표)와 `verification.fix_batches`

**`error_types`** 초기 코드는 기존 카탈로그에서 가져온다.
- `missing_row`(행 누락), `extra_row`(잉여 행), `value_mismatch`(값 불일치)
- `sign_flip`(부호 반전), `unit_scale`(단위 배수)
- `column_misassign`(열 오귀속), `period_misassign`(기간 오귀속), `label_mismatch`(계정명 불일치)
- `source_defect`(DART 원문 자체 오타, 예 R162)

코드는 필요할 때 추가한다.

**`fix_batches`** = 수정 워크트리의 작업 단위이고, **배치 1개 = 오류 패턴 1개**다.
- 컬럼: `batch_id` · `error_type` · `rule_id` · `title` · `status`(`open`/`waiting_decision`/`reloading`/`done`) · `commit_sha` ·
  대상 rcept 수 · `created_at`/`done_at`.

### 1.6 `verification.issue_events` (+ `progress_events`) — 추가만 가능한 이력

- 컬럼: `event_id` · `issue_id` · `from_status` · `to_status` · `actor`(워크트리/세션) · `db_role` · `at` ·
  `action`(`create`/`transition`/`comment`/`relink`) · `evidence` · `commit_sha` · `load_seq`.
- 상태가 바뀔 때마다 **트리거가 자동 기록**한다 — 세션이 기록을 빠뜨릴 수 없다.
- 이벤트 테이블은 UPDATE/DELETE 권한을 회수한다.
- `progress_events`는 같은 구조로 슬롯·filing 판정 이력을 남긴다.

### 1.6b `verification.runner_runs` — 외부 루프의 `claude -p` 1회 실행 = 1행

- 컬럼: `run_id` · `worktree` · `slot`(corp_code, fiscal_year, fiscal_period) · `started_at`/`ended_at` · `exit_code` ·
  `num_turns` · `input_tokens`/`output_tokens` · `outcome`(`passed`/`has_issues`/`incomplete`/`timeout`/`usage_limit`/`error`) ·
  `log_path` · `git_head`.
- 용도는 세 가지다: 슬롯 1개당 토큰·시간 실측(→ 규모 조정, §2.5), 연속 실패 감지, 아침 다이제스트.

### 1.6c `verification.decisions` — 텔레그램으로 묻고 답받는 사용자 판단 (§2.7)

| 컬럼 | 설명 |
|---|---|
| decision_id bigserial PK | |
| category | `irreversible` / `policy` / `scope` / `source_ambiguity` (CHECK) — 이 넷 외에는 만들 수 없다 |
| asked_by | 워크트리/세션 |
| batch_id, issue_id | 무엇에 대한 판단인가(FK, NULL 허용) |
| question | ≤ 200자, 한국어 |
| options jsonb | `[{key, label, consequence}]` 2~4개. 선택지마다 결과를 한 줄로 적는다 |
| recommended | 권장 선택지 key (필수) |
| dedupe_key | 같은 판단이 대기 중이면 새로 만들지 않는다(부분 유니크, `status='pending'`) |
| status | `pending` / `answered` / `expired` / `cancelled` |
| answer_key, answer_text | 버튼 선택, 또는 답장으로 보낸 자유 입력 |
| answered_via | `telegram` / `terminal` |
| nonce | 콜백 위조와 오래된 버튼 탭 방지용 난수 |
| tg_message_id | 답이 오면 해당 메시지를 "✅ 선택됨"으로 수정할 때 사용 |
| created_at, sent_at, answered_at, expires_at | |

### 1.7 상태 머신 (규약이 아니라 트리거로 강제)

```
open ──수정──▶ fixing ──수정──▶ fixed ──검증──▶ closed
  ▲                                │                 │
  └────── reopened ◀──검증─────────┘◀────검증────────┘ (회귀)
reopened ──수정──▶ fixing
```

- 트리거가 `current_user`를 검사한다.
  - 검증 계정: 생성, fixed→closed, fixed→reopened, closed→reopened만 가능.
  - 수정 계정: open/reopened→fixing, fixing→fixed만 가능.
- `fixed`가 되려면 `fixed_parser_commit`이 있어야 하고, `filing_loads.load_seq`가 `found_load_seq`보다 커야 한다.
  즉 실제로 재적재하지 않으면 fixed가 될 수 없다.

---

## 2. 2-워크트리 운영 (사용자 결정: 기존 워크트리 재사용)

| | 검증 = `camp_run` | 수정 = `camp_err_review` |
|---|---|---|
| DB 계정 | `tjf_verify`: `public`은 SELECT만, `verification.progress*`·`issues`(등록 + 검증 쪽 전이) RW | `tjf_fix`: `public` RW, `issues`(수정 쪽 전이)·`fix_batches`·`filing_loads` RW |
| 재적재 | **절대 안 함.** 적재된 값을 읽기만 한다 → 구코드 재적재 위험을 뿌리부터 제거 | 함. 반드시 `filing_loads` 스탬프를 찍는 로더 경유 |
| 이어하기 명령 | `python scripts/vq.py next` — 내 `in_progress` 슬롯을 재개하거나 다음 슬롯을 점유(`FOR UPDATE SKIP LOCKED`, 시총순) | `python scripts/vq.py fix-queue` — open 이슈를 error_type별로 묶어 보여줌 → 배치 선택/생성 |

- 워크트리마다 `.env`의 `DATABASE_URL`이 다르다. 그래서 역할 구분을 세션이 잊어도 Postgres가 막는다.
- CLI는 `scripts/vq.py` 하나이고, 역할별 서브커맨드를 둔다.
  - 검증: `next`, `show`, `issue add`, `pass`, `recheck`, `close`, `reopen`
  - 수정: `fix-queue`, `batch new`, `batch reload`, `batch mark-fixed`
  - 공통: `status`
- 기존 코드를 재사용한다.
  - `scripts/layer2_review.py`의 시총 순서·scope 게이트
  - `fin2/extract/review_csv.py`의 검토 CSV
  - `store_report_lines`는 그대로 쓰고 스탬프 훅만 추가

### 2.5 검증 러너 — 바깥 셸 루프가 `claude -p`를 슬롯 단위로 반복 호출

**왜**: 한 세션이 여러 슬롯을 연달아 처리하면 문제가 생긴다. 컨텍스트가 쌓여 autocompact가 일어나면 규약을 잃고
(8scope 축약이 3회 재발), 앞 슬롯의 값이 다음 판정에 섞인다. 그래서 **세션 수명 = 슬롯 1개**로 만든다.
매 실행이 빈 컨텍스트에서 시작하고, 이어갈 상태는 전부 DB에 있으므로 잃을 것이 없다.

**구조** (`scripts/verify_runner.sh`, 검증 워크트리에서 실행)

```
while 정지조건 아님:
  0. 정지파일(~/.claude/notify/STOP_VERIFY) 있으면 종료
  1. git fetch && git merge --ff-only origin/main   ← 수정 워크트리의 push를 매 회 자동 반영(검증 쪽은 코드 수정이 없어 항상 ff)
  2. SLOT=$(python scripts/vq.py claim --json)       ← 점유는 모델이 아니라 스크립트가 한다(결정적, lease 설정)
     비어 있으면(큐 소진) 종료
  3. timeout 45m claude -p "<고정 프롬프트 + SLOT>" \
        --output-format json --max-turns 80 \
        --allowedTools "Read,Bash(python scripts/vq.py:*),mcp__claude-in-chrome__*" \
        > logs/verify_runner/<날짜>/<slot>.json
  4. python scripts/vq.py runner-finish <run_id> <log>   ← 결과 검사 후 runner_runs 기록
       - 슬롯이 passed/has_issues가 됐으면 정상
       - 여전히 in_progress면 lease 해제 + retry_count+1 (3회 넘으면 blocked로 바꾸고 알림)
       - 출력에 사용량 한도 메시지가 있으면 → 리셋 시각까지 sleep
  5. 연속 실패 3회 → 러너 정지 + telegram 알림
  6. 슬롯 사이 짧은 휴지(예: 30초)
```

- 실행은 `caffeinate -i`로 감싸 tmux에서 돌린다. **launchd에는 올리지 않는다** — TCC가 NAS/SD 접근을 막았던 전례가 있다.
- 권한은 `--allowedTools` 화이트리스트로 준다. `--dangerously-skip-permissions`는 쓰지 않는다.
  설령 잘못 허용해도 `tjf_verify` 계정이라 `public`에는 쓸 수 없다.
- 고정 프롬프트는 `docs/verification/verify_prompt.md`에 둔다(커밋 대상). 내용: "이 슬롯 하나만 처리하고 종료,
  8scope 전체대조, `vq.py pass`/`issue add` 중 하나로 반드시 끝낼 것". CLAUDE.local.md는 `-p`에서도 자동으로 읽힌다.

**규모 — 1회 실행 = 슬롯 1개(회사 × 연도 × 보고서, rcept 1~3건, 대략 300~1,500행)**
- 근거: 기존 세션은 한 번에 7필링(약 3,800행)을 처리했지만 그 과정에서 규약 이탈이 재발했다.
  슬롯 1개는 한 컨텍스트에 여유 있게 들어가는 크기다.
- 기본값(**파일럿으로 조정**):
  - `--max-turns 80`, 1회 제한시간 45분.
- **요금제 = Max(x5), 캠페인 기간 내내 유지** (2026-09-24 사용자 확인). 사용량 한도가 두 겹이라 예산도 두 겹으로 잡는다.
  - **5시간 창**: 창당 러너 슬롯 상한 `SLOTS_PER_WINDOW`를 둔다. 초기값 **12**(Pro 기준 4의 약 3배 — 5배 전부가 아니라,
    나머지는 수정 세션 몫으로 남긴다).
  - **주간 한도**: `WEEKLY_RUNNER_SHARE`를 둔다. 초기값 **60%**, 즉 주간 사용량의 약 60%는 러너, 약 40%는 수정 세션과 대화형 작업.
    `runner_runs`의 누적 토큰으로 주간 소진 속도를 계산해서, 페이스를 넘으면 러너가 스스로 휴지 간격을 늘린다.
    한도에 부딪혀 수정 세션이 막히는 일을 막기 위해서다.
  - **모델**: 러너는 기본 Sonnet, 수정 세션은 Opus로 시작한다. 파일럿에서 Sonnet 판정 품질이 부족하면
    (§9-2 오판 샘플로 측정) 러너도 Opus로 올리고, 그만큼 `SLOTS_PER_WINDOW`를 낮춘다.
- **파일럿 3일**: 러너를 낮 시간에 사용자가 지켜보며 돌린다. `runner_runs`에서 슬롯당 토큰·턴·소요시간을 측정한 뒤
  `SLOTS_PER_WINDOW`, `WEEKLY_RUNNER_SHARE`, max-turns, 모델을 확정한다.
- **규모를 쉽게 말하면**
  - 검사할 칸(슬롯) 수: 2,531사 × 11년(2015~2025) × 4보고서 ≈ **약 11만 개**.
  - 하루 처리량 추정: 5시간 창당 12슬롯 × 하루 4~5개 창 ≈ **하루 40~70개**. 추정치이므로 파일럿에서 실측한다.
  - 전부 끝내는 데 걸리는 기간: 11만 ÷ 55 ≈ 2,000일 ≈ **약 5년**(범위 4~7년). 즉 몇 달로는 전수가 안 된다.
  - 그래서 몇 달 동안 현실적으로 되는 범위는 이렇다. 1개사 = 11년 × 4 = 44슬롯이므로,
    하루 55슬롯이면 **하루 1개사 남짓, 한 달 약 35~40개사**다. 6개월이면 **시총 상위 약 200개사**, 슬롯 약 9천 개다.
    이 200개사가 전체 시가총액에서 차지하는 비중은 구현할 때 DB로 실측해 `vq.py status`에 표시한다.
  그래서 이 캠페인은 기존 설계처럼 **시총 상위부터 가는 열린 캠페인**이다. 진척은 "검증 완료 회사 수"로 센다.
  속도를 올리는 방법(예: 원문 표를 스크립트로 추출해 기계대조하고 불일치만 모델이 보는 하이브리드)은 파일럿 뒤에 따로 검토한다.
- **Chrome은 하나다**: 브라우저를 조작하는 세션은 동시에 하나만 둔다. 그래서 러너 병렬도는 1이고,
  수정 세션은 러너가 돌 때 브라우저를 쓰지 않는다(원문 확인이 필요하면 러너를 잠시 멈추거나 `html_viewer.py`로 HTML을 받아 본다).
- **파일럿 1일차 첫 확인 항목**: `claude -p`(headless)에서 claude-in-chrome MCP가 실제로 붙는지 스모크 테스트.
  안 붙으면 러너 구조는 유지하되 대조 수단을 바꿔야 하므로 그 시점에 다시 결정한다.

### 2.6 수정 워크트리 시작 가이드 (정확한 절차)

수정 작업은 판단이 많고, 가끔 사용자 확인도 필요하다. 그래서 **대화형 세션 + 배치 1개 = 세션 1개**로 운영한다.
러너로 자동화하는 것은 운영이 안정된 뒤에 검토한다.

**① 터미널 준비** (명령은 실제 구현 후 경로를 확정해 WORKFLOW.md에 그대로 싣는다)

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

`whoami`가 `role=tjf_fix, worktree=camp_err_review`가 아니면 여기서 멈춘다(`.env` 확인).

**② 현황 확인**

```bash
python scripts/vq.py fix-queue
```

진행 중인 배치(`reloading`)가 있으면 반드시 그것부터 끝낸다.

**③ Claude 세션 시작**

```bash
claude
```

첫 프롬프트는 이렇게 준다: `vq.py fix-queue 보고 진행 중 배치가 있으면 이어서, 없으면 가장 큰 error_type 묶음으로 새 배치를 만들어 진행해`.

**④ 세션 1회의 흐름** (CLAUDE.local.md가 강제)
- `batch new` → 원인 조사 → 파서 수정 → 회귀 테스트(`pytest tests/ fin2/tests/`) → PARSING_RULES.md에 R번호 추가
  → commit/push(`worktree-camp_err_review:main`) → `batch reload` → `batch mark-fixed`.
- 검증 러너는 다음 반복에서 코드를 자동으로 ff한다. 따로 알릴 필요가 없다.

**⑤ 배치가 끝나면 `/clear` 또는 세션 종료** → 다음 배치는 ①부터. 세션이 중간에 죽어도 배치 상태가 DB에 있으니 ②부터 다시 하면 된다.

### 2.7 텔레그램 양방향 판단 — 밖에서 버튼으로 결정하기

**지금 상태**:
- `~/.claude/notify/telegram.sh`는 **보내기만** 한다(22–08시에는 queue에 쌓고 08:00 다이제스트가 보냄).
- `notification_hook.sh`는 idle 알림을 버리고 권한 요청·플랜 승인 알림만 전달한다.
- 답을 받는 경로가 없어서, 판단이 필요하면 사용자가 터미널 앞에 와야 한다.

**추가하는 것**

```
수정 세션 ──vq.py ask──▶ decisions(pending) ──sendMessage + 인라인 버튼──▶ 텔레그램
                                   ▲                                         │ 사용자가 버튼 탭 / 답장
                                   └──── decision_bot.py (getUpdates 롱폴링) ◀┘
수정 세션/다음 세션 ◀── vq.py wait-decision / fix-queue 가 답을 읽음
```

1. **`vq.py ask`**: 판단을 DB에 기록한 뒤 인라인 키보드 메시지를 보낸다. 버튼 = 선택지 2~4개, 권장안에 ★ 표시.
   `callback_data`는 `d:<id>:<key>:<nonce>`다.
2. **`scripts/decision_bot.py`**: 상주 롱폴링 데몬이다. 외부에 열린 웹훅 서버가 필요 없다.
   - `TELEGRAM_CHAT_ID`와 보낸 사람 id가 일치하는 업데이트만 받는다. 그 외는 무시하고 로그만 남긴다.
   - `status='pending'`이고 nonce가 맞을 때만 답을 기록한다. 두 번 탭하거나 오래된 버튼을 누르면 "이미 처리됨"으로 응답한다.
   - 기록 후 원래 메시지를 "✅ ○○ 선택됨 (HH:MM)"으로 고치고 버튼을 없앤다.
   - 메시지에 **답장(reply)**으로 글을 보내면 자유 입력 답(`answer_text`)으로 기록한다("기타" 선택지 역할).
   - getUpdates offset은 DB에 저장한다. **이 봇 토큰으로 getUpdates를 쓰는 소비자는 이 데몬 하나뿐이어야 한다**
     (구현 시 `link_chat.sh`가 getUpdates를 쓰는지 확인해 충돌을 피한다).
   - 실행은 launchd `KeepAlive`로 한다. DB(로컬 소켓)와 네트워크만 필요하고 NAS/SD를 쓰지 않으므로 TCC 문제가 없다.
     venv python은 절대경로로 지정한다. 토큰은 지금처럼 `telegram.env`(chmod 600)에서만 읽고, 로그에 출력하지 않는다.
3. **세션이 답을 받는 방식**: 세션을 오래 붙잡지 않는다.
   - 곧 답이 올 것 같으면 `vq.py wait-decision <id> --timeout 540`(Bash 1회 한도 이내)을 최대 몇 번만 반복한다.
   - 답이 없으면 배치를 `waiting_decision`으로 **주차**하고, 그 판단과 무관한 다른 배치를 진행하거나 세션을 끝낸다.
   - 다음 세션의 `fix-queue`는 **답이 온 판단이 걸린 배치를 맨 위에** 보여준다. 이것도 DB 기반 이어하기다.
   - 터미널 앞에 있으면 `vq.py answer <id> <key>`로 답해도 된다(`answered_via=terminal`).

**불필요한 메시지를 막는 장치** (규약만이 아니라 `vq.py ask`가 코드로 거부)

| 장치 | 내용 |
|---|---|
| 카테고리 화이트리스트 | 다음 넷만 보낼 수 있다: `irreversible`(대량 삭제, force-push, 스키마 변경, 수시간 전체 재적재), `policy`(값 의미가 바뀌는 새 파싱 정책, 예 R160 마침표 정책 / 새 error_type 코드), `scope`(배치 범위 밖으로 확장 — 기존 메모리 규약), `source_ambiguity`(원문 해석이 둘 다 성립). 그 외는 **CLI가 "스스로 결정하라"며 거부**한다 |
| 형식 요건 | 선택지 2~4개, 권장안 필수, 선택지별 결과 한 줄. 이 조건이 안 되면 거부한다 — "뭘 할까요?" 같은 열린 질문은 못 보낸다 |
| 중복 억제 | 같은 `dedupe_key`가 대기 중이면 새 메시지 없음 |
| 대기 상한 | 대기 중 판단은 최대 3건, 즉시 발송은 하루 최대 5건. 넘치면 다음 다이제스트에 한 메시지로 묶는다 |
| 야간(22–08시) | CLAUDE.md 규약대로 스스로 결정한다. `irreversible`만 판단을 만들 수 있고, 발송은 08:00 다이제스트가 버튼과 함께 한다. 그동안 해당 배치는 주차 |
| 만료 | `expires_at` 기본 24시간. 만료되면 `irreversible`은 **절대 자동 적용하지 않고** 주차를 유지하며 다이제스트에 다시 올린다. 나머지는 권장안을 적용하고 이벤트로 기록한다(선택: `--no-default`) |
| 알림 전면 정리 | 진행 상황·성공·FYI 메시지는 텔레그램으로 보내지 않고 08:00 다이제스트에만 넣는다. 즉시 알림은 **"판단 요청" + "러너 정지(연속 3실패/디스크 50 GB 미만)"** 둘뿐이다. 검증 러너는 판단을 만들지 않는다(새 error_type은 임시 코드 `unclassified`로 기록 → 다이제스트) |
| 판단 요청 알림 | 처리한 결정과 답을 받을 창구는 이 판단 메시지 하나로 모은다. 세션은 판단 요청에 `telegram.sh`를 직접 부르지 않는다(자리 표시용 알림 중복 방지) |

**메시지 예시** (이 정도 길이로 제한)

```
[판단 #12 · irreversible] R167 백필: SCE 3,410필링 재적재(약 2시간), 검증 중 슬롯 0
 ★A 지금 실행 — 러너 lease 대상은 자동 보류
  B 오늘 밤 22시 이후 실행
  C 보류 — 원인 재검토
(답장으로 다른 지시 가능 · 24h 후 만료, 자동 실행 안 함)
```

---

## 3. CLAUDE.md 초안

**배치 방식**: 공통 규칙은 커밋되는 `docs/verification/WORKFLOW.md`에 둔다. 역할 규칙은 각 워크트리 루트의
**`CLAUDE.local.md`**에 둔다. 이 파일은 gitignore 대상이고 워크트리마다 따로 있으며, Claude Code가 자동으로 읽는다.
그래서 git merge를 해도 두 역할 문서가 서로를 덮어쓰지 않는다.

### 3.1 검증 워크트리(`camp_run`) — `CLAUDE.local.md` 초안

```markdown
# 역할: 검증(verify) 워크트리
- 임무: DART 원문 재무제표(웹뷰)와 DB 적재값을 대조하고, 불일치를 verification.issues 에 등록한다.
  fixed 이슈 재확인(closed/reopened)도 담당한다.
- ★금지: 파서/로더 코드 수정, 재적재(store_*, reload_*, backfill_*, layer2_review.py next/redo).
  DB 계정(tjf_verify)이 public 쓰기를 막는다 — 권한 오류가 나면 우회하지 말고 보고.
- 기본 실행 방식은 러너(scripts/verify_runner.sh)가 호출하는 `claude -p` 1회 = 슬롯 1개.
  프롬프트에 받은 슬롯 하나만 처리하고, `vq.py pass` 또는 `vq.py issue add`+`vq.py done` 으로 끝낸 뒤 종료한다.
  다음 슬롯을 스스로 claim 하지 않는다.
- 대화형으로 열었을 때: `python scripts/vq.py status` → `python scripts/vq.py next`. 상태는 전부 DB에 있다.
  세션 메모리·마크다운 이슈로그를 진행상태의 근거로 쓰지 않는다.
- 대조 규칙: 연결/별도 × BS·IS(CIS)·CF·SCE 8 scope 전부, 모든 행·모든 열. 총계/EPS/마감행만 보는 축약 금지.
  기재정정은 base 대비 byte-identity 비교 후 달라진 scope만 원문 재대조.
- 이슈 등록: 1 셀 불일치 = 1 이슈 (`vq.py issue add`). 원문 셀 문자열(source_value_raw)과 단위를 그대로 남긴다.
  error_type은 목록에서 고르고, 없으면 새 코드를 제안만 한다(사용자 확인).
  이미 PARSING_RULES.md에 있는 원문오타 패턴이면 source_defect 로 등록 — 신규결함 판단은 PARSING_RULES.md grep.
- 판정: 모든 scope 대조 완료 + 미해결 이슈 0 → `vq.py pass --verified-scopes ...`.
  이슈가 있으면 has_issues로 두고 다음 슬롯으로.
- 재확인: `vq.py recheck` 로 fixed 이슈 목록 → 원문 재대조 → close / reopen(근거 필수).
- 알림: 텔레그램을 직접 보내지 않는다. 새 패턴은 error_type=unclassified 로 기록하면 08:00 다이제스트에 올라간다.
  기록 후 다음 슬롯으로 진행하며, 대기하지 않는다. 사용자 판단(vq.py ask)도 만들지 않는다.
```

### 3.2 수정 워크트리(`camp_err_review`) — `CLAUDE.local.md` 초안

```markdown
# 역할: 수정(fix) 워크트리
- 임무: verification.issues 를 error_type 단위 fix_batch 로 묶어 근본원인 수정 → 회귀테스트 →
  docs/PARSING_RULES.md(R번호) → 재적재 → 이슈 fixed.
- 세션 시작: `python scripts/vq.py status` → `python scripts/vq.py fix-queue`. 진행 중 batch가 있으면 그것부터.
- ★파서 규칙 작업 전 docs/PARSING_RULES.md 필독, 편입은 docs/runbook_new_parser_pipeline_integration.md
  (collect_new.py 두 call site + 소급 백필 + 검증).
- 재적재는 반드시 `vq.py batch reload <id>` 경유(= filing_loads 스탬프). 스크립트로 직접 store_* 호출 금지.
  in_progress(검증 중) 슬롯은 자동으로 보류되고 lease 해제 후 재시도된다 — 강제 해제 금지.
- fixed 조건: 커밋이 main에 push됨 + 대상 rcept 재적재됨(load_seq 증가) + 해당 셀 값이 원문과 일치.
  같은 패턴의 '이슈 미등록' 필링도 전수 스캔해 함께 백필하고 batch 노트에 스캔 범위/건수를 남긴다.
  (복원 건수를 특정 규칙 효과로 귀속하지 말 것 — 측정값만 기록)
- 권한: 이슈를 closed 로 만들 수 없다(검증 워크트리 몫).
- 사용자 판단: 반드시 `vq.py ask --category <irreversible|policy|scope|source_ambiguity> --question ... --option ... --recommend ...`
  로만 묻는다(텔레그램 버튼으로 전달). 그 외 결정은 스스로 한다 — CLI가 거부하면 스스로 결정하라는 뜻이다.
  판단 요청에 telegram.sh 를 직접 부르지 않는다. 진행 보고용 메시지도 보내지 않는다(다이제스트가 git log/DB에서 만든다).
- 답을 기다릴 때: `vq.py wait-decision <id> --timeout 540` 을 최대 2회까지 반복한다. 그래도 답이 없으면 배치를 주차하고,
  무관한 배치로 넘어가거나 세션을 끝낸다. 세션을 붙잡고 대기하지 않는다.
- 대량 삭제·force-push·스키마 변경·수시간 전체 재적재(irreversible)는 답을 받기 전 절대 실행하지 않는다.
  만료돼도 자동으로 실행되지 않는다.
- push 후 커밋 메시지는 08:00 다이제스트로 쓰이므로 batch id·R번호·재적재 건수를 포함.
```

---

## 4. 재적재가 검증 중인 데이터와 섞이지 않게 하는 방법

문제는 행이 반쯤 바뀌는 것이 아니다. rcept 단위 delete+insert는 이미 한 트랜잭션이라, 읽는 쪽은 옛 버전이나
새 버전 중 하나만 본다. 진짜 문제는 **시점**이다. 검증자는 t 시점에 적재된 값을 보고 있는데, t+1에 재적재가
일어나면 판정과 이슈의 "DB값"이 뜻하는 대상이 조용히 바뀐다. 아래 4겹으로 막는다. 큰 테이블 복사는 없다.

1. **검증 워크트리는 절대 적재하지 않는다**(§2 계정 분리). `public`에 쓰는 것은 수정 워크트리와 데일리 파이프라인뿐이다.
   그래서 구코드 회귀가 구조적으로 불가능하다.
2. **Lease 잠금.** 슬롯이 `in_progress`이고 `lease_until`이 유효하면, 로더가 그 rcept 적재를 거부한다
   (`store_report_lines` 가드, 기존 R139 검사 `report_lines.py:1985` 옆). `batch reload`는 그 건을 보류했다가
   lease가 끝난 뒤 다시 시도한다. 세션이 죽어도 lease가 만료되므로(예: 2시간) 영구히 막히지 않는다.
3. **낙관적 버전 검사.** `next`가 시작할 때 `load_seq`를 기록한다. `pass`와 `issue add`는 그 값을 함께 저장하고,
   그 사이에 `filing_loads.load_seq`가 바뀌었으면 거부된다 → 검증자가 다시 봐야 한다.
4. **이미 passed인 필링의 재적재.** 수정 배치는 이를 재적재할 수 있다(기존 R139 하드 차단을 대체).
   그러면 트리거가 그 filing을 `pending`으로 되돌리고 `progress_events`에 `reloaded_after_pass (batch N)`를 남기며,
   슬롯은 다시 큐에 들어간다. 그래서 "passed"는 언제나 **현재 적재본 기준** 통과를 뜻한다.

**채택하지 않은 대안**: 수정 워크트리용으로 `report_lines`/`note_lines` 전체 staging 사본을 두는 것.
26~120 GB가 들고, 여유는 129 GB다. before/after diff가 필요하면 배치 대상 rcept만 임시 테이블에 담았다가
배치가 끝나면 DROP한다.

---

## 5. 디스크 예산과 가드

- **크기 추정**: progress 약 11만 행(2,531사 × 11년 × 4보고서), progress_filings 약 11만, filing_loads 약 19만,
  issues는 수만 건 예상. 인덱스를 포함해도 **200 MB 미만**이다. 이벤트 테이블은 선형으로 늘지만 작다.
- **가드**
  - 텍스트 길이 CHECK로 HTML·CSV·스크린샷이 DB에 못 들어가게 한다. 근거는 URL/경로 + 짧은 텍스트로 남긴다.
    검토 CSV는 지금처럼 디스크(gitignore)에 두고 pass 시 삭제한다.
  - 큰 테이블의 `*_snap_*` 사본을 만들지 않는다. 롤백용 사본은 배치 대상 rcept만 담고, 배치가 끝나면 DROP한다.
  - `vq.py status`가 `pg_database_size`와 디스크 여유를 출력하고, 여유가 50 GB 미만이면 경고한다.
  - 기존 잔여 스냅샷 테이블(약 1.2 GB)은 **목록만** 보여주고 삭제 여부는 사용자가 정한다. 자동 삭제하지 않는다.

---

## 6. 이관 / 전환 순서

**사용자 결정 (2026-09-24)**
- 큐 판정과 마크다운 이슈 #1~#41을 **둘 다 이관**한다.
- **기존 워크트리를 재사용**한다: `camp_run` = 검증, `camp_err_review` = 수정. 두 브랜치가 main보다 72~76파일 앞서 있어서 먼저 main에 합친다.
- **DB 계정을 역할별로 분리**한다: `tjf_verify` / `tjf_fix`, 워크트리별 `.env`로 설정.

**구현 전 확인 완료 (2026-09-24, 사용자)**
- R139 변경 승인: pass 필링의 재적재를 허용하고, 그 필링은 pending으로 되돌려 재검증한다(하드 차단 폐지).
- 병합 절차 승인: camp_run 미커밋 이슈로그를 커밋 → main 루트의 미추적 구버전 사본(300줄)을 삭제 → 두 브랜치를 main에 병합 → origin/main에 push.
- 스키마·계정·로더 변경 승인: 이 설계 범위 안이면 22시 이후에도 자율 진행한다. 기존 public 테이블의 구조 변경·삭제는 범위 밖이다.
- 프로젝트 CLAUDE.md의 요금제 문구를 Max(x5)로 변경한다.
- camp_run 세션은 중단된 상태다.

**단계**
0. 실행 중인 camp_run 세션을 슬롯 경계에서 멈춘다 → 미커밋 이슈로그 53줄을 커밋 → 두 워크트리 브랜치를 main에 병합.
1. DDL 마이그레이션: 기존 `schema_migrations` 방식(`collector/db.py`)으로 만들고 `python run.py init`으로 적용한다. 계정과 GRANT도 이때 만든다.
2. `vq.py init --era 2015+`: `filings`에서 `progress`/`progress_filings`를 생성한다(상장 보통주, fiscal_year ≥ 2015).
3. `layer2_review_queue` 이관:
   - pass → filing `passed` (`verified_scopes`, `note` 포함)
   - skipped → `skipped`
   - fail, blocked → 해당 filing `has_issues`
4. 마크다운 이슈 #1~#41 이관: 일회성 파서 스크립트로 옮긴다.
   - 해결 후 push까지 된 건 → `closed`
   - peer 대기 중인 건 → `open`
   - R번호를 연결하고, 원문 항목 텍스트는 `evidence`에 넣는다(길면 자르고 문서 앵커를 남김).
   - insert 전에 dry-run 결과를 사용자에게 먼저 보여준다.
5. 로더 훅: `store_report_lines` / `store_report_tables` / `store_note_lines`에 `filing_loads` 스탬프와 lease 가드를 넣는다.
   런북대로 `collect_new.py` **두 call site**(메인 + `--standardize-only`)에 배선한다.
6. `layer2_review.py`는 동결한다(`status`만 동작). 기존 테이블은 감사용으로 남긴다.
7. `CLAUDE.local.md` 두 개와 `docs/verification/WORKFLOW.md`를 배치하고, `PARSING_RULES.md`에 "검증 ↔ 재적재 규칙" 절을 추가한다.
8. `verification` 스키마 야간 백업을 켠다(§9-1).
8b. 텔레그램 판단 봇(§2.7)
   - `decision_bot.py` + launchd plist를 설치하고, `morning_digest.sh`에 "대기 중 판단 + DB 요약" 섹션을 추가한다.
   - 실측 확인: 테스트 판단 1건 → 폰에서 버튼 탭 → DB 기록 → 메시지가 수정되는지 확인한다.
9. 러너 파일럿 3일(§2.5): 첫날 `-p` + Chrome 스모크 → 낮 시간에 감시하며 운영 → 규모 수치를 확정해 WORKFLOW.md에 반영.
10. 파일럿이 끝나면 야간 무인 운영을 시작한다.

## 7. 주요 파일

- **신규**: 마이그레이션(`collector/db.py` 항목 + `collector/models.py` ORM), `scripts/vq.py`, `scripts/verify_runner.sh`,
  `docs/verification/verify_prompt.md`, `docs/verification/WORKFLOW.md`, 백업 스크립트,
  `scripts/decision_bot.py`, `fin2/verification/decisions.py`(ask/answer/gate 로직), `~/.claude/notify/` 쪽 launchd plist와 digest 확장,
  `CLAUDE.local.md` ×2, 테스트 `fin2/tests/test_verification_*.py`, 이슈로그 이관 스크립트.
- **수정**: `fin2/extract/report_lines.py`(`store_*` 가드·스탬프), `collector/note_lines_sync.py`, `scripts/collect_new.py`(두 call site).
- **재사용**: `scripts/layer2_review.py`의 순서·scope 게이트, `fin2/extract/review_csv.py`, R139 가드 위치.

## 8. 검증 방법 (구현 후)

- 트리거 테스트: 두 계정으로 불법 전이와 권한 밖 전이가 전부 거부되는지 확인.
- Lease 테스트: A가 슬롯을 점유 → B의 `batch reload`가 그 rcept를 보류 → lease 만료 후 재적재 진행.
- 버전 테스트: `next`와 `pass` 사이에 재적재가 있으면 `pass`가 거부된다.
- passed 필링을 재적재하면 pending으로 돌아가고 이벤트 행이 남는다.
- 이관 건수: 큐의 pass/skip/fail 건수 = 이관된 건수.
- 러너 테스트:
  - 가짜 `claude` 스텁으로 정상 / 미완료(in_progress 잔존) / 타임아웃 / 사용량 한도 / 연속 3실패 5개 경로를 확인한다(lease 해제, retry, 정지, 알림).
  - STOP 파일을 넣으면 현재 슬롯이 끝난 뒤 멈추는지 확인한다.
- 판단 봇 테스트(Telegram API는 목(mock)으로 대체):
  - gate: 화이트리스트 밖 카테고리, 선택지 1개, 권장안 없음, 대기 3건 초과, 중복 key → 전부 거부된다.
  - 보안: 다른 chat id/user id에서 온 콜백, nonce 불일치, 이미 answered인 판단 → 무시된다.
  - 야간에 만든 irreversible → 발송 보류 → 08:00 다이제스트로 발송된다.
  - 만료: irreversible은 주차가 유지되고, 나머지는 권장안 적용 + 이벤트가 남는다.
  - 그다음 실제 폰으로 E2E 1회 확인.
- `pytest tests/ fin2/tests/` 통과, Gate B 무영향, init 후 실측 스키마 크기 200 MB 미만.

## 9. 처음 하는 대형 구조라 놓치기 쉬운 것 (설계에 반영함)

1. **작업 상태 백업**: 몇 달 치 판정이 전부 DB에 쌓이므로, 잃으면 되돌릴 수 없다.
   매일 밤 `pg_dump -n verification`(수십 MB)을 SD/NAS에 남기고 최근 30개만 보관한다.
   마크다운 이슈로그가 사실상 백업 역할을 하던 것을 이것이 대신한다.
2. **검증자 오판 측정**: camp_run이 BS 값을 보고 SCE가 맞다고 판정한 전례가 있다(이슈#31).
   passed 슬롯 중 무작위 약 2%를 `vq.py audit-sample`로 뽑아 다른 세션이나 사용자가 재검증하고, 오판률을 `status`에 표시한다.
3. **새 필링·새 정정본 유입**: 데일리 파이프라인이 새 rcept를 넣으면 progress에 자동으로 편입되고,
   passed 슬롯에 정정본이 새로 들어오면 그 슬롯은 `pending`으로 돌아간다(`collect_new.py` 두 call site에 배선).
4. **사용량 한도 공유 (Max x5)**: 러너와 수정 세션이 같은 한도(5시간 창 + 주간)를 쓴다.
   `SLOTS_PER_WINDOW`와 `WEEKLY_RUNNER_SHARE`가 수정 몫을 보장하는 장치다.
   프로젝트 `CLAUDE.md`에 있는 "Pro 요금제에 맞게 관리해" 줄은 **"Max(x5) 요금제에 맞게 관리해"로 바꾸자고 제안한다**
   (구현 단계에서 사용자 확인 후 수정).
5. **맥 절전·재부팅**: `caffeinate`로 절전을 막는다. 재부팅 후에는 사용자가 러너를 수동으로 다시 켠다.
   lease가 만료되므로 점유가 꼬이지는 않는다.
6. **스키마 변경은 러너를 멈추고 한다**: STOP 파일 → 현재 슬롯 종료 대기 → 마이그레이션 → 재개.
7. **로그 디스크**: `logs/verify_runner/`는 30일 지나면 삭제한다. 검토 CSV는 pass 시 삭제한다(현행 유지).
8. **아침 보고**: 08:00 다이제스트가 git log 외에 `vq.py status --digest`(전날 슬롯 수, 신규 이슈, error_type 분포, 디스크 여유)도 보낸다.
9. **범위 확장(2015 이전)**: `vq.py init --era 2011-14`로 행만 추가한다. 스키마는 그대로이고, 순서는 era → 시총순이다.


---

## 10. 구현 메모 (2026-09-24, 설계 대비 달라진 점)

- **적재 스탬프를 호출부 배선 대신 DB 트리거로 구현했다.** `report_lines` 문장 트리거가 필링을 모으고,
  커밋 시점의 지연 트리거가 내용 해시를 계산한다. 이렇게 하면 데일리·백필·임시 스크립트 모두 빠짐없이
  기록되고, `collect_new.py` 두 call site 를 배선할 필요가 없다. 대상은 `report_lines` 만이다
  (`note_lines`·`report_tables` 는 대조 대상이 아니고, 2억 행 테이블에 트리거를 거는 비용을 피했다).
  규칙: `docs/PARSING_RULES.md` R167.
- **load_seq 는 "적재 횟수"가 아니라 "내용 버전"이다.** 해시가 같으면 오르지 않으므로, 같은 결과로
  재파싱해도 판정이 무효화되지 않는다. passed 필링은 내용이 바뀐 경우에만 pending 으로 돌아간다.
  재대조는 바뀐 scope 만 하면 된다(`show` 가 판정 당시 scope 해시와 비교해 알려준다).
- **lease 가드는 수정 계정(tjf_fix)에만 건다.** 관리자(데일리)는 막지 않는다. 그 대신 버전 검사가
  `pass`/`issue add` 를 거부한다 — 데일리 배치 전체가 실패하는 것을 피하기 위해서다.
- 슬롯 상태에 **`blocked`** 를 추가했다(러너 3회 실패).
- 이슈 이관: 마크다운 #1~#41 은 **현재 필링 상태로만** 상태를 정한다.
  - 필링이 passed/skipped → closed
  - 필링이 pending → `fixed`(`legacy-unverified`). 러너가 원문과 재대조하도록 가장 먼저 배정된다.
- main 루트에 있던 미추적 이슈로그는 camp_run 문서의 구버전이 아니라 **이름만 같은 별개 문서**(셀프체크 시기 이슈 1~26)였다.
  그래서 삭제하지 않고 `docs/qa/layer2_review_selfcheck_issues_main_2026-09-20.md` 로 보존했다.
- 파일
  - 스키마: `fin2/verification/schema.sql`
  - 로직: `fin2/verification/{ops,decisions,runner,session_info,schema}.py`
  - CLI: `scripts/vq.py`
  - 러너: `scripts/verify_runner.sh`
  - 봇: `scripts/decision_bot.py`
  - 백업: `scripts/vq_backup.sh`
  - 이관: `scripts/vq_import_legacy_issues.py`
  - 문서: `docs/verification/{WORKFLOW,verify_prompt}.md`

---

## 11. 파일럿 측정과 Max(x5) 튜닝 계획 (2026-09-24, 사용자 결정: 파일럿 중 사용량 제한 없음)

**측정 규모 = 30회**. 계정 사용률 스냅샷이 있는 회차만 센다(run 17~). 채우면 러너가 스스로 정지하고 알린다
(`kv runner.stop_after_measured_runs=30`).
- 근거: 슬롯당 사용량은 편차가 크다. run 5~16 에서 턴 18~81, API 환산 $0.57~$3.50 이었고, 변동계수는 대략 0.5다.
  평균을 ±20% 안쪽으로 잡으려면 약 25회가 필요하다(n ≈ (2·0.5/0.2)²).
  여기에 처음 몇 회차에서 새로 드러날 문제의 여유를 더해 30회로 정했다.
- run 5~16 은 튜닝 표본에서 제외한다. 그 사이 프롬프트·스크립트 결함 5종을 고치는 중이었다(Chrome 미연결, 화면 판독, 탭,
  턴 상한, SCE 열 이름). 또 대부분 이관 이슈의 재확인이라 일반 슬롯과 부하가 다르다.
- 표본은 실제 큐 순서 그대로 쓴다. 남은 fixed 재확인 3개 슬롯 → 판정 일부가 남은 슬롯(495개,
  주로 검증된 슬롯의 미검증 정정본) → 일반 슬롯 순이다. 앞으로 몇 주의 실제 작업이 이 순서이므로 그대로가 대표성이 있다.
- 약 6분/회 × 30 ≈ 3시간. 비용 추정은 API 환산 $1.5~2/회, 주간 한도로는 실측이 나와야 안다.

**측정 후 튜닝(Max x5, 캠페인 내내 유지)**
1. 회차별 Δ주간%(`usage_7d_end - usage_7d_start`)의 중앙값을 구하고, 슬롯 유형별(재확인·정정본·일반·금융업)로 나눠 본다.
   같은 계정의 다른 세션 사용분이 섞이므로, 러너만 돌던 구간의 값을 우선한다.
2. **주간 배분**: 러너 60%, 수정 세션+대화형 40%(설계 §2.5). 고정 슬롯 수 대신 **실측 사용률로 페이스를 조절**한다.
   계정 주간 사용률이 `경과비율×100 + 10%p` 를 넘으면 러너가 쉬고, 따라잡히면 재개한다.
   이렇게 하면 주 후반에 수정 세션이 막히는 일을 막는다.
3. **5시간 창**: 계정 5h 사용률 70% 이상이면 러너가 리셋까지 대기한다. 나머지 30%는 대화형·수정 세션 몫이다.
4. 슬롯/일 기대치 = (주간 60% ÷ Δ주간% 중앙값) ÷ 7. 이 값으로 §2.5 의 "시총 상위 200개사 약 6개월" 추정을 다시 계산한다.
5. **모델**: Sonnet 판정 품질을 `admin audit-sample` 로 재검증해 확인한다. 부족하면 Opus 로 바꾸고 2~4번을 다시 계산한다.
6. `runner.slots_per_window` 고정 상한은 폐지하거나 안전장치(예: 30)로만 남긴다.
