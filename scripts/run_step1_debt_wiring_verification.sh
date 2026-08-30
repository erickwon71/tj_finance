#!/bin/bash
# B1-D2 step1 "wiring" (net_debt-only additive debt sum, fin2/layer3/combine.py) 검증
# 파이프라인 원샷: face_audit 스냅샷 -> std_financials_v3 전체 재빌드(5-shard) ->
# Gate B 전수재감사(5-shard) -> pass->fail_a 전이 확인 -> net_debt v2/v3 불일치율 측정.
#
# docs/plans/valuation_daily_blockers_da_netdebt_design_2026-08-30.md §2-7 순서1
#
# 각 단계는 이전 단계가 전부 끝난 뒤에만 시작한다(gateb_audit 샤드는 재빌드가 끝난
# std_financials_v3에서 corp 목록을 다시 뽑아야 하므로 순서가 중요함). run_r57_
# verification.sh 와 동일 패턴 — 재사용.
#
# 사용법(터미널을 열어두고 지켜볼 때):
#   caffeinate -i bash scripts/run_step1_debt_wiring_verification.sh
#
# 사용법(백그라운드로 돌리고 터미널을 닫아도 될 때):
#   caffeinate -i nohup bash scripts/run_step1_debt_wiring_verification.sh > logs/run_step1_debt_wiring_verification.log 2>&1 &
#
# 진행상황 확인:
#   tail -f logs/run_step1_debt_wiring_verification.log
#   tail -f logs/build_std_v3_step1_shard_*.log
#   tail -f logs/gateb_step1_shard_*.log
# 프로세스 확인:
#   ps aux | grep -E "build_std_v3.py|gateb_audit.py"
# 중단:
#   pkill -f build_std_v3.py; pkill -f gateb_audit.py
# 재실행:
#   이 스크립트를 다시 실행하면 된다. build_std_v3.py는 corp 단위 upsert,
#   gateb_audit.py는 --recheck라 이미 끝난 회사를 다시 돌려도 안전하다.
#   face_audit 스냅샷 테이블이 이미 있으면 새로 뜨지 않고 기존 베이스라인을 재사용한다.

set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate

DB_URL="postgresql://localhost/tj_finance"
SNAP_TABLE="face_audit_snap_20260831_step1"
N_SHARDS=5
YEAR_MIN=1999

if pgrep -f "build_std_v3.py" > /dev/null || pgrep -f "gateb_audit.py" > /dev/null; then
    echo "이미 build_std_v3.py 또는 gateb_audit.py 프로세스가 돌고 있습니다. 중복 실행 방지를 위해 종료합니다."
    ps aux | grep -E "build_std_v3.py|gateb_audit.py" | grep -v grep
    echo "다시 시작하려면 먼저: pkill -f build_std_v3.py; pkill -f gateb_audit.py"
    exit 1
fi

mkdir -p scratchpad logs

START_TS=$(date +%s)
echo "시작: $(date)"

echo ""
echo "===== 0단계: net_debt 불일치율 측정(재빌드 전) ====="
python scripts/measure_net_debt_v2_v3_mismatch.py --label before_step1_rebuild | tee -a logs/net_debt_mismatch_progress.log

echo ""
echo "===== 1단계: face_audit 스냅샷 (${SNAP_TABLE}) ====="
SNAP_EXISTS=$(psql "$DB_URL" -tAc "SELECT to_regclass('public.${SNAP_TABLE}') IS NOT NULL;")
if [ "$SNAP_EXISTS" = "t" ]; then
    echo "스냅샷 테이블이 이미 있습니다 — 기존 베이스라인을 그대로 재사용합니다: ${SNAP_TABLE}"
else
    psql "$DB_URL" -v ON_ERROR_STOP=1 -c "CREATE TABLE ${SNAP_TABLE} AS SELECT * FROM face_audit;"
    echo "스냅샷 생성 완료: ${SNAP_TABLE}"
fi

echo ""
echo "===== 2단계: std_financials_v3 전체 재빌드 (${N_SHARDS}-shard) ====="
pids=()
for i in $(seq 0 $((N_SHARDS - 1))); do
    python scripts/build_std_v3.py --all --year-min "$YEAR_MIN" \
        --shard "${i}/${N_SHARDS}" \
        > "logs/build_std_v3_step1_shard_${i}.log" 2>&1 &
    pids+=("$!")
    echo "std_v3 shard $i 시작: PID $!"
done
fail=0
for pid in "${pids[@]}"; do
    wait "$pid" || fail=1
done
if [ "$fail" -eq 1 ]; then
    echo "std_v3 재빌드 중 하나 이상의 샤드가 실패했습니다. 로그를 확인하세요: logs/build_std_v3_step1_shard_*.log"
    exit 1
fi
echo "std_v3 재빌드 ${N_SHARDS}개 샤드 전부 정상 종료됨. 로그 마지막 줄:"
tail -n 3 logs/build_std_v3_step1_shard_*.log

echo ""
echo "===== 3단계: net_debt 불일치율 측정(재빌드 후) ====="
python scripts/measure_net_debt_v2_v3_mismatch.py --label after_step1_rebuild | tee -a logs/net_debt_mismatch_progress.log

echo ""
echo "===== 4단계: Gate B 전수재감사 (${N_SHARDS}-shard) ====="
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
    with open(f"scratchpad/gateb_step1_shard_{i}.txt", "w") as f:
        f.write("\n".join(s) + "\n")
    print(f"scratchpad/gateb_step1_shard_{i}.txt: {len(s)}개사")
PYEOF

pids=()
for i in $(seq 0 $((N_SHARDS - 1))); do
    python scripts/gateb_audit.py --source v3 --fy-min "$YEAR_MIN" --recheck \
        --corp-file "scratchpad/gateb_step1_shard_${i}.txt" \
        > "logs/gateb_step1_shard_${i}.log" 2>&1 &
    pids+=("$!")
    echo "gateb shard $i 시작: PID $!"
done
fail=0
for pid in "${pids[@]}"; do
    wait "$pid" || fail=1
done
if [ "$fail" -eq 1 ]; then
    echo "Gate B 전수재감사 중 하나 이상의 샤드가 실패했습니다. 로그를 확인하세요: logs/gateb_step1_shard_*.log"
    exit 1
fi
echo "Gate B 전수재감사 ${N_SHARDS}개 샤드 전부 정상 종료됨. 로그 마지막 줄:"
tail -n 3 logs/gateb_step1_shard_*.log

echo ""
echo "===== 5단계: pass -> fail_a 전이 확인 ====="
psql "$DB_URL" -v ON_ERROR_STOP=1 -c "
SELECT count(*) AS pass_to_fail_a
FROM ${SNAP_TABLE} s
JOIN face_audit c
  ON s.corp_code = c.corp_code AND s.fiscal_year = c.fiscal_year
 AND s.fiscal_period = c.fiscal_period AND s.statement_type = c.statement_type
 AND s.is_stub = c.is_stub AND s.source_version = c.source_version
WHERE s.gate_status = 'pass' AND c.gate_status = 'fail_a';
"

END_TS=$(date +%s)
echo ""
echo "===== 완료: $(date) (총 $(( (END_TS - START_TS) / 60 ))분 소요) ====="
echo "위 pass_to_fail_a 가 0이고, net_debt 불일치율이 개선됐으면 step1 트랙 종료 조건 충족."
