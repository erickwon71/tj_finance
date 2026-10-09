#!/bin/bash
# Read-only verifier A/B run: the production prompt and tool permissions, against a frozen slot
# snapshot, with scripts/vq.py replaced by vq_shim.py (writes go to actions.jsonl, not the DB).
# Usage: SNAPDIR=<snap dir> run.sh <round> <model> <rep> [start] [end]
# Layout under $SIM_HOME (default logs/verify_sim): work_<round>/ (frozen docs + shim), runs/<round>/<model>_<rep>/<i>/
SIM_HOME="${SIM_HOME:-/Users/taejin/Project/tj_finance/logs/verify_sim}"
SNAPDIR="${SNAPDIR:-$SIM_HOME/snap}"
PY=/Users/taejin/Project/tj_finance/.venv/bin/python
ROUND="$1"; MODEL="$2"; REP="$3"; START="${4:-0}"; END="${5:-999}"
W="$SIM_HOME/work_$ROUND"
N=$($PY -c "import json;print(len(json.load(open('$SNAPDIR/manifest.json'))))")
[ "$END" -gt "$N" ] && END=$N
cd "$W" || exit 1
for ((i=START; i<END; i++)); do
  [ -e "$SIM_HOME/STOP" ] && { echo "STOP"; exit 0; }
  slot=$($PY -c "import json;print(json.load(open('$SNAPDIR/manifest.json'))[$i]['slot'])")
  OUT="$SIM_HOME/runs/$ROUND/${MODEL}_$REP/$i"
  [ -s "$OUT/claude.json" ] && continue
  rm -rf "$OUT"; mkdir -p "$OUT"
  prompt="$(cat "$W/docs/verification/verify_prompt.md")

  ---
  이번 실행의 슬롯: $slot   (run_id=sim)
  임시 파일(이슈 JSON 등)은 $OUT 아래에만 쓴다."
  echo "$(date '+%H:%M:%S') [$ROUND $MODEL#$REP $i] $slot start"
  SIM_SNAP="$SNAPDIR" SIM_OUT="$OUT" SIM_SLOT="$slot" \
  perl -e 'alarm shift; exec @ARGV' 2700 \
    claude -p "$prompt" --output-format stream-json --verbose --max-turns 120 --model "$MODEL" \
    --chrome --permission-mode dontAsk \
    --allowedTools "Read" "Grep" "Glob" "Bash($PY scripts/vq.py:*)" "Write(/$OUT/**)" "mcp__claude-in-chrome__*" \
    --disallowedTools "Edit" "NotebookEdit" "Bash(git:*)" "Bash(python3:*)" "Bash(psql:*)" \
    > "$OUT/claude.json" 2> "$OUT/claude.err"
  echo "$(date '+%H:%M:%S') [$ROUND $MODEL#$REP $i] $slot rc=$?"
  sleep 3
done
