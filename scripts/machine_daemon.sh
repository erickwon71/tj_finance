#!/bin/bash
# Machine-compare worker daemon: relaunches `vq.py machine run` workers whenever pending
# filings need checking, and periodically runs `vq.py machine recheck` for the fix side's
# 'fixed' issues — so nobody has to notice either queue drained and restart things by hand.
#
# Why a separate daemon: machine_pass.run()'s and .recheck()'s claim loops exit as soon as
# there is nothing to claim (must stay that way — turning either into a busy DB poll is
# worse). Reload batches and daily new filings then pile up unchecked forever, and a fix
# batch's 'fixed' issues sit unverified forever, unless something re-launches them. This
# script is that something (docs/qa/handoff_2026-09-26_full_automation.md §1, extended
# 2026-09-26 to also cover `machine recheck` — found idle with 481 'fixed' issues waiting).
#
# Design: docs/qa/handoff_2026-09-26_full_automation.md section 1.
#
# Run it in the camp_run worktree, inside tmux:
#   caffeinate -i scripts/machine_daemon.sh
# Stop it gracefully (finishes the in-flight batch first):
#   touch ~/.claude/notify/STOP_MACHINE
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
PY="${VQ_PYTHON:-/Users/taejin/Project/tj_finance/.venv/bin/python}"
VQ=("$PY" scripts/vq.py)
STOP_FILE="$HOME/.claude/notify/STOP_MACHINE"
NOTIFY="$HOME/.claude/notify/telegram.sh"
LOG_ROOT="$ROOT/logs/verify_runner"
WORKERS="${VQ_MACHINE_WORKERS:-6}"
POLL_S="${VQ_MACHINE_POLL_S:-600}"

log() { printf '%s  %s\n' "$(date '+%m-%d %H:%M:%S')" "$*"; }

notify() {
  [ -x "$NOTIFY" ] || return 0
  local st=queued
  "$NOTIFY" "$1" >/dev/null 2>&1 && st=sent
  printf '%s  machine_daemon  %s %s\n' "$(date '+%m-%d %H:%M:%S')" "$st" "$1" >> "$HOME/.claude/notify/sent.log"
}

# The camp_run worktree never edits code, so a fast-forward always succeeds unless someone
# broke that rule — then stop instead of running old code against new data.
sync_code() {
  git fetch -q origin main || { log "git fetch 실패 - 이번 회차는 현재 코드로 진행"; return 0; }
  if ! git merge --ff-only -q origin/main; then
    log "ff-only 실패: camp_run 워크트리에 로컬 변경이 있다 - 데몬 정지"
    notify "[machine_daemon 정지] camp_run 에 로컬 변경이 있어 코드 동기화 실패 - 확인 필요"
    exit 3
  fi
}

prune_logs() { find "$LOG_ROOT" -type f -mtime +30 -delete 2>/dev/null; }

# Everything runs inside main(): bash parses a function body completely before running it,
# so `git merge --ff-only` above can safely replace this very file mid-loop.
SELF="$ROOT/scripts/machine_daemon.sh"
SELF_SUM="$(shasum "$SELF" | cut -d' ' -f1)"

main() {
  "${VQ[@]}" whoami | grep -q '"role": "verify"' || {
    log "이 워크트리의 DB 역할이 verify 가 아니다 - .env 의 DATABASE_URL 확인"; exit 1; }

  mkdir -p "$LOG_ROOT"
  log "기계 대조 데몬 시작 (workers=$WORKERS, poll=${POLL_S}s)"

  while :; do
    if [ -e "$STOP_FILE" ]; then
      log "STOP 파일 발견 - 정지 (재개하려면 파일 삭제 후 다시 실행)"
      exit 0
    fi

    sync_code
    if [ "$(shasum "$SELF" | cut -d' ' -f1)" != "$SELF_SUM" ]; then
      log "데몬 스크립트가 갱신됨 - 새 버전으로 재시작"
      exec "$SELF" "$@"
    fi
    prune_logs

    day_dir="$LOG_ROOT/$(date '+%Y-%m-%d')"
    mkdir -p "$day_dir"
    stamp="$(date '+%H%M%S')"

    recheck_out=$(VQ_ACTOR=camp_run:machine "${VQ[@]}" machine recheck 2>>"$day_dir/recheck_${stamp}.log")
    log "recheck: ${recheck_out:-처리 없음}"

    n=$("${VQ[@]}" status --json | jq -r '.machine.unchecked_pending_filings // 0')
    if [ "${n:-0}" -eq 0 ]; then
      log "미대조 pending 필링 없음 - ${POLL_S}s 후 재확인"
      sleep "$POLL_S"
      continue
    fi

    log "미대조 pending 필링 ${n}건 - 워커 ${WORKERS}개 기동"
    pids=()
    for i in $(seq 1 "$WORKERS"); do
      VQ_ACTOR=camp_run:machine "${VQ[@]}" machine run \
        > "$day_dir/machine_${i}_${stamp}.log" 2>&1 &
      pids+=("$!")
    done
    for pid in "${pids[@]}"; do wait "$pid"; done
    log "워커 전부 종료 - ${POLL_S}s 후 재확인"
    sleep "$POLL_S"
  done
}

main "$@"
exit $?
