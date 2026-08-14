#!/bin/bash
# Gate B 감사(gateb_audit.py --source v3 --recheck)를 5-shard 병렬로 실행.
# 터미널 창을 닫거나 어떤 이유로든 프로세스가 죽었을 때, 이 스크립트 하나만
# 다시 실행하면 처음부터 5-shard 병렬로 재시작한다(--recheck 라 이미 끝난 회사는
# 값만 다시 확인하고 지나가므로 중복 실행해도 안전함).
#
# 사용법:
#   bash scripts/run_gateb_audit_parallel.sh
#
# 진행상황 확인:
#   tail -f logs/gateb_shard_*.log
# 프로세스 확인:
#   ps aux | grep gateb_audit
# 중단:
#   pkill -f gateb_audit.py

set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate

if pgrep -f "gateb_audit.py" > /dev/null; then
    echo "이미 gateb_audit.py 프로세스가 돌고 있습니다. 중복 실행을 막기 위해 종료합니다."
    echo "실행 중인 프로세스:"
    ps aux | grep gateb_audit.py | grep -v grep
    echo "다시 시작하려면 먼저: pkill -f gateb_audit.py"
    exit 1
fi

mkdir -p scratchpad logs

N_SHARDS=5

python3 - "$N_SHARDS" << 'PYEOF'
import sys
from sqlalchemy import create_engine, text

n_shards = int(sys.argv[1])
eng = create_engine('postgresql://localhost/tj_finance')
with eng.connect() as c:
    r = c.execute(text("SELECT DISTINCT corp_code FROM std_financials_v3 ORDER BY corp_code"))
    corps = [row[0] for row in r]

shards = [[] for _ in range(n_shards)]
for i, corp in enumerate(corps):
    shards[i % n_shards].append(corp)

for i, s in enumerate(shards):
    with open(f"scratchpad/gateb_shard_{i}.txt", "w") as f:
        f.write("\n".join(s) + "\n")
    print(f"scratchpad/gateb_shard_{i}.txt: {len(s)}개사")
PYEOF

for i in $(seq 0 $((N_SHARDS - 1))); do
    nohup python scripts/gateb_audit.py --source v3 --fy-min 1999 --recheck \
        --corp-file "scratchpad/gateb_shard_${i}.txt" \
        > "logs/gateb_shard_${i}.log" 2>&1 &
    echo "shard $i 시작: PID $!"
done

echo ""
echo "5개 샤드 전부 백그라운드로 시작됨. 아래 명령으로 진행상황 확인:"
echo "  tail -f logs/gateb_shard_*.log"
echo "  ps aux | grep gateb_audit"
