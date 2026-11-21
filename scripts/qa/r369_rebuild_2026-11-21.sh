#!/bin/zsh
# R369 (2026-11-21) retro rebuild: company-wide std_v3 rebuild (5 shards, --year-min 1990, calendar included)
# so the five one-off accounts (impairment / disposal / debt forgiveness) fill past periods.
# Expected: std_financials_v3 unchanged; extended_facts_v3 only gains rows of the five R369 accounts.
set -e
cd /Users/taejin/Project/tj_finance
if pgrep -f "scripts/collect_new.py" >/dev/null && [ "${ALLOW_DURING_DAILY:-0}" != "1" ]; then
  echo "daily pipeline (collect_new.py) is still running"; exit 1
fi
mkdir -p logs
psql -d tj_finance -v ON_ERROR_STOP=1 -f scripts/qa/r369_snapshot_2026-11-21.sql
for i in 0 1 2 3 4; do
  .venv/bin/python scripts/build_std_v3.py --all --shard $i/5 --year-min 1990 > logs/r369_build_$i.log 2>&1 &
done
wait
grep -h "완료\|^  !" logs/r369_build_*.log || true
psql -d tj_finance -f scripts/qa/r369_compare_2026-11-21.sql | tee logs/r369_compare.txt
