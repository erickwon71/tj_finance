#!/bin/bash
# classB 유형1(§5.4, ACONTEXT 유무 신호로 선두 None 절삭 재설계) 전수 백필 —
# R19 백필(scripts/run_r19_backfill_parallel_2026-08-14.sh)과 정확히 같은 2단계 패턴:
#   1단계: report_lines 전량 재추출(--recheck, 5-shard 병렬)
#   2단계: std_v3 재표준화(1단계 전부 끝난 뒤에만 시작, 5-shard 병렬)
# 근거: docs/plans/gateb_trade_payables_classB_stale_column_investigation_2026-08-29.md §5~7.
# 변경 파일: parser/xml/table_extractor.py, fin2/extract/text.py, fin2/extract/report_lines.py.
#
# 파급범위(census, 3,000건 표본): 전체 외삽 약 22,000행 / 약 2,000개 필링, CF 위주,
# 2023Q3 군집. R19 와 동일하게 **전량 재추출**을 택한다(부분 대상 목록보다 단순·안전 —
# census 는 표본 추정치일 뿐 정확한 대상 목록이 아님).
#
# 이 스크립트 자체가 장시간 실행되므로(수시간 예상) 백그라운드로 돌리는 걸 권장:
#   nohup caffeinate -i bash scripts/run_classB_leadingNone_backfill_2026-08-29.sh \
#       > logs/classB_leadingNone_backfill_wrapper.log 2>&1 &
#
# 진행상황 확인(아무 때나):
#   tail -f logs/classB_leadingNone_backfill_wrapper.log
#   tail -f logs/layer2_classB_recheck_shard_*.log
#   tail -f logs/std_v3_classB_shard_*.log
#   .venv/bin/python scripts/load_report_lines.py --status
# 중단:
#   pkill -f load_report_lines.py; pkill -f build_std_v3.py
#   (멱등 — report_lines 는 rcept 단위 delete-then-insert, std_v3 는 corp 단위 동일 원리.
#    다시 실행하면 이어서 처리됨.)

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
        > "logs/layer2_classB_recheck_shard_${i}.log" 2>&1 &
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
        > "logs/std_v3_classB_shard_${i}.log" 2>&1 &
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
    echo "!! 2단계에서 하나 이상 샤드가 실패했습니다. 로그를 확인하세요."
    exit 1
fi

echo ""
echo "=== 백필 전체 완료 $(date) — 다음은 Gate B 전수 재감사 ==="
echo "  bash scripts/run_gateb_audit_parallel.sh"
