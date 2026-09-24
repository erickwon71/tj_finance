#!/bin/bash
# Verification runner: one fresh `claude -p` per slot, forever, until stopped.
#
# Why a loop outside Claude: a long interactive session accumulates context, gets
# autocompacted and loses the rules (the 8-scope full-comparison shortcut recurred 3x).
# Here every run starts empty and all state is in the DB, so nothing is lost between runs.
#
# Run it in the verify worktree (camp_run), inside tmux:
#   caffeinate -i scripts/verify_runner.sh
# Stop it gracefully (finishes the current slot first):
#   touch ~/.claude/notify/STOP_VERIFY
#
# Design: docs/plans/verification_schema_two_worktree_design_2026-09-24.md section 2.5
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
PY="${VQ_PYTHON:-/Users/taejin/Project/tj_finance/.venv/bin/python}"
VQ=("$PY" scripts/vq.py)
STOP_FILE="$HOME/.claude/notify/STOP_VERIFY"
NOTIFY="$HOME/.claude/notify/telegram.sh"
PROMPT_FILE="$ROOT/docs/verification/verify_prompt.md"
LOG_ROOT="$ROOT/logs/verify_runner"
RUN_TIMEOUT="${VQ_RUN_TIMEOUT:-2700}"          # 45 min per slot
MAX_TURNS="${VQ_MAX_TURNS:-120}"   # run 6 hit 80 on a 2-filing SCE-heavy slot
MODEL="${VQ_MODEL:-sonnet}"
PAUSE="${VQ_PAUSE:-30}"
MIN_FREE_GB="${VQ_MIN_FREE_GB:-50}"
# Extra claude flags for the pilot (e.g. the Chrome integration switch), space separated.
read -r -a EXTRA_ARGS <<< "${VQ_CLAUDE_ARGS:-}"

# Enforced with --permission-mode dontAsk: anything not listed here is denied outright.
# (The user's global defaultMode is "auto", which would otherwise approve arbitrary Bash -
# seen in the first pilot run.) Absolute paths in permission rules need a leading "//".
ALLOWED_TOOLS=(
  "Read" "Grep" "Glob"
  "Bash($PY scripts/vq.py:*)"
  "Write(/$LOG_ROOT/**)"
  "mcp__claude-in-chrome__*"
)
DISALLOWED_TOOLS=("Edit" "NotebookEdit" "Bash(git:*)" "Bash(python3:*)" "Bash(psql:*)")

log() { printf '%s  %s\n' "$(date '+%m-%d %H:%M:%S')" "$*"; }

notify() {
  [ -x "$NOTIFY" ] || return 0
  local st=queued
  "$NOTIFY" "$1" >/dev/null 2>&1 && st=sent
  printf '%s  runner    %s %s\n' "$(date '+%m-%d %H:%M:%S')" "$st" "$1" >> "$HOME/.claude/notify/sent.log"
}

# The verify worktree never edits code, so a fast-forward always succeeds unless someone
# broke that rule - then stop instead of running old code against new data.
sync_code() {
  git fetch -q origin main || { log "git fetch 실패 - 이번 회차는 현재 코드로 진행"; return 0; }
  if ! git merge --ff-only -q origin/main; then
    log "ff-only 실패: 검증 워크트리에 로컬 커밋/변경이 있다 - 러너 정지"
    notify "[verify 러너 정지] camp_run 에 로컬 변경이 있어 코드 동기화 실패 - 확인 필요"
    exit 3
  fi
}

free_gb() { df -g /opt/homebrew/var 2>/dev/null | awk 'NR==2 {print $4}'; }

prune_logs() { find "$LOG_ROOT" -type f -mtime +30 -delete 2>/dev/null; }

# Close the Chrome tabs this slot opened. Each `claude -p` gets its own tab group and cannot
# see earlier ones, and a run cut off by max-turns/timeout never closes its tab - so the
# runner does it. Only tabs whose URL carries one of THIS slot's rcept numbers are touched,
# so DART tabs the user opened for other filings stay open.
# DONE_RCEPTS accumulates every slot this runner finished (last ~60 rcepts), so a tab that
# one cleanup missed (observed once: 0 closed while the tab was still settling) is retried
# on every later run instead of being left behind for good.
DONE_RCEPTS=""
close_slot_tabs() {  # $1 = slot just finished
  local rcepts
  rcepts=$("${VQ[@]}" rcepts "$1" 2>/dev/null) || rcepts=""
  DONE_RCEPTS=$(printf '%s %s' "$DONE_RCEPTS" "$rcepts" | tr ' ' '\n' | grep -v '^$' | tail -60 | tr '\n' ' ')
  rcepts="$DONE_RCEPTS"
  [ -n "${rcepts// /}" ] || return 0
  # shellcheck disable=SC2086
  osascript - $rcepts <<'OSA' 2>/dev/null || log "탭 정리 실패(Chrome 자동화 권한 확인)"
on run argv
  set n to 0
  if application "Google Chrome" is not running then return n
  tell application "Google Chrome"
    repeat with w in windows
      repeat with i from (count of tabs of w) to 1 by -1
        set u to URL of tab i of w
        repeat with r in argv
          if u contains ("rcpNo=" & (contents of r as text)) then
            close tab i of w
            set n to n + 1
            exit repeat
          end if
        end repeat
      end repeat
    end repeat
  end tell
  return n
end run
OSA
}

