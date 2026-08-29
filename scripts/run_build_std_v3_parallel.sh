#!/bin/bash
# std_v3 전체 재백필(build_std_v3.py --all)을 5-shard 병렬로 실행.
# build_std_v3.py 는 자체 --shard a/n 옵션을 지원하므로(내부에서 corp_code 목록을
# a/n 으로 분할), gateb_audit.py 용 run_gateb_audit_parallel.sh 와 달리 corp 목록
# 파일을 미리 만들 필요 없다.
#
# 터미널 창을 닫거나 어떤 이유로든 프로세스가 죽었을 때, 이 스크립트 하나만
# 다시 실행하면 처음부터 5-shard 병렬로 재시작한다(build_corp 는 corp 단위 upsert라
# 이미 끝난 회사를 다시 돌려도 안전함).
#
# 사용법:
#   bash scripts/run_build_std_v3_parallel.sh
#
# 진행상황 확인:
#   tail -f logs/build_std_v3_shard_*.log
# 프로세스 확인:
#   ps aux | grep build_std_v3
# 중단:
#   pkill -f build_std_v3.py

set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate

if pgrep -f "build_std_v3.py" > /dev/null; then
    echo "이미 build_std_v3.py 프로세스가 돌고 있습니다. 중복 실행을 막기 위해 종료합니다."
    echo "실행 중인 프로세스:"
    ps aux | grep build_std_v3.py | grep -v grep
    echo "다시 시작하려면 먼저: pkill -f build_std_v3.py"
    exit 1
fi

mkdir -p logs

N_SHARDS=5
YEAR_MIN=1999

for i in $(seq 0 $((N_SHARDS - 1))); do
    nohup python scripts/build_std_v3.py --all --year-min "$YEAR_MIN" \
        --shard "${i}/${N_SHARDS}" \
        > "logs/build_std_v3_shard_${i}.log" 2>&1 &
    echo "shard $i 시작: PID $!"
done

echo ""
echo "5개 샤드 전부 백그라운드로 시작됨. 아래 명령으로 진행상황 확인:"
echo "  tail -f logs/build_std_v3_shard_*.log"
echo "  ps aux | grep build_std_v3"
