# 핸드오프 — 검증 루프 완전자동화 보강 (2026-09-26 11:34)

**갱신(2026-09-26 12:50)**: ①②④⑤ 구현·적용 완료(커밋 `885fa6b`). ③은 보류(관찰 데이터 부족).
세부 내용은 각 절 하단 "✅ 완료" 블록과 메모리 [[fix-batch-id-stale-cleanup-backfill-2026-09-26]] 참조.
⑤는 실측 결과가 이 문서의 원래 추정(18건)과 크게 달라 — **실제로는 open/reopened 이슈 12,168건 중
11,949건(98%)** 이 이미 이 상태였고 전량 백필했다. 백필 후 fix-queue에 sign_flip 11,967건이 새로
노출됐으니 다음 세션에서 이 배치를 어떻게 쪼갤지 사용자와 우선순위를 논의할 것.

이어받는 세션: 아무 워크트리든(항목마다 다름, 각 항목에 표기). 시작 전에 `docs/verification/WORKFLOW.md` ·
`docs/plans/verification_machine_compare_design_2026-09-24.md`(특히 §11 예산) 를 먼저 읽을 것.

## 0. 배경

2026-09-25~26 세션에서 웹뷰 전수대조(하루 60슬롯, 2015+ 완료까지 약 4년)를 기계 대조(A안)로 전환해
핵심 병목은 풀었다(37시간에 82% passed). Max(x5) 예산 분배(`runner.pace_mode`)도 실측으로 작동 확인됨.
남은 건 **사람이 손으로 계속 챙겨야 하는 부분**이다 — 이걸 없애는 게 이번 백로그의 목표다.

사용자 질문(2026-09-26): "캠페인 loop 최적화(Max x5 리소스 분배) 목표가 해결됐나?" → 핵심 병목은 해결,
운영 자동화는 미완이라고 답했고, 그 미완 부분을 이 문서로 넘긴다.

## 1. 기계 대조 워커 자동 재기동 ★가장 시급 (camp_run 워크트리 또는 main)

**증상**: `vq.py machine run` 은 claim 할 슬롯이 없으면 그냥 종료한다(`machine_pass.run()` 의 `while` 루프가
`ops.claim(...) is None` 이면 break). 그래서 tmux `verify_machine` 세션의 6프로세스가 일이 끝나면 전부
죽는다. 재적재(fix 배치)·데일리 신규 필링이 쌓이면 `기계대조: stale N` 이 다시 늘어나는데, **아무도 재기동
안 하면 그 필링들은 영원히 기계 대조를 못 받고, 모델 게이트(`machine.gate=on`) 때문에 모델도 안 집는다.**
지금(11:34) stale 은 아니지만 미대조 pending 필링이 쌓여 있다(`vq.py status` 의 "미대조 pending 필링" 값 확인).

**하지 말 것**: `machine_pass.run()` 의 while 루프 자체를 무한루프로 바꾸는 건 안 된다 — claim 할 게
없을 때 DB 를 폴링으로 계속 두드리게 된다.

**제안**: `scripts/verify_runner.sh` 와 같은 패턴의 데몬 스크립트를 새로 만든다(`scripts/machine_daemon.sh`).
```
while :; do
  [ -e "$STOP_FILE" ] && exit 0
  n=$(vq.py status --json | jq '.machine.unchecked_pending_filings')
  if [ "$n" -gt 0 ]; then
    for i in 1 2 3 4 5 6; do VQ_ACTOR=camp_run:machine .venv/bin/python scripts/vq.py machine run & done
    wait
  fi
  sleep 600   # 폴링 주기는 실측해서 조정
done
```
- `verify_runner.sh` 의 코드-변경 감지 재실행 패턴(`shasum` 비교 후 `exec`)도 그대로 가져올 것.
- tmux 로 상시 기동(`verify` 세션과 같은 방식), `docs/verification/WORKFLOW.md` §4-1 을 이 데몬 실행법으로
  갱신한다(지금 문서는 "한 번 띄우고 끝나면 다시 띄워라" 로 돼 있는데, 이걸 데몬으로 대체).