# macOS has no coreutils `timeout`. perl's alarm survives exec, so the claude process
# itself gets SIGALRM at the deadline - no watchdog subshell, no orphaned sleep.
# ${EXTRA_ARGS[@]+...}: an empty array is "unbound" under `set -u` in bash 3.2.
run_claude() {  # $1 = prompt, $2 = log file; returns claude's exit code (124 on timeout)
  perl -e 'alarm shift; exec @ARGV' "$RUN_TIMEOUT" \
    claude -p "$1" --output-format json --max-turns "$MAX_TURNS" --model "$MODEL" \
    --chrome --permission-mode dontAsk \
    --allowedTools "${ALLOWED_TOOLS[@]}" --disallowedTools "${DISALLOWED_TOOLS[@]}" \
    ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} \
    > "$2" 2>"$2.err"
  local rc=$?
  [ "$rc" -eq 142 ] && rc=124
  return "$rc"
}

# Everything runs inside main(): bash parses a function body completely before running it,
# so the `git merge --ff-only` below can safely replace this very file mid-loop (a plain
# top-level script is read incrementally and would execute the new bytes at an old offset).
SELF="$ROOT/scripts/verify_runner.sh"
SELF_SUM="$(shasum "$SELF" | cut -d' ' -f1)"

main() {
  [ -f "$PROMPT_FILE" ] || { log "프롬프트 파일 없음: $PROMPT_FILE"; exit 1; }
  "${VQ[@]}" whoami | grep -q '"role": "verify"' || {
    log "이 워크트리의 DB 역할이 verify 가 아니다 - .env 의 DATABASE_URL 확인"; exit 1; }

  mkdir -p "$LOG_ROOT"
  log "verify 러너 시작 (model=$MODEL, timeout=${RUN_TIMEOUT}s, max-turns=$MAX_TURNS)"

  while :; do
    if [ -e "$STOP_FILE" ]; then
      log "STOP 파일 발견 - 정지 (재개하려면 파일 삭제 후 다시 실행)"
      exit 0
    fi

    free=$(free_gb)
    if [ -n "$free" ] && [ "$free" -lt "$MIN_FREE_GB" ]; then
      log "디스크 여유 ${free}GB < ${MIN_FREE_GB}GB - 정지"
      notify "[verify 러너 정지] 디스크 여유 ${free}GB (<${MIN_FREE_GB}GB)"
      exit 4
    fi

    budget=$("${VQ[@]}" runner budget)
    if [ "$(printf '%s' "$budget" | jq -r '.stop')" = "true" ]; then
      n=$(printf '%s' "$budget" | jq -r '.measured_runs')
      log "파일럿 목표 ${n}회 완료 - 러너 정지"
      notify "[verify 러너] 파일럿 측정 ${n}회 완료 - 정지. 튜닝 분석 대기"
      exit 0
    fi
    wait_s=$(printf '%s' "$budget" | jq -r '.wait_seconds')
    if [ "${wait_s:-0}" -gt 0 ]; then
      log "사용량 예산 대기 ${wait_s}s"
      sleep "$(( wait_s < 1800 ? wait_s : 1800 ))"
      continue
    fi

    sync_code
    # main() is parsed once at start, so a pulled change to THIS script would otherwise only
    # take effect after a manual restart (it did: the tab cleanup and max-turns 120 stayed
    # inactive for hours). Re-exec between runs when the file changed.
    if [ "$(shasum "$SELF" | cut -d' ' -f1)" != "$SELF_SUM" ]; then
      log "러너 스크립트가 갱신됨 - 새 버전으로 재시작"
      exec "$SELF" "$@"
    fi
    prune_logs

    slot=$("${VQ[@]}" claim --json | jq -r '.slot // empty')
    if [ -z "$slot" ]; then
      log "대기 슬롯 없음 - 종료"
      exit 0
    fi

    day_dir="$LOG_ROOT/$(date '+%Y-%m-%d')"
    mkdir -p "$day_dir"
    logf="$day_dir/${slot//:/_}_$(date '+%H%M%S').json"
    run_id=$("${VQ[@]}" runner start --slot "$slot" --model "$MODEL")
    prompt="$(cat "$PROMPT_FILE")

  ---
  이번 실행의 슬롯: $slot   (run_id=$run_id)
  임시 파일(이슈 JSON 등)은 $day_dir 아래에만 쓴다."

    log "run $run_id 시작: $slot"
    run_claude "$prompt" "$logf"
    rc=$?
    res=$("${VQ[@]}" runner finish --run-id "$run_id" --log "$logf" --exit-code "$rc")
    log "run $run_id 종료(rc=$rc): $res"
    closed=$(close_slot_tabs "$slot")
    [ -n "$closed" ] && [ "$closed" != "0" ] && log "탭 ${closed}개 닫음"

    if printf '%s' "$res" | grep -q '"stop": true'; then
      log "연속 실패 - 러너 정지 (알림 발송됨)"
      exit 5
    fi
    sleep "$PAUSE"
  done
}

main "$@"
exit $?
