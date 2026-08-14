#!/bin/bash
# R19(주석번호 가드 콤마+표단위컨텍스트 수정) 전수 백필 — 2단계를 순서대로 실행:
#   1단계: report_lines 전량 재추출(185,067건, --recheck, 5-shard 병렬)
#   2단계: std_v3 재표준화(1단계 전부 끝난 뒤에만 시작, 5-shard 병렬)
# 계획 = docs/plans/note_ref_guard_body_statement_fix_plan_2026-08-14.md Phase 2.
#
# 이 스크립트 자체가 장시간 실행되므로(수시간) 백그라운드로 돌리는 걸 권장:
#   nohup caffeinate -i bash scripts/run_r19_backfill_parallel_2026-08-14.sh \
#       > logs/r19_backfill_wrapper.log 2>&1 &
#
# 진행상황 확인(아무 때나):
#   tail -f logs/r19_backfill_wrapper.log
#   tail -f logs/layer2_r19_recheck_shard_*.log
#   tail -f logs/std_v3_r19_shard_*.log
#   .venv/bin/python scripts/load_report_lines.py --status
# 중단:
#   pkill -f load_report_lines.py; pkill -f build_std_v3.py
#   (멱등이라 이 스크립트 다시 실행하면 이어서 처리됨 — report_lines 는 --recheck 라 전량
#    재검사하지만 rcept 단위 delete-then-insert 라 중복이 안 생기고, std_v3 는 corp 단위
#    동일 원리.)

set -uo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate

mkdir -p logs

N_SHARDS=5

if pgrep -f "load_report_lines.py" > /dev/null || pgrep -f "build_std_v3.py" > /dev/null; then
    echo "이미 load_report_lines.py 또는 build_std_v3.py 프로세스가 돌고 있습니다. 종료합니다."
    ps aux | grep -E "load_report_lines\.py|build_std_v3\.py" | grep -v grep
    echo "다시 시작하려면 먼저: pkill -f load_report_lines.py; pkill -f build_std_v3.py"
    exit 1
fi

echo "=== 1단계: report_lines 전량 재추출 시작 $(date) ==="
pids=()
for i in $(seq 0 $((N_SHARDS - 1))); do
    caffeinate -i python scripts/load_report_lines.py \
        --fy-min 1999 --recheck --shard "${i}/${N_SHARDS}" \
        > "logs/layer2_r19_recheck_shard_${i}.log" 2>&1 &
    pids+=($!)
    echo "  shard $i 시작: PID $!"
done

fail=0
for pid in "${pids[@]}"; do
    if ! wait "$pid"; then
        echo "  !! PID $pid 비정상 종료(exit != 0) — 해당 로그 확인 필요"
        fail=1
    fi
done

echo "=== 1단계 종료 $(date) ==="
.venv/bin/python scripts/load_report_lines.py --status

if [ "$fail" -ne 0 ]; then
    echo "!! 1단계에서 하나 이상 샤드가 실패했습니다. 2단계(std_v3)는 자동으로 진행하지"
    echo "   않습니다 — 로그를 확인하고, 문제 해결 후 이 스크립트를 다시 실행하세요"
    echo "   (report_lines 는 delete-then-insert 멱등이라 재실행해도 안전합니다)."
    exit 1
fi

echo ""
echo "=== 2단계: std_v3 재표준화 시작 $(date) ==="
pids=()
for i in $(seq 0 $((N_SHARDS - 1))); do
    caffeinate -i python scripts/build_std_v3.py \
        --year-min 1999 --shard "${i}/${N_SHARDS}" \
        > "logs/std_v3_r19_shard_${i}.log" 2>&1 &
    pids+=($!)
    echo "  shard $i 시작: PID $!"
done

fail2=0
for pid in "${pids[@]}"; do
    if ! wait "$pid"; then
        echo "  !! PID $pid 비정상 종료(exit != 0) — 해당 로그 확인 필요"
        fail2=1
    fi
done

echo "=== 2단계 종료 $(date) ==="
if [ "$fail2" -ne 0 ]; then
    echo "!! 2단계에서 하나 이상 샤드가 실패했습니다. logs/std_v3_r19_shard_*.log 확인 후"
    echo "   이 스크립트를 다시 실행하면 됩니다(1단계는 이미 끝났으니 금방 스킵되고 2단계만 재개)."
    exit 1
fi

echo ""
echo "=== 전체 완료 $(date) — Phase 3(Gate B 재감사·항등식 검사)로 넘어가면 됩니다 ==="
