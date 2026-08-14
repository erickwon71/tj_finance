#!/bin/bash
# scan_note_ref_guard_dropped_amounts_2026-08-14.py 를 5-shard 병렬로 실행(읽기전용, DB 쓰기 없음).
# run_gateb_audit_parallel.sh 와 동일 패턴 — 죽으면 이 스크립트만 다시 실행하면 된다
# (출력 파일이 매번 덮어써지므로 재실행해도 안전).
#
# 사용법:
#   bash scripts/run_note_ref_scan_parallel_2026-08-14.sh
#
# 진행상황 확인:
#   tail -f logs/note_ref_scan_shard_*.log
# 프로세스 확인:
#   ps aux | grep scan_note_ref_guard
# 중단:
#   pkill -f scan_note_ref_guard_dropped_amounts

set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate

if pgrep -f "scan_note_ref_guard_dropped_amounts" > /dev/null; then
    echo "이미 스캔 프로세스가 돌고 있습니다. 중복 실행을 막기 위해 종료합니다."
    ps aux | grep scan_note_ref_guard_dropped_amounts | grep -v grep
    echo "다시 시작하려면 먼저: pkill -f scan_note_ref_guard_dropped_amounts"
    exit 1
fi

mkdir -p scratchpad logs

N_SHARDS=5

for i in $(seq 0 $((N_SHARDS - 1))); do
    nohup python scripts/scan_note_ref_guard_dropped_amounts_2026-08-14.py \
        --shard "$i" --n-shards "$N_SHARDS" \
        --out-prefix scratchpad/note_ref_scan \
        > "logs/note_ref_scan_shard_${i}.log" 2>&1 &
    echo "shard $i 시작: PID $!"
done

echo ""
echo "5개 샤드 전부 백그라운드로 시작됨(예상 소요 ~40분). 완료되면 각 샤드가"
echo "scratchpad/note_ref_scan_summary_shard{0..4}.json 을 남긴다."
echo "진행상황: tail -f logs/note_ref_scan_shard_*.log"
