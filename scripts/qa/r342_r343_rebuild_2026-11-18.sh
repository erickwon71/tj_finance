#!/bin/zsh
# R342/R342-b/R343/R344/R345 (2026-11-18) retro rebuild: snapshot -> company-wide std_v3 rebuild in 5 shards
# (--year-min 1990, calendar included) -> before/after comparison -> consumer_guide reload.
# Run from anywhere, after the daily pipeline (collect_new.py) has finished.
set -e
cd /Users/taejin/Project/tj_finance
# The daily writes std_v3 only in step ④ (before its DQ gate); its later steps (biz/order/doc
# sections, valuation refresh, curated scan, mirror) do not. ALLOW_DURING_DAILY=1 lets this run
# while the daily is past step ④ (checked 2026-11-18 23:05: daily in ⑤ DQ gate since 03:49).
if pgrep -f "scripts/collect_new.py" >/dev/null && [ "${ALLOW_DURING_DAILY:-0}" != "1" ]; then
  echo "daily pipeline (collect_new.py) is still running; run this after it finishes"; exit 1
fi
mkdir -p logs
psql -d tj_finance -v ON_ERROR_STOP=1 -f scripts/qa/r342_r343_snapshot_2026-11-18.sql
for i in 0 1 2 3 4; do
  .venv/bin/python scripts/build_std_v3.py --all --shard $i/5 --year-min 1990 > logs/r342_build_$i.log 2>&1 &
done
wait
grep -h "완료\|^  !" logs/r342_build_*.log
psql -d tj_finance -f scripts/qa/r342_r343_compare_2026-11-18.sql | tee logs/r342_r343_compare.txt
.venv/bin/python scripts/load_consumer_guide.py
