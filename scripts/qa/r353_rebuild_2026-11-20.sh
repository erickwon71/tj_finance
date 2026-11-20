#!/bin/zsh
# R353 (2026-11-20) retro rebuild: std_v3 for the 53 corps whose IS has a loose continuing/discontinued NI
# line (A/B: scratchpad ab353 — 286 new is.continuing_ni, 48 is.discontinued_ni, 10 tax_expense sign fixes,
# no other value changed). Waits for the daily (collect_new.py), which holds the pre-R353 combine.py in memory
# and re-standardizes 35 of these corps (Q3 filings of 2026-11-16).
set -e
cd /Users/taejin/Project/tj_finance
while pgrep -f "scripts/collect_new.py" >/dev/null; do sleep 120; done
mkdir -p logs
.venv/bin/python scripts/build_std_v3.py --corp "$(paste -sd, scripts/qa/r353_rebuild_corps_2026-11-20.txt)" \
  --year-min 1990 > logs/r353_build.log 2>&1
grep -h "완료\|^  !" logs/r353_build.log || true