- launchd(macOS) 로 주기 기동하는 대안도 검토할 것 — 사용자 환경은 `~/.claude/notify/` 에 이미 launchd
  에이전트(08:00 다이제스트)가 있으니 같은 패턴 참고 가능.

**✅ 완료(2026-09-26 12:48)**: `scripts/machine_daemon.sh` 구현(verify_runner.sh 패턴: 자기 코드
재동기화·STOP 파일·로그정리, poll 기본 600초). `docs/verification/WORKFLOW.md` §4-1 갱신.
tmux `verify_machine` 세션에서 기동해 즉시 미대조 pending 3,104건을 집어 워커 6개 기동 확인.
정지: `touch ~/.claude/notify/STOP_MACHINE`. launchd 전환은 보류(tmux 상시기동으로 충분히 검증됨).

## 2. dontAsk 모드 Bash 권한 전면거부 버그 완화 (camp_run 워크트리)

**증상**(2026-09-26 10:19~10:55, run 368~370): 모델이 한 턴에 Bash 를 약 14개 병렬호출하자 이후 세션 내내
Bash 전체(읽기전용 `vq.py show` 포함)가 거부됨. 같은 슬롯(00117212:2019:FY)에서 3연속 재현 → 러너가
"연속 실패"로 자기 자신을 정지시킴(텔레그램 알림 발송됨, 사용자가 뒤늦게 발견).
제품 버그로 이미 `/feedback` 접수됨(사용자 전송, receipt `439ebd7c-884b-48ce-9f33-3c542f5955a2`).
근본 수정은 Claude Code 쪽이라 여기서 못 고친다. **로컬에서 할 수 있는 완화책**:

1. **`docs/verification/verify_prompt.md` 에 병렬 Bash 호출 개수 제한 가이드 추가.**
   "한 턴에 Bash 를 동시에 여러 개 부르지 말 것(권장 상한 5개 이하), 특히 `issue add`/`close`/`reopen`
   반복 호출은 순차로" 같은 문구. (이번 세션에서 만든 `issues-json` 일괄등록 기능도 병렬호출을 줄이는
   효과가 있으니 같이 언급.)
2. **`scripts/verify_runner.sh` 의 실패 분류에 이 시그니처를 특수 처리.**
   로그(`log_path` 의 JSON)에 `"Permission to use Bash has been denied"` 문자열이 있으면, 진짜 데이터
   문제로 인한 실패와 구분해서 — 예를 들어 `retry_count` 를 소진시키지 않고 다음 순번으로 미루거나,
   `MAX_RETRIES` 를 이 사유에 한해 늘리거나, 연속실패 카운터에 안 들어가게 하는 방안을 검토.
   (`fin2/verification/ops.py::release()`, `_reap_expired()` 근처)
3. 재현되면 최소한 모델이 "Bash 막힘 → 남은 안내만 짧게 보고 후 종료"를 더 빨리 하도록(지금은 52턴,
   9분 넘게 쓰고 나서야 포기) 프롬프트에 "Bash 첫 거부 감지 즉시 포기, 재시도하지 말 것" 같은 조기종료
   조건을 넣는 것도 턴 낭비를 줄인다.

**✅ 완료(2026-09-26 12:48), ★2차 수정 필요했음(16:00~16:40)**: 1·3 항목 구현. `verify_prompt.md` 에
병렬 Bash 상한(≤5)·거부 즉시포기 가이드 추가. `runner.py` 에 `tool_denied` outcome 신설
(`_BASH_DENIED_RE`) — usage_limit과 동일하게 retry_count 미증가·연속실패 카운터·예산 슬롯 집계
제외, `runner_runs.outcome` CHECK 제약 갱신. 2 항목(제품 버그 자체)은 여전히 Claude Code 쪽 몫,
이 세션에서는 로컬 완화만.

