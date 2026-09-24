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
MAX_TURNS="${VQ_MAX_TURNS:-80}"
MODEL="${VQ_MODEL:-sonnet}"
PAUSE="${VQ_PAUSE:-30}"
MIN_FREE_GB="${VQ_MIN_FREE_GB:-50}"
# Extra claude flags for the pilot (e.g. the Chrome integration switch), space separated.
read -r -a EXTRA_ARGS <<< "${VQ_CLAUDE_ARGS:-}"

ALLOWED_TOOLS=(
  "Read" "Grep" "Glob"
  "Bash($PY scripts/vq.py:*)"
  "Write($LOG_ROOT/**)"
  "mcp__claude-in-chrome__*"
)

log() { printf '%s  %s\n' "$(date '+%m-%d %H:%M:%S')" "$*"; }

notify() { [ -x "$NOTIFY" ] && "$NOTIFY" "$1" >/dev/null 2>&1; }

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

run_claude() {  # $1 = prompt, $2 = log file; returns claude's exit code (124 on timeout)
  claude -p "$1" --output-format json --max-turns "$MAX_TURNS" --model "$MODEL" \
    --allowedTools "${ALLOWED_TOOLS[@]}" "${EXTRA_ARGS[@]}" > "$2" 2>"$2.err" &
  local pid=$!
  ( sleep "$RUN_TIMEOUT"; kill -TERM "$pid" 2>/dev/null ) &
  local watchdog=$!
  wait "$pid"
  local rc=$?
  kill "$watchdog" 2>/dev/null
  wait "$watchdog" 2>/dev/null
  [ "$rc" -eq 143 ] && rc=124
  return "$rc"
}

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

  wait_s=$("${VQ[@]}" runner budget | jq -r '.wait_seconds')
  if [ "${wait_s:-0}" -gt 0 ]; then
    log "사용량 예산 대기 ${wait_s}s"
    sleep "$(( wait_s < 1800 ? wait_s : 1800 ))"
    continue
  fi

  sync_code
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

  if printf '%s' "$res" | grep -q '"stop": true'; then
    log "연속 실패 - 러너 정지 (알림 발송됨)"
    exit 5
  fi
  sleep "$PAUSE"
done
