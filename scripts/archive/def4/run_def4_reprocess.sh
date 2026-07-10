#!/bin/bash
# DEF-4 전수 재처리 런처 — 붙여넣기 따옴표/줄바꿈 문제 회피용.
# 사용법: bash scripts/run_def4_reprocess.sh
set -e
cd /Users/taejin/Project/tj_finance
source .venv_tj_finance/bin/activate
nohup python scripts/def4_reprocess.py \
  --corps-file /tmp/def4_affected_corps.txt \
  --resume-file /tmp/def4_reprocess_done.txt \
  > /tmp/def4_reprocess.log 2>&1 &
echo "started pid $!"
echo "log: /tmp/def4_reprocess.log"