★같은 날 오후 **두 번 더 재발**했다(커밋 fc5e9de, 5cb3f37 — memory
[[sign-flip-r162e-residual-investigation-2026-09-26]] 아님, 별도 이슈). 1차 재발: 모델이 도구
오류를 리터럴로 인용하지 않고 매번 다르게 풀어썼다("Bash access was just denied" 등) — 리터럴
정규식이 못 잡음, "don't ask mode" 문구까지 넓혀서 대응. 2차 재발(더 심각): 그 패러프레이즈도
매번 또 달랐고("Bash 권한이 거부되었습니다"(한국어), "don't ask mode" 언급도 없음) — **정규식으로
패러프레이즈를 쫓는 접근 자체가 한계**임을 확인. 최종 수정: Claude Code가 result JSON에 항상
붙이는 구조화 필드 `permission_denials`(도구명·명령어 포함)를 1차 신호로 전환, 텍스트 정규식은
폴백으로만 남김.
**더 심각한 부수적 발견**: 재발 3건 중 1건만 진짜 dontAsk 전면차단이었고, 나머지 2건은
`grep`/`find`를 Bash로 시도해 **정상적으로**(원래 허용 목록 밖이라) 거부된 것뿐인데, 앞서 추가한
"Bash 거부되면 즉시 포기" 규칙이 이 정상적인 단발성 거부까지 치명적 버그로 오인해 40~49턴
작업한 세션을 통째로 포기시켰다 — **완화책 자체가 새로운 낭비를 만든 것**. `verify_prompt.md`를
"vq.py 자체가 거부됐을 때만 포기, 그 외 도구 거부는 맞는 도구로 바꿔서 계속"으로 재수정.
회귀 테스트 `test_runner_tool_denied_has_no_retry_penalty`·
`test_runner_tool_denied_paraphrased_still_detected`·
`test_runner_tool_denied_detected_via_permission_denials_field`.

## 3. 예산 예비율(reserve_7d_pct=40 / safety_7d_pct=5) 실측 기반 재검토 (main, 관찰 위주)

**현재**: 고정값. 설계 §11 근거는 파일럿 30회(2026-09-24 13~15시) 뿐이었다.
**이번에 추가로 실측한 것**: 한도 초기화(09-24 22:37) 이후 37시간 동안 시간당 평균 1.16%p, 부하가
몰린 구간(수정 워크트리 배치 + admin 세션 동시 작업)에서는 시간당 1.5%p 까지 관찰됨(09-26 08:02→11:15,
38%→43%). **아직 7일 풀 사이클 데이터가 없다.**

**할 일**: 이번 주 리셋(다음 리셋 시점은 `runner_runs.usage_7d_*` 이력으로 역산 가능)까지 데이터를 더
모은 뒤, 예비율이 실제로 수정 워크트리·admin 세션 몫을 충분히 남기는지 재계산한다. 모자라면
`verification.kv` 의 `runner.reserve_7d_pct`/`runner.safety_7d_pct` 값을 조정한다(코드 변경 없이 UPDATE
한 줄).

**보강 아이디어**: 지금은 검증 러너만 `runner_runs` 에 사용량을 남긴다. 수정 워크트리 세션·admin 세션의
사용량은 안 남아서 "3주체 중 누가 얼마 썼는지" 를 못 나눠본다. 가능하면 fix 세션도 시작/끝에 사용량
스냅샷을 남기는 방법을 검토(예: `vq.py whoami` 나 별도 명령에 usage probe 를 붙여 `verification.kv` 나
새 테이블에 기록). 우선순위는 낮음(관찰만으로도 대략 감은 잡힘).

## 4. passed 역행(reload 로 인한 재검증) 가시성 부족 (main)

**증상**: 오늘 passed 슬롯 수가 79,344 → 77,278 로 **줄었다**(수정 워크트리 재적재로 실제 값이 바뀐
필링이 자동으로 pending 복귀 — `trg_finalize_load` 의 `reloaded_after_pass` 안전장치, 설계대로 정상
동작). 그런데 `vq.py status` 에는 이 "왜 줄었는지" 가 안 보여서, 매번 DB 를 직접 파야 안다.

**제안**: `ops.status()`/`machine_status()` 에 최근 24h `progress_events` 중
`action='reloaded_after_pass'` 건수를 한 줄 추가한다. 스키마 변경 없음(기존 `progress_events` 테이블
조회만 추가).

**✅ 완료(2026-09-26 12:48)**: `machine_status()` 에 `reloaded_after_pass_24h` 추가, `vq.py status`
출력에 한 줄 추가. 실측: 09-26 12시 기준 24h 역행 2,357건(수정 워크트리 재적재로 인한 정상 동작).

