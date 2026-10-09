#!/bin/bash
# Usage: mkwork.sh <round>  - frozen copy of what the verifier reads (CLAUDE.md, camp_run CLAUDE.local.md, docs) + the shim
SIM_HOME="${SIM_HOME:-/Users/taejin/Project/tj_finance/logs/verify_sim}"
R="$1"; SRC=/Users/taejin/Project/tj_finance; HERE="$(cd "$(dirname "$0")" && pwd)"
W="$SIM_HOME/work_$R"; rm -rf "$W"; mkdir -p "$W/scripts" "$W/docs/verification"
cp "$SRC/CLAUDE.md" "$W/CLAUDE.md"
cp "$SRC/.claude/worktrees/camp_run/CLAUDE.local.md" "$W/CLAUDE.local.md"
cp "$SRC/docs/verification/"*.md "$W/docs/verification/"
cp "$SRC/docs/PARSING_RULES.md" "$W/docs/PARSING_RULES.md"
cp "$HERE/vq_shim.py" "$W/scripts/vq.py"
echo "work_$R ready"
