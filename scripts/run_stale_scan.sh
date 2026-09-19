#!/usr/bin/env bash
# DB vs 현재 파서 대조 — 8샤드 병렬. 재시작 안전(각 샤드가 자기 jsonl 을 읽어 건너뛴다).
#
# ★평소엔 이게 아니라 아래 한 줄을 쓴다(2026-09-19 사용자 지적):
#     python scripts/scan_report_lines_stale_vs_parser.py --never-revisited --out logs/nr.jsonl
#   계층2 캠페인이 매 건 재적재를 하므로 `pending` 의 stale 은 저절로 해소된다. 전수를
#   돌리는 건 "곧 저절로 고쳐질 것"을 2시간 들여 미리 세는 낭비다. 이 스크립트는 그래도
#   전수가 필요할 때(예: 캠페인과 무관하게 DB 전체 신뢰도를 재야 할 때)만 쓴다.
set -u
cd "$(dirname "$0")/.."
source .venv/bin/activate
SHARDS=${SHARDS:-8}
mkdir -p logs
for k in $(seq 0 $((SHARDS-1))); do
  python scripts/scan_report_lines_stale_vs_parser.py \
      --shard "$k" --shards "$SHARDS" --year-min "${YEAR_MIN:-2015}" \
      --out "logs/stale_shard${k}.jsonl" > "logs/stale_shard${k}.log" 2>&1 &
done
wait
echo "ALL SHARDS DONE"
