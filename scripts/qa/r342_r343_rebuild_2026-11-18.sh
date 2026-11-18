#!/bin/zsh
# R342/R342-b/R343/R344 (2026-11-18) retro rebuild: snapshot -> std_v3 rebuild of the affected corps in 5 shards
# (--year-min 1990, calendar included) -> before/after comparison -> consumer_guide reload.
# Run from anywhere, after the daily pipeline (collect_new.py) has finished.
set -e
cd /Users/taejin/Project/tj_finance
if pgrep -f "scripts/collect_new.py" >/dev/null; then
  echo "daily pipeline (collect_new.py) is still running; run this after it finishes"; exit 1
fi
LIST=scripts/qa/r342_r343_corps_2026-11-18.txt
mkdir -p logs
psql -d tj_finance -v ON_ERROR_STOP=1 -f scripts/qa/r342_r343_snapshot_2026-11-18.sql
for i in 0 1 2 3 4; do
  corps=$(awk -v i=$i 'NR % 5 == i' $LIST | paste -sd, -)
  .venv/bin/python scripts/build_std_v3.py --corp "$corps" --year-min 1990 > logs/r342_build_$i.log 2>&1 &
done
wait
grep -h "완료\|^  !" logs/r342_build_*.log
psql -d tj_finance -f scripts/qa/r342_r343_compare_2026-11-18.sql | tee logs/r342_r343_compare.txt
.venv/bin/python scripts/load_consumer_guide.py