## 5. 이번 세션에서 발견한 운영 함정 — 재발 방지용 코드화 검토 (camp_run 또는 main)

`vq.py reopen` 이 `fix_batch_id` 를 그대로 두는 바람에, 이미 `status=done` 인 배치에 걸린 이슈를
reopen 하면 `fix-queue` 의 "미배정"(`fix_batch_id IS NULL`)에도 "진행중 배치"(배치 status 조건)에도
안 걸려 **아무 데도 안 보이는 상태**가 될 수 있다(오늘 admin 세션에서 18건 발생, 수동으로
`fix_batch_id=NULL` UPDATE 해서 복구함).

**제안**: `ops.transition()` 또는 `cmd_reopen`/`cmd_close` 에서, 대상 이슈의 `fix_batch_id` 가 가리키는
배치가 `status NOT IN ('open','waiting_decision','reloading')` 이면(=이미 끝난 배치) **자동으로
`fix_batch_id` 를 NULL 로 같이 비우는 로직**을 추가한다. verify 역할은 이 필드를 못 건드리므로
(`trg_issue_before` 제약) 이 로직은 SECURITY DEFINER 트리거 쪽(`trg_issue_after` 나 별도 트리거)에
넣거나, admin 전용 헬퍼 함수로 만들어 `close`/`reopen` CLI 가 내부적으로 호출하게 한다.
재발하면 또 수동 삽질해야 하므로 **자동화 우선순위 중간~상**.

**✅ 완료(2026-09-26 12:48)**: `trg_issue_before` 에 자동청소 규칙 추가(admin 헬퍼가 아니라 트리거
자체에 — `fixed`→`closed` 정상종료는 감사기록으로 `fix_batch_id` 유지, `open`/`reopened` 로 갈 때만
가리키는 배치가 done/abandoned 면 자동 NULL). 회귀 테스트 `test_reopen_after_batch_done_clears_stale_fix_batch_id`.
**실측 규모가 원래 추정(18건)과 크게 다름**: 라이브 DB 전체 스캔 결과 open/reopened 12,168건 중
11,949건(98%)이 이미 이 상태였음 — `scripts/backfill_stale_fix_batch_id_2026-09-26.py` 로 전량 백필,
잔존 0건. 백필 후 fix-queue: sign_flip 11,967건(3,881필링/1,212사) · source_defect 152 · missing_row 44 ·
period_misassign 4 · unclassified 3 · value_mismatch 2 — sign_flip 물량이 이 규모로 드러난 건 신규 결함이
아니라 이 버그로 오래 방치돼 있던 것. **다음 세션 논의 필요**: 이 sign_flip 11,967건을 어떻게 배치로
쪼개 처리할지(R162-d 형제열 미수정 패턴이 상당수 원인일 가능성, 미확인).

## 6. 완전자동화의 정의 (참고용 체크리스트)

사람이 지금 손으로 해야 하는 것 — 이게 전부 없어지면 "완전자동화":
- [x] 검증 러너 재시작 (§2 완화 — tool_denied 로 재시도 낭비/연속실패오정지는 줄었으나, 제품버그 자체는
      여전히 재현 가능. 완전 해소는 Claude Code 쪽 수정 대기)
- [x] 기계 대조 워커 재기동 (§1 — `scripts/machine_daemon.sh`, tmux `verify_machine` 로 가동 중)
- [x] fix_batch_id 정리 같은 상태 불일치 수동 복구 (§5 — 트리거 자동청소 + 기존 11,949건 백필)
- [ ] 예산 소진 시 사람이 눈치채고 쉬게 하기 (지금도 `pace_mode` 가 자동으로 하므로 이미 해결됨 — 참고용)
- [ ] 8scope 전체대조 vs 발견항목만 대조 전환 판단 (이미 자동 — `기계대조` 줄 보고 모델이 스스로 분기)

우선순위: **1 > 5 > 2 > 4 > 3**(3 은 관찰 기간이 더 필요해 지금 당장 코드로 할 게 적음).
**진행상황(2026-09-26 12:50)**: 1·5·2·4 구현·적용·커밋(`885fa6b`)·push 완료. 3만 보류.
