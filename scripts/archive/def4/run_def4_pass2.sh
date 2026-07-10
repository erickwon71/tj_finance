#!/bin/bash
# DEF-4 pass 2 런처(stale comparative/discrete 행 교정). 사용법: bash scripts/run_def4_pass2.sh
set -e
cd /Users/taejin/Project/tj_finance
source .venv_tj_finance/bin/activate
nohup python scripts/def4_reprocess_pass2.py \
  --corps-file /tmp/def4_affected_corps.txt \
  --resume-file /tmp/def4_pass2_done.txt \
  > /tmp/def4_pass2.log 2>&1 &
echo "started pid $!"
echo "log: /tmp/def4_pass2.log"
